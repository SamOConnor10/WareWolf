"""Seed existing orders with receiving_location (purchase) and shipping_location (sale).
Also backfills item locations: for delivered purchases with receiving_location, sets item.location."""
import random
from django.core.management.base import BaseCommand

from inventory.models import Location, Order


# Location types that make sense as shipping/receiving points (warehouses, bays, etc.)
PREFERRED_LOCATION_TYPES = ("warehouse", "external", "receiving", "shipping")


def get_suitable_locations():
    """Get locations suitable for shipping/receiving - prefer warehouses over aisles/bins."""
    # Prefer: warehouse, external, receiving, shipping
    preferred = list(
        Location.objects.filter(
            location_type__in=PREFERRED_LOCATION_TYPES,
            is_active=True,
        ).order_by("name")
    )
    if preferred:
        return preferred
    # Fallback: top-level internal locations (e.g. "Main Warehouse" often has type internal)
    fallback = list(
        Location.objects.filter(
            location_type="internal",
            parent__isnull=True,
            is_active=True,
        ).order_by("name")
    )
    if fallback:
        return fallback
    # Last resort: any location (e.g. if all are aisles)
    return list(Location.objects.filter(is_active=True).order_by("name")[:10])


class Command(BaseCommand):
    help = "Assign shipping/receiving locations to existing orders (warehouses preferred over aisles/bins)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        locations = get_suitable_locations()

        if not locations:
            self.stderr.write("No suitable locations found. Create warehouse/receiving/shipping locations first.")
            return

        self.stdout.write(f"Using {len(locations)} location(s): {', '.join(l.name for l in locations)}")

        # Purchase orders: set receiving_location
        purchases = Order.objects.filter(
            order_type=Order.TYPE_PURCHASE,
            receiving_location__isnull=True,
        )
        purchase_count = purchases.count()
        if purchase_count:
            if not dry_run:
                for order in purchases:
                    order.receiving_location = random.choice(locations)
                    order.save(update_fields=["receiving_location"])
            self.stdout.write(
                self.style.SUCCESS(f"{'Would update' if dry_run else 'Updated'} {purchase_count} purchase order(s) with receiving_location")
            )
        else:
            self.stdout.write("No purchase orders need receiving_location.")

        # Sale orders: set shipping_location
        sales = Order.objects.filter(
            order_type=Order.TYPE_SALE,
            shipping_location__isnull=True,
        )
        sale_count = sales.count()
        if sale_count:
            if not dry_run:
                for order in sales:
                    order.shipping_location = random.choice(locations)
                    order.save(update_fields=["shipping_location"])
            self.stdout.write(
                self.style.SUCCESS(f"{'Would update' if dry_run else 'Updated'} {sale_count} sale order(s) with shipping_location")
            )
        else:
            self.stdout.write("No sale orders need shipping_location.")

        # Backfill: for delivered purchase orders with receiving_location, set item.location
        delivered_with_loc = Order.objects.filter(
            order_type=Order.TYPE_PURCHASE,
            status=Order.STATUS_DELIVERED,
            receiving_location__isnull=False,
        )
        backfill_count = 0
        for order in delivered_with_loc.select_related("receiving_location").prefetch_related("lines__item"):
            for line in order.lines.all():
                if line.item.location_id != order.receiving_location_id:
                    if not dry_run:
                        line.item.location = order.receiving_location
                        line.item.save(update_fields=["location"])
                    backfill_count += 1
        if backfill_count:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{'Would update' if dry_run else 'Updated'} {backfill_count} item location(s) from delivered purchases"
                )
            )

        if dry_run and (purchase_count or sale_count or backfill_count):
            self.stdout.write(self.style.WARNING("Run without --dry-run to apply changes."))
