from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Count, Sum
from .models import Item, Supplier, Client, Location, Order, OrderLine, StockHistory, Category
from .forms import ItemForm, OrderForm, OrderLineFormSet, SupplierForm, ClientForm, CategoryForm, LocationForm
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
from django.db.models.functions import TruncWeek, Coalesce
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
from django.utils.dateparse import parse_date
from django.core.cache import cache
from collections import Counter
import logging
from .recommendation_engine import (
    ensure_recommendations_fresh,
    get_recommendations_for_context,
)
from .context_processors import get_alerts_for_user

logger = logging.getLogger(__name__)

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

                # Groups are created by `manage.py setup_roles`; on a fresh DB use get_or_create
                # so signup does not 500 before that command has been run (e.g. first Render deploy).
                staff_group, _ = Group.objects.get_or_create(name="Staff")
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

    return redirect("dashboard")


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
            "url": reverse("supplier_view", args=[s.id]),
        })

    # Customers -> edit page (no separate profile view; edit shows details)
    for c in Client.objects.filter(
        Q(name__icontains=q) | Q(email__icontains=q)
    )[:5]:
        results.append({
            "type": "Customer",
            "name": c.name,
            "sub": c.email,
            "url": reverse("client_view", args=[c.id]),
        })

    # Locations -> profile/view page (already correct)
    for l in Location.objects.filter(Q(name__icontains=q))[:5]:
        results.append({
            "type": "Location",
            "name": l.name,
            "sub": l.get_breadcrumb(),
            "url": reverse("location_view", args=[l.id]),
        })

    # Orders -> order detail
    for o in Order.objects.prefetch_related("lines__item").filter(
        Q(notes__icontains=q) |
        Q(reference__icontains=q) |
        Q(lines__item__name__icontains=q)
    ).distinct()[:5]:
        lines = list(o.lines.select_related("item").all()[:2])
        sub = ", ".join(ln.item.name for ln in lines) if lines else "—"
        if o.lines.count() > 2:
            sub += f" (+{o.lines.count() - 2} more)"
        results.append({
            "type": "Order",
            "name": f"Order #{o.id}",
            "sub": f"{o.order_type.title()} – {sub}",
            "url": reverse("order_detail", args=[o.id]),
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
    cache.delete(f"ctx_notifications:{request.user.pk}")
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
    cache.delete(f"ctx_notifications:{request.user.pk}")
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
    total_items = Item.objects.filter(is_active=True).count()
    low_stock_items = Item.objects.filter(is_active=True, quantity__lte=F("reorder_level")).count()
    active_supplier_count = Supplier.objects.filter(is_active=True).count()
    active_customer_count = Client.objects.filter(is_active=True).count()
    pending_purchase_orders_count = Order.objects.filter(
        status=Order.STATUS_PENDING,
        order_type=Order.TYPE_PURCHASE,
    ).count()
    pending_sales_orders_count = Order.objects.filter(
        status=Order.STATUS_PENDING,
        order_type=Order.TYPE_SALE,
    ).count()
    low_stock_percent = round((low_stock_items / total_items) * 100, 1) if total_items else 0

    # ---- inventory trend + forecasting ----
    today = timezone.localdate()
    trend_days = int(request.GET.get("trend_days", 30))
    trend_days = max(7, min(30, trend_days))
    debug_trend = request.GET.get("debug_trend") == "1"

    from .inventory_forecasting import (
        evaluate_model,
        generate_forecast,
        get_daily_inventory_series,
    )

    full_series_df = get_daily_inventory_series(days_back=180)
    trend_df = full_series_df.tail(trend_days).copy()

    stock_dates = [d.strftime("%d %b") for d in trend_df["date"]]
    stock_values = [int(v) for v in trend_df["total_units"]]
    current_stock_value = int(stock_values[-1]) if stock_values else 0

    inventory_change_pct = None
    if len(stock_values) >= 2 and stock_values[0] > 0:
        inventory_change_pct = round(((stock_values[-1] - stock_values[0]) / stock_values[0]) * 100, 1)

    forecast_days = int(request.GET.get("forecast_days", 7))
    if forecast_days not in (7, 14, 30):
        forecast_days = 7
    chart_history_days = 60 if forecast_days == 30 else 45

    forecast_result = generate_forecast(
        series_df=full_series_df,
        horizon_days=forecast_days,
        chart_history_days=chart_history_days,
    )
    model_eval = evaluate_model(series_df=full_series_df, horizon_days=forecast_days)

    forecast_metric_value = (
        forecast_result["next_day_forecast"] if forecast_result["next_day_forecast"] else forecast_result["latest_forecast"]
    )
    forecast_badge = forecast_result["trend_badge"]
    forecast_change_pct = float(forecast_result.get("forecast_change_pct", 0.0))
    forecast_has_significant_change = bool(forecast_result.get("has_significant_change", False))

    if forecast_badge == "rising":
        forecast_insight = (
            f"Projected inventory increases by {abs(forecast_change_pct):.1f}% over the next {forecast_days} days, "
            "indicating a net stock build-up."
        )
    elif forecast_badge == "falling":
        forecast_insight = (
            f"Projected inventory decreases by {abs(forecast_change_pct):.1f}% over the next {forecast_days} days, "
            "indicating a net stock drawdown."
        )
    else:
        forecast_insight = f"No significant change in stock levels expected over the next {forecast_days} days."

    if debug_trend:
        live_total = int(Item.objects.filter(is_active=True).aggregate(total=Sum("quantity"))["total"] or 0)
        logger.info(
            "Forecast debug | points=%s trend_points=%s live_total=%s series_last=%s model=%s fallback=%s",
            len(full_series_df),
            len(stock_values),
            live_total,
            current_stock_value,
            forecast_result.get("model_used"),
            forecast_result.get("used_fallback"),
        )
        if model_eval.get("can_evaluate"):
            logger.info(
                "Forecast backtest | baseline=%s advanced=%s train=%s valid=%s",
                model_eval.get("baseline"),
                model_eval.get("advanced"),
                model_eval.get("train_points"),
                model_eval.get("validation_points"),
            )

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
        .annotate(total_orders=Count("order_lines"))
        .filter(total_orders__gt=0)
        .order_by("-total_orders")[:5]
    )
    top_item = top_items_qs.first()
    top_items_labels = [item.name[:25] + ("…" if len(item.name) > 25 else "") for item in top_items_qs]
    top_items_counts = [item.total_orders for item in top_items_qs]

    # ---- recent activity feed ----
    from inventory.models import Activity
    # Compact card shows a short list (newest -> oldest). Expanded modal shows more history.
    recent_activity = Activity.objects.all().order_by("-timestamp")[:5]
    recent_activity_detail_list = Activity.objects.all().order_by("-timestamp")[:50]
    recent_activity_export_list = [
        {
            "message": a.message,
            "user": (a.user.username if a.user else "System"),
            "timestamp": a.timestamp.isoformat(),
        }
        for a in recent_activity_detail_list
    ]

    # ---- recent demand anomalies ----
    recent_anomalies = (
        DemandAnomaly.objects
        .filter(dismissed=False)
        .select_related("item")
        .order_by("-date", "-score")[:8]
    )

    # Demand anomalies expanded (modal) filters mimic the anomaly_list page,
    # but render inside the dashboard instead of a separate page.
    anom_severity = request.GET.get("anom_severity", "")
    anom_show = request.GET.get("anom_show", "active")  # active | dismissed | all
    anom_q = request.GET.get("q", "").strip()

    anomalies_qs = DemandAnomaly.objects.select_related("item").order_by("-date", "-score")
    if anom_severity:
        anomalies_qs = anomalies_qs.filter(severity=anom_severity)
    if anom_show == "active":
        anomalies_qs = anomalies_qs.filter(dismissed=False)
    elif anom_show == "dismissed":
        anomalies_qs = anomalies_qs.filter(dismissed=True)
    # "all" -> no filter
    if anom_q:
        anomalies_qs = anomalies_qs.filter(item__name__icontains=anom_q)

    anomalies_heading_label = (
        "Active anomalies" if anom_show == "active" else
        "Dismissed anomalies" if anom_show == "dismissed" else
        "All anomalies"
    )

    # Paginator for the detailed modal (so it behaves like the other list pages)
    anomalies_per_page = get_per_page(request)
    anomalies_paginator = Paginator(anomalies_qs, anomalies_per_page)
    anomalies_page_obj = anomalies_paginator.get_page(request.GET.get("page"))
    anomalies_detail_list = list(anomalies_page_obj.object_list)
    anomalies_total_count = anomalies_paginator.count
    def _export_score(val):
        try:
            v = float(val)
            return 0.0 if v != v else v  # NaN -> 0
        except (TypeError, ValueError):
            return 0.0

    # Plain list for {% json_script %} — avoids breaking the dashboard Chart.js block via </script> in names
    anomalies_export_list = [
        {
            "item": a.item.name,
            "date": a.date.isoformat(),
            "quantity": int(a.quantity) if a.quantity is not None else 0,
            "score": _export_score(a.score),
            "severity": a.severity,
        }
        for a in anomalies_qs[:200]
    ]
    # String form kept for any callers/templates that still expect it; dashboard uses json_script + list
    anomalies_export_json = json.dumps(anomalies_export_list)

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
    pie_total_units = int(sum(pie_values)) if pie_values else 0
    pie_table_rows = [
        {
            "label": lbl,
            "qty": int(qty),
            "pct": round(100.0 * int(qty) / pie_total_units, 2) if pie_total_units else 0.0,
        }
        for lbl, qty in zip(pie_labels, pie_values)
    ]

    # ---- inventory-by-location (for chart next to category pie) ----
    location_qs = (
        Item.objects
        .values("location__name")
        .annotate(total_qty=Sum("quantity"))
        .order_by("-total_qty")[:8]
    )
    location_labels = [row["location__name"] or "No location" for row in location_qs]
    location_values = [int(row["total_qty"]) for row in location_qs]
    location_total_units = int(sum(location_values)) if location_values else 0
    location_table_rows = [
        {"label": lbl, "qty": int(qty)} for lbl, qty in zip(location_labels, location_values)
    ]

    is_manager_or_admin = request.user.groups.filter(name__in=["Manager", "Admin"]).exists()

    context = {
        "total_items": total_items,
        "low_stock_items": low_stock_items,
        "active_supplier_count": active_supplier_count,
        "active_customer_count": active_customer_count,
        "pending_purchase_orders_count": pending_purchase_orders_count,
        "pending_sales_orders_count": pending_sales_orders_count,
        "low_stock_percent": low_stock_percent,

        "trend_days": trend_days,
        "stock_dates": stock_dates,
        "stock_values": stock_values,
        "current_stock_value": current_stock_value,
        "inventory_change_pct": inventory_change_pct,
        "forecast_metric_value": forecast_metric_value,
        "forecast_days": forecast_days,
        "forecast_badge": forecast_badge,
        "forecast_chart_labels": json.dumps(forecast_result["chart_labels"]),
        "forecast_hist_values": json.dumps(forecast_result["chart_hist_values"]),
        "forecast_values": json.dumps(forecast_result["chart_forecast_values"]),
        "forecast_lower_values": json.dumps(forecast_result["chart_lower_values"]),
        "forecast_upper_values": json.dumps(forecast_result["chart_upper_values"]),
        "forecast_points_json": json.dumps(forecast_result.get("forecast_points", [])),
        "forecast_model_name": forecast_result.get("model_used", "baseline"),
        "forecast_model_used_fallback": forecast_result.get("used_fallback", False),
        "forecast_model_fallback_reason": forecast_result.get("fallback_reason", ""),
        "forecast_eval": model_eval,
        "forecast_change_pct": round(forecast_change_pct, 2),
        "forecast_has_significant_change": forecast_has_significant_change,
        "forecast_expected_range_lower": forecast_result.get("expected_range_lower", 0),
        "forecast_expected_range_upper": forecast_result.get("expected_range_upper", 0),
        "forecast_history_days_used": forecast_result.get("history_days_used", 0),
        "forecast_confidence_label": forecast_result.get("confidence_label", "Medium"),
        "forecast_today_index": forecast_result.get("chart_today_index", 0),
        "forecast_insight_text": forecast_insight,

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
        "recent_activity_detail_list": recent_activity_detail_list,
        "recent_activity_export_list": recent_activity_export_list,
        "anomalies_detail_list": anomalies_detail_list,
        "anomalies_page_obj": anomalies_page_obj,
        "anomalies_total_count": anomalies_total_count,
        "anomalies_export_list": anomalies_export_list,
        "anomalies_export_json": anomalies_export_json,
        "anom_severity": anom_severity,
        "anom_show": anom_show,
        "anom_q": anom_q,
        "anomalies_per_page": anomalies_per_page,
        "per_page_choices": PER_PAGE_CHOICES,
        "anomalies_heading_label": anomalies_heading_label,
        "is_manager_or_admin": is_manager_or_admin,

        "pie_labels": pie_labels,
        "pie_values": pie_values,
        "pie_total_units": pie_total_units,
        "pie_table_rows": pie_table_rows,
        "location_labels": location_labels,
        "location_values": location_values,
        "location_total_units": location_total_units,
        "location_table_rows": location_table_rows,
        "debug_trend": debug_trend,
        "trend_today_index": (len(stock_dates) - 1) if stock_dates else 0,
        "trend_debug_start_units": stock_values[0] if stock_values else 0,
        "trend_debug_end_units": stock_values[-1] if stock_values else 0,
        "trend_debug_forecast_points": len(forecast_result.get("forecast_points", [])),
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

from .alerts_jobs import run_anomaly_scan_and_notify
from .tasks import run_anomaly_scan_task
@login_required
@user_passes_test(is_manager_or_admin)
def run_anomaly_scan_view(request):
    try:
        run_anomaly_scan_task.delay()
        messages.success(request, "Anomaly scan queued in background. Results will appear shortly.")
    except Exception:
        # Fallback to sync execution when broker/worker is unavailable.
        summary = run_anomaly_scan_and_notify()
        messages.success(
            request,
            f"Anomaly scan complete. Detected {summary['detected']} anomalies ({summary['created']} new).",
        )
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
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
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
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
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
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("anomaly_list")


@require_POST
@login_required
@user_passes_test(is_manager_or_admin)
def anomaly_bulk_review(request):
    selected_ids = request.POST.getlist("selected_anomalies")
    if not selected_ids:
        messages.info(request, "No anomalies selected.")
        return redirect(request.POST.get("next") or "dashboard")

    DemandAnomaly.objects.filter(pk__in=selected_ids).update(is_reviewed=True)
    messages.success(request, "Marked selected anomalies as reviewed.")

    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("dashboard")


@require_POST
@login_required
@user_passes_test(is_manager_or_admin)
def anomaly_bulk_dismiss(request):
    selected_ids = request.POST.getlist("selected_anomalies")
    if not selected_ids:
        messages.info(request, "No anomalies selected.")
        return redirect(request.POST.get("next") or "dashboard")

    anomalies = (
        DemandAnomaly.objects
        .select_related("item")
        .filter(pk__in=selected_ids)
    )
    now = timezone.now()
    anomalies.update(dismissed=True, dismissed_at=now)

    # Also dismiss matching notifications for each anomaly (clean up bell)
    Notification = apps.get_model("inventory", "Notification")
    for a in anomalies:
        needle = f": {a.item.name} on {a.date:%d/%m/%Y} "
        Notification.objects.filter(
            user=request.user,
            dismissed=False,
            message__startswith="Demand anomaly (",
            message__contains=needle,
        ).update(dismissed=True, dismissed_at=now)

    messages.success(request, "Dismissed selected anomalies.")

    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("dashboard")


@require_POST
@login_required
@user_passes_test(is_manager_or_admin)
def anomaly_bulk_undismiss(request):
    selected_ids = request.POST.getlist("selected_anomalies")
    if not selected_ids:
        messages.info(request, "No anomalies selected.")
        return redirect(request.POST.get("next") or "dashboard")

    DemandAnomaly.objects.filter(pk__in=selected_ids).update(dismissed=False, dismissed_at=None)
    messages.success(request, "Restored selected anomalies.")

    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("dashboard")


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
        order_count=Count("order_lines"),
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

    # -------------------------
    # SUPPLIER FILTER
    # -------------------------
    supplier_id = request.GET.get("supplier")
    if supplier_id:
        items = items.filter(supplier_id=supplier_id)

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
    order_lines = (
        OrderLine.objects.filter(item=item)
        .select_related("order", "order__supplier", "order__client")
        .order_by("-order__order_date")[:20]
    )
    recent_history = item.history.order_by("-date")[:14]
    anomalies = item.demand_anomalies.filter(dismissed=False).order_by("-date")[:5]

    # Clients who have purchased this item (from sale orders)
    client_ids = (
        Order.objects.filter(
            lines__item=item,
            order_type=Order.TYPE_SALE,
            client__isnull=False,
        )
        .values_list("client", flat=True)
        .distinct()
    )
    clients = Client.objects.filter(id__in=client_ids)[:10]

    # Order stats (count lines, not orders)
    order_stats = {
        "total_purchased": OrderLine.objects.filter(item=item, order__order_type=Order.TYPE_PURCHASE).count(),
        "total_sold": OrderLine.objects.filter(item=item, order__order_type=Order.TYPE_SALE).count(),
    }

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
        "order_lines": order_lines,
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
        new_qty = item.quantity + adjustment
        if new_qty < 0:
            messages.error(
                request,
                f"Cannot adjust {item.name}: quantity would become {new_qty}. "
                "Stock cannot go below zero."
            )
            return redirect("item_list")
        item.quantity = new_qty
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
        order_lines_deleted = OrderLine.objects.filter(item=item).count()
        history_deleted = StockHistory.objects.filter(item=item).count()

        # Delete related records first (OrderLine before Item)
        OrderLine.objects.filter(item=item).delete()
        StockHistory.objects.filter(item=item).delete()

        name = item.name
        item.delete()

        messages.success(
            request,
            f"Permanently deleted item '{name}' (order lines: {order_lines_deleted}, history: {history_deleted})."
        )
        return redirect("item_list")

    # GET -> show confirmation page with counts
    order_count = OrderLine.objects.filter(item=item).count()
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
        child_count=Count("children", distinct=True),
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
    if request.method == "POST":
        delete_mode = request.POST.get("delete_mode", "detach")
        ids = request.POST.getlist("ids")
        if ids:
            roots = list(Location.objects.filter(id__in=ids))
        else:
            roots = [get_object_or_404(Location, pk=pk)]

        if delete_mode == "cascade":
            # Delete each selected location and all of its descendants
            ids_to_delete = set()
            queue = list(roots)
            while queue:
                current = queue.pop(0)
                if current.id in ids_to_delete:
                    continue
                ids_to_delete.add(current.id)
                queue.extend(list(current.children.all()))
            Location.objects.filter(id__in=ids_to_delete).delete()
        else:
            # Delete only root locations and detach their direct children
            for root in roots:
                Location.objects.filter(parent=root).update(parent=None)
                root.delete()
        return redirect("location_list")

    return render(request, "inventory/location_confirm_delete.html", {
        "location": get_object_or_404(Location, pk=pk),
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
    sales_shipped = Order.objects.prefetch_related("lines__item").filter(
        order_type=Order.TYPE_SALE,
        shipping_location=location,
    ).select_related("client").order_by("-order_date")[:15]
    purchases_received = Order.objects.prefetch_related("lines__item").filter(
        order_type=Order.TYPE_PURCHASE,
        receiving_location=location,
    ).select_related("supplier").order_by("-order_date")[:15]
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
    orders = (
        Order.objects.select_related(
            "supplier", "client", "shipping_location", "receiving_location"
        )
        .prefetch_related("lines", "lines__item")
        .annotate(
            total_value=Sum(F("lines__quantity") * F("lines__unit_price")),
            party_name_sort=Coalesce("supplier__name", "client__name"),
            location_name_sort=Coalesce("shipping_location__name", "receiving_location__name"),
        )
    )

    # --- filter by item ---
    item_id = request.GET.get("item")
    if item_id:
        orders = orders.filter(lines__item_id=item_id).distinct()

    # --- search ---
    q = request.GET.get("q", "").strip()
    if q:
        orders = orders.filter(
            Q(lines__item__name__icontains=q)
            | Q(supplier__name__icontains=q)
            | Q(client__name__icontains=q)
            | Q(reference__icontains=q)
        ).distinct()

    # --- filter by type (purchase / sale only; no "all") ---
    type_filter = request.GET.get("type", "purchase")
    if type_filter not in ("purchase", "sale"):
        type_filter = "purchase"
    if type_filter == "purchase":
        orders = orders.filter(order_type=Order.TYPE_PURCHASE)
    else:
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

    # --- saved view presets (override date range) ---
    today = timezone.now().date()
    saved_view = request.GET.get("saved_view")
    if saved_view == "today":
        date_from_str = today.isoformat()
        date_to_str = today.isoformat()
    elif saved_view == "week":
        start_week = today - timedelta(days=today.weekday())
        date_from_str = start_week.isoformat()
        date_to_str = today.isoformat()
    elif saved_view == "30d":
        date_from_str = (today - timedelta(days=30)).isoformat()
        date_to_str = today.isoformat()
    else:
        date_from_str = request.GET.get("date_from")
        date_to_str = request.GET.get("date_to")

    # --- quick filter chips ---
    if request.GET.get("overdue") == "1":
        orders = orders.filter(
            target_date__lt=today,
            status__in=[Order.STATUS_PENDING, Order.STATUS_PROCESSING, Order.STATUS_SHIPPED],
        )
    if request.GET.get("priority") == "HIGH":
        orders = orders.filter(priority=Order.PRIORITY_HIGH)
    min_total_val = request.GET.get("min_total")
    if min_total_val:
        try:
            min_t = Decimal(min_total_val)
            orders = orders.filter(total_value__gte=min_t)
        except (ValueError, TypeError):
            pass

    # --- date range filters ---
    if date_from_str:
        date_from = parse_date(date_from_str)
        if date_from:
            orders = orders.filter(order_date__gte=date_from)
    if date_to_str:
        date_to = parse_date(date_to_str)
        if date_to:
            orders = orders.filter(order_date__lte=date_to)

    # --- sorting ---
    sort = request.GET.get("sort", "-order_date")
    valid_sorts = [
        "order_date", "-order_date",
        "id", "-id",
        "reference", "-reference",
        "status", "-status",
        "party_name_sort", "-party_name_sort",
        "location_name_sort", "-location_name_sort",
        "total_value", "-total_value",
        "order_type", "-order_type",
    ]
    if sort not in valid_sorts:
        sort = "-order_date"
    orders = orders.order_by(sort)

    # Pagination
    per_page = get_per_page(request)
    paginator = Paginator(orders, per_page)
    page = request.GET.get("page")
    orders = paginator.get_page(page)

    # Summary counts for current order type only
    type_qs = Order.objects.filter(
        order_type=Order.TYPE_PURCHASE if type_filter == "purchase" else Order.TYPE_SALE
    )
    current_total = type_qs.count()
    current_pending = type_qs.filter(status=Order.STATUS_PENDING).count()
    current_delivered = type_qs.filter(status=Order.STATUS_DELIVERED).count()
    current_processing = type_qs.filter(status=Order.STATUS_PROCESSING).count()
    current_shipped = type_qs.filter(status=Order.STATUS_SHIPPED).count()
    current_overdue = type_qs.filter(
        target_date__lt=today,
        status__in=[Order.STATUS_PENDING, Order.STATUS_PROCESSING, Order.STATUS_SHIPPED],
    ).count()

    # Locations for filters
    locations = Location.objects.filter(is_active=True).order_by("name")

    # Determine if any filters are active (for "clear filters" banner)
    has_filters = any(
        [
            q,
            status_filter != "all",
            item_id,
            shipping_location_id,
            receiving_location_id,
            date_from_str,
            date_to_str,
            request.GET.get("overdue") == "1",
            request.GET.get("priority") == "HIGH",
            request.GET.get("min_total"),
        ]
    )

    # Recommendations popup should only appear for manager/admin accounts.
    is_manager_or_admin = request.user.groups.filter(name__in=["Manager", "Admin"]).exists()
    recommendations = []
    if is_manager_or_admin:
        ensure_recommendations_fresh()
        recommendations = get_recommendations_for_context(
            "purchase" if type_filter == "purchase" else "sale", limit=6
        )

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
        "date_from": date_from_str or "",
        "date_to": date_to_str or "",
        "shipping_location_id": shipping_location_id or "",
        "receiving_location_id": receiving_location_id or "",
        "locations": locations,
        "has_filters": has_filters,
        "current_total": current_total,
        "current_pending": current_pending,
        "current_delivered": current_delivered,
        "current_processing": current_processing,
        "current_shipped": current_shipped,
        "current_overdue": current_overdue,
        "today": today,
        "recommendations": recommendations,
        "context_type": type_filter,
    })


@login_required
@permission_required("inventory.view_order", raise_exception=True)
def order_detail(request, pk):
    order = get_object_or_404(
        Order.objects.prefetch_related("lines", "lines__item").select_related(
            "supplier", "client", "shipping_location", "receiving_location"
        ),
        pk=pk,
    )
    # Other orders from same party (supplier/client)
    other_orders = None
    if order.supplier_id:
        other_orders = Order.objects.filter(supplier_id=order.supplier_id).exclude(pk=order.pk).select_related("supplier").prefetch_related("lines", "lines__item").order_by("-order_date")[:10]
    elif order.client_id:
        other_orders = Order.objects.filter(client_id=order.client_id).exclude(pk=order.pk).select_related("client").prefetch_related("lines", "lines__item").order_by("-order_date")[:10]

    return render(request, "inventory/order_detail.html", {
        "order": order,
        "today": timezone.now().date(),
        "other_orders_from_party": other_orders or [],
        "type_filter": order.order_type.lower(),
    })


@login_required
@permission_required("inventory.view_order", raise_exception=True)
def order_export_csv(request):
    """Export orders to CSV, respecting current filters. Pass ids=1,2,3 to export only selected orders."""
    orders = Order.objects.prefetch_related("lines", "lines__item").select_related("supplier", "client")
    ids_param = request.GET.get("ids", "").strip()
    if ids_param:
        try:
            id_list = [int(x.strip()) for x in ids_param.split(",") if x.strip()]
            if id_list:
                orders = orders.filter(pk__in=id_list)
        except (ValueError, TypeError):
            pass
    item_id = request.GET.get("item")
    if item_id:
        orders = orders.filter(lines__item_id=item_id).distinct()
    q = request.GET.get("q", "").strip()
    if q:
        orders = orders.filter(
            Q(lines__item__name__icontains=q)
            | Q(supplier__name__icontains=q)
            | Q(client__name__icontains=q)
            | Q(reference__icontains=q)
        ).distinct()

    type_filter = request.GET.get("type", "purchase")
    if type_filter not in ("purchase", "sale"):
        type_filter = "purchase"
    if type_filter == "purchase":
        orders = orders.filter(order_type=Order.TYPE_PURCHASE)
    else:
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

    date_from_str = request.GET.get("date_from")
    date_to_str = request.GET.get("date_to")
    if date_from_str:
        date_from = parse_date(date_from_str)
        if date_from:
            orders = orders.filter(order_date__gte=date_from)
    if date_to_str:
        date_to = parse_date(date_to_str)
        if date_to:
            orders = orders.filter(order_date__lte=date_to)

    sort = request.GET.get("sort", "-order_date")
    valid_sorts = [
        "order_date", "-order_date",
        "id", "-id",
        "status", "-status",
        "order_type", "-order_type",
    ]
    if sort in valid_sorts:
        orders = orders.order_by(sort)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="orders.csv"'
    writer = csv.writer(response)
    writer.writerow(["Order #", "Type", "Item", "Party", "Date", "Qty", "Unit Price", "Line Total", "Order Total", "Status", "Shipping location", "Receiving location"])
    for o in orders:
        lines = list(o.lines.select_related("item").all())
        if lines:
            for i, ln in enumerate(lines):
                writer.writerow([
                    f"ORD-{o.id}" if i == 0 else "",
                    o.get_order_type_display() if i == 0 else "",
                    ln.item.name if ln.item else "",
                    o.party_name if i == 0 else "",
                    o.order_date if i == 0 else "",
                    ln.quantity,
                    ln.unit_price,
                    ln.total,
                    o.total if i == 0 else "",
                    o.get_status_display() if i == 0 else "",
                    o.shipping_location.name if o.shipping_location and i == 0 else "",
                    o.receiving_location.name if o.receiving_location and i == 0 else "",
                ])
        else:
            writer.writerow([f"ORD-{o.id}", o.get_order_type_display(), "", o.party_name, o.order_date, "", "", o.total, o.get_status_display(), "", ""])
    return response


@login_required
@permission_required("inventory.add_order", raise_exception=True)
def order_create(request):
    # Query parameters:
    # ?type=purchase or ?type=sale (your existing behaviour)
    forced_type = request.GET.get("type")  

    # Recommendation parameters:
    # ?item=ID  and ?qty=NUMBER (legacy)
    # or ?rec=ID (unified Recommendation model)
    item_id = request.GET.get("item")
    qty = request.GET.get("qty")
    rec_id = request.GET.get("rec")

    # Build initial form values
    initial = {}

    # If unified Recommendation is provided, use it as the primary source
    recommendation = None
    if rec_id:
        from .models import Recommendation
        try:
            recommendation = Recommendation.objects.select_related(
                "item", "suggested_supplier", "suggested_customer"
            ).get(pk=rec_id)
        except Recommendation.DoesNotExist:
            recommendation = None

    if recommendation:
        rec_item = recommendation.item
        initial["item"] = rec_item
        if recommendation.suggested_quantity:
            initial["quantity"] = int(recommendation.suggested_quantity)
        # Infer order type from recommendation type if not forced via URL
        if not forced_type:
            if recommendation.recommendation_type == Recommendation.TYPE_SALES_OVERSTOCK:
                initial["order_type"] = Order.TYPE_SALE
            else:
                initial["order_type"] = Order.TYPE_PURCHASE
        # Party + dates for the header form
        if recommendation.suggested_supplier:
            initial["supplier"] = recommendation.suggested_supplier
        if recommendation.suggested_customer:
            initial["client"] = recommendation.suggested_customer
        if recommendation.target_date:
            initial["target_date"] = recommendation.target_date
    else:
        # Legacy query-string behaviour
        if item_id:
            try:
                initial["item"] = Item.objects.get(pk=item_id)
            except Item.DoesNotExist:
                pass

        if qty:
            try:
                initial["quantity"] = int(qty)
            except ValueError:
                pass

        if item_id or qty:
            initial["order_type"] = Order.TYPE_PURCHASE

    # Existing forced type from your URLs overrides everything else
    if forced_type in ["purchase", "sale"]:
        initial["order_type"] = forced_type.upper()

    # Pre-fill supplier/client from contact profile links (?supplier=ID or ?client=ID)
    supplier_id = request.GET.get("supplier")
    if supplier_id and (initial.get("order_type") == Order.TYPE_PURCHASE or forced_type == "purchase"):
        try:
            initial.setdefault("supplier", Supplier.objects.get(pk=supplier_id))
        except (Supplier.DoesNotExist, ValueError):
            pass
    client_id = request.GET.get("client")
    if client_id and (initial.get("order_type") == Order.TYPE_SALE or forced_type == "sale"):
        try:
            initial.setdefault("client", Client.objects.get(pk=client_id))
        except (Client.DoesNotExist, ValueError):
            pass

    # Auto-fill from item's order/stock history (purchase orders)
    item_for_history = initial.get("item")
    if item_for_history and (initial.get("order_type") == Order.TYPE_PURCHASE or forced_type == "purchase"):
        initial.setdefault("order_date", timezone.now().date())
        # Last purchase order containing this item
        last_po = (
            Order.objects.filter(
                order_type=Order.TYPE_PURCHASE,
                lines__item=item_for_history,
            )
            .select_related("supplier", "receiving_location")
            .prefetch_related("lines")
            .order_by("-order_date")
            .first()
        )
        if last_po:
            if "supplier" not in initial or not initial["supplier"]:
                initial.setdefault("supplier", last_po.supplier)
            if "receiving_location" not in initial or not initial["receiving_location"]:
                initial.setdefault("receiving_location", last_po.receiving_location)
            initial.setdefault("priority", last_po.priority)
            # Last unit_price for this item from any purchase order line
            last_line = (
                OrderLine.objects.filter(
                    order__order_type=Order.TYPE_PURCHASE,
                    item=item_for_history,
                )
                .order_by("-order__order_date")
                .values_list("unit_price", flat=True)
                .first()
            )
            if last_line is not None:
                initial.setdefault("unit_price", last_line)
        # Fallbacks from item
        if not initial.get("supplier") and item_for_history.supplier_id:
            initial["supplier"] = item_for_history.supplier
        if not initial.get("receiving_location") and item_for_history.location_id:
            initial["receiving_location"] = item_for_history.location
        if "priority" not in initial or not initial["priority"]:
            initial.setdefault("priority", Order.PRIORITY_MEDIUM)
        if "unit_price" not in initial or initial["unit_price"] is None:
            initial.setdefault("unit_price", item_for_history.unit_cost)

    # Auto-fill for sale orders (from item's sale history)
    if item_for_history and (initial.get("order_type") == Order.TYPE_SALE or forced_type == "sale"):
        initial.setdefault("order_date", timezone.now().date())
        last_so = (
            Order.objects.filter(
                order_type=Order.TYPE_SALE,
                lines__item=item_for_history,
            )
            .select_related("client", "shipping_location")
            .order_by("-order_date")
            .first()
        )
        if last_so:
            if "client" not in initial or not initial["client"]:
                initial.setdefault("client", last_so.client)
            if "shipping_location" not in initial or not initial["shipping_location"]:
                initial.setdefault("shipping_location", last_so.shipping_location)
            initial.setdefault("priority", last_so.priority)
            last_line = (
                OrderLine.objects.filter(
                    order__order_type=Order.TYPE_SALE,
                    item=item_for_history,
                )
                .order_by("-order__order_date")
                .values_list("unit_price", flat=True)
                .first()
            )
            if last_line is not None:
                initial.setdefault("unit_price", last_line)
        if "priority" not in initial or not initial["priority"]:
            initial.setdefault("priority", Order.PRIORITY_MEDIUM)
        if "unit_price" not in initial or initial["unit_price"] is None:
            initial.setdefault("unit_price", item_for_history.unit_cost)

    # -------------------------
    # POST REQUEST (Form submit)
    # -------------------------
    if request.method == "POST":
        form = OrderForm(request.POST)
        if forced_type in ["purchase", "sale"]:
            form.data = form.data.copy()
            form.data["order_type"] = forced_type.upper()

        formset = OrderLineFormSet(request.POST, instance=Order())
        if form.is_valid() and formset.is_valid():
            order = form.save()
            formset.instance = order
            formset.save()
            try:
                order.apply_stock_if_needed(actor=request.user)
            except ValueError as e:
                order.status = Order.STATUS_PENDING
                order.save(update_fields=["status"])
                messages.error(request, str(e))
                return redirect(reverse("order_edit", args=[order.pk]))
            # Mark recommendation as accepted once the order is created successfully
            if recommendation:
                recommendation.status = Recommendation.STATUS_ACCEPTED
                recommendation.save(update_fields=["status", "updated_at"])
            return redirect(reverse("order_list") + f"?type={order.order_type.lower()}")
        formset = OrderLineFormSet(request.POST, instance=Order())
    else:
        form = OrderForm(initial=initial)
        line_initial = None
        if initial.get("item"):
            line_data = {"item": initial["item"], "quantity": initial.get("quantity", 1)}
            if initial.get("unit_price") is not None:
                line_data["unit_price"] = initial["unit_price"]
            line_initial = [line_data]
        formset = OrderLineFormSet(instance=Order(), initial=line_initial)
        if forced_type in ["purchase", "sale"]:
            form.fields["order_type"].widget.attrs.update({"disabled": True})

    return render(request, "inventory/order_form.html", {
        "form": form,
        "formset": formset,
        "forced_type": forced_type,
    })



@login_required
@permission_required("inventory.change_order", raise_exception=True)
def order_edit(request, pk):
    order = get_object_or_404(Order.objects.prefetch_related("lines"), pk=pk)

    if request.method == "POST":
        form = OrderForm(request.POST, instance=order)
        formset = OrderLineFormSet(request.POST, instance=order)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            return redirect(reverse("order_list") + f"?type={order.order_type.lower()}")
    else:
        form = OrderForm(instance=order)
        formset = OrderLineFormSet(instance=order)

    return render(
        request,
        "inventory/order_form.html",
        {"form": form, "formset": formset, "edit": True, "order": order},
    )


@login_required
@permission_required("inventory.add_order", raise_exception=True)
def order_duplicate(request, pk):
    """Create a copy of an order (same lines, party, location) with status PENDING."""
    order = get_object_or_404(
        Order.objects.prefetch_related("lines", "lines__item").select_related(
            "supplier", "client", "shipping_location", "receiving_location"
        ),
        pk=pk,
    )
    new_order = Order(
        order_type=order.order_type,
        supplier=order.supplier,
        client=order.client,
        shipping_location=order.shipping_location,
        receiving_location=order.receiving_location,
        order_date=timezone.now().date(),
        status=Order.STATUS_PENDING,
        reference="",
        description=order.description,
        party_reference=order.party_reference,
        target_date=order.target_date,
        external_link=order.external_link,
        priority=order.priority,
        notes=order.notes,
        stock_applied=False,
    )
    new_order.save()
    for ln in order.lines.all():
        OrderLine.objects.create(
            order=new_order,
            item=ln.item,
            quantity=ln.quantity,
            unit_price=ln.unit_price,
        )
    messages.success(request, f"Duplicated order #{order.id} as order #{new_order.id}.")
    return redirect(reverse("order_edit", args=[new_order.pk]))


@login_required
@permission_required("inventory.delete_order", raise_exception=True)
def order_delete(request, pk):
    order = get_object_or_404(Order, pk=pk)

    if request.method == "POST":
        order_type = order.order_type.lower()
        order.delete()
        messages.success(request, "Order deleted.")
        return redirect(reverse("order_list") + f"?type={order_type}")

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
        prev_status = order.status
        order.status = Order.STATUS_DELIVERED
        order.save(update_fields=["status"])
        try:
            order.apply_stock_if_needed(actor=request.user)
        except ValueError as e:
            order.status = prev_status
            order.save(update_fields=["status"])
            messages.error(request, str(e))
        else:
            messages.success(request, f"Order #{order.id} marked as delivered.")
        return redirect(reverse("order_list") + f"?type={order.order_type.lower()}")

    return redirect(reverse("order_list") + f"?type={order.order_type.lower()}")


@login_required
@permission_required("inventory.view_supplier", raise_exception=True)
@permission_required("inventory.view_client", raise_exception=True)
def contacts_list(request):
    # ----------------------------
    # 1. GET FILTERS (suppliers or customers only; default suppliers)
    # ----------------------------
    type_filter = request.GET.get("type", "suppliers")
    if type_filter not in ("suppliers", "customers"):
        type_filter = "suppliers"
    q = request.GET.get("q", "").strip()
    quick_filter = request.GET.get("filter", "")
    min_orders_val = request.GET.get("min_orders", "")
    min_value_val = request.GET.get("min_value", "")
    has_contact = request.GET.get("has_contact", "")
    status_filter = request.GET.get("status", "active")

    suppliers = Supplier.objects.all()
    clients = Client.objects.all()

    def _contact_dict(obj, contact_type):
        if contact_type == "supplier":
            orders_qs = Order.objects.filter(supplier=obj)
            line_total = OrderLine.objects.filter(order__supplier=obj).aggregate(
                t=Sum(F("quantity") * F("unit_price"))
            )["t"] or 0
        else:
            orders_qs = Order.objects.filter(client=obj)
            line_total = OrderLine.objects.filter(order__client=obj).aggregate(
                t=Sum(F("quantity") * F("unit_price"))
            )["t"] or 0
        return {
            "id": obj.id,
            "name": obj.name,
            "type": contact_type,
            "email": obj.email or "",
            "phone": obj.phone or "",
            "address": obj.address or "",
            "website": getattr(obj, "website", "") or "",
            "tax_id": getattr(obj, "tax_id", "") or "",
            "description": getattr(obj, "description", "") or "",
            "image": getattr(obj, "image", None),
            "is_active": getattr(obj, "is_active", True),
            "currency": getattr(obj, "currency", "") or "",
            "orders": orders_qs.count(),
            "total_value": line_total,
        }

    # ----------------------------
    # 2. Build merged contact dataset
    # ----------------------------
    contacts = []
    for s in suppliers:
        contacts.append(_contact_dict(s, "supplier"))
    for c in clients:
        contacts.append(_contact_dict(c, "customer"))

    # ----------------------------
    # 3. Apply TYPE FILTER (always suppliers or customers only - no "all")
    # ----------------------------
    if type_filter == "suppliers":
        contacts = [c for c in contacts if c["type"] == "supplier"]
    elif type_filter == "customers":
        contacts = [c for c in contacts if c["type"] == "customer"]

    # Compute summary card counts (before search/dropdown filters, after type)
    all_of_type = list(contacts)
    count_with_orders = sum(1 for c in all_of_type if c["orders"] > 0)
    count_no_orders = sum(1 for c in all_of_type if c["orders"] == 0)
    count_high_value = sum(1 for c in all_of_type if float(c["total_value"] or 0) >= 500)
    count_with_contact = sum(1 for c in all_of_type if (c.get("email") or "").strip() or (c.get("phone") or "").strip())

    # ----------------------------
    # 4. Apply SEARCH FILTER
    # ----------------------------
    if q:
        ql = q.lower()
        contacts = [
            c for c in contacts
            if ql in (c["name"] or "").lower()
            or ql in (c["email"] or "").lower()
            or ql in (c["phone"] or "").lower()
            or ql in (c["address"] or "").lower()
            or ql in (c["website"] or "").lower()
        ]

    # ----------------------------
    # 5. Apply QUICK FILTER (summary card clicks)
    # ----------------------------
    if quick_filter == "with_orders":
        contacts = [c for c in contacts if c["orders"] > 0]
    elif quick_filter == "no_orders":
        contacts = [c for c in contacts if c["orders"] == 0]
    elif quick_filter == "high_value":
        contacts = [c for c in contacts if float(c["total_value"] or 0) >= 500]

    # ----------------------------
    # 6. Apply DROPDOWN FILTERS
    # ----------------------------
    if min_orders_val:
        try:
            mo = int(min_orders_val)
            contacts = [c for c in contacts if c["orders"] >= mo]
        except (ValueError, TypeError):
            pass
    if min_value_val:
        try:
            mv = Decimal(min_value_val)
            contacts = [c for c in contacts if float(c["total_value"] or 0) >= float(mv)]
        except (ValueError, TypeError, Exception):
            pass
    if has_contact == "yes":
        contacts = [c for c in contacts if (c["email"] or "").strip() or (c["phone"] or "").strip()]
    elif has_contact == "no":
        contacts = [c for c in contacts if not ((c["email"] or "").strip() or (c["phone"] or "").strip())]

    # ----------------------------
    # 6b. STATUS FILTER (active/inactive)
    # ----------------------------
    if status_filter == "active":
        contacts = [c for c in contacts if c.get("is_active", True)]
    elif status_filter == "inactive":
        contacts = [c for c in contacts if not c.get("is_active", True)]
    # "all" -> no filter

    # ----------------------------
    # 7. Sorting
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
    # Summary card counts
    # ----------------------------
    total_suppliers = suppliers.count()
    total_customers = clients.count()
    active_relationships = total_suppliers + total_customers

    # ----------------------------
    # Filter state for UI (only show filter banner when user-applied filters)
    # ----------------------------
    has_filters = any([
        q,
        quick_filter,
        min_orders_val,
        min_value_val,
        has_contact,
        status_filter and status_filter != "active",
    ])

    # ----------------------------
    # Render page
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
        "count_with_orders": count_with_orders,
        "count_no_orders": count_no_orders,
        "count_high_value": count_high_value,
        "active_filter": quick_filter,
        "min_orders": min_orders_val,
        "min_value": min_value_val,
        "has_contact_filter": has_contact,
        "status_filter": status_filter,
        "count_with_contact": count_with_contact,
        "top_supplier": top_supplier,
        "top_customer": top_customer,
        "search_query": q,
        "sort": sort,
        "has_filters": has_filters,
    })


