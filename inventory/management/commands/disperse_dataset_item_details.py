"""
Vary item master data for rows still tied to the dataset import supplier: reorder levels
(from current stock, without changing on-hand qty), unit cost, stock status (mostly OK),
expiry (mostly blank / long-dated), and assign a plausible supplier per item (create if
missing). Optionally shift related order and stock-history dates into [2025-01-01, now]
with a bias toward more recent dates.

On-hand quantity is never modified so totals stay consistent with orders and stock history.

Uses the same keyword buckets as disperse_imported_categories for supplier choice.

Usage:
  python manage.py disperse_dataset_item_details --dry-run
  python manage.py disperse_dataset_item_details
  python manage.py disperse_dataset_item_details --source-supplier "Dataset Supplier" --no-orders
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from random import Random

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from inventory.management.commands.disperse_imported_categories import classify_item
from inventory.models import Item, Order, OrderLine, StockHistory, Supplier


BUCKET_TO_SUPPLIER_NAME = {
    "Seasonal & gifts": "Seasonal Imports Ltd",
    "Kitchen & dining": "KitchenCraft Wholesale Ltd",
    "Candles & lighting": "Brightwick Supplies Ltd",
    "Home décor": "Homestyle Wholesale Ltd",
    "Party & entertaining": "Party Pro Distributors Ltd",
    "Crafts & textiles": "Thread & Bolt Traders Ltd",
    "Bags & storage": "Pack & Carry Imports Ltd",
    "Bathroom & wellness": "AquaSoft Wholesale Ltd",
    "Toys & novelty": "Playwell Merchandising Ltd",
    "Stationery & office": "Deskline Office Supplies Ltd",
    "Garden & outdoor": "Greenfield Outdoors Ltd",
    "Electronics & accessories": "TechSource Wholesale Ltd",
    "Jewellery & accessories": "Adorn Wholesale Ltd",
    "Table linens": "Linen Loft Ltd",
    "Homeware general": "Meridian General Imports Ltd",
    "Giftware": "Ribbon Box Wholesale Ltd",
}


def _rng(sku: str) -> Random:
    digest = hashlib.md5((sku or "").encode("utf-8")).digest()
    return Random(int.from_bytes(digest[:8], "big"))


def supplier_name_for_item(item: Item) -> str:
    bucket = classify_item(item.name, item.description or "", item.sku)
    return BUCKET_TO_SUPPLIER_NAME.get(bucket, "Meridian General Imports Ltd")


def first_or_create_supplier(name: str) -> Supplier:
    existing = Supplier.objects.filter(name=name).order_by("pk").first()
    if existing:
        return existing
    return Supplier.objects.create(name=name)


def pick_stock_status(r: Random) -> str:
    x = r.random()
    if x < 0.86:
        return "OK"
    if x < 0.91:
        return "damaged"
    if x < 0.94:
        return "quarantine"
    if x < 0.97:
        return "returned"
    return "on_hold"


def pick_expiry_date(r: Random, today):
    x = r.random()
    if x < 0.78:
        return None
    if x < 0.93:
        start = today + timedelta(days=120)
        end = today + timedelta(days=720)
        delta = (end - start).days
        return start + timedelta(days=r.randint(0, max(0, delta)))
    start = today + timedelta(days=21)
    end = today + timedelta(days=90)
    delta = (end - start).days
    return start + timedelta(days=r.randint(0, max(0, delta)))


def skewed_datetime_between(r: Random, start: datetime, end: datetime) -> datetime:
    if end <= start:
        return start
    span = (end - start).total_seconds()
    u = r.random() ** 0.62
    return start + timedelta(seconds=u * span)


class Command(BaseCommand):
    help = (
        "Disperses non-stock fields on dataset items (supplier, reorder, cost, status, "
        "expiry, created_at); leaves on-hand quantity unchanged; optional order/history dates."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-supplier",
            type=str,
            default="Dataset Supplier",
            help='Only items with this supplier name (default: "Dataset Supplier")',
        )
        parser.add_argument("--dry-run", action="store_true", help="Print summary only")
        parser.add_argument(
            "--no-orders",
            action="store_true",
            help="Do not change order_date / created_at on fully-in-scope orders",
        )
        parser.add_argument(
            "--no-stock-history",
            action="store_true",
            help="Do not remap StockHistory rows dated before 2025",
        )
        parser.add_argument(
            "--also-category",
            type=str,
            default="",
            metavar="NAME",
            help='Also include items in this category (e.g. "Imported Dataset") in addition to --source-supplier',
        )

    def handle(self, *args, **opts):
        source = opts["source_supplier"]
        also_cat = (opts["also_category"] or "").strip()
        dry = opts["dry_run"]
        touch_orders = not opts["no_orders"]
        touch_history = not opts["no_stock_history"]

        flt = Q(supplier__name=source)
        if also_cat:
            flt |= Q(category__name=also_cat)
        items = list(Item.objects.filter(flt).select_related("supplier", "category").distinct())
        if not items:
            hint = f' supplier "{source}"' + (f' or category "{also_cat}"' if also_cat else "")
            self.stdout.write(self.style.WARNING(f"No items matching{hint}. Nothing to do."))
            return

        item_ids = frozenset(i.pk for i in items)
        today = timezone.now().date()
        now = timezone.now()
        date_min = timezone.make_aware(datetime(2025, 1, 1, 0, 0, 0))

        name_counts: Counter = Counter()
        for it in items:
            name_counts[supplier_name_for_item(it)] += 1

        self.stdout.write(self.style.NOTICE("Planned supplier assignment (by name):"))
        for nm, c in name_counts.most_common():
            self.stdout.write(f"  {nm}: {c} items")
        self.stdout.write(
            self.style.NOTICE(
                "On-hand quantity is left unchanged (consistent with orders / stock history)."
            )
        )

        to_update: list[Item] = []
        status_counts: Counter = Counter()
        expiry_with = 0

        for it in items:
            r = _rng(it.sku)
            sup_name = supplier_name_for_item(it)
            if not dry:
                it.supplier = first_or_create_supplier(sup_name)

            q = int(it.quantity)
            if q <= 0:
                it.reorder_level = r.randint(8, 28)
            else:
                cap = max(1, q - 1) if q > 1 else 3
                it.reorder_level = max(3, min(int(q * r.uniform(0.09, 0.22)), cap))

            base_cost = float(it.unit_cost or 0)
            if base_cost <= 0 or base_cost == 1.0:
                unit = Decimal(str(round(r.uniform(0.89, 22.5), 2)))
            else:
                unit = Decimal(str(round(max(0.35, min(89.0, base_cost * r.uniform(0.75, 1.35))), 2)))
            it.unit_cost = unit

            st = pick_stock_status(r)
            it.stock_status = st
            status_counts[st] += 1

            ex = pick_expiry_date(r, today)
            it.expiry_date = ex
            if ex is not None:
                expiry_with += 1

            if not dry:
                it.created_at = skewed_datetime_between(r, date_min, now)

            to_update.append(it)

        self.stdout.write(self.style.NOTICE("Stock status mix:"))
        for k, v in status_counts.most_common():
            self.stdout.write(f"  {k}: {v}")
        self.stdout.write(f"  (items with expiry_date set: {expiry_with})")

        orders_to_shift: list[Order] = []
        if touch_orders:
            touched_orders = set(
                OrderLine.objects.filter(item_id__in=item_ids).values_list("order_id", flat=True)
            )
            mixed_orders = set(
                OrderLine.objects.filter(order_id__in=touched_orders)
                .exclude(item_id__in=item_ids)
                .values_list("order_id", flat=True)
            )
            full_order_ids = touched_orders - mixed_orders
            orders_to_shift = list(Order.objects.filter(pk__in=full_order_ids))
            self.stdout.write(
                self.style.NOTICE(
                    f"Orders with only dataset-supplier items (will shift dates): {len(orders_to_shift)}"
                )
            )

        history_rows: list[StockHistory] = []
        if touch_history:
            cutoff = datetime(2025, 1, 1).date()
            history_rows = list(
                StockHistory.objects.filter(item_id__in=item_ids, date__lt=cutoff).select_related("item")
            )
            self.stdout.write(
                self.style.NOTICE(f"StockHistory rows before 2025-01-01 to remap: {len(history_rows)}")
            )

        if dry:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN — would update {len(to_update)} items; "
                    f"{len(orders_to_shift)} orders; {len(history_rows)} stock history rows."
                )
            )
            return

        with transaction.atomic():
            Item.objects.bulk_update(
                to_update,
                [
                    "supplier",
                    "reorder_level",
                    "unit_cost",
                    "stock_status",
                    "expiry_date",
                    "created_at",
                ],
                batch_size=400,
            )

            for ord_ in orders_to_shift:
                r = _rng(f"ord{ord_.pk}")
                new_dt = skewed_datetime_between(r, date_min, now)
                ord_.order_date = new_dt.date()
                ord_.created_at = new_dt
            if orders_to_shift:
                Order.objects.bulk_update(orders_to_shift, ["order_date", "created_at"], batch_size=400)

            remap_start = datetime(2025, 1, 1).date()
            remap_end = today
            for sh in history_rows:
                r = _rng(f"sh{sh.pk}{sh.item.sku}")
                span = (remap_end - remap_start).days
                sh.date = remap_start + timedelta(days=r.randint(0, max(0, span)))
            if history_rows:
                StockHistory.objects.bulk_update(history_rows, ["date"], batch_size=500)

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated {len(to_update)} items; {len(orders_to_shift)} orders; "
                f"{len(history_rows)} stock history rows."
            )
        )
