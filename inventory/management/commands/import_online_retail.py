import pandas as pd
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from inventory.models import Item, Order, Category, Supplier, Location

class Command(BaseCommand):
    help = "Import UCI Online Retail dataset into WareWolf (SME-sized slice)."

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Path to Online Retail.xlsx")
        parser.add_argument("--top-items", type=int, default=100, help="How many SKUs to import (default 100)")
        parser.add_argument("--months", type=int, default=12, help="How many months from end of dataset (default 12)")

    @transaction.atomic
    def handle(self, *args, **options):
        file_path = options["file_path"]
        top_n = options["top_items"]
        months = options["months"]

        self.stdout.write(self.style.WARNING(f"Loading dataset: {file_path}"))
        df = pd.read_excel(file_path)

        # Expected columns in UCI file:
        # InvoiceNo, StockCode, Description, Quantity, InvoiceDate, UnitPrice, CustomerID, Country
        df = df.dropna(subset=["StockCode", "Description", "InvoiceDate", "Quantity"])
        df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
        df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce").fillna(0)

        # Keep only positive quantities (sales). Returns/cancellations are negative/zero.
        df = df[df["Quantity"] > 0]

        # Limit timeframe to last N months to simulate SME history
        end_date = df["InvoiceDate"].max()
        start_date = end_date - pd.DateOffset(months=months)
        df = df[df["InvoiceDate"].between(start_date, end_date)]

        # Pick top N items by total quantity sold
        top_items = (
            df.groupby("StockCode")["Quantity"].sum()
            .sort_values(ascending=False)
            .head(top_n)
            .index
        )
        df = df[df["StockCode"].isin(top_items)]

        # Aggregate to daily demand per SKU (prevents huge Order counts)
        df["order_date"] = df["InvoiceDate"].dt.date
        daily = (
            df.groupby(["StockCode", "Description", "order_date"])["Quantity"]
            .sum()
            .reset_index()
        )

        # Create defaults (so Items have required FK fields)
        category, _ = Category.objects.get_or_create(name="Imported Dataset")
        supplier, _ = Supplier.objects.get_or_create(name="Dataset Supplier")
        location, _ = Location.objects.get_or_create(name="Imported Location")

        created_items = 0
        created_orders = 0

        for _, row in daily.iterrows():
            sku = str(row["StockCode"]).strip()
            name = str(row["Description"]).strip()
            if not name or name.lower() == "nan":
                name = f"Item {sku}"
            name = name[:255]
            qty = int(row["Quantity"])
            order_date = row["order_date"]

            item, created = Item.objects.get_or_create(
                sku=sku,
                defaults={
                    "name": name,
                    "category": category,
                    "supplier": supplier,
                    "location": location,
                    "quantity": 0,
                    "reorder_level": 10,
                    "unit_cost": 1.00,
                    "lead_time_days": 7,
                    "safety_stock": 0,
                }
            )
            if created:
                created_items += 1

            # Create a SALE order per day per SKU
            Order.objects.create(
                item=item,
                order_type=Order.TYPE_SALE,
                quantity=qty,
                order_date=order_date,
                unit_price=item.unit_cost,
                status=Order.STATUS_DELIVERED,
            )
            created_orders += 1

        self.stdout.write(self.style.SUCCESS(
            f"Import complete. Items created: {created_items}, Orders created: {created_orders}"
        ))