from django import forms
from .models import Item, Supplier, Client, Location, Order, Category
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
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

    class Meta:
        model = Item
        fields = [
            "name",
            "sku",
            "description",
            "quantity",
            "category",
            "reorder_level",
            "lead_time_days",
            "safety_stock",
            "unit_cost",
            "supplier",
            "location",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "sku": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "quantity": forms.NumberInput(attrs={"class": "form-control"}),
            "reorder_level": forms.NumberInput(attrs={"class": "form-control"}),
            "lead_time_days": forms.NumberInput(attrs={"class": "form-control"}),
            "safety_stock": forms.NumberInput(attrs={"class": "form-control"}),
            "unit_cost": forms.NumberInput(attrs={"class": "form-control"}),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "location": forms.Select(attrs={"class": "form-select"}),
        }



# -------------------------------------------------
# CATEGORY FORM
# -------------------------------------------------
class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "parent"]

        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "parent": forms.Select(attrs={"class": "form-select"}),
        }


class OrderForm(forms.ModelForm):

    order_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        required=True,
    )

    class Meta:
        model = Order
        fields = [
            "order_type",
            "item",
            "quantity",
            "unit_price",
            "supplier",
            "client",
            "order_date",
            "status",
            "priority",
            "notes",
        ]

        widgets = {
            "order_type": forms.Select(attrs={"class": "form-select"}),
            "item": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control"}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control"}),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "client": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "priority": forms.Select(attrs={"class": "form-select"}),
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

        # Purchase must have supplier
        if order_type == Order.TYPE_PURCHASE and not supplier:
            self.add_error("supplier", "Purchase orders must have a supplier.")

        # Sale must have client
        if order_type == Order.TYPE_SALE and not client:
            self.add_error("client", "Sale orders must have a customer.")

        return cleaned


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "email", "phone", "address"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["name", "email", "phone", "address"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
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