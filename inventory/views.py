from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Count, Sum
from .models import Item, Supplier, Client, Location, Order, StockHistory, Category
from .forms import ItemForm, OrderForm, SupplierForm, ClientForm, CategoryForm, LocationForm
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
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.cache import never_cache

# Shared pagination settings for all list views
DEFAULT_PER_PAGE = 20
PER_PAGE_CHOICES = [10, 20, 50, 100]


def get_per_page(request):
    """Read and validate per_page from request. Returns int in PER_PAGE_CHOICES or DEFAULT_PER_PAGE."""
    try:
        val = int(request.GET.get("per_page", DEFAULT_PER_PAGE))
        return val if val in PER_PAGE_CHOICES else DEFAULT_PER_PAGE
    except (TypeError, ValueError):
        return DEFAULT_PER_PAGE


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

    # Stock Items -> detail/profile page
    for i in Item.objects.filter(
        Q(name__icontains=q) |
        Q(sku__icontains=q) |
        Q(description__icontains=q)
    )[:5]:
        results.append({
            "type": "Stock Item",
            "name": i.name,
            "sub": f"SKU: {i.sku}",
            "url": reverse("item_detail", args=[i.id]),
        })

    # Categories -> item list filtered by category (shows items in that category)
    for c in Category.objects.filter(Q(name__icontains=q))[:5]:
        results.append({
            "type": "Category",
            "name": c.name,
            "sub": c.full_path,
            "url": reverse("item_list") + f"?category={c.id}",
        })

    # Suppliers -> edit page (no separate profile view; edit shows details)
    for s in Supplier.objects.filter(Q(name__icontains=q))[:5]:
        results.append({
            "type": "Supplier",
            "name": s.name,
            "sub": s.email or "",
            "url": reverse("supplier_edit", args=[s.id]),
        })

    # Customers -> edit page (no separate profile view; edit shows details)
    for c in Client.objects.filter(
        Q(name__icontains=q) | Q(email__icontains=q)
    )[:5]:
        results.append({
            "type": "Customer",
            "name": c.name,
            "sub": c.email,
            "url": reverse("client_edit", args=[c.id]),
        })

    # Locations -> profile/view page (already correct)
    for l in Location.objects.filter(Q(name__icontains=q))[:5]:
        results.append({
            "type": "Location",
            "name": l.name,
            "sub": l.get_breadcrumb(),
            "url": reverse("location_view", args=[l.id]),
        })

    # Orders -> order edit (acts as profile page; no separate order_detail view)
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


def is_manager_or_admin(user):
    return (
        user.is_authenticated
        and (
            user.is_superuser
            or user.groups.filter(name__in=["Manager", "Admin"]).exists()
        )
    )

