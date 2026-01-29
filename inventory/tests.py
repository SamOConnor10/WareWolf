from django.test import TestCase
from .models import Supplier, Location, Item


class ItemModelTest(TestCase):
    def test_item_str(self):
        supplier = Supplier.objects.create(name="Test Supplier")
        location = Location.objects.create(name="A-01")
        item = Item.objects.create(
            name="HDMI Cable",
            sku="HDMI-001",
            quantity=10,
            reorder_level=2,
            unit_cost=5.99,
            supplier=supplier,
            location=location,
        )
        self.assertEqual(str(item), "HDMI Cable (HDMI-001)")
