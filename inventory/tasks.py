from celery import shared_task
from django.contrib.auth import get_user_model

from .alerts_jobs import (
    run_anomaly_scan_and_notify,
    sync_recommendation_notifications,
)
from .anomaly_scan_notifications import record_anomaly_scan_completion_for_user
from .models import Activity
from .recommendation_engine import recalculate_all_recommendations


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def run_anomaly_scan_task(self, user_id=None):
    result = run_anomaly_scan_and_notify()
    if user_id:
        User = get_user_model()
        user = User.objects.filter(pk=user_id).first()
        if user:
            record_anomaly_scan_completion_for_user(user, result)
            Activity.objects.create(
                user=user,
                kind=Activity.KIND_ANOMALY_SCAN,
                message=(
                    f"Anomaly scan completed: {result['detected']} match rules "
                    f"({result['created']} new, {result['pruned']} obsolete rows removed)"
                ),
            )
    else:
        Activity.objects.create(
            user=None,
            kind=Activity.KIND_ANOMALY_SCAN,
            message=(
                f"Scheduled anomaly scan completed: {result['detected']} match rules "
                f"({result['created']} new)."
            ),
        )
    return result


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def refresh_recommendations_task(self):
    recalculate_all_recommendations()
    summary = sync_recommendation_notifications()
    return {"status": "ok", **summary}


