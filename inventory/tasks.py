from celery import shared_task

from .alerts_jobs import (
    run_anomaly_scan_and_notify,
    sync_recommendation_notifications,
)
from .recommendation_engine import recalculate_all_recommendations


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def run_anomaly_scan_task(self):
    result = run_anomaly_scan_and_notify()
    return result


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def refresh_recommendations_task(self):
    recalculate_all_recommendations()
    summary = sync_recommendation_notifications()
    return {"status": "ok", **summary}


