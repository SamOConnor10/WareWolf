"""Create multiple purchase orders for testing the dashboard order chart."""
from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
import datetime

from inventory.models import Order, Item, Supplier


class Command(BaseCommand):
    help = "Create multiple purchase orders to test the dashboard order chart"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=15,
            help="Number of purchase orders to create (default: 15)",
        )
        parser.add_argument(
            "--this-week",
            action="store_true",
            dest="this_week",
            help="Put all orders in the current week only",
        )

    def handle(self, *args, **options):
        count = options["count"]
        this_week_only = options.get("this_week", False)

        items = list(Item.objects.all()[:20])
        suppliers = list(Supplier.objects.all())

        if not items:
            self.stderr.write("No items in database. Run seed_data first.")
            return
        if not suppliers:
            self.stderr.write("No suppliers in database. Run seed_data first.")
            return

        today = timezone.now().date()
        created = 0

        for i in range(count):
            item = items[i % len(items)]
            supplier = suppliers[i % len(suppliers)]

            if this_week_only:
                order_date = today - datetime.timedelta(days=i % 7)
            else:
                order_date = today - datetime.timedelta(days=i % 14)

            Order.objects.create(
                order_type=Order.TYPE_PURCHASE,
                item=item,
                quantity=1 + (i % 5),
                unit_price=item.unit_cost * Decimal("1.1"),
                supplier=supplier,
                order_date=order_date,
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} purchase orders."))
        self.stdout.write("Refresh the dashboard to see the chart update.")