@login_required
def approve_manager_request(request, request_id):
    if not is_manager_or_admin(request.user):
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
    if not is_manager_or_admin(request.user):
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

    # ---- inventory trend (configurable: 7, 14, or 30 days) ----
    today = timezone.now().date()
    trend_days = int(request.GET.get("trend_days", 30))
    trend_days = max(7, min(30, trend_days))  # clamp 7–30
    start_date = today - datetime.timedelta(days=trend_days - 1)

    # Exclude today from history: StockHistory for today is incomplete (only items with deliveries)
    history_qs = (
        StockHistory.objects
        .filter(date__range=(start_date, today), date__lt=today)
        .values("date")
        .annotate(total_qty=Sum("quantity"))
        .order_by("date")
    )

    stock_dates = [row["date"].strftime("%d %b") for row in history_qs]
    stock_values = [int(row["total_qty"]) for row in history_qs]

    # Always append today with live total (Sum of all Item.quantity) — the only accurate source
    current_total = Item.objects.aggregate(t=Sum("quantity"))["t"] or 0
    today_str = today.strftime("%d %b")
    stock_dates.append(today_str)
    stock_values.append(int(current_total))

    # Simple Moving Average forecast (average of last 7 data points, includes today)
    forecast = None
    sma_dates = []
    sma_values = []
    sma_trend = "stable"  # up, down, stable
    if stock_values:
        window = min(len(stock_values), 7)
        sma = sum(stock_values[-window:]) / window
        forecast = round(sma)
        sma_dates = stock_dates[-window:]
        sma_values = stock_values[-window:]
        if window >= 2:
            first_val = sma_values[0]
            last_val = sma_values[-1]
            if last_val > first_val:
                sma_trend = "up"
            elif last_val < first_val:
                sma_trend = "down"

    # ---- weekly orders activity (last 6 weeks, split by purchase vs sale) ----
    orders_start = today - datetime.timedelta(weeks=5)

    weekly_qs = (
        Order.objects
        .filter(order_date__gte=orders_start)
        .annotate(week=TruncWeek("order_date"))
        .values("week")
        .annotate(
            purchase_count=Count("id", filter=Q(order_type=Order.TYPE_PURCHASE)),
            sale_count=Count("id", filter=Q(order_type=Order.TYPE_SALE)),
        )
        .order_by("week")
    )

    weekly_data = [
        (row["week"].strftime("%d %b"), row["purchase_count"], row["sale_count"])
        for row in weekly_qs if row["week"]
    ]
    weekly_labels = [x[0] for x in weekly_data]
    weekly_purchase_counts = [x[1] for x in weekly_data]
    weekly_sale_counts = [x[2] for x in weekly_data]
    weekly_counts = [x[1] + x[2] for x in weekly_data]  # total for backwards compat

    this_week_orders = weekly_counts[-1] if weekly_counts else 0
    last_week_orders = weekly_counts[-2] if len(weekly_counts) >= 2 else None

    # ---- top items by number of orders (for chart + highlight) ----
    top_items_qs = (
        Item.objects
        .annotate(total_orders=Count("orders"))
        .filter(total_orders__gt=0)
        .order_by("-total_orders")[:5]
    )
    top_item = top_items_qs.first()
    top_items_labels = [item.name[:25] + ("…" if len(item.name) > 25 else "") for item in top_items_qs]
    top_items_counts = [item.total_orders for item in top_items_qs]

    # ---- recent activity feed ----
    from inventory.models import Activity
    recent_activity = Activity.objects.all()[:5]

    # ---- recent demand anomalies ----
    recent_anomalies = DemandAnomaly.objects.filter(dismissed=False).select_related("item")[:8]

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

    # ---- inventory-by-location (for chart next to category pie) ----
    location_qs = (
        Item.objects
        .values("location__name")
        .annotate(total_qty=Sum("quantity"))
        .order_by("-total_qty")[:8]
    )
    location_labels = [row["location__name"] or "No location" for row in location_qs]
    location_values = [int(row["total_qty"]) for row in location_qs]

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

    is_manager_or_admin = request.user.groups.filter(name__in=["Manager", "Admin"]).exists()

    context = {
        "total_items": total_items,
        "low_stock_items": low_stock_items,
        "supplier_count": supplier_count,
        "client_count": client_count,

        "trend_days": trend_days,
        "stock_dates": stock_dates,
        "stock_values": stock_values,
        "forecast": forecast,
        "sma_dates": sma_dates,
        "sma_values": sma_values,
        "sma_trend": sma_trend,

        "weekly_order_labels": weekly_labels,
        "weekly_order_counts": weekly_counts,
        "weekly_purchase_counts": weekly_purchase_counts,
        "weekly_sale_counts": weekly_sale_counts,
        "this_week_orders": this_week_orders,
        "last_week_orders": last_week_orders,

        "top_item": top_item,
        "top_items_labels": top_items_labels,
        "top_items_counts": top_items_counts,
        "recent_activity": recent_activity,
        "recent_anomalies": recent_anomalies,
        "is_manager_or_admin": is_manager_or_admin,

        "pie_labels": pie_labels,
        "pie_values": pie_values,
        "location_labels": location_labels,
        "location_values": location_values,

        "recommendations": recommendations,
    }

    response = render(request, "inventory/dashboard.html", context)
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


@login_required
@permission_required("inventory.view_item", raise_exception=True)
@never_cache
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
        "view": "items",
        "hide_stock_sidebar": True,
    })

from inventory.ml.anomaly import detect_sales_anomalies, save_anomalies
@login_required
@user_passes_test(is_manager_or_admin)
def run_anomaly_scan_view(request):
    # Use the defaults that worked for you
    results = detect_sales_anomalies(
        days_back=120,
        min_points=10,
        last_n_days_only=180,
        z_thresh_low=2.5,
        z_thresh_med=3.5,
        z_thresh_high=4.5,
    )

    created, created_objs = save_anomalies(results)

    # Notifications for new MED/HIGH
    from django.apps import apps
    from django.contrib.auth import get_user_model

    Notification = apps.get_model("inventory", "Notification")
    User = get_user_model()

    # Notify managers/admins for new MEDIUM/HIGH anomalies (one per item per scan)
    notify = [a for a in created_objs if a.severity in ("MEDIUM", "HIGH")]

    if notify:
        # keep highest severity/score anomaly per item
        sev_rank = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}
        best_by_item = {}

        for a in notify:
            cur = best_by_item.get(a.item_id)
            if (
                cur is None
                or sev_rank.get(a.severity, 0) > sev_rank.get(cur.severity, 0)
                or (a.severity == cur.severity and a.score > cur.score)
            ):
                best_by_item[a.item_id] = a

        recipients = User.objects.filter(groups__name__in=["Manager", "Admin"]).distinct()

        from django.urls import reverse
        link = reverse("item_forecast", args=[a.item_id])

        for a in list(best_by_item.values())[:25]:
            msg = (
                f"Demand anomaly ({a.severity}): {a.item.name} on {a.date:%d/%m/%Y} "
                f"(Qty {a.quantity}, Score {a.score:.2f})"
            )
            for u in recipients:
                pref, _ = UserPreference.objects.get_or_create(user=u)
                if not pref.notify_anomalies:
                    continue

                Notification.objects.create(
                    user=u,
                    message=msg,
                    url=link,   # keep only if your Notification model actually has url
                )

    messages.success(request, f"Anomaly scan complete. Detected {len(results)} anomalies ({created} new).")
    return redirect("dashboard")



