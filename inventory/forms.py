from django import forms
from django.conf import settings
from .models import Item, Supplier, Client, Location, Order, OrderLine, Category
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, PasswordChangeForm
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from django.contrib.auth import get_user_model
from .models import UserPreference
from .models import UserProfile


class WareWolfPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].widget.attrs.setdefault("class", "form-control")
        self.fields["old_password"].widget.attrs.setdefault("autocomplete", "current-password")
        for key in ("new_password1", "new_password2"):
            self.fields[key].widget.attrs.setdefault("class", "form-control")
            self.fields[key].widget.attrs.setdefault("autocomplete", "new-password")


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


class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    """Allow signing in with email in the username field; clearer error when account exists but is inactive."""

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username is None or not password:
            return self.cleaned_data

        User = get_user_model()
        key = username.strip()

        self.user_cache = authenticate(self.request, username=key, password=password)
        if self.user_cache is None:
            try:
                u = User.objects.get(email__iexact=key)
            except User.DoesNotExist:
                pass
            else:
                self.user_cache = authenticate(
                    self.request, username=u.get_username(), password=password
                )

        if self.user_cache is None:
            user = None
            try:
                user = User.objects.get(username__iexact=key)
            except User.DoesNotExist:
                try:
                    user = User.objects.get(email__iexact=key)
                except User.DoesNotExist:
                    raise self.get_invalid_login_error() from None
            if user.check_password(password) and not user.is_active:
                raise ValidationError(
                    "This account is not active yet. Manager accounts must be approved by an "
                    "administrator in Django admin before you can log in.",
                    code="inactive",
                )
            raise self.get_invalid_login_error() from None

        self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


# -------------------------------------------------
# ITEM FORM
# -------------------------------------------------
class ItemForm(forms.ModelForm):
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    def __init__(self, *args, user_pref=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            uom = "pcs"
            cur = "EUR"
            if user_pref is not None:
                valid_uom = {c[0] for c in self.fields["unit_of_measure"].choices}
                cand = (user_pref.default_unit_of_measure or "").strip()
                if cand in valid_uom and cand:
                    uom = cand
                cc = (user_pref.default_currency or "").strip()
                if cc in {"EUR", "USD", "GBP"}:
                    cur = cc
            self.fields["unit_of_measure"].initial = uom
            self.fields["currency"].initial = cur

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
            "address", "latitude", "longitude", "currency", "tax_id", "notes", "image", "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Company name"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Description of the company"}),
            "website": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://example.com"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Contact email address"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Contact phone number"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Full address"}),
            "latitude": forms.NumberInput(attrs={"class": "form-control", "placeholder": "e.g. 53.3498", "step": "any"}),
            "longitude": forms.NumberInput(attrs={"class": "form-control", "placeholder": "e.g. -6.2603", "step": "any"}),
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
            "address", "latitude", "longitude", "currency", "tax_id", "notes", "image", "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Company name"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Description of the company"}),
            "website": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://example.com"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Contact email address"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Contact phone number"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Full address"}),
            "latitude": forms.NumberInput(attrs={"class": "form-control", "placeholder": "e.g. 53.3498", "step": "any"}),
            "longitude": forms.NumberInput(attrs={"class": "form-control", "placeholder": "e.g. -6.2603", "step": "any"}),
            "tax_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "Company Tax ID"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Internal notes"}),
            "image": forms.FileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


User = get_user_model()

class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]
        widgets = {
            "username": forms.TextInput(
                attrs={"class": "form-control ww-profile-input", "autocomplete": "username"}
            ),
            "first_name": forms.TextInput(attrs={"class": "form-control ww-profile-input"}),
            "last_name": forms.TextInput(attrs={"class": "form-control ww-profile-input"}),
            "email": forms.EmailInput(attrs={"class": "form-control ww-profile-input"}),
        }

    def clean_username(self):
        name = (self.cleaned_data.get("username") or "").strip()
        if not name:
            raise ValidationError("Username is required.")
        if User.objects.filter(username__iexact=name).exclude(pk=self.instance.pk).exists():
            raise ValidationError("That username is already taken.")
        return name

class UserProfileDetailsForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["avatar", "job_title", "department", "phone_number", "employee_id", "bio"]
        widgets = {
            "avatar": forms.FileInput(
                attrs={
                    "class": "d-none",
                    "accept": "image/*",
                    "id": "ww-profile-avatar-input",
                }
            ),
            "job_title": forms.TextInput(attrs={"class": "form-control ww-profile-input"}),
            "department": forms.TextInput(attrs={"class": "form-control ww-profile-input"}),
            "phone_number": forms.TextInput(attrs={"class": "form-control ww-profile-input"}),
            "employee_id": forms.TextInput(attrs={"class": "form-control ww-profile-input"}),
            "bio": forms.Textarea(attrs={"class": "form-control ww-profile-input", "rows": 4}),
        }

class UserPreferenceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = [
            "notify_anomalies",
            "notify_low_stock",
            "email_notifications",
            "low_stock_threshold",
            "theme",
            "accent_color",
            "font_size",
            "compact_mode",
            "items_per_page",
        ]
        widgets = {
            "notify_anomalies": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notify_low_stock": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "email_notifications": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "low_stock_threshold": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "theme": forms.RadioSelect(),
            "accent_color": forms.RadioSelect(),
            "font_size": forms.RadioSelect(),
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


COMMON_TIMEZONE_CHOICES = [
    ("UTC", "UTC"),
    ("Europe/Dublin", "Europe — Dublin"),
    ("Europe/London", "Europe — London"),
    ("Europe/Paris", "Europe — Paris"),
    ("Europe/Berlin", "Europe — Berlin"),
    ("America/New_York", "Americas — New York"),
    ("America/Chicago", "Americas — Chicago"),
    ("America/Denver", "Americas — Denver"),
    ("America/Los_Angeles", "Americas — Los Angeles"),
    ("America/Toronto", "Americas — Toronto"),
    ("America/Sao_Paulo", "Americas — São Paulo"),
    ("Asia/Dubai", "Asia — Dubai"),
    ("Asia/Kolkata", "Asia — Kolkata"),
    ("Asia/Shanghai", "Asia — Shanghai"),
    ("Asia/Singapore", "Asia — Singapore"),
    ("Asia/Tokyo", "Asia — Tokyo"),
    ("Australia/Sydney", "Australia — Sydney"),
    ("Pacific/Auckland", "Pacific — Auckland"),
]


class GeneralPreferenceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = [
            "items_per_page",
            "default_table_density",
            "compact_mode",
            "default_landing",
            "timezone_name",
            "language_code",
            "date_format_style",
            "clock_format",
            "default_currency",
            "default_unit_of_measure",
            "confirm_destructive_actions",
            "keyboard_shortcuts_enabled",
            "accessibility_mode",
            "voice_feedback_enabled",
            "reduce_motion",
            "underline_links",
        ]
        widgets = {
            "items_per_page": forms.Select(attrs={"class": "form-select"}),
            "default_table_density": forms.Select(attrs={"class": "form-select"}),
            "compact_mode": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "default_landing": forms.Select(attrs={"class": "form-select"}),
            "timezone_name": forms.Select(attrs={"class": "form-select"}),
            "language_code": forms.Select(attrs={"class": "form-select"}),
            "date_format_style": forms.Select(attrs={"class": "form-select"}),
            "clock_format": forms.Select(attrs={"class": "form-select"}),
            "default_currency": forms.Select(attrs={"class": "form-select"}),
            "default_unit_of_measure": forms.Select(attrs={"class": "form-select"}),
            "confirm_destructive_actions": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "keyboard_shortcuts_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "accessibility_mode": forms.Select(attrs={"class": "form-select"}),
            "voice_feedback_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "reduce_motion": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "underline_links": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["items_per_page"].widget.choices = [
            (10, "10"),
            (20, "20"),
            (50, "50"),
            (100, "100"),
        ]
        self.fields["timezone_name"].widget.choices = list(COMMON_TIMEZONE_CHOICES)
        self.fields["language_code"].widget.choices = list(settings.LANGUAGES)
        uom_choices = [
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
        ]
        self.fields["default_unit_of_measure"].widget.choices = uom_choices


class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = [
            "notify_anomalies",
            "notify_low_stock",
            "email_notifications",
            "low_stock_threshold",
        ]
        widgets = {
            "notify_anomalies": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notify_low_stock": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "email_notifications": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "low_stock_threshold": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
        }


class AppearancePreferenceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = ["theme", "accent_color", "font_size"]
        widgets = {
            "theme": forms.RadioSelect(),
            "accent_color": forms.RadioSelect(),
            "font_size": forms.RadioSelect(),
        }