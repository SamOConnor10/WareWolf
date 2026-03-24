import datetime
import hashlib
import json
from decimal import Decimal
from typing import Dict, Iterable, Optional, Set

from django.db.models import F, Sum
from django.utils import timezone

from .models import (
    Item,
    Order,
    OrderLine,
    Recommendation,
    StockHistory,
)


# -----------------------------
# Thresholds / configuration
# -----------------------------

RECENT_USAGE_DAYS = 30
TYPICAL_USAGE_DAYS = 90
DORMANT_DAYS = 365
OVERSTOCK_MULTIPLIER = Decimal("3.0")
LOW_STOCK_WINDOW_DAYS = 7
MIN_ACTIVITY_FOR_OVERSTOCK = 10  # minimum historical sales qty to trust overstock signal


def _hash_conditions(data: Dict) -> str:
    """Return a stable hash for the given metric dict."""
    payload = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _upsert_recommendation(
    *,
    item: Item,
    rec_type: str,
    title: str,
    reason: str,
    priority: int,
    metrics: Dict,
    suggested_quantity: Optional[int] = None,
    suggested_supplier=None,
    suggested_customer=None,
    target_date: Optional[datetime.date] = None,
    stock_value: Optional[Decimal] = None,
) -> Recommendation:
    """
    Create or update a Recommendation for the given item/type based on a metrics signature.

    - If an ACTIVE recommendation with the same source_hash exists, update it in place.
    - If an ACTIVE recommendation with a different hash exists, expire it and create a new ACTIVE row.
    - If only non-active rows exist with this hash, do nothing (avoids recreating a dismissed/accepted
      recommendation until conditions change meaningfully).
    """
    source_hash = _hash_conditions(metrics)

    qs = Recommendation.objects.filter(
        item=item,
        recommendation_type=rec_type,
    )
    active = qs.filter(status=Recommendation.STATUS_ACTIVE).first()

    # If there is already any recommendation (of any status) with the same hash, we generally
    # do not want to recreate it unless it is ACTIVE (which we handle above).
    same_hash_exists = qs.filter(source_hash=source_hash).exclude(
        status=Recommendation.STATUS_ACTIVE
    ).exists()

    if active and active.source_hash == source_hash:
        # Update in place
        active.title = title
        active.reason = reason
        active.priority = priority
        active.suggested_quantity = suggested_quantity
        active.suggested_supplier = suggested_supplier
        active.suggested_customer = suggested_customer
        active.target_date = target_date
        active.stock_value = stock_value
        active.metadata = metrics
        active.source_hash = source_hash
        active.save()
        return active

    if active and active.source_hash != source_hash:
        # Conditions changed – expire old one
        active.status = Recommendation.STATUS_EXPIRED
        active.save(update_fields=["status", "updated_at"])

    if not active and same_hash_exists:
        # Previously dismissed/accepted with same conditions; don't recreate yet.
        return qs.filter(source_hash=source_hash).order_by("-created_at").first()

    rec = Recommendation.objects.create(
        item=item,
        recommendation_type=rec_type,
        status=Recommendation.STATUS_ACTIVE,
        priority=priority,
        title=title,
        reason=reason,
        suggested_quantity=suggested_quantity,
        suggested_supplier=suggested_supplier,
        suggested_customer=suggested_customer,
        target_date=target_date,
        source_hash=source_hash,
        stock_value=stock_value,
        metadata=metrics,
    )
    return rec


def _expire_missing_types(item: Item, generated_types: Set[str]) -> None:
    """Mark ACTIVE recommendations for this item as EXPIRED if their type wasn't regenerated."""
    for rec in Recommendation.objects.filter(
        item=item, status=Recommendation.STATUS_ACTIVE
    ):
        if rec.recommendation_type not in generated_types:
            rec.status = Recommendation.STATUS_EXPIRED
            rec.save(update_fields=["status", "updated_at"])


