from django.db.models import F
from django.utils import timezone
from django.urls import reverse
from django.core.cache import cache
import re

from inventory.models import Item, Order
from .models import ManagerRequest, Notification, UserPreference, UserProfile

NOTIFICATIONS_DROPDOWN_LIMIT = 25


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


def _build_alerts(request):
    alerts = []

    can_manage_requests = False
    dismissed = set()

    pref = None
    if request.user.is_authenticated:
        can_manage_requests = request.user.groups.filter(name__in=["Manager", "Admin"]).exists()
        dismissed = set(request.session.get("dismissed_alerts", []))

        # Load user preferences once (so we can reuse below)
        pref, _ = UserPreference.objects.get_or_create(user=request.user)

        # A) DB-backed notifications (dismiss -> is_read + dismissed on Notification).
        # These records are created by anomaly / forecast jobs only — respect demand-anomaly pref.
        # Low-stock line items are built separately in section C from live stock quantities.
        if pref.notify_anomalies:
            # Load all active DB notifications for counting and the Alerts page. A low slice (e.g. [:20])
            # made len(merged alerts) stay flat while unread rows remained: dismissing one only swapped in
            # the next row, so the badge/totals never dropped until the backlog fell below the slice size.
            user_notes = (
                Notification.objects
                .filter(user=request.user, is_read=False, dismissed=False)
                .order_by("-created_at")[:2000]
            )

            for n in user_notes:
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

                alerts.append({
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
                })

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

    # C) Low stock items (dismiss via session-based dismiss_alert)
    # Respect low stock notification preference (only if authenticated)
    if request.user.is_authenticated:
        if pref is None:
            pref, _ = UserPreference.objects.get_or_create(user=request.user)

        if pref.notify_low_stock:
            low_stock_items = Item.objects.filter(is_active=True).order_by("quantity")[:300]
            for item in low_stock_items:
                user_buffer = max(int(pref.low_stock_threshold or 0), 0)
                item_threshold = max(int(item.reorder_level or 0), 0)
                # Alert when quantity is at or below reorder level plus optional early-warning buffer.
                effective_threshold = item_threshold + user_buffer
                if effective_threshold <= 0:
                    continue
                if item.quantity > effective_threshold:
                    continue

                key = f"low_stock:{item.id}"
                if key in dismissed:
                    continue

                alerts.append({
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
                })

    # D) Delivered orders recently (dismiss via session-based dismiss_alert)
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

    alerts = sorted(alerts, key=lambda a: (_severity_rank(a.get("severity")), a.get("time", "")))
    return alerts, can_manage_requests


def get_alerts_for_user(request, limit=10):
    if not request.user.is_authenticated:
        return [], False
    alerts, can_manage_requests = _build_alerts(request)
    if limit is not None:
        alerts = alerts[:limit]
    return alerts, can_manage_requests


def notifications(request):
    if not request.user.is_authenticated:
        return {
            "global_alerts": [],
            "alerts_critical": [],
            "alerts_warning": [],
            "alerts_info": [],
            "can_manage_requests": False,
        }

    # Do not cache navbar notifications: LocMem is per-process, so cache.delete() from
    # dismiss views only clears one worker; other workers could serve stale counts (e.g. on Render).

    all_alerts, can_manage_requests = get_alerts_for_user(request, limit=None)
    total_alert_count = len(all_alerts)
    alerts = all_alerts[:NOTIFICATIONS_DROPDOWN_LIMIT]

    alerts_critical = [a for a in alerts if a.get("severity") == "critical"]
    alerts_warning = [a for a in alerts if a.get("severity") == "warning"]
    alerts_info = [a for a in alerts if a.get("severity") == "info"]

    return {
        "global_alerts": alerts,
        "global_alerts_count": total_alert_count,
        "alerts_critical": alerts_critical,
        "alerts_warning": alerts_warning,
        "alerts_info": alerts_info,
        "can_manage_requests": can_manage_requests,
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