from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Count, Sum
from .models import Item, Supplier, Client, Location, Order, StockHistory, Category
from .forms import ItemForm, OrderForm, SupplierForm, ClientForm, CategoryForm
from django.db.models import F, Q
from django.core.paginator import Paginator
from django.http import HttpResponse
import csv
import datetime
import json
from datetime import date, timedelta
from django.db import models
from decimal import Decimal
from django.utils import timezone
from django.db.models.functions import TruncWeek
from django.http import JsonResponse
from django.urls import reverse
from inventory.models import Activity
from django.contrib.auth import login
from django.shortcuts import render, redirect, get_object_or_404
from .forms import SignUpForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import permission_required
from django.contrib.auth import logout
from django.contrib import messages
from .forms import SignUpForm
from .models import ManagerRequest
from django.contrib.auth.password_validation import password_validators_help_texts
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model
User = get_user_model()
from django.core.mail import send_mail
from django.conf import settings


def signup(request):
    
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            role = form.cleaned_data["role"]

            user = form.save(commit=False)

            # -------------------------
            # STAFF: active immediately
            # -------------------------
            if role == "staff":
                user.is_active = True
                user.save()

                staff_group = Group.objects.get(name="Staff")
                user.groups.add(staff_group)

                # Notify everyone in-app
                Notification.objects.bulk_create([
                    Notification(
                        user=u,
                        message=f"New account created: {user.username} (Staff)."
                    )
                    for u in User.objects.all()
                ])

                # Email the user (confirmation)
                if user.email:
                    send_mail(
                        subject="WareWolf: Account created",
                        message=(
                            f"Hi {user.username},\n\n"
                            "Your WareWolf account has been created successfully as Staff.\n"
                            "You can log in and start using the system right away.\n\n"
                            "Regards,\n"
                            "WareWolf"
                        ),
                        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                        recipient_list=[user.email],
                        fail_silently=True,
                    )

                login(request, user)
                messages.success(request, f"Welcome back, {request.user.username}!")
                return redirect("dashboard")

            # ---------------------------------------
            # MANAGER: must be approved before login
            # ---------------------------------------
            user.is_active = False
            user.save()

            ManagerRequest.objects.get_or_create(user=user)

            # Notify everyone in-app
            Notification.objects.bulk_create([
                Notification(
                    user=u,
                    message=f"New account created: {user.username} (Manager request)."
                )
                for u in User.objects.all()
            ])

            # Email the user (request received)
            if user.email:
                send_mail(
                    subject="WareWolf: Manager access requested",
                    message=(
                        f"Hi {user.username},\n\n"
                        "Your WareWolf account has been created and your Manager access request has been submitted.\n"
                        "You will receive another email once the request is approved or declined.\n\n"
                        "Regards,\n"
                        "WareWolf"
                    ),
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                    recipient_list=[user.email],
                    fail_silently=True,
                )

            messages.info(
                request,
                "Manager access requested. Your account has been created and is awaiting approval."
            )
            return redirect("login")
    else:
        form = SignUpForm()

    return render(request, "registration/signup.html", {
        "form": form,
        "password_help": password_validators_help_texts(),
    })



@login_required
def logout_view(request):
    if request.method == "POST":
        logout(request)
        return redirect("login")

    return render(request, "registration/logout_confirm.html")


@login_required
def global_search(request):
    q = request.GET.get("q", "").strip()

    if not q:
        return JsonResponse({"results": []})

    results = []

    # Stock Items
    for i in Item.objects.filter(
        Q(name__icontains=q) |
        Q(sku__icontains=q) |
        Q(description__icontains=q)
    )[:5]:
        results.append({
            "type": "Stock Item",
            "name": i.name,
            "sub": f"SKU: {i.sku}",
            "url": reverse("item_edit", args=[i.id]),
        })

    # Categories
    for c in Category.objects.filter(Q(name__icontains=q))[:5]:
        results.append({
            "type": "Category",
            "name": c.name,
            "sub": c.full_path,
            "url": reverse("category_edit", args=[c.id]),
        })

    # Suppliers
    for s in Supplier.objects.filter(Q(name__icontains=q))[:5]:
        results.append({
            "type": "Supplier",
            "name": s.name,
            "sub": s.email or "",
            "url": reverse("supplier_edit", args=[s.id]),
        })

    # Customers
    for c in Client.objects.filter(
        Q(name__icontains=q) | Q(email__icontains=q)
    )[:5]:
        results.append({
            "type": "Customer",
            "name": c.name,
            "sub": c.email,
            "url": reverse("client_edit", args=[c.id]),
        })

    # Locations
    for l in Location.objects.filter(Q(name__icontains=q))[:5]:
        results.append({
            "type": "Location",
            "name": l.name,
            "sub": l.get_breadcrumb(),
            "url": reverse("location_view", args=[l.id]),
        })

    # Orders (both purchase + sale)
    for o in Order.objects.filter(
        Q(id__icontains=q) |
        Q(notes__icontains=q) |
        Q(item__name__icontains=q)
    )[:5]:
        results.append({
            "type": "Order",
            "name": f"Order #{o.id}",
            "sub": f"{o.order_type.title()} – {o.item.name}",
            "url": reverse("order_edit", args=[o.id]),
        })

    return JsonResponse({"results": results})


