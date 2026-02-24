from django.db.models import F
from django.utils import timezone
from django.urls import reverse

from inventory.models import Item, Order
from .models import ManagerRequest, Notification


def notifications(request):
    alerts = []

    can_manage_requests = False
    dismissed = set()

    if request.user.is_authenticated:
        can_manage_requests = request.user.groups.filter(name__in=["Manager", "Admin"]).exists()
        dismissed = set(request.session.get("dismissed_alerts", []))

        # A) DB-backed notifications (dismiss via dismiss_notification view -> sets is_read=True)
        user_notes = (
            Notification.objects
            .filter(user=request.user, is_read=False)
            .order_by("-created_at")[:20]
        )

        for n in user_notes:
            alerts.append({
                "type": "user_notification",
                "id": n.id,
                "message": n.message,
                "time": n.created_at.strftime("%Y-%m-%d %H:%M"),
                # IMPORTANT: this X must post to dismiss_notification, not dismiss_alert
                "dismiss_post_url": reverse("dismiss_notification", args=[n.id]),
                # keep a consistent key field so your template can always reference alert.key safely
                "key": f"notification:{n.id}",
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
            })

    # C) Low stock items (dismiss via session-based dismiss_alert)
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
        })

    return {
        "global_alerts": alerts[:10],
        "can_manage_requests": can_manage_requests,
    }