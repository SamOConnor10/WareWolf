from django import forms
from .models import Item, Supplier, Client, Location, Order, OrderLine, Category
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from django.contrib.auth import get_user_model
from .models import UserPreference
from .models import UserProfile


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    ROLE_CHOICES = [
        ("staff", "Staff"),
        ("manager", "Manager (requires approval)"),
    ]
    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.Select(attrs={"class": "form-select"}))

    class Meta:
        model = User
        fields = ("username", "email", "role", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Make built-in fields look like Bootstrap
        for f in ["username", "email", "password1", "password2"]:
            self.fields[f].widget.attrs.update({"class": "form-control"})

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Email already in use.")
        return email
    
    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("Username already in use.")
        return username


# -------------------------------------------------
# ITEM FORM
# -------------------------------------------------
class ItemForm(forms.ModelForm):
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["unit_of_measure"].initial = "pcs"

    unit_of_measure = forms.ChoiceField(
        choices=[
            ("", "—"),
            ("pcs", "Pieces (pcs)"),
            ("kg", "Kilograms (kg)"),
            ("g", "Grams (g)"),
            ("L", "Liters (L)"),
            ("ml", "Milliliters (ml)"),
            ("m", "Meters (m)"),
            ("cm", "Centimeters (cm)"),
            ("box", "Box"),
            ("pack", "Pack"),
            ("unit", "Unit"),
        ],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Item
        fields = [
            "name",
            "sku",
            "image",
            "barcode",
            "unit_of_measure",
            "description",
            "quantity",
            "category",
            "reorder_level",
            "lead_time_days",
            "safety_stock",
            "unit_cost",
            "currency",
            "supplier",
            "location",
            "batch_code",
            "stock_status",
            "expiry_date",
            "packaging",
            "external_link",
            "serial_numbers",
            "delete_on_deplete",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Steel Bolts M8"}),
            "sku": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. BOLT-M8-001"}),
            "image": forms.FileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "barcode": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional barcode / ISBN"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Product description"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "reorder_level": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "lead_time_days": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "safety_stock": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "unit_cost": forms.NumberInput(attrs={"class": "form-control", "min": 0, "step": "0.01", "placeholder": "0.00"}),
            "currency": forms.Select(attrs={"class": "form-select"}),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "location": forms.Select(attrs={"class": "form-select"}),
            "batch_code": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. BATCH-2026-001"}),
            "stock_status": forms.Select(attrs={"class": "form-select"}),
            "expiry_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "packaging": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. box, pallet"}),
            "external_link": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://"}),
            "serial_numbers": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "One per line"}),
            "delete_on_deplete": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Internal notes (not shown externally)"}),
        }

    def clean_quantity(self):
        qty = self.cleaned_data.get("quantity")
        if qty is not None and qty < 0:
            raise ValidationError("Stock quantity cannot be below zero.")
        return qty


# -------------------------------------------------
# LOCATION FORM
# -------------------------------------------------
class LocationForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["parent"].queryset = Location.objects.exclude(id=self.instance.pk)

    class Meta:
        model = Location
        fields = [
            "name",
            "code",
            "parent",
            "location_type",
            "description",
            "image",
            "address",
            "latitude",
            "longitude",
            "barcode",
            "structural",
            "external",
            "is_active",
            "capacity",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Aisle A, Zone B"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. A-01, B-12"}),
            "parent": forms.Select(attrs={"class": "form-select"}),
            "location_type": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Description of this location"}),
            "image": forms.FileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Physical address (for external)"}),
            "latitude": forms.NumberInput(attrs={"class": "form-control", "step": "any", "placeholder": "e.g. 53.349805"}),
            "longitude": forms.NumberInput(attrs={"class": "form-control", "step": "any", "placeholder": "e.g. -6.260310"}),
            "barcode": forms.TextInput(attrs={"class": "form-control", "placeholder": "Barcode for scanning"}),
            "structural": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "external": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "capacity": forms.NumberInput(attrs={"class": "form-control", "min": 1, "placeholder": "Max units (optional)"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Internal notes"}),
        }


# -------------------------------------------------
# CATEGORY FORM
# -------------------------------------------------
class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "parent"]

        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Electronics, Cables"}),
            "parent": forms.Select(attrs={"class": "form-select"}),
        }

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")
        instance = self.instance
        if parent and instance and instance.pk:
            # Prevent circular reference: parent cannot be self or a descendant of self
            current = parent
            while current:
                if current.pk == instance.pk:
                    raise ValidationError("A category cannot be its own parent or a descendant of itself.")
                current = current.parent
        return parent


OrderLineFormSet = inlineformset_factory(
    Order,
    OrderLine,
    fields=("item", "quantity", "unit_price"),
    extra=1,
    min_num=1,
    validate_min=True,
    can_delete=True,
    widgets={
        "item": forms.Select(attrs={"class": "form-select order-line-item"}),
        "quantity": forms.NumberInput(attrs={"class": "form-control order-line-qty", "min": 1}),
        "unit_price": forms.NumberInput(attrs={"class": "form-control order-line-price"}),
    },
)