def recalculate_recommendations_for_item(item: Item) -> None:
    """
    Recalculate all recommendation types for a single item.

    This is item-centric and relatively cheap; callers can loop over items.
    """
    today = timezone.now().date()
    generated: Set[str] = set()

    # Basic current state
    qty = item.quantity
    reorder_level = max(item.reorder_level, 0)
    unit_cost = item.unit_cost or Decimal("0")

    # Sales history
    recent_from = today - datetime.timedelta(days=RECENT_USAGE_DAYS)
    typical_from = today - datetime.timedelta(days=TYPICAL_USAGE_DAYS)

    recent_sales_qs = OrderLine.objects.filter(
        item=item,
        order__order_type=Order.TYPE_SALE,
        order__order_date__gte=recent_from,
    )
    recent_sales_qty = (
        recent_sales_qs.aggregate(q=Sum("quantity"))["q"] or 0
    )
    recent_sales_orders = recent_sales_qs.values("order_id").distinct().count()

    typical_sales_qs = OrderLine.objects.filter(
        item=item,
        order__order_type=Order.TYPE_SALE,
        order__order_date__gte=typical_from,
    )
    typical_sales_qty = (
        typical_sales_qs.aggregate(q=Sum("quantity"))["q"] or 0
    )

    typical_months = max(TYPICAL_USAGE_DAYS / 30.0, 1.0)
    typical_monthly_usage = (
        Decimal(typical_sales_qty) / Decimal(typical_months)
        if typical_sales_qty
        else Decimal("0")
    )

    # Movement history (for dormancy)
    dormant_from = today - datetime.timedelta(days=DORMANT_DAYS)
    recent_stock_history_exists = StockHistory.objects.filter(
        item=item, date__gte=dormant_from
    ).exists()
    recent_sales_exists = typical_sales_qs.exists()

    # ------------------------
    # PURCHASE DEMAND
    # ------------------------
    low_stock = qty <= max(reorder_level, item.safety_stock or 0)
    active_demand = recent_sales_qty > 0 or recent_sales_orders > 0

    if low_stock and active_demand:
        # naive reorder: bring stock up to ~2x reorder level or 1 month of usage
        target_level = max(
            reorder_level * 2,
            int(typical_monthly_usage) or reorder_level * 2 or 1,
        )
        recommended_qty = max(target_level - qty, 1)

        metrics = {
            "kind": "purchase_demand",
            "qty": qty,
            "reorder_level": reorder_level,
            "recent_sales_qty": recent_sales_qty,
            "recent_sales_orders": recent_sales_orders,
            "typical_sales_qty": typical_sales_qty,
            "typical_monthly_usage": str(typical_monthly_usage),
        }
        reason_parts = []
        if qty <= 0:
            reason_parts.append("Out of stock")
        elif qty <= reorder_level:
            reason_parts.append("Below reorder level")
        if recent_sales_orders:
            reason_parts.append(
                f"Sold in {recent_sales_orders} orders in last {RECENT_USAGE_DAYS} days"
            )
        elif recent_sales_qty:
            reason_parts.append(
                f"{recent_sales_qty} units sold in last {RECENT_USAGE_DAYS} days"
            )
        reason = " · ".join(reason_parts) or "Low stock with recent demand"

        priority = Recommendation.PRIORITY_CRITICAL if qty <= 0 else Recommendation.PRIORITY_HIGH
        target_date = today + datetime.timedelta(
            days=item.lead_time_days or 7
        )
        stock_value = unit_cost * Decimal(recommended_qty)

        _upsert_recommendation(
            item=item,
            rec_type=Recommendation.TYPE_PURCHASE_DEMAND,
            title=f"Reorder {item.name}",
            reason=reason,
            priority=priority,
            metrics=metrics,
            suggested_quantity=recommended_qty,
            suggested_supplier=item.supplier,
            target_date=target_date,
            stock_value=stock_value,
        )
        generated.add(Recommendation.TYPE_PURCHASE_DEMAND)

    # ------------------------
    # OVERSTOCK ALERT / SALES RECOMMENDATION
    # ------------------------
    if typical_monthly_usage > 0 and qty > 0:
        overstock_threshold = typical_monthly_usage * OVERSTOCK_MULTIPLIER
        if qty > overstock_threshold and typical_sales_qty >= MIN_ACTIVITY_FOR_OVERSTOCK:
            multiplier = (
                Decimal(qty) / overstock_threshold
                if overstock_threshold > 0
                else Decimal("0")
            )
            metrics = {
                "kind": "overstock",
                "qty": qty,
                "typical_monthly_usage": str(typical_monthly_usage),
                "overstock_threshold": str(overstock_threshold),
                "multiplier": str(multiplier),
            }
            reason = (
                f"Stock level is {multiplier:.1f}× higher than typical monthly usage "
                f"({qty} vs ≈{int(typical_monthly_usage)} per month)"
            )
            # Suggest selling down towards 2× monthly usage
            target_level = int(typical_monthly_usage * 2)
            suggested_qty = max(qty - target_level, 1)
            stock_value = unit_cost * Decimal(suggested_qty)

            _upsert_recommendation(
                item=item,
                rec_type=Recommendation.TYPE_SALES_OVERSTOCK,
                title=f"Consider selling down {item.name}",
                reason=reason,
                priority=Recommendation.PRIORITY_MEDIUM,
                metrics=metrics,
                suggested_quantity=suggested_qty,
                stock_value=stock_value,
            )
            generated.add(Recommendation.TYPE_SALES_OVERSTOCK)

            # Also track as a general overstock alert (for dashboard/notifications)
            _upsert_recommendation(
                item=item,
                rec_type=Recommendation.TYPE_OVERSTOCK_ALERT,
                title=f"Overstock: {item.name}",
                reason=reason,
                priority=Recommendation.PRIORITY_MEDIUM,
                metrics=metrics,
                suggested_quantity=None,
                stock_value=unit_cost * Decimal(qty),
            )
            generated.add(Recommendation.TYPE_OVERSTOCK_ALERT)

    # ------------------------
    # DORMANT STOCK
    # ------------------------
    if not recent_stock_history_exists and not recent_sales_exists and qty > 0:
        # No movements or sales within dormant window
        metrics = {
            "kind": "dormant",
            "qty": qty,
            "dormant_days": DORMANT_DAYS,
        }
        reason = (
            f"No stock movement or sales for at least {DORMANT_DAYS} days "
            f"while {qty} units remain in stock."
        )
        stock_value = unit_cost * Decimal(qty)

        _upsert_recommendation(
            item=item,
            rec_type=Recommendation.TYPE_DORMANT_STOCK,
            title=f"Dormant stock: {item.name}",
            reason=reason,
            priority=Recommendation.PRIORITY_LOW,
            metrics=metrics,
            stock_value=stock_value,
        )
        generated.add(Recommendation.TYPE_DORMANT_STOCK)

    # Expire any active recommendations whose conditions no longer hold
    _expire_missing_types(item, generated)


