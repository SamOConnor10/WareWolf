from django.db.models import F, IntegerField, Value
from django.db.models.expressions import ExpressionWrapper
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone
from django.urls import reverse
from django.core.cache import cache
import re

from inventory.models import Item, Order
from inventory.anomaly_scan_notifications import ANOMALY_SCAN_RESULT_PREFIX
from .models import ManagerRequest, Notification, UserPreference, UserProfile

NOTIFICATIONS_DROPDOWN_LIMIT = 25
# Navbar merge: newest N DB notifications (full count still shown on badge; Alerts page loads all).
NAVBAR_NOTIFICATION_MERGE_LIMIT = 600


def _severity_rank(level):
    return {"critical": 0, "warning": 1, "info": 2}.get(level, 3)


def _humanize_type(alert_type):
    labels = {
        "user_notification": "User Notification",
        "low_stock": "Low Stock",
        "forecast_risk": "Forecast Risk",
        "overstock": "Overstock",
        "dormant_stock": "Dormant Stock",
        "order_delivered": "Order Delivered",
        "manager_request": "Manager Request",
    }
    return labels.get(alert_type, (alert_type or "").replace("_", " ").title())


def _extract_anomaly_fields(message):
    # Expected format: Demand anomaly (HIGH): ITEM ... (Qty 767, Score 56.55)
    m = re.search(r"Demand anomaly \(([^)]+)\):\s*(.+?)\s+on\s+\d{2}/\d{2}/\d{4}\s+\(Qty\s+(\d+),\s+Score\s+([0-9.]+)\)", message or "")
    if not m:
        return {"item_name": "", "quantity": "", "score": "", "status": ""}
    sev = m.group(1).strip().title()
    return {
        "item_name": m.group(2).strip(),
        "quantity": m.group(3),
        "score": m.group(4),
        "status": sev,
    }


def _extract_forecast_fields(message):
    # Expected format:
    # Forecast alert (CRITICAL): ITEM — Status: Active | Qty: 12 | Score: 345.00
    m = re.search(
        r"Forecast alert \(([^)]+)\):\s*(.+?)\s+—\s+Status:\s*([^|]+)\|\s*Qty:\s*([^|]+)\|\s*Score:\s*(.+)$",
        message or "",
    )
    if not m:
        return {"item_name": "", "quantity": "", "score": "", "status": ""}
    return {
        "item_name": m.group(2).strip(),
        "quantity": m.group(4).strip(),
        "score": m.group(5).strip(),
        "status": m.group(3).strip(),
    }


def _low_stock_candidates_queryset(pref):
    """Items at or below reorder + buffer (matches previous Python logic; uses SQL)."""
    user_buffer = max(int(pref.low_stock_threshold or 0), 0)
    return (
        Item.objects.filter(is_active=True)
        .annotate(
            _item_thr=Greatest(Coalesce(F("reorder_level"), Value(0)), Value(0)),
        )
        .annotate(
            _eff=ExpressionWrapper(
                F("_item_thr") + Value(user_buffer),
                output_field=IntegerField(),
            )
        )
        .filter(_eff__gt=0, quantity__lte=F("_eff"))
        .order_by("quantity")
    )


def _append_notification_alert(alerts, n):
    msg_lower = (n.message or "").lower()
    source = "anomaly"
    alert_type = "user_notification"
    type_label = _humanize_type("user_notification")
    extra_fields = _extract_anomaly_fields(n.message)

    if msg_lower.startswith("forecast alert ("):
        source = "forecast"
        alert_type = "forecast_risk"
        if "dormant" in msg_lower:
            alert_type = "dormant_stock"
        elif "overstock" in msg_lower or "sell down" in msg_lower:
            alert_type = "overstock"
        type_label = _humanize_type(alert_type)
        extra_fields = _extract_forecast_fields(n.message)

    severity = "info"
    if "critical" in msg_lower or "high" in msg_lower:
        severity = "critical"
    elif "warning" in msg_lower or "medium" in msg_lower:
        severity = "warning"

    alerts.append(
        {
            "type": alert_type,
            "type_label": type_label,
            "is_db_notification": True,
            "source": source,
            "severity": severity,
            "id": n.id,
            "message": n.message,
            "time": n.created_at.strftime("%Y-%m-%d %H:%M"),
            "dismiss_post_url": reverse("dismiss_notification", args=[n.id]),
            "key": f"notification:{n.id}",
            "url": n.url or reverse("anomaly_list"),
            **extra_fields,
        }
    )


