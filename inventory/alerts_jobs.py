import datetime
import logging

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from inventory.ml.anomaly import detect_sales_anomalies, save_anomalies
from inventory.models import Recommendation, UserPreference

logger = logging.getLogger(__name__)


def _send_grouped_alert_email(*, user, subject, intro, lines):
    if not user.email:
        return False
    if not lines:
        return False
    body = [f"Hi {user.username},", "", intro, ""]
    for line in lines[:25]:
        body.append(f"- {line}")
    body += ["", "Regards,", "WareWolf"]
    try:
        sent = send_mail(
            subject=subject,
            message="\n".join(body),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[user.email],
            fail_silently=False,
        )
        if sent != 1:
            logger.warning(
                "Email backend returned %s for user=%s subject=%s",
                sent,
                user.email,
                subject,
            )
        return sent == 1
    except Exception:
        logger.exception(
            "Failed sending alert email to user=%s subject=%s",
            user.email,
            subject,
        )
        return False


def run_anomaly_scan_and_notify(
    *,
    days_back=120,
    min_points=10,
    last_n_days_only=180,
    z_thresh_low=2.5,
    z_thresh_med=3.5,
    z_thresh_high=4.5,
):
    """
    Run anomaly detection and create in-app notifications for new MEDIUM/HIGH anomalies.

    Returns dict:
      {
        "detected": int,
        "created": int,
      }
    """
    results = detect_sales_anomalies(
        days_back=days_back,
        min_points=min_points,
        last_n_days_only=last_n_days_only,
        z_thresh_low=z_thresh_low,
        z_thresh_med=z_thresh_med,
        z_thresh_high=z_thresh_high,
    )
    created, created_objs = save_anomalies(results)

    Notification = apps.get_model("inventory", "Notification")
    User = get_user_model()
    emails_sent = 0

    notify = [a for a in created_objs if a.severity in ("MEDIUM", "HIGH")]
    if notify:
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
        email_lines_by_user = {}

        for a in list(best_by_item.values())[:25]:
            msg = (
                f"Demand anomaly ({a.severity}): {a.item.name} on {a.date:%d/%m/%Y} "
                f"(Qty {a.quantity}, Score {a.score:.2f})"
            )
            link = reverse("item_forecast", args=[a.item_id])
            for u in recipients:
                pref, _ = UserPreference.objects.get_or_create(user=u)
                if not pref.notify_anomalies:
                    continue
                if Notification.objects.filter(user=u, message=msg, url=link).exists():
                    continue
                Notification.objects.create(user=u, message=msg, url=link)
                if pref.email_notifications and a.severity == "HIGH":
                    email_lines_by_user.setdefault(u.id, {"user": u, "lines": []})
                    email_lines_by_user[u.id]["lines"].append(msg)

        for row in email_lines_by_user.values():
            ok = _send_grouped_alert_email(
                user=row["user"],
                subject="WareWolf: Critical demand anomaly alerts",
                intro="New critical demand anomalies were detected:",
                lines=row["lines"],
            )
            if ok:
                emails_sent += 1

    return {"detected": len(results), "created": created, "critical_emails_sent": emails_sent}


def sync_recommendation_notifications(*, limit=50):
    """
    Create/update DB-backed notification records from active recommendations.

    This keeps predictive alerts persistent and decoupled from request-time assembly.
    """
    Notification = apps.get_model("inventory", "Notification")
    User = get_user_model()

    recs = (
        Recommendation.objects
        .filter(status=Recommendation.STATUS_ACTIVE)
        .select_related("item")
        .order_by("priority", "-updated_at")[:limit]
    )

    recipients = User.objects.filter(groups__name__in=["Manager", "Admin"]).distinct()
    created_count = 0
    critical_emails_sent = 0
    now = timezone.now()
    cooldown_hours = max(int(getattr(settings, "FORECAST_NOTIFICATION_COOLDOWN_HOURS", 12)), 0)
    cooldown_since = now - datetime.timedelta(hours=cooldown_hours)

    active_urls = set()
    payloads = []
    for rec in recs:
        if rec.priority <= Recommendation.PRIORITY_HIGH:
            severity = "CRITICAL"
        elif rec.priority == Recommendation.PRIORITY_MEDIUM:
            severity = "WARNING"
        else:
            severity = "INFO"

        qty_text = str(rec.suggested_quantity) if rec.suggested_quantity is not None else "-"
        score_text = str(rec.stock_value) if rec.stock_value is not None else "-"
        url = f"{reverse('item_forecast', args=[rec.item_id])}?rec={rec.id}"
        msg = (
            f"Forecast alert ({severity}): {rec.item.name} — "
            f"Status: {rec.get_status_display()} | Qty: {qty_text} | Score: {score_text}"
        )
        active_urls.add(url)
        payloads.append((msg, url))

    for u in recipients:
        pref, _ = UserPreference.objects.get_or_create(user=u)
        if not pref.notify_anomalies:
            continue
        critical_lines = []

        # Retire stale forecast notifications when recommendation is no longer active.
        Notification.objects.filter(
            user=u,
            is_read=False,
            dismissed=False,
            message__startswith="Forecast alert (",
            url__contains="?rec=",
        ).exclude(url__in=active_urls).update(dismissed=True, dismissed_at=timezone.now())

        for msg, url in payloads:
            if Notification.objects.filter(user=u, message=msg, url=url).exists():
                continue
            # Cooldown guard: if a forecast notification for this recommendation URL
            # was recently created, skip creating another one even if message changed.
            if Notification.objects.filter(
                user=u,
                url=url,
                message__startswith="Forecast alert (",
                created_at__gte=cooldown_since,
            ).exists():
                continue
            Notification.objects.create(user=u, message=msg, url=url)
            created_count += 1
            if pref.email_notifications and "Forecast alert (CRITICAL)" in msg:
                critical_lines.append(msg)

        if critical_lines:
            ok = _send_grouped_alert_email(
                user=u,
                subject="WareWolf: Critical forecast alerts",
                intro="New critical forecast alerts require attention:",
                lines=critical_lines,
            )
            if ok:
                critical_emails_sent += 1

    return {
        "active_recommendations": len(payloads),
        "created_notifications": created_count,
        "critical_emails_sent": critical_emails_sent,
    }