@login_required
@permission_required("inventory.view_supplier", raise_exception=True)
@permission_required("inventory.view_client", raise_exception=True)
def contact_export_csv(request):
    """Export contacts to CSV, respecting current filters."""
    type_filter = request.GET.get("type", "suppliers")
    q = request.GET.get("q", "").strip()
    quick_filter = request.GET.get("filter", "")
    min_orders_val = request.GET.get("min_orders", "")
    min_value_val = request.GET.get("min_value", "")
    has_contact = request.GET.get("has_contact", "")
    status_filter = request.GET.get("status", "active")
    suppliers = Supplier.objects.all()
    clients = Client.objects.all()
    contacts = []
    for s in suppliers:
        supplier_orders = Order.objects.filter(supplier=s)
        line_total = OrderLine.objects.filter(order__supplier=s).aggregate(
            t=Sum(F("quantity") * F("unit_price"))
        )["t"] or 0
        contacts.append({
            "id": s.id, "name": s.name, "type": "supplier", "email": s.email or "", "phone": s.phone or "",
            "address": s.address or "", "website": getattr(s, "website", "") or "",
            "orders": supplier_orders.count(),
            "total_value": line_total,
            "is_active": getattr(s, "is_active", True),
        })
    for c in clients:
        client_orders = Order.objects.filter(client=c)
        line_total = OrderLine.objects.filter(order__client=c).aggregate(
            t=Sum(F("quantity") * F("unit_price"))
        )["t"] or 0
        contacts.append({
            "id": c.id, "name": c.name, "type": "customer", "email": c.email or "", "phone": c.phone or "",
            "address": c.address or "", "website": getattr(c, "website", "") or "",
            "orders": client_orders.count(),
            "total_value": line_total,
            "is_active": getattr(c, "is_active", True),
        })
    if type_filter == "suppliers":
        contacts = [c for c in contacts if c["type"] == "supplier"]
    elif type_filter == "customers":
        contacts = [c for c in contacts if c["type"] == "customer"]
    if q:
        ql = q.lower()
        contacts = [
            c for c in contacts
            if ql in (c["name"] or "").lower()
            or ql in (c["email"] or "").lower()
            or ql in (c["phone"] or "").lower()
            or ql in (c["address"] or "").lower()
            or ql in (c["website"] or "").lower()
        ]
    if quick_filter == "with_orders":
        contacts = [c for c in contacts if c["orders"] > 0]
    elif quick_filter == "no_orders":
        contacts = [c for c in contacts if c["orders"] == 0]
    elif quick_filter == "high_value":
        contacts = [c for c in contacts if float(c["total_value"] or 0) >= 500]
    if min_orders_val:
        try:
            mo = int(min_orders_val)
            contacts = [c for c in contacts if c["orders"] >= mo]
        except (ValueError, TypeError):
            pass
    if min_value_val:
        try:
            mv = Decimal(min_value_val)
            contacts = [c for c in contacts if float(c["total_value"] or 0) >= float(mv)]
        except (ValueError, TypeError, Exception):
            pass
    if has_contact == "yes":
        contacts = [c for c in contacts if (c["email"] or "").strip() or (c["phone"] or "").strip()]
    elif has_contact == "no":
        contacts = [c for c in contacts if not ((c["email"] or "").strip() or (c["phone"] or "").strip())]
    if status_filter == "active":
        contacts = [c for c in contacts if c.get("is_active", True)]
    elif status_filter == "inactive":
        contacts = [c for c in contacts if not c.get("is_active", True)]
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
    writer.writerow(["Name", "Type", "Email", "Phone", "Website", "Address", "Orders", "Total Value"])
    for c in contacts:
        writer.writerow([
            c["name"], c["type"].title(), c["email"] or "", c["phone"] or "",
            c.get("website", "") or "", c.get("address", "") or "",
            c["orders"], c["total_value"],
        ])
    return response