def _is_manager_or_admin(user):
    return (
        user.is_authenticated
        and (
            user.is_superuser
            or user.groups.filter(name__in=["Manager", "Admin"]).exists()
        )
    )

@login_required
def approve_manager_request(request, request_id):
    if not _is_manager_or_admin(request.user):
        return redirect("dashboard")

    req = get_object_or_404(ManagerRequest, id=request_id, status="PENDING")
    manager_group = Group.objects.get(name="Manager")

    req.status = "APPROVED"
    req.decided_by = request.user
    req.decided_at = timezone.now()
    req.save()

    # allow login + grant manager permissions
    req.user.is_active = True
    req.user.save()
    req.user.groups.add(manager_group)

    # email user (ONLY if they have an email)
    if req.user.email:
        send_mail(
            subject="WareWolf: Manager access approved",
            message=(
                f"Hi {req.user.username},\n\n"
                "Your request for Manager access has been APPROVED.\n"
                "You can now log in and use WareWolf with Manager permissions.\n\n"
                "Regards,\nWareWolf"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[req.user.email],
            fail_silently=True,
        )

    messages.success(request, f"Approved manager access for {req.user.username}.")
    return redirect("dashboard")


@login_required
def decline_manager_request(request, request_id):
    if not _is_manager_or_admin(request.user):
        return redirect("dashboard")

    req = get_object_or_404(ManagerRequest, id=request_id, status="PENDING")

    req.status = "DECLINED"
    req.decided_by = request.user
    req.decided_at = timezone.now()
    req.save()

    # keep blocked from logging in
    req.user.is_active = False
    req.user.save()

    # email user (ONLY if they have an email)
    if req.user.email:
        send_mail(
            subject="WareWolf: Manager access declined",
            message=(
                f"Hi {req.user.username},\n\n"
                "Your request for Manager access has been DECLINED.\n"
                "If you believe this was a mistake, please contact an Admin/Manager.\n\n"
                "Regards,\nWareWolf"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[req.user.email],
            fail_silently=True,
        )

    messages.warning(request, f"Declined manager access for {req.user.username}.")
    return redirect("dashboard")


from .models import Notification
@require_POST
@login_required
def dismiss_notification(request, notification_id):
    n = get_object_or_404(Notification, id=notification_id, user=request.user)
    n.is_read = True
    n.save(update_fields=["is_read"])
    return redirect(request.META.get("HTTP_REFERER", "dashboard"))


@require_POST
@login_required
def dismiss_alert(request):
    """
    Session-based dismiss for 'dynamic' alerts (low stock / delivered / manager request).
    """
    key = request.POST.get("key")
    if key:
        dismissed = set(request.session.get("dismissed_alerts", []))
        dismissed.add(key)
        request.session["dismissed_alerts"] = list(dismissed)
    return redirect(request.META.get("HTTP_REFERER", "dashboard"))



# -------------------------------
# Dashboard
# -------------------------------
@login_required
def dashboard(request):
    from django.db.models import Sum, Count
    from django.db.models.functions import TruncWeek
    import datetime
    from inventory.models import DemandAnomaly

    # ---- basic counts ----
    total_items = Item.objects.count()
    low_stock_items = Item.objects.filter(quantity__lte=F("reorder_level")).count()
    supplier_count = Supplier.objects.count()
    client_count = Client.objects.count()

    # ---- inventory trend (last 30 days) ----
    today = timezone.now().date()
    start_date = today - datetime.timedelta(days=29)

    history_qs = (
        StockHistory.objects
        .filter(date__range=(start_date, today))
        .values("date")
        .annotate(total_qty=Sum("quantity"))
        .order_by("date")
    )

    stock_dates = [row["date"].strftime("%d %b") for row in history_qs]
    stock_values = [int(row["total_qty"]) for row in history_qs]

    # Simple Moving Average forecast
    forecast = None
    if stock_values:
        window = min(len(stock_values), 7)
        sma = sum(stock_values[-window:]) / window
        forecast = round(sma)

    # ---- weekly orders activity (last 6 weeks) ----
    orders_start = today - datetime.timedelta(weeks=5)

    weekly_qs = (
        Order.objects
        .filter(order_date__gte=orders_start)
        .annotate(week=TruncWeek("order_date"))
        .values("week")
        .annotate(count=Count("id"))
        .order_by("week")
    )

    weekly_labels = [row["week"].strftime("%d %b") for row in weekly_qs if row["week"]]
    weekly_counts = [row["count"] for row in weekly_qs]

    # ---- top item by number of orders ----
    top_item = (
        Item.objects
        .annotate(total_orders=Count("orders"))
        .filter(total_orders__gt=0)
        .order_by("-total_orders")
        .first()
    )

    # ---- recent activity feed ----
    from inventory.models import Activity
    recent_activity = Activity.objects.all()[:5]

    # ---- recent demand anomalies ----
    recent_anomalies = DemandAnomaly.objects.select_related("item").all()[:8]

    # ---- inventory-by-category pie data ----
    # Sum quantities grouped by category name
    category_qs = (
        Item.objects
        .values("category__name")
        .annotate(total_qty=Sum("quantity"))
        .order_by("category__name")
    )

    pie_labels = [row["category__name"] or "Uncategorised" for row in category_qs]
    pie_values = [int(row["total_qty"]) for row in category_qs]

    # -------------------------------
    # SMART PURCHASE ORDER RECOMMENDATIONS
    # -------------------------------
    recommendations = []
    today = timezone.now().date()

    for item in Item.objects.all():
        # Must be low stock
        if item.quantity > item.reorder_level:
            continue

        # Recent stock adjustments (from StockHistory):
        recent_adjustments = StockHistory.objects.filter(
            item=item,
            date__gte=today - datetime.timedelta(days=7)
        ).count()

        # Recent sale orders:
        recent_sales = Order.objects.filter(
            item=item,
            order_type="SALE",
            order_date__gte=today - datetime.timedelta(days=7)
        ).count()

        # Total 30-day activity:
        monthly_activity = recent_adjustments + Order.objects.filter(
            item=item,
            order_type="SALE",
            order_date__gte=today - datetime.timedelta(days=30)
        ).count()

        # NEW RULES
        active = False

        # Rule 1: recent adjustments
        if recent_adjustments >= 2:
            active = True

        # Rule 2: recent sales
        if recent_sales >= 1:
            active = True

        # Rule 3: monthly activity threshold
        if monthly_activity >= 3:
            active = True

        # Rule 4: new item but recently changed
        if StockHistory.objects.filter(item=item).count() < 5:
            if recent_adjustments >= 1 or recent_sales >= 1:
                active = True

        if not active:
            continue

        # Recommendation amount
        recommended_qty = max(item.reorder_level * 2 - item.quantity, 1)

        recommendations.append({
            "item": item,
            "recommended_qty": recommended_qty,
        })


    context = {
        "total_items": total_items,
        "low_stock_items": low_stock_items,
        "supplier_count": supplier_count,
        "client_count": client_count,

        "stock_dates": stock_dates,
        "stock_values": stock_values,
        "forecast": forecast,

        "weekly_order_labels": weekly_labels,
        "weekly_order_counts": weekly_counts,

        "top_item": top_item,
        "recent_activity": recent_activity,
        "recent_anomalies": recent_anomalies,

        "pie_labels": pie_labels,
        "pie_values": pie_values,

        "recommendations": recommendations,
    }

    return render(request, "inventory/dashboard.html", context)


@login_required
@permission_required("inventory.view_item", raise_exception=True)
def item_forecast(request, pk):
    item = get_object_or_404(Item, pk=pk)
    from inventory.ml.forecasting import prophet_forecast_item
    result = prophet_forecast_item(item, horizon_days=30)

    return render(request, "inventory/item_forecast.html", {
        "item": item,
        "history": result.history,
        "forecast": result.forecast,
        "metrics": result.metrics,
        "rec": result.recommendation,
    })



# -------------------------------
# ITEM CRUD
# -------------------------------

# ======================================================
# STOCK ITEMS LIST + FILTER + SORT + CATEGORY FILTERING
# ======================================================
@login_required
@permission_required("inventory.view_item", raise_exception=True)
def item_list(request):

    items = Item.objects.select_related("supplier", "location", "category").annotate(
        order_count=Count("orders")
    )

    # -----------------------------
    # ACTIVE / ARCHIVED FILTER
    # -----------------------------
    status = request.GET.get("status", "active")  # active | archived | all

    if status == "active":
        items = items.filter(is_active=True)
    elif status == "archived":
        items = items.filter(is_active=False)
    # "all" -> no filter

    # -------------------------
    # SEARCH
    # -------------------------
    q = request.GET.get("q", "").strip()
    if q:
        items = items.filter(
            Q(name__icontains=q) |
            Q(sku__icontains=q)
        )

    # -------------------------
    # STOCK FILTER
    # -------------------------
    filter_option = request.GET.get("filter", "")

    if filter_option == "in_stock":
        items = items.filter(quantity__gt=F("reorder_level"))

    elif filter_option == "low_stock":
        items = items.filter(quantity__gt=0, quantity__lte=F("reorder_level"))

    elif filter_option == "out_of_stock":
        items = items.filter(quantity__lte=0)

    # -------------------------
    # CATEGORY FILTER
    # -------------------------
    category_id = request.GET.get("category")
    if category_id:
        items = items.filter(category_id=category_id)

    categories = Category.objects.all()

    # -------------------------
    # SORTING
    # -------------------------
    sort = request.GET.get("sort", "name")

    valid_sorts = [
        "name", "-name",
        "sku", "-sku",
        "quantity", "-quantity",
        "reorder_level", "-reorder_level",
        "supplier__name", "-supplier__name",
        "location__name", "-location__name",
        "category__name", "-category__name",
    ]

    if sort not in valid_sorts:
        sort = "name"

    items = items.order_by(sort)

    # -------------------------
    # PAGINATION
    # -------------------------
    paginator = Paginator(items, 12)
    page = request.GET.get("page")
    items = paginator.get_page(page)

    return render(request, "inventory/item_list.html", {
        "items": items,
        "query": q,
        "filter_option": filter_option,
        "sort": sort,
        "show_categories": False,
    })



@login_required
@permission_required("inventory.change_item", raise_exception=True)
def item_toggle_archive(request, pk):
    item = get_object_or_404(Item, pk=pk)
    item.is_active = not item.is_active
    item.save(update_fields=["is_active"])

    if item.is_active:
        messages.success(request, f"Unarchived item: {item.name}")
    else:
        messages.success(request, f"Archived item: {item.name}")

    # Preserve filters if you want (optional), otherwise just go back to list
    return redirect("item_list")

# ======================================================
# ITEM ADJUST QUANTITY
# ======================================================
@login_required
@permission_required("inventory.change_item", raise_exception=True)
def item_adjust_quantity(request, pk):
    item = get_object_or_404(Item, pk=pk)

    if request.method == "POST":
        adjustment = int(request.POST.get("adjustment"))
        item.quantity = item.quantity + adjustment
        item.save()

        # Log activity
        from django.apps import apps
        Activity = apps.get_model("inventory", "Activity")
        Activity.objects.create(
            message=f"Adjusted quantity for {item.name}: change of {adjustment}",
            user=request.user
        )

        return redirect("item_list")

    return render(request, "inventory/item_adjust.html", {"item": item})



# ======================================================
# ITEM CRUD
# ======================================================
@login_required
@permission_required("inventory.add_item", raise_exception=True)
def item_create(request):
    if request.method == "POST":
        form = ItemForm(request.POST)
        if form.is_valid():
            item = form.save()

            # Log activity
            from django.apps import apps
            Activity = apps.get_model("inventory", "Activity")
            Activity.objects.create(
                message=f"New item created: {item.name}",
                user=request.user
            )

            return redirect("item_list")
    else:
        form = ItemForm()

    return render(request, "inventory/item_form.html", {
        "form": form,
        "all_categories": Category.objects.all(),
    })


@login_required
@permission_required("inventory.change_item", raise_exception=True)
def item_edit(request, pk):
    item = get_object_or_404(Item, pk=pk)

    if request.method == "POST":
        form = ItemForm(request.POST, instance=item)
        if form.is_valid():
            updated_item = form.save()

            # Log activity
            from django.apps import apps
            Activity = apps.get_model("inventory", "Activity")
            Activity.objects.create(
                message=f"Item updated: {updated_item.name}",
                user=request.user
            )

            return redirect("item_list")
    else:
        form = ItemForm(instance=item)

    return render(request, "inventory/item_form.html", {
        "form": form,
        "all_categories": Category.objects.all(),
    })


from django.db.models.deletion import ProtectedError
from django.contrib import messages
@login_required
@permission_required("inventory.delete_item", raise_exception=True)
def item_delete(request, pk):
    item = get_object_or_404(Item, pk=pk)

    if request.method == "POST":
        item.delete()
        return redirect("item_list")
    
    try:
        item.delete()
        messages.success(request, "Item deleted.")
    except ProtectedError:
        messages.error(request, "Cannot delete item because it has order history. Archive it instead.")
        return redirect("item_list")

    return render(request, "inventory/item_confirm_delete.html", {"item": item})

from django.db import transaction
from django.contrib.auth.decorators import login_required, user_passes_test
@login_required
@user_passes_test(_is_manager_or_admin)
@transaction.atomic
def item_hard_delete(request, pk):
    item = get_object_or_404(Item, pk=pk)

    if request.method == "POST":
        # Count related records for messaging
        orders_deleted = Order.objects.filter(item=item).count()
        history_deleted = StockHistory.objects.filter(item=item).count()

        # Delete related records first
        Order.objects.filter(item=item).delete()
        StockHistory.objects.filter(item=item).delete()

        name = item.name
        item.delete()

        messages.success(
            request,
            f"Permanently deleted item '{name}' (orders: {orders_deleted}, history: {history_deleted})."
        )
        return redirect("item_list")

    # GET -> show confirmation page with counts
    order_count = Order.objects.filter(item=item).count()
    history_count = StockHistory.objects.filter(item=item).count()

    return render(request, "inventory/item_hard_delete_confirm.html", {
        "item": item,
        "order_count": order_count,
        "history_count": history_count,
    })

@login_required
@permission_required("inventory.view_item", raise_exception=True)
def item_export_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename=\"stock_items.csv\"'

    writer = csv.writer(response)
    writer.writerow([
        "Name", "SKU", "Quantity",
        "Reorder Level", "Supplier",
        "Location", "Category"
    ])

    for item in Item.objects.select_related(
        "supplier", "location", "category"
    ).all():

        writer.writerow([
            item.name,
            item.sku,
            item.quantity,
            item.reorder_level,
            item.supplier.name if item.supplier else "",
            item.location.name if item.location else "",
            item.category.name if item.category else "",
        ])

    return response


# ======================================================
# CATEGORY TREE VIEW + CRUD
# ======================================================
@login_required
@permission_required("inventory.view_category", raise_exception=True)
def category_list(request):
    roots = Category.objects.filter(parent__isnull=True)

    return render(request, "inventory/category_list.html", {
        "categories": roots,
        "show_categories": True,
    })

@login_required
@permission_required("inventory.add_category", raise_exception=True)
def category_create_from_item(request):
    if request.method == "POST":
        name = request.POST.get("name")
        parent_id = request.POST.get("parent")

        parent = Category.objects.get(id=parent_id) if parent_id else None
        Category.objects.create(name=name, parent=parent)

        return redirect(request.META.get("HTTP_REFERER", "item_create"))
    

@login_required
@permission_required("inventory.add_category", raise_exception=True)
def category_create(request):
    if request.method == "POST":
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("category_list")
    else:
        form = CategoryForm()

    return render(request, "inventory/category_form.html", {
        "form": form,
        "title": "Add Category",
        "view": "categories",
    })

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


@login_required
@permission_required("inventory.add_category", raise_exception=True)
@csrf_exempt
def category_create_ajax(request):
    """Create a category from the item form modal (AJAX)."""
    if request.method == "POST":
        name = request.POST.get("name")
        parent_id = request.POST.get("parent")

        if not name:
            return JsonResponse({"success": False, "error": "Name required"})

        parent = None
        if parent_id:
            parent = Category.objects.filter(id=parent_id).first()

        category = Category.objects.create(name=name, parent=parent)

        return JsonResponse({
            "success": True,
            "id": category.id,
            "name": category.full_path,
        })

    return JsonResponse({"success": False})


@login_required
@permission_required("inventory.change_category", raise_exception=True)
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == "POST":
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            return redirect("category_list")
    else:
        form = CategoryForm(instance=category)

    return render(request, "inventory/category_form.html", {
        "form": form,
        "title": "Edit Category",
        "view": "categories",
    })

@login_required
@permission_required("inventory.delete_category", raise_exception=True)
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == "POST":
        category.delete()
        return redirect("category_list")

    return render(request, "inventory/category_confirm_delete.html", {
        "category": category,
        "view": "categories",
    })




# -------------------------------
# LOCATION CRUD
# -------------------------------
@login_required
@permission_required("inventory.view_location", raise_exception=True)
def location_list(request):
    """
    Location listing with:
    - Search
    - Filtering (type, structural, external)
    - Sorting
    - Stock count (via annotation)
    """

    # -------------------------
    # Base Query + STOCK ANNOTATION
    # -------------------------
    locations = Location.objects.annotate(
        stock=Sum("inventory_items__quantity")
    )

    # -------------------------
    # SEARCH
    # -------------------------
    q = request.GET.get("q", "")
    if q:
        locations = locations.filter(name__icontains=q)

    # -------------------------
    # FILTERS
    # -------------------------
    type_filter = request.GET.get("type")
    structural_filter = request.GET.get("structural")
    external_filter = request.GET.get("external")

    if type_filter:
        locations = locations.filter(location_type=type_filter)

    if structural_filter in ["yes", "no"]:
        locations = locations.filter(structural=(structural_filter == "yes"))

    if external_filter in ["yes", "no"]:
        locations = locations.filter(external=(external_filter == "yes"))

    # -------------------------
    # SORTING
    # -------------------------
    sort = request.GET.get("sort", "name")

    # prevent invalid sorting fields from crashing the query
    valid_sorts = ["name", "parent__name", "location_type", "structural", "external", "stock"]

    if sort not in valid_sorts:
        sort = "name"

    locations = locations.order_by(sort)

    # -------------------------
    # RENDER
    # -------------------------
    return render(request, "inventory/location_list.html", {
        "locations": locations,
        "location_types": Location.LOCATION_TYPES,
        "query": q,
    })


@login_required
@permission_required("inventory.add_location", raise_exception=True)
def location_create(request):
    if request.method == "POST":
        parent_id = request.POST.get("parent") or None

        Location.objects.create(
            parent=Location.objects.get(id=parent_id) if parent_id else None,
            name=request.POST.get("name"),
            description=request.POST.get("description"),
            structural=("structural" in request.POST),
            external=("external" in request.POST),
            location_type=request.POST.get("location_type"),
        )
        return redirect("location_list")

    return render(request, "inventory/location_form.html", {
        "all_locations": Location.objects.all(),
        "location_types": Location.LOCATION_TYPES,
    })

@login_required
@permission_required("inventory.change_location", raise_exception=True)
def location_edit(request, pk):
    location = get_object_or_404(Location, pk=pk)

    if request.method == "POST":
        parent_id = request.POST.get("parent") or None

        location.parent = Location.objects.get(id=parent_id) if parent_id else None
        location.name = request.POST.get("name")
        location.description = request.POST.get("description")
        location.structural = ("structural" in request.POST)
        location.external = ("external" in request.POST)
        location.location_type = request.POST.get("location_type")
        location.save()

        return redirect("location_list")

    return render(request, "inventory/location_form.html", {
        "location": location,
        "all_locations": Location.objects.exclude(id=location.id),
        "location_types": Location.LOCATION_TYPES,
    })


@login_required
@permission_required("inventory.delete_location", raise_exception=True)
def location_delete(request, pk):
    location = get_object_or_404(Location, pk=pk)

    if request.method == "POST":
        location.delete()
        return redirect("location_list")

    return render(request, "inventory/location_confirm_delete.html", {"location": location})


# -------------------------------
# LOCATION TREE (Hierarchy View)
# -------------------------------
@login_required
@permission_required("inventory.view_location", raise_exception=True)
def location_tree(request):
    roots = Location.objects.filter(parent__isnull=True)
    return render(request, "inventory/location_tree.html", {"roots": roots})


# -------------------------------
# LOCATION DETAIL VIEW
# -------------------------------
@login_required
@permission_required("inventory.view_location", raise_exception=True)
def location_view(request, pk):
    location = get_object_or_404(Location, pk=pk)
    items = location.inventory_items.all()

    return render(request, "inventory/location_view.html", {
        "location": location,
        "items": items,
    })

# -------------------------------
# ORDER CRUD
# -------------------------------
@login_required
@permission_required("inventory.view_order", raise_exception=True)
def order_list(request):
    orders = Order.objects.select_related("item", "supplier", "client")

    # --- search ---
    q = request.GET.get("q", "").strip()
    if q:
        orders = orders.filter(
            Q(item__name__icontains=q)
            | Q(supplier__name__icontains=q)
            | Q(client__name__icontains=q)
        )

    # --- filter by type (all / purchase / sale) ---
    type_filter = request.GET.get("type", "all")
    if type_filter == "purchase":
        orders = orders.filter(order_type=Order.TYPE_PURCHASE)
    elif type_filter == "sale":
        orders = orders.filter(order_type=Order.TYPE_SALE)

    # --- filter by status ---
    status_filter = request.GET.get("status", "all")
    valid_statuses = dict(Order.STATUS_CHOICES).keys()
    if status_filter in valid_statuses:
        orders = orders.filter(status=status_filter)

    # Summary cards
    purchase_count = Order.objects.filter(order_type=Order.TYPE_PURCHASE).count()
    sale_count = Order.objects.filter(order_type=Order.TYPE_SALE).count()
    pending_count = Order.objects.filter(status=Order.STATUS_PENDING).count()
    delivered_count = Order.objects.filter(status=Order.STATUS_DELIVERED).count()

    return render(request, "inventory/order_list.html", {
        "orders": orders,
        "search_query": q,
        "type_filter": type_filter,
        "context_type": type_filter,   # <-- IMPORTANT FOR TEMPLATE BUTTONS
        "status_filter": status_filter,
        "status_choices": Order.STATUS_CHOICES,
        "purchase_count": purchase_count,
        "sale_count": sale_count,
        "pending_count": pending_count,
        "delivered_count": delivered_count,
    })


@login_required
@permission_required("inventory.add_order", raise_exception=True)
def order_create(request):
    # Query parameters:
    # ?type=purchase or ?type=sale (your existing behaviour)
    forced_type = request.GET.get("type")  

    # Recommendation parameters:
    # ?item=ID  and ?qty=NUMBER
    item_id = request.GET.get("item")
    qty = request.GET.get("qty")

    # Build initial form values
    initial = {}

    # If recommendation supplied an item
    if item_id:
        try:
            initial["item"] = Item.objects.get(pk=item_id)
        except Item.DoesNotExist:
            pass

    # If recommendation supplied a quantity
    if qty:
        try:
            initial["quantity"] = int(qty)
        except ValueError:
            pass

    # If coming from recommendation popup → default to PURCHASE
    if item_id or qty:
        initial["order_type"] = Order.TYPE_PURCHASE

    # Existing forced type from your URLs overrides everything else
    if forced_type in ["purchase", "sale"]:
        initial["order_type"] = forced_type.upper()

    # -------------------------
    # POST REQUEST (Form submit)
    # -------------------------
    if request.method == "POST":
        form = OrderForm(request.POST)

        # If field was locked in UI, reapply the forced value
        if forced_type in ["purchase", "sale"]:
            form.data = form.data.copy()
            form.data["order_type"] = forced_type.upper()

        if form.is_valid():
            order = form.save()
            order.apply_stock_if_needed(actor=request.user)  # stock update logic
            return redirect("order_list")

    # -------------------------
    # GET REQUEST (Render form)
    # -------------------------
    else:
        form = OrderForm(initial=initial)

        # Lock drop-down if URL forced a type (?type=purchase)
        if forced_type in ["purchase", "sale"]:
            form.fields["order_type"].widget.attrs.update({"disabled": True})

    return render(request, "inventory/order_form.html", {
        "form": form,
        "forced_type": forced_type,
    })



@login_required
@permission_required("inventory.change_order", raise_exception=True)
def order_edit(request, pk):
    order = get_object_or_404(Order, pk=pk)

    if request.method == "POST":
        form = OrderForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            return redirect("order_list")
    else:
        form = OrderForm(instance=order)

    return render(
        request,
        "inventory/order_form.html",
        {"form": form, "edit": True, "order": order},
    )


@login_required
@permission_required("inventory.delete_order", raise_exception=True)
def order_delete(request, pk):
    order = get_object_or_404(Order, pk=pk)

    if request.method == "POST":
        order.delete()
        return redirect("order_list")

    return render(
        request,
        "inventory/order_confirm_delete.html",
        {"order": order},
    )


@login_required
@permission_required("inventory.change_order", raise_exception=True)
def order_mark_delivered(request, pk):
    """
    Mark an order as delivered and automatically apply stock movement
    once. Uses a small POST form in the list page.
    """
    order = get_object_or_404(Order, pk=pk)

    if request.method == "POST":
        # set status first, then apply stock once
        order.status = Order.STATUS_DELIVERED
        order.save(update_fields=["status"])
        order.apply_stock_if_needed(actor=request.user)
        return redirect("order_list")

    return redirect("order_list")


@login_required
@permission_required("inventory.view_supplier", raise_exception=True)
@permission_required("inventory.view_client", raise_exception=True)
def contacts_list(request):
    # ----------------------------
    # 1. GET FILTERS
    # ----------------------------
    type_filter = request.GET.get("type", "all")
    q = request.GET.get("q", "").strip()

    suppliers = Supplier.objects.all()
    clients = Client.objects.all()

    # ----------------------------
    # 2. Build merged contact dataset
    # ----------------------------
    contacts = []

    # SUPPLIERS
    for s in suppliers:
        supplier_orders = Order.objects.filter(supplier=s)
        contacts.append({
            "id": s.id,
            "name": s.name,
            "type": "supplier",
            "email": s.email,
            "phone": s.phone,
            "address": s.address,
            "orders": supplier_orders.count(),
            "total_value": supplier_orders.aggregate(total=Sum("unit_price"))["total"] or 0,
        })

    # CUSTOMERS
    for c in clients:
        client_orders = Order.objects.filter(client=c)
        contacts.append({
            "id": c.id,
            "name": c.name,
            "type": "customer",
            "email": c.email,
            "phone": c.phone,
            "address": c.address,
            "orders": client_orders.count(),
            "total_value": client_orders.aggregate(total=Sum("unit_price"))["total"] or 0,
        })

    # ----------------------------
    # 3. Apply SEARCH FILTER
    # ----------------------------
    if q:
        contacts = [
            c for c in contacts
            if q.lower() in c["name"].lower()
            or q.lower() in c["email"].lower()
            or q.lower() in c["phone"].lower()
        ]

    # ----------------------------
    # 4. Apply TYPE FILTER
    # ----------------------------
    if type_filter == "suppliers":
        contacts = [c for c in contacts if c["type"] == "supplier"]

    elif type_filter == "customers":
        contacts = [c for c in contacts if c["type"] == "customer"]

    # ----------------------------
    # 5. Analytics (Top contact insights)
    # ----------------------------
    top_supplier = None
    top_customer = None

    # Only evaluate if contacts exist to avoid errors
    suppliers_only = [c for c in contacts if c["type"] == "supplier"]
    customers_only = [c for c in contacts if c["type"] == "customer"]

    if suppliers_only:
        top_supplier = max(suppliers_only, key=lambda c: c["orders"])

    if customers_only:
        top_customer = max(customers_only, key=lambda c: c["total_value"])

    # ----------------------------
    # 6. PAGINATION
    # ----------------------------
    paginator = Paginator(contacts, 10)  # 10 per page
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # ----------------------------
    # 7. Summary cards
    # ----------------------------
    total_suppliers = suppliers.count()
    total_customers = clients.count()
    active_relationships = total_suppliers + total_customers

    # ----------------------------
    # 8. Render page
    # ----------------------------
    return render(request, "inventory/contacts_list.html", {
        "contacts": page_obj,
        "page_obj": page_obj,
        "pagination": True,

        "type_filter": type_filter,
        "total_suppliers": total_suppliers,
        "total_customers": total_customers,
        "active_relationships": active_relationships,

        # analytics
        "top_supplier": top_supplier,
        "top_customer": top_customer,

        # keep search value in form
        "search_query": q,
    })

@login_required
@permission_required("inventory.add_supplier", raise_exception=True)
def supplier_create(request):
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("contacts_list")
    else:
        form = SupplierForm()

    return render(request, "inventory/supplier_form.html", {"form": form})


@login_required
@permission_required("inventory.change_supplier", raise_exception=True)
def supplier_edit(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)

    if request.method == "POST":
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            return redirect("contacts_list")
    else:
        form = SupplierForm(instance=supplier)

    return render(request, "inventory/supplier_form.html", {
        "form": form,
        "edit": True,
        "supplier": supplier
    })


@login_required
@permission_required("inventory.delete_supplier", raise_exception=True)
def supplier_delete(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)

    if request.method == "POST":
        supplier.delete()
        return redirect("contacts_list")

    return render(request, "inventory/supplier_confirm_delete.html", {
        "supplier": supplier
    })


@login_required
@permission_required("inventory.add_client", raise_exception=True)
def client_create(request):
    if request.method == "POST":
        form = ClientForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("contacts_list")
    else:
        form = ClientForm()

    return render(request, "inventory/client_form.html", {"form": form})


@login_required
@permission_required("inventory.change_client", raise_exception=True)
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)

    if request.method == "POST":
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            return redirect("contacts_list")
    else:
        form = ClientForm(instance=client)

    return render(request, "inventory/client_form.html", {
        "form": form,
        "edit": True,
        "client": client
    })


@login_required
@permission_required("inventory.delete_client", raise_exception=True)
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk)

    if request.method == "POST":
        client.delete()
        return redirect("contacts_list")

    return render(request, "inventory/client_confirm_delete.html", {
        "client": client
    })