def recalculate_recommendations_for_items(items: Iterable[Item]) -> None:
    for item in items:
        recalculate_recommendations_for_item(item)


def recalculate_all_recommendations() -> None:
    items = Item.objects.filter(is_active=True)
    recalculate_recommendations_for_items(items)


RECALC_CACHE_KEY = "warewolf_recommendations_recalc"
RECALC_CACHE_SECONDS = 300  # 5 minutes


def ensure_recommendations_fresh() -> None:
    """
    Run full recalculation only if we haven't done so recently.
    Throttles the expensive per-item recalc to avoid slowing every page load.
    """
    from django.core.cache import cache

    if cache.get(RECALC_CACHE_KEY):
        return
    recalculate_all_recommendations()
    cache.set(RECALC_CACHE_KEY, True, RECALC_CACHE_SECONDS)


def get_recommendations_for_context(context_type: str, limit: int = 10):
    """
    Return a queryset of active recommendations appropriate for a UI context.

    context_type:
        - 'dashboard'
        - 'purchase'
        - 'sale'
    """
    qs = Recommendation.objects.filter(status=Recommendation.STATUS_ACTIVE).select_related(
        "item", "suggested_supplier", "suggested_customer"
    )

    if context_type == "purchase":
        # Only items to buy (low/out of stock); dormant/overstock suggest selling, not buying
        qs = qs.filter(recommendation_type=Recommendation.TYPE_PURCHASE_DEMAND)
    elif context_type == "sale":
        qs = qs.filter(
            recommendation_type__in=[
                Recommendation.TYPE_SALES_OVERSTOCK,
                Recommendation.TYPE_DORMANT_STOCK,
                Recommendation.TYPE_OVERSTOCK_ALERT,
            ]
        )
    else:  # dashboard
        # Show a mix of the most important items
        qs = qs.filter(
            recommendation_type__in=[
                Recommendation.TYPE_PURCHASE_DEMAND,
                Recommendation.TYPE_SALES_OVERSTOCK,
                Recommendation.TYPE_DORMANT_STOCK,
                Recommendation.TYPE_OVERSTOCK_ALERT,
            ]
        )

    return qs.order_by("priority", "-stock_value", "-created_at")[:limit]