from inventory.models import DemandAnomaly
@login_required
@user_passes_test(is_manager_or_admin)
def anomaly_list(request):
    qs = DemandAnomaly.objects.select_related("item")

    # filters
    item_id = request.GET.get("item")
    if item_id:
        qs = qs.filter(item_id=item_id)
    severity = request.GET.get("severity", "")
    show = request.GET.get("show", "active")  # active | dismissed | all

    if severity:
        qs = qs.filter(severity=severity)

    if show == "active":
        qs = qs.filter(dismissed=False)
    elif show == "dismissed":
        qs = qs.filter(dismissed=True)
    # all -> no filter

    anomalies = qs[:200]  # cap for UI safety

    return render(request, "inventory/anomaly_list.html", {
        "anomalies": anomalies,
        "severity": severity,
        "show": show,
    })

@require_POST
@login_required
@user_passes_test(is_manager_or_admin)
def anomaly_review(request, pk):
    a = get_object_or_404(DemandAnomaly, pk=pk)
    a.is_reviewed = True
    a.save(update_fields=["is_reviewed"])
    messages.success(request, "Marked anomaly as reviewed.")
    return redirect("anomaly_list")

from django.apps import apps
@require_POST
@login_required
@user_passes_test(is_manager_or_admin)
def anomaly_dismiss(request, pk):
    a = get_object_or_404(DemandAnomaly, pk=pk)
    a.dismissed = True
    a.dismissed_at = timezone.now()
    a.save(update_fields=["dismissed", "dismissed_at"])

    # Also dismiss matching notifications for this anomaly (clean up bell)
    Notification = apps.get_model("inventory", "Notification")

    needle = f": {a.item.name} on {a.date:%d/%m/%Y} "
    Notification.objects.filter(
        user=request.user,
        dismissed=False,
        message__startswith="Demand anomaly (",
        message__contains=needle,
    ).update(dismissed=True, dismissed_at=timezone.now())

    messages.success(request, "Dismissed anomaly.")
    return redirect("anomaly_list")

