"""
Add modest purchase/sale orders so the dashboard "Weekly Orders Activity" chart shows
both colours. Past weeks (oldest 5 of the 6-week window) get purchase orders only so
existing sale history is not inflated. The current calendar week gets a small mix of
purchase and sale orders.

Safe to run once per environment; use --force to seed again (creates additional rows).

Usage:
  python manage.py seed_weekly_orders_chart --dry-run
  python manage.py seed_weekly_orders_chart
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from inventory.models import Client, Item, Location, Order, OrderLine, Supplier


REF_PREFIX = "WW-SEED-CHART"


def monday_of(d):
    return d - timedelta(days=d.weekday())


def day_in_week(week_start, seq: int):
    h = int(hashlib.md5(f"{week_start.isoformat()}-{seq}".encode()).hexdigest()[:8], 16)
    return week_start + timedelta(days=h % 7)


class Command(BaseCommand):
    help = "Seed purchase/sale orders for a balanced weekly orders dashboard chart."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show plan only")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even if WW-SEED-CHART orders already exist",
        )
        parser.add_argument(
            "--purchase-past-min",
            type=int,
            default=55,
            help="Minimum purchase orders per past week (default 55)",
        )
        parser.add_argument(
            "--purchase-past-max",
            type=int,
            default=92,
            help="Maximum purchase orders per past week (default 92)",
        )
        parser.add_argument(
            "--purchase-current",
            type=int,
            default=18,
            help="Purchase orders in the current week only (default 18)",
        )
        parser.add_argument(
            "--sale-current",
            type=int,
            default=16,
            help="Sale orders in the current week only (default 16); past weeks get none",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        force = opts["force"]
        pmin, pmax = int(opts["purchase_past_min"]), int(opts["purchase_past_max"])
        if pmin > pmax:
            pmin, pmax = pmax, pmin

        if not force and Order.objects.filter(reference__startswith=REF_PREFIX).exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Orders with reference {REF_PREFIX!r} already exist. "
                    "Use --force to add another batch, or skip."
                )
            )
            return

        items = list(Item.objects.filter(is_active=True).order_by("pk")[:400])
        suppliers = list(Supplier.objects.filter(is_active=True).order_by("pk"))
        clients = list(Client.objects.filter(is_active=True).order_by("pk"))
        locs = list(Location.objects.filter(is_active=True).order_by("pk")[:30])

        if not items or not suppliers:
            self.stdout.write(self.style.ERROR("Need at least one active Item and Supplier."))
            return
        if not clients:
            self.stdout.write(self.style.ERROR("Need at least one active Client for current-week sales."))
            return

        today = timezone.localdate()
        current_week_start = monday_of(today)
        week_starts = [current_week_start - timedelta(weeks=k) for k in range(5, -1, -1)]

        # Deterministic counts per past week (indices 0..4)
        past_counts = []
        for i, ws in enumerate(week_starts[:5]):
            h = int(hashlib.md5(ws.isoformat().encode()).hexdigest()[:6], 16)
            span = max(0, pmax - pmin)
            past_counts.append(pmin + (h % (span + 1)))

        plan_purchase = past_counts + [max(0, int(opts["purchase_current"]))]
        plan_sale = [0] * 5 + [max(0, int(opts["sale_current"]))]

        self.stdout.write(self.style.NOTICE("Week starts (Mon) and planned new orders:"))
        for i, ws in enumerate(week_starts):
            self.stdout.write(
                f"  {ws.isoformat()}  purchase +{plan_purchase[i]}  sale +{plan_sale[i]}"
            )

        if dry:
            total_p = sum(plan_purchase)
            total_s = sum(plan_sale)
            self.stdout.write(
                self.style.WARNING(f"DRY RUN — would create {total_p} purchase + {total_s} sale orders.")
            )
            return

        recv_loc = locs[0] if locs else None
        ship_loc = locs[min(1, len(locs) - 1)] if locs else None

        seq = 0
        created = 0
        with transaction.atomic():
            for wi, ws in enumerate(week_starts):
                for _ in range(plan_purchase[wi]):
                    item = items[seq % len(items)]
                    sup = suppliers[seq % len(suppliers)]
                    od = day_in_week(ws, seq)
                    ref = f"{REF_PREFIX}-P-{od.isoformat()}-{seq}"[:80]
                    o = Order.objects.create(
                        order_type=Order.TYPE_PURCHASE,
                        supplier=sup,
                        receiving_location=recv_loc,
                        order_date=od,
                        status=Order.STATUS_DELIVERED,
                        stock_applied=True,
                        reference=ref,
                        priority=Order.PRIORITY_MEDIUM,
                    )
                    OrderLine.objects.create(
                        order=o,
                        item=item,
                        quantity=1 + (seq % 5),
                        unit_price=(item.unit_cost or Decimal("1")) * Decimal("1.04"),
                    )
                    seq += 1
                    created += 1

                for _ in range(plan_sale[wi]):
                    item = items[seq % len(items)]
                    cl = clients[seq % len(clients)]
                    od = day_in_week(ws, seq + 999)
                    ref = f"{REF_PREFIX}-S-{od.isoformat()}-{seq}"[:80]
                    o = Order.objects.create(
                        order_type=Order.TYPE_SALE,
                        client=cl,
                        shipping_location=ship_loc,
                        order_date=od,
                        status=Order.STATUS_DELIVERED,
                        stock_applied=True,
                        reference=ref,
                        priority=Order.PRIORITY_MEDIUM,
                    )
                    OrderLine.objects.create(
                        order=o,
                        item=item,
                        quantity=1 + (seq % 3),
                        unit_price=(item.unit_cost or Decimal("1")) * Decimal("1.12"),
                    )
                    seq += 1
                    created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} orders ({REF_PREFIX})."))