@login_required
@permission_required("inventory.add_supplier", raise_exception=True)
def supplier_create(request):
    if request.method == "POST":
        form = SupplierForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect(reverse("contacts_list") + "?type=suppliers")
    else:
        form = SupplierForm()

    return render(request, "inventory/supplier_form.html", {"form": form, "hide_contacts_sidebar": True})


@login_required
@permission_required("inventory.change_supplier", raise_exception=True)
def supplier_edit(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)

    if request.method == "POST":
        form = SupplierForm(request.POST, request.FILES, instance=supplier)
        if form.is_valid():
            form.save()
            return redirect(reverse("contacts_list") + "?type=suppliers")
    else:
        form = SupplierForm(instance=supplier)

    return render(request, "inventory/supplier_form.html", {
        "form": form,
        "edit": True,
        "supplier": supplier,
        "hide_contacts_sidebar": True,
    })


@login_required
@permission_required("inventory.delete_supplier", raise_exception=True)
def supplier_delete(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)

    if request.method == "POST":
        supplier.delete()
        return redirect(reverse("contacts_list") + "?type=suppliers")

    return render(request, "inventory/supplier_confirm_delete.html", {
        "supplier": supplier
    })


@login_required
@permission_required("inventory.view_supplier", raise_exception=True)
@never_cache
def supplier_view(request, pk):
    """Supplier profile page with orders, stats, and details."""
    supplier = get_object_or_404(Supplier, pk=pk)
    orders = Order.objects.filter(supplier=supplier).prefetch_related("lines__item").select_related(
        "receiving_location", "shipping_location"
    ).order_by("-order_date")[:20]
    orders_count = Order.objects.filter(supplier=supplier).count()
    total_value = OrderLine.objects.filter(order__supplier=supplier).aggregate(
        t=Sum(F("quantity") * F("unit_price"))
    )["t"] or 0
    items_supplied = Item.objects.filter(supplier=supplier, is_active=True).order_by("name")[:30]
    items_supplied_count = Item.objects.filter(supplier=supplier).count()
    # Chart data: order value by month (bar chart - different from location pie)
    from django.db.models.functions import TruncMonth
    order_values_by_month = (
        OrderLine.objects.filter(order__supplier=supplier)
        .annotate(month=TruncMonth("order__order_date"))
        .values("month")
        .annotate(total=Sum(F("quantity") * F("unit_price")))
        .order_by("month")[:12]
    )
    chart_labels = [d["month"].strftime("%b %Y") if d["month"] else "" for d in order_values_by_month]
    chart_values = [float(d["total"] or 0) for d in order_values_by_month]

    return render(request, "inventory/supplier_view.html", {
        "supplier": supplier,
        "orders": orders,
        "orders_count": orders_count,
        "total_value": total_value,
        "items_supplied": items_supplied,
        "items_supplied_count": items_supplied_count,
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "hide_contacts_sidebar": True,
    })


