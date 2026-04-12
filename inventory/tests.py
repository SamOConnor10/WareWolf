from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from inventory import alerts_jobs
from inventory.ml import anomaly as anomaly_ml
from inventory.ml.anomaly import AnomalyResult, anomaly_keep_set, build_daily_sales_df, detect_sales_anomalies

from .models import (
    Category,
    Client,
    Item,
    Location,
    Order,
    OrderLine,
    Recommendation,
    Supplier,
    UserPreference,
)


class ItemModelTest(TestCase):
    def test_item_str(self):
        supplier = Supplier.objects.create(name="Test Supplier")
        location = Location.objects.create(name="A-01")
        item = Item.objects.create(
            name="HDMI Cable",
            sku="HDMI-001",
            quantity=10,
            reorder_level=2,
            unit_cost=Decimal("5.99"),
            supplier=supplier,
            location=location,
        )
        self.assertEqual(str(item), "HDMI Cable (HDMI-001)")

    def test_maybe_archive_on_deplete_sets_inactive_when_zero(self):
        supplier = Supplier.objects.create(name="S")
        loc = Location.objects.create(name="L")
        item = Item.objects.create(
            name="Widget",
            sku="W-ARCH",
            quantity=0,
            reorder_level=0,
            unit_cost=Decimal("1.00"),
            supplier=supplier,
            location=loc,
            delete_on_deplete=True,
            is_active=True,
        )
        item.maybe_archive_on_deplete()
        item.refresh_from_db()
        self.assertFalse(item.is_active)

    def test_maybe_archive_on_deplete_does_not_archive_when_stock_positive(self):
        supplier = Supplier.objects.create(name="S")
        loc = Location.objects.create(name="L")
        item = Item.objects.create(
            name="Widget",
            sku="W-OK",
            quantity=3,
            reorder_level=0,
            unit_cost=Decimal("1.00"),
            supplier=supplier,
            location=loc,
            delete_on_deplete=True,
            is_active=True,
        )
        item.maybe_archive_on_deplete()
        item.refresh_from_db()
        self.assertTrue(item.is_active)


class CategoryModelTest(TestCase):
    def test_full_path_with_parent(self):
        parent = Category.objects.create(name="Electronics")
        child = Category.objects.create(name="Cables", parent=parent)
        self.assertEqual(child.full_path, "Electronics > Cables")

    def test_full_path_root_only(self):
        cat = Category.objects.create(name="Uncategorised")
        self.assertEqual(cat.full_path, "Uncategorised")


class LocationModelTest(TestCase):
    def test_get_breadcrumb_parent_chain(self):
        wh = Location.objects.create(name="Warehouse A")
        aisle = Location.objects.create(name="Aisle 2", parent=wh)
        shelf = Location.objects.create(name="Shelf B", parent=aisle)
        self.assertEqual(shelf.get_breadcrumb(), "Warehouse A → Aisle 2 → Shelf B")

    def test_stock_count(self):
        supplier = Supplier.objects.create(name="S")
        loc = Location.objects.create(name="Bin-1")
        Item.objects.create(
            name="A",
            sku="SKU-A",
            quantity=1,
            unit_cost=Decimal("1"),
            supplier=supplier,
            location=loc,
        )
        Item.objects.create(
            name="B",
            sku="SKU-B",
            quantity=2,
            unit_cost=Decimal("2"),
            supplier=supplier,
            location=loc,
        )
        self.assertEqual(loc.stock_count(), 2)

    def test_get_map_url_with_coordinates(self):
        loc = Location.objects.create(
            name="DC1",
            latitude=Decimal("53.349800"),
            longitude=Decimal("-6.260310"),
        )
        url = loc.get_map_url()
        self.assertIn("google.com/maps", url)
        self.assertIn("53.3498", url)


class SupplierClientMapUrlTest(TestCase):
    def test_supplier_map_url_prefers_coordinates(self):
        s = Supplier.objects.create(
            name="Acme",
            address="1 Main St",
            latitude=Decimal("10.0"),
            longitude=Decimal("20.0"),
        )
        self.assertIn("10.0,20.0", s.get_map_url())

    def test_client_map_url_falls_back_to_address(self):
        c = Client.objects.create(name="Buyer", address="Dublin Docklands")
        url = c.get_map_url()
        self.assertIsNotNone(url)
        self.assertIn("query=", url)