@require_POST
@login_required
@user_passes_test(is_manager_or_admin)
def anomaly_undismiss(request, pk):
    a = get_object_or_404(DemandAnomaly, pk=pk)
    a.dismissed = False
    a.dismissed_at = None
    a.save(update_fields=["dismissed", "dismissed_at"])
    messages.success(request, "Restored anomaly.")
    return redirect("anomaly_list")


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
        order_count=Count("orders"),
        history_count=Count("history", distinct=True),
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
    # STOCK LEVEL / EXPIRY FILTER (merged)
    # -------------------------
    filter_option = request.GET.get("filter", "")
    today = timezone.now().date()

    if filter_option == "in_stock":
        items = items.filter(quantity__gt=F("reorder_level"))
    elif filter_option == "low_stock":
        items = items.filter(quantity__gt=0, quantity__lte=F("reorder_level"))
    elif filter_option == "out_of_stock":
        items = items.filter(quantity__lte=0)
    elif filter_option == "expired":
        items = items.filter(expiry_date__lt=today)
    elif filter_option == "expiring_soon":
        from datetime import timedelta
        soon = today + timedelta(days=30)
        items = items.filter(expiry_date__isnull=False, expiry_date__lte=soon, expiry_date__gte=today)

    # -------------------------
    # CATEGORY FILTER
    # -------------------------
    category_id = request.GET.get("category")
    if category_id:
        items = items.filter(category_id=category_id)

    # -------------------------
    # LOCATION FILTER
    # -------------------------
    location_id = request.GET.get("location")
    if location_id:
        items = items.filter(location_id=location_id)

    categories = Category.objects.order_by("name")
    locations = Location.objects.order_by("name")

    # -------------------------
    # CONDITION (stock status) FILTER
    # -------------------------
    stock_status_filter = request.GET.get("stock_status", "")
    if stock_status_filter:
        items = items.filter(stock_status=stock_status_filter)

    # Legacy: expiry_filter removed (merged into filter_option); keep for URL compatibility
    expiry_filter = ""

    # -------------------------
    # SORTING
    # -------------------------
    sort = request.GET.get("sort", "name")

    valid_sorts = [
        "name", "-name",
        "sku", "-sku",
        "quantity", "-quantity",
        "reorder_level", "-reorder_level",
        "unit_cost", "-unit_cost",
        "expiry_date", "-expiry_date",
        "stock_status",
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
    per_page = get_per_page(request)
    paginator = Paginator(items, per_page)
    page = request.GET.get("page")
    items = paginator.get_page(page)

    return render(request, "inventory/item_list.html", {
        "items": items,
        "per_page": per_page,
        "per_page_choices": PER_PAGE_CHOICES,
        "query": q,
        "filter_option": filter_option,
        "sort": sort,
        "categories": categories,
        "locations": locations,
        "today": today,
        "stock_status_filter": stock_status_filter,
        "expiry_filter": expiry_filter,
        "view": "items",
    })


@login_required
@permission_required("inventory.view_item", raise_exception=True)
@never_cache
def item_detail(request, pk):
    """Stock item profile page with full details and related data (always fresh)."""
    item = get_object_or_404(
        Item.objects.select_related("supplier", "location", "category"),
        pk=pk,
    )
    orders = item.orders.select_related("supplier", "client", "shipping_location", "receiving_location").order_by("-order_date")[:20]
    recent_history = item.history.order_by("-date")[:14]
    anomalies = item.demand_anomalies.filter(dismissed=False).order_by("-date")[:5]

    # Clients who have purchased this item (from sale orders)
    client_ids = (
        item.orders.filter(order_type=Order.TYPE_SALE, client__isnull=False)
        .values_list("client", flat=True)
        .distinct()
    )
    clients = Client.objects.filter(id__in=client_ids)[:10]

    # Order stats
    order_stats = item.orders.aggregate(
        total_purchased=Count("id", filter=Q(order_type=Order.TYPE_PURCHASE)),
        total_sold=Count("id", filter=Q(order_type=Order.TYPE_SALE)),
    )

    # Related items (same category)
    related_items = []
    if item.category_id:
        related_items = (
            Item.objects.filter(category_id=item.category_id, is_active=True)
            .exclude(pk=item.pk)
            .order_by("name")[:5]
        )

    try:
        from inventory.ml.forecasting import prophet_forecast_item
        result = prophet_forecast_item(item, horizon_days=30)
        rec = result.recommendation
        has_forecast = bool(result.forecast)
    except Exception:
        rec = None
        has_forecast = False

    return render(request, "inventory/item_detail.html", {
        "item": item,
        "orders": orders,
        "recent_history": recent_history,
        "anomalies": anomalies,
        "clients": clients,
        "order_stats": order_stats,
        "related_items": related_items,
        "rec": rec,
        "has_forecast": has_forecast,
        "today": timezone.now().date(),
        "view": "items",
        "hide_stock_sidebar": True,
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
        item.maybe_archive_on_deplete()

        messages.success(request, f"Adjusted {item.name}: quantity updated by {adjustment:+d}")

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
        form = ItemForm(request.POST, request.FILES)
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
        "view": "items",
        "auto_scan": request.GET.get("scan") == "1",
    })


@login_required
@permission_required("inventory.change_item", raise_exception=True)
def item_edit(request, pk):
    item = get_object_or_404(Item, pk=pk)

    if request.method == "POST":
        form = ItemForm(request.POST, request.FILES, instance=item)
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
        "view": "items",
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
@user_passes_test(is_manager_or_admin)
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
        "view": "items",
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

    add_form = CategoryForm()
    all_categories = Category.objects.order_by("name")
    return render(request, "inventory/category_list.html", {
        "categories": roots,
        "show_categories": True,
        "view": "categories",
        "add_form": add_form,
        "all_categories": all_categories,
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
@never_cache
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
        stock=Sum("inventory_items__quantity"),
        item_count=Count("inventory_items", distinct=True),
    )

    # -------------------------
    # SEARCH
    # -------------------------
    q = request.GET.get("q", "")
    if q:
        locations = locations.filter(Q(name__icontains=q) | Q(code__icontains=q))

    # -------------------------
    # FILTERS
    # -------------------------
    type_filter = request.GET.get("type")
    structural_filter = request.GET.get("structural")
    external_filter = request.GET.get("external")
    status_filter = request.GET.get("status", "active")

    if status_filter == "active":
        locations = locations.filter(is_active=True)
    elif status_filter == "inactive":
        locations = locations.filter(is_active=False)

    if type_filter:
        locations = locations.filter(location_type=type_filter)

    if structural_filter in ["yes", "no"]:
        locations = locations.filter(structural=(structural_filter == "yes"))

    if external_filter in ["yes", "no"]:
        locations = locations.filter(external=(external_filter == "yes"))

    # Quick-filter from summary cards
    quick_filter = request.GET.get("filter")
    if quick_filter == "with_stock":
        locations = locations.filter(item_count__gt=0)
    elif quick_filter == "empty":
        locations = locations.filter(item_count=0)
    elif quick_filter == "low_stock":
        locations = locations.filter(
            inventory_items__quantity__lte=F("inventory_items__reorder_level"),
            inventory_items__quantity__gt=0,
        ).distinct()
    elif quick_filter == "warehouses":
        locations = locations.filter(location_type="warehouse")

    # -------------------------
    # SORTING
    # -------------------------
    sort = request.GET.get("sort", "name")
    valid_sorts = ["name", "-name", "code", "-code", "parent__name", "-parent__name", "location_type",
                   "structural", "external", "stock", "-stock", "item_count", "-item_count"]
    if sort not in valid_sorts:
        sort = "name"
    locations = locations.order_by(sort)

    # -------------------------
    # PAGINATION
    # -------------------------
    per_page = get_per_page(request)
    paginator = Paginator(locations, per_page)
    page = request.GET.get("page")
    locations = paginator.get_page(page)

    # -------------------------
    # SUMMARY STATS (global, unfiltered)
    # -------------------------
    base_locations = Location.objects.filter(is_active=True)
    total_locations = base_locations.count()
    warehouse_count = base_locations.filter(location_type="warehouse").count()
    total_stock_qty = Item.objects.aggregate(total=Sum("quantity"))["total"] or 0
    locations_with_stock = (
        base_locations.annotate(c=Count("inventory_items")).filter(c__gt=0).count()
    )
    empty_locations_count = (
        base_locations.annotate(c=Count("inventory_items")).filter(c=0).count()
    )
    low_stock_locations_count = (
        base_locations.filter(
            inventory_items__quantity__lte=F("inventory_items__reorder_level"),
            inventory_items__quantity__gt=0,
        )
        .distinct()
        .count()
    )

    # Stock distribution chart (top 10 locations by stock)
    stock_chart_qs = (
        Location.objects.filter(is_active=True)
        .annotate(loc_stock=Sum("inventory_items__quantity"))
        .filter(loc_stock__gt=0)
        .order_by("-loc_stock")[:10]
    )
    stock_chart_labels = [loc.name for loc in stock_chart_qs]
    stock_chart_values = [int(loc.loc_stock) for loc in stock_chart_qs]

    # Top location by stock (busiest)
    top_location = (
        Location.objects.filter(is_active=True)
        .annotate(
            loc_stock=Sum("inventory_items__quantity"),
            loc_item_count=Count("inventory_items", distinct=True),
        )
        .filter(loc_item_count__gt=0)
        .order_by("-loc_stock")
        .first()
    )

    # Top shipping location (most sales shipped from)
    top_shipping_loc = (
        Location.objects.filter(is_active=True)
        .annotate(
            sales_count=Count(
                "orders_shipped_from",
                filter=Q(orders_shipped_from__order_type=Order.TYPE_SALE),
                distinct=True,
            )
        )
        .filter(sales_count__gt=0)
        .order_by("-sales_count")
        .first()
    )

    # Top receiving location (most purchases received at)
    top_receiving_loc = (
        Location.objects.filter(is_active=True)
        .annotate(
            purchases_count=Count(
                "orders_received_at",
                filter=Q(orders_received_at__order_type=Order.TYPE_PURCHASE),
                distinct=True,
            )
        )
        .filter(purchases_count__gt=0)
        .order_by("-purchases_count")
        .first()
    )

    view_mode = request.GET.get("view", "list")
    roots = Location.objects.filter(parent__isnull=True) if view_mode == "tree" else None

    # Map data: locations with coordinates (for popup map)
    locations_with_coords = list(
        Location.objects.filter(
            is_active=True,
            latitude__isnull=False,
            longitude__isnull=False,
        ).values("id", "name", "address", "latitude", "longitude", "location_type")
    )
    for loc in locations_with_coords:
        loc["latitude"] = float(loc["latitude"])
        loc["longitude"] = float(loc["longitude"])
        loc["map_url"] = (
            f"https://www.google.com/maps?q={loc['latitude']},{loc['longitude']}&z=17"
        )
        loc["detail_url"] = reverse("location_view", args=[loc["id"]])

    return render(request, "inventory/location_list.html", {
        "locations": locations,
        "per_page": per_page,
        "per_page_choices": PER_PAGE_CHOICES,
        "location_types": Location.LOCATION_TYPES,
        "query": q,
        "sort": sort,
        "status_filter": status_filter,
        "view": "locations",
        "view_mode": view_mode,
        "roots": roots,
        "total_locations": total_locations,
        "warehouse_count": warehouse_count,
        "total_stock_qty": total_stock_qty,
        "locations_with_stock": locations_with_stock,
        "empty_locations_count": empty_locations_count,
        "low_stock_locations_count": low_stock_locations_count,
        "stock_chart_labels": stock_chart_labels,
        "stock_chart_values": stock_chart_values,
        "top_location": top_location,
        "top_shipping_loc": top_shipping_loc,
        "top_receiving_loc": top_receiving_loc,
        "active_filter": quick_filter,
        "locations_with_coords": locations_with_coords,
    })


@login_required
@permission_required("inventory.add_location", raise_exception=True)
def location_create(request):
    form = LocationForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("location_list")
    return render(request, "inventory/location_form.html", {
        "form": form,
        "location": None,
        "view": "locations",
    })


@login_required
@permission_required("inventory.change_location", raise_exception=True)
def location_edit(request, pk):
    location = get_object_or_404(Location, pk=pk)
    form = LocationForm(request.POST or None, request.FILES or None, instance=location)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("location_list")
    return render(request, "inventory/location_form.html", {
        "form": form,
        "location": location,
        "view": "locations",
    })


@login_required
@permission_required("inventory.delete_location", raise_exception=True)
def location_delete(request, pk):
    location = get_object_or_404(Location, pk=pk)

    if request.method == "POST":
        location.delete()
        return redirect("location_list")

    return render(request, "inventory/location_confirm_delete.html", {
        "location": location,
        "view": "locations",
    })


@login_required
@permission_required("inventory.view_location", raise_exception=True)
def location_export_csv(request):
    """Export locations to CSV, respecting current filters."""
    locations = Location.objects.annotate(
        stock=Sum("inventory_items__quantity"),
        item_count=Count("inventory_items", distinct=True),
    )
    q = request.GET.get("q", "")
    if q:
        locations = locations.filter(Q(name__icontains=q) | Q(code__icontains=q))
    status_filter = request.GET.get("status", "active")
    if status_filter == "active":
        locations = locations.filter(is_active=True)
    elif status_filter == "inactive":
        locations = locations.filter(is_active=False)
    type_filter = request.GET.get("type")
    if type_filter:
        locations = locations.filter(location_type=type_filter)
    structural_filter = request.GET.get("structural")
    if structural_filter in ["yes", "no"]:
        locations = locations.filter(structural=(structural_filter == "yes"))
    external_filter = request.GET.get("external")
    if external_filter in ["yes", "no"]:
        locations = locations.filter(external=(external_filter == "yes"))
    sort = request.GET.get("sort", "name")
    valid_sorts = ["name", "-name", "code", "-code", "parent__name", "-parent__name", "location_type",
                   "structural", "external", "stock", "-stock", "item_count", "-item_count"]
    if sort in valid_sorts:
        locations = locations.order_by(sort)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="locations.csv"'
    writer = csv.writer(response)
    writer.writerow(["Name", "Code", "Breadcrumb", "Parent", "Type", "Structural", "External", "Active", "Address", "Barcode", "Notes", "Item Count"])
    for loc in locations:
        writer.writerow([
            loc.name,
            loc.code or "",
            loc.get_breadcrumb(),
            loc.parent.name if loc.parent else "",
            loc.get_location_type_display(),
            "Yes" if loc.structural else "No",
            "Yes" if loc.external else "No",
            "Yes" if loc.is_active else "No",
            loc.address or "",
            loc.barcode or "",
            (loc.notes or "").replace("\n", " "),
            loc.item_count,
        ])
    return response


# -------------------------------
# LOCATION TREE (Hierarchy View)
# -------------------------------
@login_required
@permission_required("inventory.view_location", raise_exception=True)
def location_tree(request):
    roots = Location.objects.filter(parent__isnull=True)
    return render(request, "inventory/location_tree.html", {
        "roots": roots,
        "view": "locations",
    })


# -------------------------------
# LOCATION DETAIL VIEW
# -------------------------------
@login_required
@permission_required("inventory.view_location", raise_exception=True)
@never_cache
def location_view(request, pk):
    """Location profile page (always fresh - orders, items, stats)."""
    location = get_object_or_404(Location, pk=pk)
    items = location.inventory_items.select_related("category", "supplier").order_by("name")
    children = location.children.all()
    total_qty = items.aggregate(total=Sum("quantity"))["total"] or 0

    # Orders connected to this location
    sales_shipped = Order.objects.filter(
        order_type=Order.TYPE_SALE,
        shipping_location=location,
    ).select_related("item", "client").order_by("-order_date")[:15]
    purchases_received = Order.objects.filter(
        order_type=Order.TYPE_PURCHASE,
        receiving_location=location,
    ).select_related("item", "supplier").order_by("-order_date")[:15]
    sales_shipped_count = Order.objects.filter(
        order_type=Order.TYPE_SALE,
        shipping_location=location,
    ).count()
    purchases_received_count = Order.objects.filter(
        order_type=Order.TYPE_PURCHASE,
        receiving_location=location,
    ).count()

    utilisation_pct = None
    if location.capacity and location.capacity > 0:
        utilisation_pct = min(100, round(100 * int(total_qty) / location.capacity, 1))

    return render(request, "inventory/location_view.html", {
        "location": location,
        "items": items,
        "children": children,
        "total_qty": total_qty,
        "item_count": items.count(),
        "sales_shipped": sales_shipped,
        "purchases_received": purchases_received,
        "sales_shipped_count": sales_shipped_count,
        "purchases_received_count": purchases_received_count,
        "utilisation_pct": utilisation_pct,
    })

# -------------------------------
# ORDER CRUD
# -------------------------------
@login_required
@permission_required("inventory.view_order", raise_exception=True)
def order_list(request):
    orders = Order.objects.select_related("item", "supplier", "client", "shipping_location", "receiving_location")

    # --- filter by item ---
    item_id = request.GET.get("item")
    if item_id:
        orders = orders.filter(item_id=item_id)

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

    # --- filter by location ---
    shipping_location_id = request.GET.get("shipping_location")
    if shipping_location_id:
        orders = orders.filter(shipping_location_id=shipping_location_id)
    receiving_location_id = request.GET.get("receiving_location")
    if receiving_location_id:
        orders = orders.filter(receiving_location_id=receiving_location_id)

    # --- sorting ---
    sort = request.GET.get("sort", "-order_date")
    valid_sorts = ["order_date", "-order_date", "id", "-id", "quantity", "-quantity", "status", "-status",
                   "item__name", "-item__name", "order_type", "-order_type"]
    if sort not in valid_sorts:
        sort = "-order_date"
    orders = orders.order_by(sort)

    # Pagination
    per_page = get_per_page(request)
    paginator = Paginator(orders, per_page)
    page = request.GET.get("page")
    orders = paginator.get_page(page)

    # Summary cards
    purchase_count = Order.objects.filter(order_type=Order.TYPE_PURCHASE).count()
    sale_count = Order.objects.filter(order_type=Order.TYPE_SALE).count()
    pending_count = Order.objects.filter(status=Order.STATUS_PENDING).count()
    delivered_count = Order.objects.filter(status=Order.STATUS_DELIVERED).count()

    return render(request, "inventory/order_list.html", {
        "orders": orders,
        "per_page": per_page,
        "per_page_choices": PER_PAGE_CHOICES,
        "search_query": q,
        "type_filter": type_filter,
        "context_type": type_filter,
        "status_filter": status_filter,
        "status_choices": Order.STATUS_CHOICES,
        "sort": sort,
        "purchase_count": purchase_count,
        "sale_count": sale_count,
        "pending_count": pending_count,
        "delivered_count": delivered_count,
    })


@login_required
@permission_required("inventory.view_order", raise_exception=True)
def order_export_csv(request):
    """Export orders to CSV, respecting current filters."""
    orders = Order.objects.select_related("item", "supplier", "client")
    item_id = request.GET.get("item")
    if item_id:
        orders = orders.filter(item_id=item_id)
    q = request.GET.get("q", "").strip()
    if q:
        orders = orders.filter(
            Q(item__name__icontains=q)
            | Q(supplier__name__icontains=q)
            | Q(client__name__icontains=q)
        )
    type_filter = request.GET.get("type", "all")
    if type_filter == "purchase":
        orders = orders.filter(order_type=Order.TYPE_PURCHASE)
    elif type_filter == "sale":
        orders = orders.filter(order_type=Order.TYPE_SALE)
    status_filter = request.GET.get("status", "all")
    valid_statuses = dict(Order.STATUS_CHOICES).keys()
    if status_filter in valid_statuses:
        orders = orders.filter(status=status_filter)
    shipping_location_id = request.GET.get("shipping_location")
    if shipping_location_id:
        orders = orders.filter(shipping_location_id=shipping_location_id)
    receiving_location_id = request.GET.get("receiving_location")
    if receiving_location_id:
        orders = orders.filter(receiving_location_id=receiving_location_id)
    sort = request.GET.get("sort", "-order_date")
    valid_sorts = ["order_date", "-order_date", "id", "-id", "quantity", "-quantity", "status", "-status",
                   "item__name", "-item__name", "order_type", "-order_type"]
    if sort in valid_sorts:
        orders = orders.order_by(sort)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="orders.csv"'
    writer = csv.writer(response)
    writer.writerow(["Order #", "Type", "Item", "Party", "Date", "Qty", "Total", "Status", "Shipping location", "Receiving location"])
    for o in orders:
        writer.writerow([
            f"ORD-{o.id}",
            o.get_order_type_display(),
            o.item.name if o.item else "",
            o.party_name,
            o.order_date,
            o.quantity,
            o.total,
            o.get_status_display(),
            o.shipping_location.name if o.shipping_location else "",
            o.receiving_location.name if o.receiving_location else "",
        ])
    return response


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
    # 4b. Sorting
    # ----------------------------
    sort = request.GET.get("sort", "name")
    if sort == "name":
        contacts = sorted(contacts, key=lambda c: (c["name"] or "").lower())
    elif sort == "-name":
        contacts = sorted(contacts, key=lambda c: (c["name"] or "").lower(), reverse=True)
    elif sort == "type":
        contacts = sorted(contacts, key=lambda c: c["type"])
    elif sort == "-type":
        contacts = sorted(contacts, key=lambda c: c["type"], reverse=True)
    elif sort == "orders":
        contacts = sorted(contacts, key=lambda c: c["orders"])
    elif sort == "-orders":
        contacts = sorted(contacts, key=lambda c: c["orders"], reverse=True)
    elif sort == "total_value":
        contacts = sorted(contacts, key=lambda c: float(c["total_value"] or 0))
    elif sort == "-total_value":
        contacts = sorted(contacts, key=lambda c: float(c["total_value"] or 0), reverse=True)
    else:
        contacts = sorted(contacts, key=lambda c: (c["name"] or "").lower())

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
    per_page = get_per_page(request)
    paginator = Paginator(contacts, per_page)
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
        "per_page": per_page,
        "per_page_choices": PER_PAGE_CHOICES,
        "type_filter": type_filter,
        "total_suppliers": total_suppliers,
        "total_customers": total_customers,
        "active_relationships": active_relationships,

        # analytics
        "top_supplier": top_supplier,
        "top_customer": top_customer,

        # keep search value in form
        "search_query": q,
        "sort": sort,
    })


