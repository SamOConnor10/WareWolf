"""
Assign varied customers to sale orders that still use the generic import client,
using the same keyword buckets as disperse_imported_categories (via classify_item).
Creates missing Client rows (reuses first row if duplicate names exist).

Usage:
  python manage.py disperse_imported_sale_clients --dry-run
  python manage.py disperse_imported_sale_clients
  python manage.py disperse_imported_sale_clients --source-client "Imported Customer"
"""

from __future__ import annotations

import hashlib
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Prefetch

from inventory.management.commands.disperse_imported_categories import classify_item
from inventory.models import Client, Order, OrderLine


# Plausible retail / wholesale buyers per product bucket (not the same strings as suppliers).
BUCKET_TO_CLIENT_NAME = {
    "Seasonal & gifts": "Grafton Seasonal Retailers",
    "Kitchen & dining": "Dublin Kitchen & Table Co.",
    "Candles & lighting": "Bright Home Stores Ireland",
    "Home décor": "Homestyle Interiors Group",
    "Party & entertaining": "Celebrate More Wholesale",
    "Crafts & textiles": "Maker's Market Supply",
    "Bags & storage": "Pack & Carry Retail Chain",
    "Bathroom & wellness": "Aqua Living Outlets",
    "Toys & novelty": "Playtown Toy Shops",
    "Stationery & office": "Office & Desk Direct",
    "Garden & outdoor": "Greenfield Garden Centres",
    "Electronics & accessories": "TechSource Retail Partners",
    "Jewellery & accessories": "Adorn Boutique Network",
    "Table linens": "Linen Loft Stores",
    "Homeware general": "Meridian Homeware Buyers",
    "Giftware": "Ribbon Box Gift Shops",
}

FALLBACK_CLIENT_NAMES = (
    "Nationwide Homeware Stockists",
    "Urban Retail Collective",
    "Coastal Trading Company",
    "Metro Buyers Group",
    "All-Ireland Gift Distributors",
)


def _fallback_client_name(sku: str) -> str:
    h = int(hashlib.md5((sku or "").encode("utf-8")).hexdigest()[:8], 16)
    return FALLBACK_CLIENT_NAMES[h % len(FALLBACK_CLIENT_NAMES)]


def client_name_for_item(item) -> str:
    bucket = classify_item(item.name, getattr(item, "description", None) or "", item.sku)
    if bucket in BUCKET_TO_CLIENT_NAME:
        return BUCKET_TO_CLIENT_NAME[bucket]
    return _fallback_client_name(item.sku)


def first_or_create_client(name: str) -> Client:
    found = Client.objects.filter(name=name).order_by("pk").first()
    if found:
        return found
    return Client.objects.create(name=name)


def representative_item(order) -> OrderLine | None:
    lines = list(order.lines.all())
    if not lines:
        return None
    lines.sort(key=lambda ln: (ln.pk,))
    return lines[0]


class Command(BaseCommand):
    help = (
        "Reassign sale orders from a generic import client to keyword-based customers "
        "(creates Client rows as needed)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-client",
            type=str,
            default="Imported Customer",
            help='Only sale orders with this client name (default: "Imported Customer")',
        )
        parser.add_argument("--dry-run", action="store_true", help="Print plan only")

    def handle(self, *args, **opts):
        source = opts["source_client"]
        dry = opts["dry_run"]

        line_qs = OrderLine.objects.select_related("item")
        orders = (
            Order.objects.filter(order_type=Order.TYPE_SALE, client__name=source)
            .select_related("client")
            .prefetch_related(Prefetch("lines", queryset=line_qs))
            .order_by("pk")
        )

        to_update: list[Order] = []
        skipped = 0
        name_counts: Counter = Counter()

        for order in orders:
            line = representative_item(order)
            if line is None or not getattr(line, "item_id", None):
                skipped += 1
                continue
            item = line.item
            if item is None:
                skipped += 1
                continue
            nm = client_name_for_item(item)
            name_counts[nm] += 1
            if dry:
                to_update.append(order)
                continue
            order.client = first_or_create_client(nm)
            to_update.append(order)

        self.stdout.write(self.style.NOTICE("Planned customer assignment (counts):"))
        for nm, c in name_counts.most_common():
            self.stdout.write(f"  {nm}: {c} orders")

        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped orders with no lines: {skipped}"))

        if dry:
            self.stdout.write(
                self.style.WARNING(f"DRY RUN — would update {len(to_update)} sale orders.")
            )
            return

        with transaction.atomic():
            Order.objects.bulk_update(to_update, ["client"], batch_size=500)

        self.stdout.write(
            self.style.SUCCESS(f"Updated {len(to_update)} sale orders (client reassigned).")
        )