class OrderModelTest(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(name="Sup")
        self.client = Client.objects.create(name="Cust")
        self.loc = Location.objects.create(name="L")
        self.item = Item.objects.create(
            name="Bolt",
            sku="B-1",
            quantity=100,
            unit_cost=Decimal("0.50"),
            supplier=self.supplier,
            location=self.loc,
        )

    def test_order_total_and_party_name_sale(self):
        order = Order.objects.create(
            order_type=Order.TYPE_SALE,
            client=self.client,
            order_date=date(2026, 1, 10),
            status=Order.STATUS_PENDING,
        )
        OrderLine.objects.create(order=order, item=self.item, quantity=4, unit_price=Decimal("2.50"))
        OrderLine.objects.create(order=order, item=self.item, quantity=1, unit_price=Decimal("10.00"))
        self.assertEqual(order.total, Decimal("20.00"))
        self.assertEqual(order.party_name, "Cust")

    def test_order_party_name_purchase(self):
        order = Order.objects.create(
            order_type=Order.TYPE_PURCHASE,
            supplier=self.supplier,
            order_date=date(2026, 1, 5),
        )
        self.assertEqual(order.party_name, "Sup")

    def test_order_str_includes_line_summary(self):
        order = Order.objects.create(order_type=Order.TYPE_SALE, client=self.client)
        OrderLine.objects.create(order=order, item=self.item, quantity=1, unit_price=Decimal("1"))
        s = str(order)
        self.assertIn("Order #", s)
        self.assertIn("Bolt", s)


class OrderLineModelTest(TestCase):
    def test_line_total_property(self):
        supplier = Supplier.objects.create(name="S")
        loc = Location.objects.create(name="L")
        item = Item.objects.create(
            name="Nail",
            sku="N-1",
            quantity=50,
            unit_cost=Decimal("0.10"),
            supplier=supplier,
            location=loc,
        )
        order = Order.objects.create(order_type=Order.TYPE_PURCHASE, supplier=supplier)
        line = OrderLine.objects.create(
            order=order, item=item, quantity=12, unit_price=Decimal("3.25")
        )
        self.assertEqual(line.total, Decimal("39.00"))


class RecommendationModelTest(TestCase):
    def test_str_contains_type_and_item(self):
        supplier = Supplier.objects.create(name="S")
        loc = Location.objects.create(name="L")
        item = Item.objects.create(
            name="Gear",
            sku="G-99",
            quantity=5,
            unit_cost=Decimal("9.99"),
            supplier=supplier,
            location=loc,
        )
        rec = Recommendation.objects.create(
            item=item,
            recommendation_type=Recommendation.TYPE_PURCHASE_DEMAND,
            status=Recommendation.STATUS_ACTIVE,
            priority=Recommendation.PRIORITY_MEDIUM,
            title="Reorder",
            reason="Low stock",
        )
        text = str(rec)
        self.assertIn("Gear", text)
        self.assertIn("Active", text)


class UserPreferenceModelTest(TestCase):
    def test_defaults_after_get_or_create(self):
        User = get_user_model()
        user = User.objects.create_user(username="u1", password="pass12345")
        pref, created = UserPreference.objects.get_or_create(user=user)
        self.assertTrue(created)
        self.assertTrue(pref.notify_anomalies)
        self.assertTrue(pref.notify_low_stock)
        self.assertFalse(pref.email_notifications)


class DemandAnomalyMlTest(TestCase):
    def test_build_daily_sales_df_empty_without_sales(self):
        self.assertTrue(build_daily_sales_df(days_back=30).empty)

    def test_detect_sales_anomalies_empty_when_no_sales_series(self):
        self.assertEqual(detect_sales_anomalies(days_back=30), [])

    def test_anomaly_keep_set_parses_dates(self):
        results = [
            AnomalyResult(item_id=7, date="05/03/2026", quantity=10, score=4.2, severity="HIGH"),
        ]
        keep = anomaly_keep_set(results)
        self.assertEqual(keep, {(7, date(2026, 3, 5))})

    def test_mad_symmetric_around_median(self):
        import numpy as np

        x = np.array([1.0, 2.0, 3.0, 100.0, 5.0])
        mad = anomaly_ml._mad(x)
        self.assertGreater(mad, 0)


class AlertsJobsUtilityTest(TestCase):
    def test_forecast_item_id_from_url(self):
        self.assertEqual(
            alerts_jobs._forecast_item_id_from_url("/items/42/forecast/?rec=1"),
            42,
        )
        self.assertIsNone(alerts_jobs._forecast_item_id_from_url(""))
        self.assertIsNone(alerts_jobs._forecast_item_id_from_url(None))
