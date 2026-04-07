from django.db import models
from django.db import models
from decimal import Decimal
from datetime import date
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

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
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="GPS latitude (e.g. for maps)",
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="GPS longitude (e.g. for maps)",
    )
    description = models.TextField(blank=True, help_text="Description of the company")
    website = models.URLField(blank=True, help_text="Company website URL")
    image = models.ImageField(upload_to="suppliers/", blank=True, null=True, help_text="Company logo or image")
    currency = models.CharField(max_length=10, blank=True, help_text="Default currency e.g. EUR, USD")
    tax_id = models.CharField(max_length=50, blank=True, help_text="Company Tax ID")
    notes = models.TextField(blank=True, help_text="Internal notes")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    def get_map_url(self):
        from urllib.parse import quote
        if self.latitude is not None and self.longitude is not None:
            return f"https://www.google.com/maps?q={self.latitude},{self.longitude}&z=17"
        if self.address and str(self.address).strip():
            return f"https://www.google.com/maps/search/?api=1&query={quote(str(self.address).strip())}"
        return None


class Client(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="GPS latitude (e.g. for maps)",
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="GPS longitude (e.g. for maps)",
    )
    description = models.TextField(blank=True, help_text="Description of the company")
    website = models.URLField(blank=True, help_text="Company website URL")
    image = models.ImageField(upload_to="customers/", blank=True, null=True, help_text="Company logo or image")
    currency = models.CharField(max_length=10, blank=True, help_text="Default currency e.g. EUR, USD")
    tax_id = models.CharField(max_length=50, blank=True, help_text="Company Tax ID")
    notes = models.TextField(blank=True, help_text="Internal notes")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    def get_map_url(self):
        from urllib.parse import quote
        if self.latitude is not None and self.longitude is not None:
            return f"https://www.google.com/maps?q={self.latitude},{self.longitude}&z=17"
        if self.address and str(self.address).strip():
            return f"https://www.google.com/maps/search/?api=1&query={quote(str(self.address).strip())}"
        return None