def _build_alerts(request, max_notifications=None):
    """
    Build merged alert rows for the current user.

    max_notifications:
      None — include every unread DB notification (Alerts page; may be large).
      int — merge only the newest N DB notifications (fast path for navbar badge/dropdown).
    """
    alerts = []

    can_manage_requests = False
    dismissed = set()

    pref = None
    db_note_count = 0

    if request.user.is_authenticated:
        can_manage_requests = request.user.groups.filter(name__in=["Manager", "Admin"]).exists()
        dismissed = set(request.session.get("dismissed_alerts", []))

        pref_cache_key = f"ctx_user_pref:v6:{request.user.pk}"
        pref = cache.get(pref_cache_key)
        if pref is None:
            pref, _ = UserPreference.objects.get_or_create(user=request.user)
            cache.set(pref_cache_key, pref, 120)

        if pref.notify_anomalies:
            note_filter = Notification.objects.filter(
                user=request.user, is_read=False, dismissed=False
            ).exclude(message__startswith=ANOMALY_SCAN_RESULT_PREFIX)
            db_note_count = note_filter.count()
            qs = note_filter.order_by("-created_at").only("id", "message", "created_at", "url")
            if max_notifications is not None:
                qs = qs[: max_notifications]
                note_iter = qs
            else:
                note_iter = qs.iterator(chunk_size=200)
            for n in note_iter:
                _append_notification_alert(alerts, n)

    # B) Manager access requests (dismiss via session-based dismiss_alert)
    if can_manage_requests:
        pending = (
            ManagerRequest.objects
            .filter(status="PENDING")
            .select_related("user")
            .order_by("-created_at")[:10]
        )

        for r in pending:
            key = f"manager_request:{r.id}"
            if key in dismissed:
                continue

            alerts.append({
                "type": "manager_request",
                "type_label": _humanize_type("manager_request"),
                "is_db_notification": False,
                "source": "access",
                "severity": "warning",
                "id": r.id,
                "message": f"{r.user.username} has requested manager access.",
                "time": r.created_at.strftime("%Y-%m-%d %H:%M"),
                "approve_url": reverse("approve_manager_request", args=[r.id]),
                "decline_url": reverse("decline_manager_request", args=[r.id]),
                "dismiss_post_url": reverse("dismiss_alert"),
                "key": key,
                "url": reverse("dashboard"),
                "item_name": r.user.username,
                "quantity": "",
                "score": "",
                "status": "Pending",
            })

    # C) Low stock (SQL-filtered; session-dismissed keys skipped)
    if request.user.is_authenticated and pref is not None:
        if pref.notify_low_stock:
            for item in _low_stock_candidates_queryset(pref).only(
                "id", "name", "quantity", "reorder_level"
            ):
                user_buffer = max(int(pref.low_stock_threshold or 0), 0)
                item_threshold = max(int(item.reorder_level or 0), 0)
                effective_threshold = item_threshold + user_buffer
                key = f"low_stock:{item.id}"
                if key in dismissed:
                    continue

                alerts.append(
                    {
                        "type": "low_stock",
                        "type_label": _humanize_type("low_stock"),
                        "is_db_notification": False,
                        "source": "stock",
                        "severity": "critical" if item.quantity <= 0 else "warning",
                        "id": item.id,
                        "message": f"Low stock: {item.name} ({item.quantity}/{effective_threshold})",
                        "dismiss_post_url": reverse("dismiss_alert"),
                        "key": key,
                        "url": reverse("item_detail", args=[item.id]),
                        "item_name": item.name,
                        "quantity": item.quantity,
                        "score": "",
                        "status": "Out of stock" if item.quantity <= 0 else "Low stock",
                    }
                )

    # D) Delivered orders recently (dismiss via session-based dismiss_alert)
    if request.user.is_authenticated:
        recent_orders = Order.objects.filter(status="DELIVERED").order_by("-order_date")[:5]
        today = timezone.now().date()
        for order in recent_orders:
            key = f"order_delivered:{order.id}"
            if key in dismissed:
                continue

            alerts.append({
                "type": "order_delivered",
                "type_label": _humanize_type("order_delivered"),
                "is_db_notification": False,
                "source": "orders",
                "severity": "info",
                "id": order.id,
                "message": f"Order #{order.id} delivered",
                "time": f"{(today - order.order_date).days} days ago",
                "dismiss_post_url": reverse("dismiss_alert"),
                "key": key,
                "url": reverse("order_detail", args=[order.id]),
                "item_name": f"Order #{order.id}",
                "quantity": order.total_quantity,
                "score": "",
                "status": "Delivered",
            })

    # Pending manager access requests first, then severity, then time.
    alerts = sorted(
        alerts,
        key=lambda a: (
            0 if a.get("type") == "manager_request" else 1,
            _severity_rank(a.get("severity")),
            a.get("time", ""),
        ),
    )

    # Total for badge: all unread DB notifications + non-dismissed session alerts (not limited merge).
    non_db = [a for a in alerts if not a.get("is_db_notification")]
    total_alert_count = db_note_count + len(non_db)

    return alerts, can_manage_requests, total_alert_count