@login_required
@permission_required("inventory.view_supplier", raise_exception=True)
@permission_required("inventory.view_client", raise_exception=True)
def contact_export_csv(request):
    """Export contacts to CSV, respecting current filters."""
    type_filter = request.GET.get("type", "all")
    q = request.GET.get("q", "").strip()
    suppliers = Supplier.objects.all()
    clients = Client.objects.all()
    contacts = []
    for s in suppliers:
        supplier_orders = Order.objects.filter(supplier=s)
        contacts.append({
            "id": s.id, "name": s.name, "type": "supplier", "email": s.email, "phone": s.phone,
            "address": s.address or "",
            "orders": supplier_orders.count(),
            "total_value": supplier_orders.aggregate(total=Sum("unit_price"))["total"] or 0,
        })
    for c in clients:
        client_orders = Order.objects.filter(client=c)
        contacts.append({
            "id": c.id, "name": c.name, "type": "customer", "email": c.email, "phone": c.phone,
            "address": c.address or "",
            "orders": client_orders.count(),
            "total_value": client_orders.aggregate(total=Sum("unit_price"))["total"] or 0,
        })
    if q:
        contacts = [c for c in contacts if q.lower() in (c["name"] or "").lower()
                   or q.lower() in (c["email"] or "").lower() or q.lower() in (c["phone"] or "").lower()]
    if type_filter == "suppliers":
        contacts = [c for c in contacts if c["type"] == "supplier"]
    elif type_filter == "customers":
        contacts = [c for c in contacts if c["type"] == "customer"]
    sort = request.GET.get("sort", "name")
    if sort == "name":
        contacts = sorted(contacts, key=lambda c: (c["name"] or "").lower())
    elif sort == "-name":
        contacts = sorted(contacts, key=lambda c: (c["name"] or "").lower(), reverse=True)
    elif sort == "type":
        contacts = sorted(contacts, key=lambda c: c["type"])
    elif sort == "-type":
        contacts = sorted(contacts, key=lambda c: c["type"], reverse=True)
    elif sort == "orders":
        contacts = sorted(contacts, key=lambda c: c["orders"])
    elif sort == "-orders":
        contacts = sorted(contacts, key=lambda c: c["orders"], reverse=True)
    elif sort == "total_value":
        contacts = sorted(contacts, key=lambda c: float(c["total_value"] or 0))
    elif sort == "-total_value":
        contacts = sorted(contacts, key=lambda c: float(c["total_value"] or 0), reverse=True)
    else:
        contacts = sorted(contacts, key=lambda c: (c["name"] or "").lower())
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="contacts.csv"'
    writer = csv.writer(response)
    writer.writerow(["Name", "Type", "Email", "Phone", "Orders", "Total Value"])
    for c in contacts:
        writer.writerow([
            c["name"], c["type"].title(), c["email"] or "", c["phone"] or "",
            c["orders"], c["total_value"],
        ])
    return response


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