class Location(models.Model):
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True, help_text="Short code e.g. A-01, B-12")
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="locations/", blank=True, null=True, help_text="Location photo or diagram")
    address = models.TextField(blank=True, help_text="Physical address (for external locations)")
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="GPS latitude (e.g. 53.349805)",
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="GPS longitude (e.g. -6.260310)",
    )
    barcode = models.CharField(max_length=100, blank=True, help_text="Barcode for scanning")
    notes = models.TextField(blank=True, help_text="Internal notes (not shown externally)")

    structural = models.BooleanField(default=False)
    external = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    # Capacity (optional) - max units this location can hold; used for utilisation %
    capacity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum units this location can hold (for utilisation tracking)",
    )

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

    def get_map_url(self):
        """Return Google Maps URL for this location (coords or address)."""
        from urllib.parse import quote
        if self.latitude is not None and self.longitude is not None:
            return f"https://www.google.com/maps?q={self.latitude},{self.longitude}&z=17"
        if self.address and self.address.strip():
            return f"https://www.google.com/maps/search/?api=1&query={quote(self.address.strip())}"
        return None

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
    barcode = models.CharField(max_length=100, blank=True)
    unit_of_measure = models.CharField(max_length=20, default="pcs", blank=True)
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

    lead_time_days = models.PositiveIntegerField(default=7)
    safety_stock = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True, help_text="Internal notes (not shown to customers)")

    # Inventree-inspired fields
    batch_code = models.CharField(max_length=100, blank=True, help_text="Batch or lot number for tracking")
    STOCK_STATUS_CHOICES = [
        ("OK", "OK"),
        ("damaged", "Damaged"),
        ("quarantine", "Quarantine"),
        ("returned", "Returned"),
        ("on_hold", "On Hold"),
    ]
    stock_status = models.CharField(max_length=20, choices=STOCK_STATUS_CHOICES, default="OK", blank=True)
    expiry_date = models.DateField(null=True, blank=True, help_text="Stock considered expired after this date")
    CURRENCY_CHOICES = [
        ("EUR", "EUR - Euro"),
        ("USD", "USD - US Dollar"),
        ("GBP", "GBP - British Pound"),
    ]
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="EUR", blank=True)
    packaging = models.CharField(max_length=100, blank=True, help_text="How this item is packaged (e.g. box, pallet)")
    external_link = models.URLField(max_length=500, blank=True, help_text="Link to datasheet, product page, etc.")
    serial_numbers = models.TextField(blank=True, help_text="Serial numbers (one per line)")
    delete_on_deplete = models.BooleanField(
        default=False,
        help_text="Archive this item when stock reaches zero"
    )

    image = models.ImageField(upload_to="items/", blank=True, null=True, help_text="Product image")

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def maybe_archive_on_deplete(self):
        """If delete_on_deplete is True and quantity <= 0, archive the item."""
        if self.delete_on_deplete and self.quantity <= 0:
            self.is_active = False
            self.save(update_fields=["is_active"])


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
    # Line items: use order.lines for items, quantities, prices

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

    # Order metadata (Inventree-style)
    reference = models.CharField(
        max_length=80, blank=True,
        help_text="Order reference e.g. PO0020, SO0029",
    )
    description = models.TextField(blank=True)
    party_reference = models.CharField(
        max_length=100, blank=True,
        help_text="Supplier/customer order reference code",
    )
    target_date = models.DateField(
        null=True, blank=True,
        help_text="Expected delivery date. Order overdue after this.",
    )
    external_link = models.URLField(blank=True)

    # Location fields (sale = shipping from, purchase = receiving to)
    shipping_location = models.ForeignKey(
        "Location",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders_shipped_from",
        help_text="Location goods are shipped from (for sale orders)",
    )
    receiving_location = models.ForeignKey(
        "Location",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders_received_at",
        help_text="Location goods are received at (for purchase orders)",
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
        lines = list(self.lines.all()[:2])
        if lines:
            names = ", ".join(ln.item.name for ln in lines)
            if self.lines.count() > 2:
                names += f" (+{self.lines.count() - 2} more)"
            return f"Order #{self.id} – {names}"
        return f"Order #{self.id}"

    @property
    def total(self):
        return sum((ln.unit_price or Decimal("0")) * ln.quantity for ln in self.lines.all())

    @property
    def total_quantity(self):
        return sum(ln.quantity for ln in self.lines.all())

    @property
    def party_name(self):
        if self.order_type == self.TYPE_PURCHASE and self.supplier:
            return self.supplier.name
        if self.order_type == self.TYPE_SALE and self.client:
            return self.client.name
        return "-"

    def apply_stock_if_needed(self, actor=None):
        """
        Apply stock movement once when the order is delivered.
        Purchase = increase stock, Sale = decrease stock.
        Also log stock history for analytics.
        Raises ValueError if a sale order would reduce stock below zero.
        """
        from django.db.models import F
        from inventory.models import StockHistory
        from datetime import date

        if self.status != self.STATUS_DELIVERED or self.stock_applied:
            return

        delivery_date = timezone.now().date()
        for line in self.lines.select_related("item").all():
            item = line.item

            # Sale orders: check stock before applying (quantity must not go below zero)
            if self.order_type == self.TYPE_SALE:
                current = item.quantity
                if current < line.quantity:
                    raise ValueError(
                        f"Insufficient stock for {item.name}: "
                        f"current quantity is {current}, but order requires {line.quantity}. "
                        f"Stock cannot go below zero."
                    )

            # Update stock based on order type
            if self.order_type == self.TYPE_PURCHASE:
                item.quantity = F("quantity") + line.quantity
                if self.receiving_location_id:
                    item.location_id = self.receiving_location_id
            else:  # SALE
                item.quantity = F("quantity") - line.quantity

            update_fields = ["quantity"]
            if self.order_type == self.TYPE_PURCHASE and self.receiving_location_id:
                update_fields.append("location_id")
            item.save(update_fields=update_fields)
            item.refresh_from_db(fields=["quantity"])
            item.maybe_archive_on_deplete()

            StockHistory.objects.update_or_create(
                item=item,
                date=delivery_date,
                defaults={"quantity": item.quantity},
            )

            Activity.objects.create(
                message=f"Order #{self.id} delivered — updated stock for {item.name}",
                user=actor if actor and getattr(actor, "is_authenticated", False) else None,
                kind=Activity.KIND_ORDER_STOCK,
            )

        # Mark order as applied to avoid duplicates
        self.stock_applied = True
        self.save(update_fields=["stock_applied"])


class OrderLine(models.Model):
    """Line item on an order - allows multiple items per purchase/sale order."""
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    item = models.ForeignKey(
        "Item",
        on_delete=models.PROTECT,
        related_name="order_lines",
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.order} – {self.item.name} x {self.quantity}"

    @property
    def total(self):
        return (self.unit_price or Decimal("0")) * self.quantity


class StockHistory(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="history")
    # allow manual dates (no auto_now_add)
    date = models.DateField()
    quantity = models.IntegerField()  # current item quantity on this day

    def __str__(self):
        return f"{self.item.name} on {self.date} = {self.quantity}"
    

class Activity(models.Model):
    KIND_OTHER = "other"
    KIND_ITEM_CREATE = "item_create"
    KIND_ITEM_UPDATE = "item_update"
    KIND_ITEM_ADJUST = "item_adjust"
    KIND_ITEM_ARCHIVE = "item_archive"
    KIND_ITEM_UNARCHIVE = "item_unarchive"
    KIND_ITEM_DELETE = "item_delete"
    KIND_ITEM_HARD_DELETE = "item_hard_delete"
    KIND_ITEM_AUTO_ARCHIVE = "item_auto_archive"
    KIND_ORDER_STOCK = "order_stock"
    KIND_ANOMALY_SCAN = "anomaly_scan"

    KIND_CHOICES = [
        (KIND_ITEM_CREATE, "New item"),
        (KIND_ITEM_UPDATE, "Item updated"),
        (KIND_ITEM_ADJUST, "Quantity"),
        (KIND_ITEM_ARCHIVE, "Archived"),
        (KIND_ITEM_UNARCHIVE, "Unarchived"),
        (KIND_ITEM_DELETE, "Deleted"),
        (KIND_ITEM_HARD_DELETE, "Permanent delete"),
        (KIND_ITEM_AUTO_ARCHIVE, "Auto-archived"),
        (KIND_ORDER_STOCK, "Order & stock"),
        (KIND_ANOMALY_SCAN, "Anomaly scan"),
        (KIND_OTHER, "Other"),
    ]

    BADGE_CLASSES = {
        KIND_ITEM_CREATE: "text-bg-success",
        KIND_ITEM_UPDATE: "text-bg-primary",
        KIND_ITEM_ADJUST: "text-bg-info",
        KIND_ITEM_ARCHIVE: "text-bg-warning text-dark",
        KIND_ITEM_UNARCHIVE: "text-bg-secondary",
        KIND_ITEM_DELETE: "text-bg-danger",
        KIND_ITEM_HARD_DELETE: "text-bg-danger",
        KIND_ITEM_AUTO_ARCHIVE: "text-bg-warning text-dark",
        KIND_ORDER_STOCK: "text-bg-primary",
        KIND_ANOMALY_SCAN: "text-bg-success",
        KIND_OTHER: "text-bg-light border text-dark",
    }

    message = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(
        max_length=32,
        choices=KIND_CHOICES,
        default=KIND_OTHER,
        db_index=True,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        who = self.user.username if self.user else "System"
        return f"{self.timestamp}: {self.message} ({who})"

    @property
    def kind_badge_class(self):
        cls = type(self)
        return cls.BADGE_CLASSES.get(self.kind, cls.BADGE_CLASSES[cls.KIND_OTHER])
    
class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications"
    )
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    # read vs dismissed (dismissed = removed from bell dropdown)
    is_read = models.BooleanField(default=False)
    dismissed = models.BooleanField(default=False)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    url = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return f"{self.user} - {self.message}"
    

class DemandAnomaly(models.Model):
    SEV_LOW = "LOW"
    SEV_MED = "MEDIUM"
    SEV_HIGH = "HIGH"
    SEVERITY_CHOICES = [
        (SEV_LOW, "Low"),
        (SEV_MED, "Medium"),
        (SEV_HIGH, "High"),
    ]

    item = models.ForeignKey("Item", on_delete=models.CASCADE, related_name="demand_anomalies")
    date = models.DateField()
    quantity = models.PositiveIntegerField()
    score = models.FloatField(help_text="IsolationForest anomaly score (lower = more abnormal)")
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default=SEV_LOW)
    created_at = models.DateTimeField(auto_now_add=True)

    is_reviewed = models.BooleanField(default=False)
    dismissed = models.BooleanField(default=False)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("item", "date")
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.item.name} anomaly on {self.date} ({self.severity})"


