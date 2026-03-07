from django.db.models import F
from django.utils import timezone
from django.urls import reverse

from inventory.models import Item, Order
from .models import ManagerRequest, Notification, UserPreference


def notifications(request):
    alerts = []

    can_manage_requests = False
    dismissed = set()

    pref = None
    if request.user.is_authenticated:
        can_manage_requests = request.user.groups.filter(name__in=["Manager", "Admin"]).exists()
        dismissed = set(request.session.get("dismissed_alerts", []))

        # Load user preferences once (so we can reuse below)
        pref, _ = UserPreference.objects.get_or_create(user=request.user)

        # A) DB-backed notifications (dismiss via dismiss_notification view -> sets is_read=True)
        # Respect anomaly notification preference
        if pref.notify_anomalies:
            user_notes = (
                Notification.objects
                .filter(user=request.user, is_read=False, dismissed=False)
                .order_by("-created_at")[:20]
            )

            for n in user_notes:
                alerts.append({
                    "type": "user_notification",
                    "id": n.id,
                    "message": n.message,
                    "time": n.created_at.strftime("%Y-%m-%d %H:%M"),
                    "dismiss_post_url": reverse("dismiss_notification", args=[n.id]),
                    "key": f"notification:{n.id}",
                    "url": reverse("anomaly_list"),
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
                "id": r.id,
                "message": f"{r.user.username} has requested manager access.",
                "time": r.created_at.strftime("%Y-%m-%d %H:%M"),
                "approve_url": reverse("approve_manager_request", args=[r.id]),
                "decline_url": reverse("decline_manager_request", args=[r.id]),
                "dismiss_post_url": reverse("dismiss_alert"),
                "key": key,
                "url": reverse("anomaly_list"),
            })

    # C) Low stock items (dismiss via session-based dismiss_alert)
    # Respect low stock notification preference (only if authenticated)
    if request.user.is_authenticated:
        if pref is None:
            pref, _ = UserPreference.objects.get_or_create(user=request.user)

        if pref.notify_low_stock:
            low_stock_items = Item.objects.filter(quantity__lte=F("reorder_level"))
            for item in low_stock_items:
                key = f"low_stock:{item.id}"
                if key in dismissed:
                    continue

                alerts.append({
                    "type": "low_stock",
                    "id": item.id,
                    "message": f"Low stock: {item.name}",
                    "dismiss_post_url": reverse("dismiss_alert"),
                    "key": key,
                    "url": reverse("anomaly_list"),
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
            "id": order.id,
            "message": f"Order #{order.id} delivered",
            "time": f"{(today - order.order_date).days} days ago",
            "dismiss_post_url": reverse("dismiss_alert"),
            "key": key,
            "url": reverse("anomaly_list"),
        })

    return {
        "global_alerts": alerts[:10],
        "can_manage_requests": can_manage_requests,
    }


def user_preferences(request):
    if not request.user.is_authenticated:
        return {"user_pref": None}
    pref, _ = UserPreference.objects.get_or_create(user=request.user)
    return {"user_pref": pref}