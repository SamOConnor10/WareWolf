from django import forms
from .models import Item, Supplier, Client, Location, Order, Category
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

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