class Recommendation(models.Model):
    """
    Unified recommendation model powering purchase/sales suggestions,
    dormant stock alerts, and overstock warnings.
    """

    TYPE_PURCHASE_DEMAND = "PURCHASE_DEMAND"
    TYPE_SALES_OVERSTOCK = "SALES_OVERSTOCK"
    TYPE_DORMANT_STOCK = "DORMANT_STOCK"
    TYPE_OVERSTOCK_ALERT = "OVERSTOCK_ALERT"

    TYPE_CHOICES = [
        (TYPE_PURCHASE_DEMAND, "Purchase recommendation"),
        (TYPE_SALES_OVERSTOCK, "Sales recommendation"),
        (TYPE_DORMANT_STOCK, "Dormant stock"),
        (TYPE_OVERSTOCK_ALERT, "Overstock alert"),
    ]

    STATUS_ACTIVE = "ACTIVE"
    STATUS_DISMISSED = "DISMISSED"
    STATUS_ACCEPTED = "ACCEPTED"
    STATUS_EXPIRED = "EXPIRED"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_DISMISSED, "Dismissed"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_EXPIRED, "Expired"),
    ]

    PRIORITY_CRITICAL = 1
    PRIORITY_HIGH = 2
    PRIORITY_MEDIUM = 3
    PRIORITY_LOW = 4

    PRIORITY_CHOICES = [
        (PRIORITY_CRITICAL, "Critical"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_LOW, "Low"),
    ]

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="recommendations",
    )

    recommendation_type = models.CharField(
        max_length=32,
        choices=TYPE_CHOICES,
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    priority = models.PositiveSmallIntegerField(
        choices=PRIORITY_CHOICES,
        default=PRIORITY_MEDIUM,
    )

    title = models.CharField(max_length=255)
    reason = models.TextField(blank=True)

    suggested_quantity = models.PositiveIntegerField(null=True, blank=True)
    suggested_supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recommendations",
    )
    suggested_customer = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recommendations",
    )
    target_date = models.DateField(null=True, blank=True)

    # Fingerprint of the metrics/conditions used to generate this row.
    source_hash = models.CharField(max_length=64, blank=True, default="")

    # Approximate stock value involved in this recommendation (for ranking).
    stock_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    metadata = models.JSONField(blank=True, default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "-created_at"]
        indexes = [
            models.Index(fields=["recommendation_type", "status"]),
            models.Index(fields=["item", "recommendation_type", "status"]),
        ]

    def __str__(self):
        return f"{self.get_recommendation_type_display()} for {self.item} ({self.get_status_display()})"


class UserPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences"
    )
    notify_anomalies = models.BooleanField(default=True)
    notify_low_stock = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    # NEW (quick wins)
    email_notifications = models.BooleanField(default=False)
    push_notifications = models.BooleanField(default=False)
    weekly_reports = models.BooleanField(default=False)

    # “threshold” for low stock alerts (multiplier or absolute)
    low_stock_threshold = models.PositiveIntegerField(default=0)  # 0 = use reorder_level

    THEME_LIGHT = "light"
    THEME_DARK = "dark"
    THEME_AUTO = "auto"
    THEME_CHOICES = [(THEME_LIGHT, "Light"), (THEME_DARK, "Dark"), (THEME_AUTO, "Auto")]

    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default=THEME_LIGHT)

    ACCENT_BLUE = "blue"
    ACCENT_GREEN = "green"
    ACCENT_PURPLE = "purple"
    ACCENT_RED = "red"
    ACCENT_ORANGE = "orange"
    ACCENT_PINK = "pink"
    ACCENT_CHOICES = [
        (ACCENT_BLUE, "Blue"),
        (ACCENT_GREEN, "Green"),
        (ACCENT_PURPLE, "Purple"),
        (ACCENT_RED, "Red"),
        (ACCENT_ORANGE, "Orange"),
        (ACCENT_PINK, "Pink"),
    ]
    accent_color = models.CharField(max_length=10, choices=ACCENT_CHOICES, default=ACCENT_BLUE)

    FONT_SIZE_SMALL = "small"
    FONT_SIZE_MEDIUM = "medium"
    FONT_SIZE_LARGE = "large"
    FONT_SIZE_CHOICES = [
        (FONT_SIZE_SMALL, "Small"),
        (FONT_SIZE_MEDIUM, "Medium"),
        (FONT_SIZE_LARGE, "Large"),
    ]
    font_size = models.CharField(
        max_length=10,
        choices=FONT_SIZE_CHOICES,
        default=FONT_SIZE_MEDIUM,
    )

    compact_mode = models.BooleanField(default=False)

    items_per_page = models.PositiveIntegerField(default=20)

    TABLE_DENSITY_COMFORTABLE = "comfortable"
    TABLE_DENSITY_COMPACT = "compact"
    TABLE_DENSITY_CHOICES = [
        (TABLE_DENSITY_COMFORTABLE, "Comfortable"),
        (TABLE_DENSITY_COMPACT, "Compact"),
    ]
    default_table_density = models.CharField(
        max_length=12,
        choices=TABLE_DENSITY_CHOICES,
        default=TABLE_DENSITY_COMFORTABLE,
    )

    LANDING_DASHBOARD = "dashboard"
    LANDING_ITEM_LIST = "item_list"
    LANDING_LOCATION_LIST = "location_list"
    LANDING_ORDER_LIST = "order_list"
    LANDING_CONTACTS_LIST = "contacts_list"
    LANDING_ALERTS_LIST = "alerts_list"
    LANDING_ANOMALY_LIST = "anomaly_list"
    LANDING_SETTINGS = "settings"
    DEFAULT_LANDING_CHOICES = [
        (LANDING_DASHBOARD, "Dashboard"),
        (LANDING_ITEM_LIST, "Stock"),
        (LANDING_LOCATION_LIST, "Locations"),
        (LANDING_ORDER_LIST, "Orders"),
        (LANDING_CONTACTS_LIST, "Contacts"),
        (LANDING_ALERTS_LIST, "Alerts"),
        (LANDING_ANOMALY_LIST, "Anomalies"),
        (LANDING_SETTINGS, "Settings"),
    ]
    default_landing = models.CharField(
        max_length=32,
        choices=DEFAULT_LANDING_CHOICES,
        default=LANDING_DASHBOARD,
    )

    CLOCK_12 = "12h"
    CLOCK_24 = "24h"
    CLOCK_FORMAT_CHOICES = [
        (CLOCK_12, "12-hour (e.g. 1:30 PM)"),
        (CLOCK_24, "24-hour (e.g. 13:30)"),
    ]
    clock_format = models.CharField(
        max_length=4,
        choices=CLOCK_FORMAT_CHOICES,
        default=CLOCK_24,
    )

    DATE_DMY = "dmy"
    DATE_MDY = "mdy"
    DATE_ISO = "iso"
    DATE_FORMAT_CHOICES = [
        (DATE_DMY, "4 Jan 2026 (day month year)"),
        (DATE_MDY, "Jan 4, 2026 (month day year)"),
        (DATE_ISO, "2026-01-04 (ISO)"),
    ]
    date_format_style = models.CharField(
        max_length=8,
        choices=DATE_FORMAT_CHOICES,
        default=DATE_DMY,
    )

    timezone_name = models.CharField(max_length=64, default="UTC")

    language_code = models.CharField(max_length=10, default="en")

    default_currency = models.CharField(
        max_length=3,
        choices=Item.CURRENCY_CHOICES,
        default="EUR",
    )
    default_unit_of_measure = models.CharField(max_length=20, default="pcs", blank=True)

    confirm_destructive_actions = models.BooleanField(default=True)
    keyboard_shortcuts_enabled = models.BooleanField(default=True)

    reduce_motion = models.BooleanField(
        default=False,
        help_text="Minimise transitions and animations (also respects system reduced-motion).",
    )
    underline_links = models.BooleanField(
        default=False,
        help_text="Underline body content links for easier spotting.",
    )

    ACCESSIBILITY_BASIC = "basic"
    ACCESSIBILITY_ENHANCED = "enhanced"
    ACCESSIBILITY_ASSISTIVE = "assistive"
    ACCESSIBILITY_AUTO = "auto"
    ACCESSIBILITY_MODE_CHOICES = [
        (ACCESSIBILITY_AUTO, _("Auto — adapt from device (motion & contrast)")),
        (ACCESSIBILITY_BASIC, _("Basic — standard layout")),
        (ACCESSIBILITY_ENHANCED, _("Enhanced — larger controls, clearer focus")),
        (ACCESSIBILITY_ASSISTIVE, _("Assistive — simplified panels, maximum spacing")),
    ]
    accessibility_mode = models.CharField(
        max_length=16,
        choices=ACCESSIBILITY_MODE_CHOICES,
        default=ACCESSIBILITY_BASIC,
        help_text="Adaptive UX tier; Auto uses prefers-reduced-motion and prefers-contrast.",
    )
    voice_feedback_enabled = models.BooleanField(
        default=False,
        help_text="Allow speech synthesis for page content and alerts (browser Web Speech API).",
    )

    def __str__(self):
        return f"Preferences for {self.user}"
    

class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")

    avatar = models.ImageField(
        upload_to="profile_avatars/",
        blank=True,
        null=True,
        help_text="Shown in the header menu and on your profile.",
    )

    job_title = models.CharField(max_length=80, blank=True)
    department = models.CharField(max_length=80, blank=True)
    phone_number = models.CharField(max_length=30, blank=True)
    employee_id = models.CharField(max_length=30, blank=True)
    bio = models.TextField(blank=True)

    def __str__(self):
        return f"Profile: {self.user.username}"