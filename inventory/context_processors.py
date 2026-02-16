from django.db.models import F
from django.utils import timezone
from django.urls import reverse

from inventory.models import Item, Order
from .models import ManagerRequest


def notifications(request):
    """Make alerts globally available on all pages."""

    alerts = []

    # Safe boolean for templates (avoid calling queryset methods in templates)
    can_manage_requests = False
    if request.user.is_authenticated:
        can_manage_requests = request.user.groups.filter(name__in=["Manager", "Admin"]).exists()

    # Manager access requests (only for Manager/Admin)
    if can_manage_requests:
        pending = (
            ManagerRequest.objects
            .filter(status="PENDING")
            .select_related("user")
            .order_by("-created_at")[:10]
        )

        for r in pending:
            alerts.append({
                "type": "manager_request",
                "id": r.id,
                "message": f"{r.user.username} has requested manager access.",
                "time": r.created_at.strftime("%Y-%m-%d %H:%M"),
                "approve_url": reverse("approve_manager_request", args=[r.id]),
                "decline_url": reverse("decline_manager_request", args=[r.id]),
            })

    # Low stock items
    low_stock_items = Item.objects.filter(quantity__lte=F("reorder_level"))
    for item in low_stock_items:
        alerts.append({
            "type": "low_stock",
            "message": f"Low stock: {item.name}",
        })

    # Delivered orders recently
    recent_orders = Order.objects.filter(status="DELIVERED").order_by("-order_date")[:5]
    today = timezone.now().date()
    for order in recent_orders:
        alerts.append({
            "type": "order_delivered",
            "message": f"Order #{order.id} delivered",
            "time": f"{(today - order.order_date).days} days ago",
        })

    return {
        "global_alerts": alerts[:10],
        "can_manage_requests": can_manage_requests,
    }
