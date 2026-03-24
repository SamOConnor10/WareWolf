from django.core.management.base import BaseCommand
from inventory.alerts_jobs import run_anomaly_scan_and_notify

class Command(BaseCommand):
    help = "Run demand anomaly detection (robust MAD z-score) and store results."

    def add_arguments(self, parser):
        parser.add_argument("--days-back", type=int, default=120)
        parser.add_argument("--recent-days", type=int, default=180)
        parser.add_argument("--min-points", type=int, default=10)
        parser.add_argument("--z-low", type=float, default=2.5)
        parser.add_argument("--z-med", type=float, default=3.5)
        parser.add_argument("--z-high", type=float, default=4.5)

    def handle(self, *args, **opts):
        summary = run_anomaly_scan_and_notify(
            days_back=opts["days_back"],
            last_n_days_only=opts["recent_days"],
            min_points=opts["min_points"],
            z_thresh_low=opts["z_low"],
            z_thresh_med=opts["z_med"],
            z_thresh_high=opts["z_high"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Detected {summary['detected']} anomalies. New records created: {summary['created']}."
        ))