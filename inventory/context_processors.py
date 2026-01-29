from inventory.models import Item, Order
from django.db.models import F
from django.utils import timezone

def notifications(request):
    """Make alerts globally available on all pages."""
    
    alerts = []

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
            "time": f"{(today - order.order_date).days} days ago"
        })

    # Sort descending by newest-looking
    return {
        "global_alerts": alerts[:10]  # limit to 10 alerts
    }