class OrderForm(forms.ModelForm):

    order_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        required=True,
    )
    target_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        required=False,
    )

    class Meta:
        model = Order
        fields = [
            "order_type",
            "reference",
            "description",
            "supplier",
            "client",
            "party_reference",
            "order_date",
            "target_date",
            "status",
            "priority",
            "shipping_location",
            "receiving_location",
            "external_link",
            "notes",
        ]

        widgets = {
            "order_type": forms.Select(attrs={"class": "form-select"}),
            "reference": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. PO0020, SO0029"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Order description (optional)"}),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "client": forms.Select(attrs={"class": "form-select"}),
            "party_reference": forms.TextInput(attrs={"class": "form-control", "placeholder": "Supplier/customer order ref"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "priority": forms.Select(attrs={"class": "form-select"}),
            "shipping_location": forms.Select(attrs={"class": "form-select"}),
            "receiving_location": forms.Select(attrs={"class": "form-select"}),
            "external_link": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    # ------------------------------------------------
    # NEW: Apply forced type (purchase/sale)
    # ------------------------------------------------
    def __init__(self, *args, **kwargs):
        forced_type = kwargs.pop("forced_type", None)
        super().__init__(*args, **kwargs)

        # Make supplier & client optional in forms
        self.fields["supplier"].required = False
        self.fields["client"].required = False
        self.fields["shipping_location"].required = False
        self.fields["receiving_location"].required = False

        # Limit location choices to active locations
        active_locations = Location.objects.filter(is_active=True).order_by("name")
        self.fields["shipping_location"].queryset = active_locations
        self.fields["receiving_location"].queryset = active_locations

        # If the type is forced, set it & disable the field
        if forced_type == "purchase":
            self.fields["order_type"].initial = Order.TYPE_PURCHASE
            self.fields["order_type"].disabled = True

        elif forced_type == "sale":
            self.fields["order_type"].initial = Order.TYPE_SALE
            self.fields["order_type"].disabled = True

    # ------------------------------------------------
    # Validation Logic
    # ------------------------------------------------
    def clean(self):
        cleaned = super().clean()
        order_type = cleaned.get("order_type")
        supplier = cleaned.get("supplier")
        client = cleaned.get("client")

        if order_type == Order.TYPE_PURCHASE and not supplier:
            self.add_error("supplier", "Purchase orders must have a supplier.")
        if order_type == Order.TYPE_SALE and not client:
            self.add_error("client", "Sale orders must have a customer.")
        return cleaned


CURRENCY_CHOICES = [
    ("", "Select currency"),
    ("EUR", "€ EUR - Euro"),
    ("USD", "$ USD - US Dollar"),
    ("GBP", "£ GBP - British Pound"),
    ("CAD", "C$ CAD - Canadian Dollar"),
    ("AUD", "A$ AUD - Australian Dollar"),
]


class SupplierForm(forms.ModelForm):
    currency = forms.ChoiceField(
        choices=CURRENCY_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Supplier
        fields = [
            "name", "description", "website", "email", "phone",
            "address", "currency", "tax_id", "notes", "image", "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Company name"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Description of the company"}),
            "website": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://example.com"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Contact email address"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Contact phone number"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Full address"}),
            "tax_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "Company Tax ID"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Internal notes"}),
            "image": forms.FileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class ClientForm(forms.ModelForm):
    currency = forms.ChoiceField(
        choices=CURRENCY_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Client
        fields = [
            "name", "description", "website", "email", "phone",
            "address", "currency", "tax_id", "notes", "image", "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Company name"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Description of the company"}),
            "website": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://example.com"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Contact email address"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Contact phone number"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Full address"}),
            "tax_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "Company Tax ID"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Internal notes"}),
            "image": forms.FileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


User = get_user_model()

class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
        }

class UserProfileDetailsForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["job_title", "department", "phone_number", "employee_id", "bio"]
        widgets = {
            "job_title": forms.TextInput(attrs={"class": "form-control"}),
            "department": forms.TextInput(attrs={"class": "form-control"}),
            "phone_number": forms.TextInput(attrs={"class": "form-control"}),
            "employee_id": forms.TextInput(attrs={"class": "form-control"}),
            "bio": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

class UserPreferenceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = [
            "notify_anomalies",
            "notify_low_stock",
            "email_notifications",
            "push_notifications",
            "weekly_reports",
            "low_stock_threshold",
            "theme",
            "accent_color",
            "compact_mode",
            "items_per_page",
        ]
        widgets = {
            "notify_anomalies": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notify_low_stock": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "email_notifications": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "push_notifications": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "weekly_reports": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "low_stock_threshold": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "theme": forms.RadioSelect(),
            "accent_color": forms.RadioSelect(),
            "compact_mode": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "items_per_page": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["items_per_page"].widget.choices = [
            (10, "10"),
            (20, "20"),
            (50, "50"),
            (100, "100"),
        ]


class GeneralPreferenceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = ["compact_mode", "items_per_page"]
        widgets = {
            "compact_mode": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "items_per_page": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["items_per_page"].widget.choices = [
            (10, "10"),
            (20, "20"),
            (50, "50"),
            (100, "100"),
        ]


class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = [
            "notify_anomalies",
            "notify_low_stock",
            "email_notifications",
            "push_notifications",
            "weekly_reports",
            "low_stock_threshold",
        ]
        widgets = {
            "notify_anomalies": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notify_low_stock": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "email_notifications": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "push_notifications": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "weekly_reports": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "low_stock_threshold": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
        }


class AppearancePreferenceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = ["theme", "accent_color"]
        widgets = {
            "theme": forms.RadioSelect(),
            "accent_color": forms.RadioSelect(),
        }