@login_required
@permission_required("inventory.add_client", raise_exception=True)
def client_create(request):
    if request.method == "POST":
        form = ClientForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect(reverse("contacts_list") + "?type=customers")
    else:
        form = ClientForm()

    return render(request, "inventory/client_form.html", {"form": form, "hide_contacts_sidebar": True})


@login_required
@permission_required("inventory.change_client", raise_exception=True)
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)

    if request.method == "POST":
        form = ClientForm(request.POST, request.FILES, instance=client)
        if form.is_valid():
            form.save()
            return redirect(reverse("contacts_list") + "?type=customers")
    else:
        form = ClientForm(instance=client)

    return render(request, "inventory/client_form.html", {
        "form": form,
        "edit": True,
        "client": client,
        "hide_contacts_sidebar": True,
    })


@login_required
@permission_required("inventory.delete_client", raise_exception=True)
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk)

    if request.method == "POST":
        client.delete()
        return redirect(reverse("contacts_list") + "?type=customers")

    return render(request, "inventory/client_confirm_delete.html", {
        "client": client
    })


@login_required
@permission_required("inventory.view_client", raise_exception=True)
@never_cache
def client_view(request, pk):
    """Customer profile page with orders, stats, and details."""
    client = get_object_or_404(Client, pk=pk)
    orders = Order.objects.filter(client=client).prefetch_related("lines__item").select_related(
        "receiving_location", "shipping_location"
    ).order_by("-order_date")[:20]
    orders_count = Order.objects.filter(client=client).count()
    total_value = OrderLine.objects.filter(order__client=client).aggregate(
        t=Sum(F("quantity") * F("unit_price"))
    )["t"] or 0
    items_purchased_count = OrderLine.objects.filter(order__client=client).values("item").distinct().count()
    # Chart data: order value by month (bar chart - different from location pie)
    from django.db.models.functions import TruncMonth
    order_values_by_month = (
        OrderLine.objects.filter(order__client=client)
        .annotate(month=TruncMonth("order__order_date"))
        .values("month")
        .annotate(total=Sum(F("quantity") * F("unit_price")))
        .order_by("month")[:12]
    )
    chart_labels = [d["month"].strftime("%b %Y") if d["month"] else "" for d in order_values_by_month]
    chart_values = [float(d["total"] or 0) for d in order_values_by_month]

    return render(request, "inventory/client_view.html", {
        "client": client,
        "orders": orders,
        "orders_count": orders_count,
        "total_value": total_value,
        "items_purchased_count": items_purchased_count,
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "hide_contacts_sidebar": True,
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
            cache.delete(f"ctx_user_pref:{request.user.pk}")
            cache.delete(f"ctx_notifications:{request.user.pk}")
            messages.success(request, "Settings reset to defaults.")
            return redirect(f"{reverse('settings')}?tab={active_tab}")
        if action == "clear_dismissed_alerts":
            request.session["dismissed_alerts"] = []
            cache.delete(f"ctx_notifications:{request.user.pk}")
            messages.success(request, "Dismissed alerts have been restored.")
            return redirect(f"{reverse('settings')}?tab={active_tab}")

        form_class = tab_form_map.get(active_tab)
        if form_class is None:
            messages.error(request, "This settings section is not editable.")
            return redirect(f"{reverse('settings')}?tab={active_tab}")

        form = form_class(request.POST, instance=pref)
        if form.is_valid():
            form.save()
            cache.delete(f"ctx_user_pref:{request.user.pk}")
            cache.delete(f"ctx_notifications:{request.user.pk}")
            messages.success(request, "Settings saved.")
            return redirect(f"{reverse('settings')}?tab={active_tab}")
    else:
        form_class = tab_form_map.get(active_tab)
        form = form_class(instance=pref) if form_class else None

    return render(request, "inventory/settings.html", {
        "form": form,
        "active_tab": active_tab,
    })


@login_required
def alerts_list(request):
    alerts, _ = get_alerts_for_user(request, limit=None)

    total_all = len(alerts)
    total_critical = sum(1 for a in alerts if a.get("severity") == "critical")
    total_warning = sum(1 for a in alerts if a.get("severity") == "warning")
    total_info = sum(1 for a in alerts if a.get("severity") == "info")

    severity = (request.GET.get("severity") or "").strip().lower()
    source = (request.GET.get("source") or "").strip().lower()
    alert_type = (request.GET.get("alert_type") or "").strip().lower()
    q = (request.GET.get("q") or "").strip().lower()
    sort = (request.GET.get("sort") or "severity").strip()
    per_page = get_per_page(request)

    source_options = sorted({(a.get("source") or "") for a in alerts if a.get("source")})
    type_options = sorted({((a.get("type") or ""), (a.get("type_label") or (a.get("type") or "").replace("_", " ").title())) for a in alerts if a.get("type")}, key=lambda t: t[1])

    filtered_alerts = alerts
    if severity in {"critical", "warning", "info"}:
        filtered_alerts = [a for a in filtered_alerts if a.get("severity") == severity]
    if source:
        filtered_alerts = [a for a in filtered_alerts if (a.get("source") or "").lower() == source]
    if alert_type:
        filtered_alerts = [a for a in filtered_alerts if (a.get("type") or "").lower() == alert_type]
    if q:
        filtered_alerts = [a for a in filtered_alerts if q in (a.get("message") or "").lower()]

    if sort == "source":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: ((a.get("source") or "").lower(), (a.get("message") or "").lower()))
    elif sort == "-source":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: ((a.get("source") or "").lower(), (a.get("message") or "").lower()), reverse=True)
    elif sort == "time":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: a.get("time", ""))
    elif sort == "-time":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: a.get("time", ""), reverse=True)
    elif sort == "message":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: (a.get("message") or "").lower())
    elif sort == "-message":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: (a.get("message") or "").lower(), reverse=True)
    elif sort == "entity":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: (a.get("item_name") or "").lower())
    elif sort == "-entity":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: (a.get("item_name") or "").lower(), reverse=True)
    elif sort == "quantity":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: float(a.get("quantity") or 0))
    elif sort == "-quantity":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: float(a.get("quantity") or 0), reverse=True)
    elif sort == "score":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: float(a.get("score") or 0))
    elif sort == "-score":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: float(a.get("score") or 0), reverse=True)
    elif sort == "status":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: (a.get("status") or "").lower())
    elif sort == "-status":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: (a.get("status") or "").lower(), reverse=True)
    elif sort == "type":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: ((a.get("type_label") or "").lower(), (a.get("message") or "").lower()))
    elif sort == "-type":
        filtered_alerts = sorted(filtered_alerts, key=lambda a: ((a.get("type_label") or "").lower(), (a.get("message") or "").lower()), reverse=True)
    elif sort == "-severity":
        severity_order = {"critical": 2, "warning": 1, "info": 0}
        filtered_alerts = sorted(filtered_alerts, key=lambda a: (severity_order.get(a.get("severity"), -1), a.get("time", "")), reverse=False)
    else:
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        filtered_alerts = sorted(filtered_alerts, key=lambda a: (severity_order.get(a.get("severity"), 9), a.get("time", "")), reverse=False)

    for a in filtered_alerts:
        if a.get("is_db_notification"):
            a["dismiss_token"] = f"n:{a.get('id')}"
        else:
            a["dismiss_token"] = f"k:{a.get('key')}"

    type_counter = Counter((a.get("source") or "other").title() for a in alerts)
    chart_labels = list(type_counter.keys())
    chart_values = list(type_counter.values())

    paginator = Paginator(filtered_alerts, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    start_index = page_obj.start_index() if page_obj.paginator.count else 0
    end_index = page_obj.end_index() if page_obj.paginator.count else 0

    return render(request, "inventory/alerts_list.html", {
        "alerts": page_obj.object_list,
        "page_obj": page_obj,
        "per_page": per_page,
        "per_page_choices": PER_PAGE_CHOICES,
        "start_index": start_index,
        "end_index": end_index,
        "severity_filter": severity,
        "source_filter": source,
        "type_filter": alert_type,
        "q": request.GET.get("q", ""),
        "sort": sort,
        "source_options": source_options,
        "type_options": type_options,
        "total_count": paginator.count,
        "total_all": total_all,
        "total_critical": total_critical,
        "total_warning": total_warning,
        "total_info": total_info,
        "has_filters": bool(severity or source or alert_type or q),
        "chart_labels": chart_labels,
        "chart_values": chart_values,
    })


@require_POST
@login_required
def dismiss_alerts_bulk(request):
    tokens = request.POST.getlist("selected_alerts")
    dismissed = set(request.session.get("dismissed_alerts", []))
    notification_ids = []
    for token in tokens:
        if token.startswith("n:"):
            try:
                notification_ids.append(int(token.split(":", 1)[1]))
            except (ValueError, TypeError):
                continue
        elif token.startswith("k:"):
            key = token.split(":", 1)[1]
            if key:
                dismissed.add(key)

    if notification_ids:
        Notification.objects.filter(id__in=notification_ids, user=request.user).update(is_read=True)
    request.session["dismissed_alerts"] = list(dismissed)
    cache.delete(f"ctx_notifications:{request.user.pk}")
    return redirect(request.META.get("HTTP_REFERER", reverse("alerts_list")))