from .forms import (
    ProfileForm,
    UserProfileDetailsForm,
    GeneralPreferenceForm,
    NotificationPreferenceForm,
    AppearancePreferenceForm,
)
from .models import UserPreference, UserProfile

@login_required
@never_cache
def profile_view(request):
    """User profile page (always fresh - activity, etc.)."""
    user = request.user
    groups = list(user.groups.values_list("name", flat=True))
    valid_tabs = {"profile", "security", "activity", "permissions", "info"}
    tab = request.GET.get("tab", "profile")
    if tab not in valid_tabs:
        tab = "profile"
    if tab == "info":
        tab = "profile"

    details, _ = UserProfile.objects.get_or_create(user=user)

    if request.method == "POST" and tab == "profile":
        form = ProfileForm(request.POST, instance=user)
        details_form = UserProfileDetailsForm(request.POST, instance=details)
        if form.is_valid() and details_form.is_valid():
            form.save()
            details_form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect(f"{reverse('profile')}?tab=profile")
    else:
        form = ProfileForm(instance=user)
        details_form = UserProfileDetailsForm(instance=details)

    activities = []
    if tab == "activity":
        activities = (
            Activity.objects
            .filter(user=user)
            .order_by("-timestamp")[:50]
        )

    all_perms = sorted(user.get_all_permissions())

    return render(request, "inventory/profile.html", {
        "form": form,
        "details_form": details_form,
        "groups": groups,
        "active_tab": tab,
        "recent_activity": activities,
        "all_perms": all_perms,
    })


