from django.core.management.base import BaseCommand
from inventory.ml.anomaly import detect_sales_anomalies, save_anomalies


class Command(BaseCommand):
    help = "Run demand anomaly detection (robust MAD z-score) and store results."

    def add_arguments(self, parser):
        parser.add_argument("--days-back", type=int, default=120)
        parser.add_argument("--recent-days", type=int, default=14)
        parser.add_argument("--min-points", type=int, default=21)
        parser.add_argument("--z-low", type=float, default=3.0)
        parser.add_argument("--z-med", type=float, default=4.0)
        parser.add_argument("--z-high", type=float, default=5.0)

    def handle(self, *args, **opts):
        results = detect_sales_anomalies(
            days_back=opts["days_back"],
            last_n_days_only=opts["recent_days"],
            min_points=opts["min_points"],
            z_thresh_low=opts["z_low"],
            z_thresh_med=opts["z_med"],
            z_thresh_high=opts["z_high"],
        )
        created = save_anomalies(results)
        self.stdout.write(self.style.SUCCESS(
            f"Detected {len(results)} anomalies. New records created: {created}."
        ))