def get_alerts_for_user(request, limit=10):
    if not request.user.is_authenticated:
        return [], False
    alerts, can_manage_requests, _total = _build_alerts(request, max_notifications=None)
    if limit is not None:
        alerts = alerts[:limit]
    return alerts, can_manage_requests


def notifications(request):
    if not request.user.is_authenticated:
        return {
            "global_alerts": [],
            "alerts_manager_requests": [],
            "alerts_critical": [],
            "alerts_warning": [],
            "alerts_info": [],
            "can_manage_requests": False,
            "anomaly_scan_banner": None,
        }

    # Do not cache navbar notifications: LocMem is per-process, so cache.delete() from
    # dismiss views only clears one worker; other workers could serve stale counts (e.g. on Render).

    all_alerts, can_manage_requests, total_alert_count = _build_alerts(
        request, max_notifications=NAVBAR_NOTIFICATION_MERGE_LIMIT
    )
    alerts = all_alerts[:NOTIFICATIONS_DROPDOWN_LIMIT]

    anomaly_scan_banner = None
    banner_n = (
        Notification.objects.filter(
            user=request.user,
            message__startswith=ANOMALY_SCAN_RESULT_PREFIX,
            dismissed=False,
        )
        .order_by("-created_at")
        .only("id", "message", "url")
        .first()
    )
    if banner_n:
        anomaly_scan_banner = {
            "id": banner_n.id,
            "body": banner_n.message[len(ANOMALY_SCAN_RESULT_PREFIX) :],
            "url": banner_n.url or reverse("dashboard") + "?open_anomalies=1",
        }

    alerts_manager_requests = [a for a in alerts if a.get("type") == "manager_request"]
    rest_dropdown = [a for a in alerts if a.get("type") != "manager_request"]
    alerts_critical = [a for a in rest_dropdown if a.get("severity") == "critical"]
    alerts_warning = [a for a in rest_dropdown if a.get("severity") == "warning"]
    alerts_info = [a for a in rest_dropdown if a.get("severity") == "info"]

    return {
        "global_alerts": alerts,
        "alerts_manager_requests": alerts_manager_requests,
        "global_alerts_count": total_alert_count,
        "alerts_critical": alerts_critical,
        "alerts_warning": alerts_warning,
        "alerts_info": alerts_info,
        "can_manage_requests": can_manage_requests,
        "anomaly_scan_banner": anomaly_scan_banner,
    }


def user_preferences(request):
    if not request.user.is_authenticated:
        return {"user_pref": None}
    cache_key = f"ctx_user_pref:v6:{request.user.pk}"
    pref = cache.get(cache_key)
    if pref is None:
        pref, _ = UserPreference.objects.get_or_create(user=request.user)
        cache.set(cache_key, pref, 120)
    return {"user_pref": pref}


def user_profile_avatar(request):
    if not request.user.is_authenticated:
        return {"profile_avatar_url": None}
    row = (
        UserProfile.objects.filter(user_id=request.user.pk)
        .only("avatar")
        .first()
    )
    if not row or not row.avatar:
        return {"profile_avatar_url": None}
    try:
        return {"profile_avatar_url": row.avatar.url}
    except ValueError:
        return {"profile_avatar_url": None}