@login_required
def export_activity_log(request):
    qs = Activity.objects.filter(user=request.user).order_by("-timestamp")[:500]

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="activity_log.csv"'

    writer = csv.writer(response)
    writer.writerow(["timestamp", "message"])
    for a in qs:
        writer.writerow([a.timestamp.strftime("%Y-%m-%d %H:%M:%S"), a.message])

    return response


@login_required
def settings_view(request):
    pref, _ = UserPreference.objects.get_or_create(user=request.user)
    valid_tabs = {"general", "notifications", "appearance", "privacy"}
    tab_form_map = {
        "general": GeneralPreferenceForm,
        "notifications": NotificationPreferenceForm,
        "appearance": AppearancePreferenceForm,
    }
    active_tab = request.GET.get("tab", "notifications")
    if active_tab not in valid_tabs:
        active_tab = "notifications"

    if request.method == "POST":
        active_tab = request.POST.get("tab", active_tab)
        if active_tab not in valid_tabs:
            active_tab = "notifications"

        action = request.POST.get("action", "save")
        if action == "reset_defaults":
            pref.delete()
            UserPreference.objects.create(user=request.user)
            messages.success(request, "Settings reset to defaults.")
            return redirect(f"{reverse('settings')}?tab={active_tab}")
        if action == "clear_dismissed_alerts":
            request.session["dismissed_alerts"] = []
            messages.success(request, "Dismissed alerts have been restored.")
            return redirect(f"{reverse('settings')}?tab={active_tab}")

        form_class = tab_form_map.get(active_tab)
        if form_class is None:
            messages.error(request, "This settings section is not editable.")
            return redirect(f"{reverse('settings')}?tab={active_tab}")

        form = form_class(request.POST, instance=pref)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings saved.")
            return redirect(f"{reverse('settings')}?tab={active_tab}")
    else:
        form_class = tab_form_map.get(active_tab)
        form = form_class(instance=pref) if form_class else None

    return render(request, "inventory/settings.html", {
        "form": form,
        "active_tab": active_tab,
    })