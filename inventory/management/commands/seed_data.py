from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import F
import random
import datetime
from decimal import Decimal

from inventory.models import (
    Supplier, Client, Category, Location, Item, Order, StockHistory
)


def get_or_create_safe(model, defaults=None, **lookup):
    """Safely fetches or creates an object without breaking if duplicates exist."""
    obj = model.objects.filter(**lookup).first()
    if obj:
        return obj
    return model.objects.create(**lookup, **(defaults or {}))


class Command(BaseCommand):
    help = "Seed the database with sample + demo analytics data"

    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding data...")

        # ============================================================
        # SUPPLIERS
        # ============================================================
        supplier1 = get_or_create_safe(Supplier, name="TechSource Ltd")
        supplier2 = get_or_create_safe(Supplier, name="Global Electronics")
        supplier3 = get_or_create_safe(Supplier, name="Mega Supply Co")
        supplier4 = get_or_create_safe(Supplier, name="OfficeMakers Inc")

        suppliers = [supplier1, supplier2, supplier3, supplier4]

        # ============================================================
        # CUSTOMERS
        # ============================================================
        customers = []
        for name in ["ACME Corp", "BlueWave Retail", "NorthStar LLC", "FastTrack Stores"]:
            c = get_or_create_safe(Client, name=name)
            customers.append(c)

        # ============================================================
        # LOCATIONS
        # ============================================================
        warehouse = get_or_create_safe(Location, name="Main Warehouse")
        loc1 = get_or_create_safe(Location, name="A-12", defaults={"parent": warehouse})
        loc2 = get_or_create_safe(Location, name="B-05", defaults={"parent": warehouse})
        loc3 = get_or_create_safe(Location, name="C-15", defaults={"parent": warehouse})

        locations = [loc1, loc2, loc3]

        # ============================================================
        # CATEGORIES
        # ============================================================
        cat_elec = get_or_create_safe(Category, name="Electronics")
        cat_computers = get_or_create_safe(Category, name="Computers", defaults={"parent": cat_elec})
        cat_cables = get_or_create_safe(Category, name="Cables", defaults={"parent": cat_elec})
        cat_furniture = get_or_create_safe(Category, name="Office Furniture")

        # ============================================================
        # ITEMS
        # ============================================================
        items = []

        item_templates = [
            ("Laptop – Dell XPS 15", "LAP-001", cat_computers, supplier1, loc1, 45, 10, 1200),
            ("USB-C Cable 2m", "CAB-102", cat_cables, supplier2, loc2, 15, 20, 12.99),
            ("Office Chair – Ergonomic", "FUR-203", cat_furniture, supplier3, loc3, 78, 5, 299.99),
            ("Keyboard – Mechanical RGB", "KEY-550", cat_computers, supplier1, loc2, 92, 15, 79.99),
            ("Monitor – 27in 144Hz", "MON-344", cat_computers, supplier2, loc1, 30, 5, 249.99),
            ("Office Desk – Wooden", "DES-220", cat_furniture, supplier4, loc3, 12, 2, 159.99),
        ]

        for name, sku, cat, sup, loc, qty, reorder, cost in item_templates:
            item = Item.objects.filter(sku=sku).first()
            if not item:
                item = Item.objects.create(
                    name=name,
                    sku=sku,
                    category=cat,
                    supplier=sup,
                    location=loc,
                    quantity=qty,
                    reorder_level=reorder,
                    unit_cost=cost,
                    description="",
                )
            items.append(item)

        # ============================================================
        # ORDERS (50 random purchase + sale orders over last 40 days)
        # ============================================================
        today = timezone.now().date()

        for _ in range(50):
            order_date = today - datetime.timedelta(days=random.randint(1, 40))
            item = random.choice(items)
            qty = random.randint(1, 5)
            purchase = random.choice([True, False])

            Order.objects.create(
                order_type="PURCHASE" if purchase else "SALE",
                item=item,
                quantity=qty,
                unit_price=item.unit_cost * Decimal(str(random.uniform(1.05, 1.4))),
                supplier=random.choice(suppliers) if purchase else None,
                client=random.choice(customers) if not purchase else None,
                order_date=order_date,
                status="DELIVERED",
                stock_applied=True,
            )


            # Affect stock levels
            if purchase:
                item.quantity = F("quantity") + qty
            else:
                item.quantity = F("quantity") - qty

            item.save()

        # ============================================================
        # STOCK HISTORY (realistic 30-day movement per item)
        # ============================================================
        self.stdout.write("Generating stock history…")
        StockHistory.objects.all().delete()

        for item in items:
            # force item.quantity to be a real int, not an F-expression
            item.refresh_from_db(fields=["quantity"])

            qty = int(item.quantity)

            for d in range(30):
                date = today - datetime.timedelta(days=d)
                qty = max(0, qty + random.randint(-3, 4))
                StockHistory.objects.create(item=item, date=date, quantity=qty)

        self.stdout.write(self.style.SUCCESS("Seeding completed successfully!"))
