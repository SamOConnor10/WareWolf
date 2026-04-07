"""
Create two demo stock items with no sales lines and no stock history so the
recommendation engine classifies them as DORMANT_STOCK (sale-side suggestions).

Run after migrations. Idempotent: reuses the same SKUs if they already exist.
"""
from decimal import Decimal

from django.core.cache import cache
from django.core.management.base import BaseCommand

from inventory.models import Category, Item, Location, Supplier
from inventory.recommendation_engine import RECALC_CACHE_KEY, recalculate_all_recommendations

DEMO_SKUS = ("WW-DEMO-DORMANT-01", "WW-DEMO-DORMANT-02")


class Command(BaseCommand):
    help = "Seed demo items so dormant stock sale recommendations appear in the UI."

    def handle(self, *args, **options):
        supplier = Supplier.objects.filter(is_active=True).first()
        if not supplier:
            self.stderr.write(self.style.ERROR("No active supplier found. Create a supplier first."))
            return

        category = Category.objects.first()
        location = Location.objects.filter(is_active=True).first()

        created = 0
        for i, sku in enumerate(DEMO_SKUS):
            name = f"Demo Dormant Stock {'A' if i == 0 else 'B'}"
            obj, was_created = Item.objects.get_or_create(
                sku=sku,
                defaults={
                    "name": name,
                    "quantity": 52,
                    "reorder_level": 0,
                    "safety_stock": 0,
                    "unit_cost": Decimal("12.50"),
                    "supplier": supplier,
                    "category": category,
                    "location": location,
                    "is_active": True,
                },
            )
            if was_created:
                created += 1

        cache.delete(RECALC_CACHE_KEY)
        recalculate_all_recommendations()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {created} new demo item(s); dormant sale recommendations recalculated. "
                "Open the purchase/sale orders view to see the recommendations popup."
            )
        )
