import json
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client as HttpClient
from django.test import TestCase
from django.urls import reverse

from inventory.models import (
    Activity,
    Client,
    Item,
    Location,
    Order,
    OrderLine,
    StockHistory,
    Supplier,
)


class IntegrationAnonymousAuthTest(TestCase):
    """Unauthenticated users are redirected away from protected inventory views."""

    def test_dashboard_redirects_to_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_item_list_redirects_to_login(self):
        response = self.client.get(reverse("item_list"))
        self.assertEqual(response.status_code, 302)

    def test_signup_page_loads_without_login(self):
        response = self.client.get(reverse("signup"))
        self.assertEqual(response.status_code, 200)


class IntegrationStaffHttpAccessTest(TestCase):
    """Staff can open read-mostly views that require ``inventory.view_item``."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.password = "IntegrationStaffPw9"
        cls.staff_user = User.objects.create_user(
            username="integration_staff",
            password=cls.password,
            email="staff.integration@example.com",
        )
        cls.staff_user.groups.set([Group.objects.get(name="Staff")])

    def setUp(self):
        self.assertTrue(
            self.client.login(username=self.staff_user.username, password=self.password)
        )

    def test_dashboard_returns_200(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_item_list_returns_200(self):
        response = self.client.get(reverse("item_list"))
        self.assertEqual(response.status_code, 200)

    def test_global_search_empty_query_returns_json(self):
        response = self.client.get(reverse("global_search"), {"q": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {"results": []})

    def test_global_search_finds_item_by_name(self):
        supplier = Supplier.objects.create(name="IntSup")
        loc = Location.objects.create(name="IntLoc")
        Item.objects.create(
            name="UniqueSearchBolt",
            sku="USB-INT-1",
            quantity=3,
            unit_cost=Decimal("1.00"),
            supplier=supplier,
            location=loc,
        )
        response = self.client.get(reverse("global_search"), {"q": "UniqueSearchBolt"})
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertTrue(any("UniqueSearchBolt" in r.get("name", "") for r in payload["results"]))


class IntegrationPermissionEnforcementTest(TestCase):
    """``permission_required`` gates write paths: Staff cannot create items; Manager can open the form."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff_pw = "StaffPermPw9"
        cls.manager_pw = "MgrPermPw9"
        cls.staff = User.objects.create_user(
            username="perm_staff", password=cls.staff_pw, email="ps@example.com"
        )
        cls.staff.groups.set([Group.objects.get(name="Staff")])
        cls.manager = User.objects.create_user(
            username="perm_manager", password=cls.manager_pw, email="pm@example.com"
        )
        cls.manager.groups.set([Group.objects.get(name="Manager")])

    def test_staff_get_item_create_returns_403(self):
        http = HttpClient()
        self.assertTrue(http.login(username="perm_staff", password=self.staff_pw))
        response = http.get(reverse("item_create"))
        self.assertEqual(response.status_code, 403)

    def test_manager_get_item_create_returns_200(self):
        http = HttpClient()
        self.assertTrue(http.login(username="perm_manager", password=self.manager_pw))
        response = http.get(reverse("item_create"))
        self.assertEqual(response.status_code, 200)


class IntegrationOrderStockFlowTest(TestCase):
    """Delivered purchase order applies stock through ``Order.apply_stock_if_needed``."""

    def test_delivered_purchase_increments_item_quantity_and_logs_history(self):
        supplier = Supplier.objects.create(name="PO Sup")
        loc = Location.objects.create(name="Recv Bay")
        item = Item.objects.create(
            name="StockedPart",
            sku="SP-INT-1",
            quantity=10,
            unit_cost=Decimal("2.00"),
            supplier=supplier,
            location=loc,
        )
        order = Order.objects.create(
            order_type=Order.TYPE_PURCHASE,
            supplier=supplier,
            receiving_location=loc,
            order_date=date(2026, 2, 1),
            status=Order.STATUS_DELIVERED,
            stock_applied=False,
        )
        OrderLine.objects.create(
            order=order, item=item, quantity=7, unit_price=Decimal("2.00")
        )

        order.apply_stock_if_needed()
        order.refresh_from_db()
        item.refresh_from_db()

        self.assertTrue(order.stock_applied)
        self.assertEqual(item.quantity, 17)
        self.assertEqual(item.location_id, loc.id)
        hist = StockHistory.objects.filter(item=item).first()
        self.assertIsNotNone(hist)
        self.assertEqual(hist.quantity, 17)
        self.assertTrue(
            Activity.objects.filter(kind=Activity.KIND_ORDER_STOCK).exists()
        )
