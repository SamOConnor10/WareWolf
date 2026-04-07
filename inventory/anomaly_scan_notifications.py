"""In-app banner for anomaly scan results (works across processes; not LocMem cache)."""

from __future__ import annotations

from django.urls import reverse

from inventory.models import Notification

# Stored in Notification.message; excluded from bell dropdown / badge count.
ANOMALY_SCAN_RESULT_PREFIX = "[ANOMALY_SCAN_RESULT] "


def record_anomaly_scan_completion_for_user(user, summary: dict) -> None:
    """Replace any prior scan banner and create one sticky result notification."""
    Notification.objects.filter(
        user=user,
        message__startswith=ANOMALY_SCAN_RESULT_PREFIX,
    ).delete()
    body = (
        f"Anomaly scan complete: {summary['detected']} anomalies match the rules "
        f"({summary['created']} new, {summary['pruned']} obsolete rows removed, "
        f"{summary.get('notifications_pruned', 0)} notifications cleared)."
    )
    Notification.objects.create(
        user=user,
        message=f"{ANOMALY_SCAN_RESULT_PREFIX}{body}",
        url=reverse("dashboard") + "?open_anomalies=1",
    )
