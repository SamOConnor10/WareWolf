from django.db import models
from django.db import models
from decimal import Decimal
from datetime import date
from django.conf import settings

class ManagerRequest(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("DECLINED", "Declined"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="manager_requests_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} ({self.status})"


class Supplier(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Client(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Location(models.Model):
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    structural = models.BooleanField(default=False)
    external = models.BooleanField(default=False)

    LOCATION_TYPES = [
        ("warehouse", "Warehouse"),
        ("internal", "Internal Storage"),
        ("external", "External Location"),
        ("receiving", "Receiving Area"),
        ("shipping", "Shipping Bay"),
    ]

    location_type = models.CharField(max_length=50, choices=LOCATION_TYPES, default="internal")

    def get_breadcrumb(self):
        path = []
        current = self
        while current is not None:
            path.append(current.name)
            current = current.parent
        return " → ".join(reversed(path))
    
    def stock_count(self):
        return self.inventory_items.count()


    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def full_path(self):
        """Return the category path, e.g. Electronics > Laptops"""
        names = [self.name]
        p = self.parent
        while p:
            names.append(p.name)
            p = p.parent
        return " > ".join(reversed(names))



class Item(models.Model):
    name = models.CharField(max_length=255)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items"
    )
    sku = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    quantity = models.IntegerField(default=0)
    reorder_level = models.IntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_items"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.sku})"


class Order(models.Model):
    TYPE_PURCHASE = "PURCHASE"
    TYPE_SALE = "SALE"

    ORDER_TYPE_CHOICES = [
        (TYPE_PURCHASE, "Purchase"),
        (TYPE_SALE, "Sale"),
    ]

    STATUS_PENDING = "PENDING"
    STATUS_PROCESSING = "PROCESSING"
    STATUS_SHIPPED = "SHIPPED"
    STATUS_DELIVERED = "DELIVERED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_SHIPPED, "Shipped"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    PRIORITY_LOW = "LOW"
    PRIORITY_MEDIUM = "MEDIUM"
    PRIORITY_HIGH = "HIGH"

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_HIGH, "High"),
    ]

    # Core fields
    order_type = models.CharField(
        max_length=10, choices=ORDER_TYPE_CHOICES, default=TYPE_SALE
    )
    item = models.ForeignKey("Item", on_delete=models.PROTECT, related_name="orders")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    # Party (one of these will be set depending on type)
    supplier = models.ForeignKey(
        "Supplier",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
    )
    client = models.ForeignKey(
        "Client",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
    )

    order_date = models.DateField(default=date.today)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM
    )
    notes = models.TextField(blank=True)

    # Has stock for this order already been applied?
    stock_applied = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-order_date", "-id"]

    def __str__(self):
        return f"Order #{self.id} – {self.item.name}"

    @property
    def total(self):
        return (self.unit_price or Decimal("0")) * self.quantity

    @property
    def party_name(self):
        if self.order_type == self.TYPE_PURCHASE and self.supplier:
            return self.supplier.name
        if self.order_type == self.TYPE_SALE and self.client:
            return self.client.name
        return "-"

    def apply_stock_if_needed(self):
        """
        Apply stock movement once when the order is delivered.
        Purchase = increase stock, Sale = decrease stock.
        Also log stock history for analytics.
        """
        from django.db.models import F
        from inventory.models import StockHistory
        from datetime import date

        if self.status != self.STATUS_DELIVERED or self.stock_applied:
            return

        # Update stock based on order type
        if self.order_type == self.TYPE_PURCHASE:
            self.item.quantity = F("quantity") + self.quantity
        else:  # SALE
            self.item.quantity = F("quantity") - self.quantity

        # Save updated item quantity
        self.item.save(update_fields=["quantity"])

        # Refresh so item.quantity becomes the REAL number, not an F-expression
        self.item.refresh_from_db(fields=["quantity"])

        # Log stock history
        StockHistory.objects.create(
            item=self.item,
            date=date.today(),
            quantity=self.item.quantity
        )

        # Log activity (safe lazy import)
        from django.apps import apps
        Activity = apps.get_model("inventory", "Activity")
        Activity.objects.create(
            message=f"Order #{self.id} delivered — updated stock for {self.item.name}"
        )

        # Mark order as applied to avoid duplicates
        self.stock_applied = True
        self.save(update_fields=["stock_applied"])





class StockHistory(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="history")
    # allow manual dates (no auto_now_add)
    date = models.DateField()
    quantity = models.IntegerField()  # current item quantity on this day

    def __str__(self):
        return f"{self.item.name} on {self.date} = {self.quantity}"
    

class Activity(models.Model):
    message = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp}: {self.message}"
