from django.core.management.base import BaseCommand
from inventory.alerts_jobs import run_anomaly_scan_and_notify

class Command(BaseCommand):
    help = "Run demand anomaly detection (robust MAD z-score) and store results."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days-back",
            type=int,
            default=60,
            help="Days of sale history to load (default 60; lower is faster).",
        )
        parser.add_argument(
            "--recent-days",
            type=int,
            default=14,
            help="Only flag spikes in the last N calendar days (default 14). Use a larger value only if needed.",
        )
        parser.add_argument("--min-points", type=int, default=28)
        parser.add_argument("--z-low", type=float, default=3.5)
        parser.add_argument("--z-med", type=float, default=5.0)
        parser.add_argument("--z-high", type=float, default=6.5)
        parser.add_argument(
            "--max-days-per-item",
            type=int,
            default=1,
            dest="max_recent_days_per_item",
            help="Keep at most this many strongest anomaly day(s) per SKU in the recent window (default 1).",
        )
        parser.add_argument(
            "--sparse-abs-min-qty",
            type=int,
            default=45,
            dest="sparse_abs_min_qty",
            help="When history is very sparse (MAD=0), only flag if quantity is at least this much.",
        )

    def handle(self, *args, **opts):
        summary = run_anomaly_scan_and_notify(
            days_back=opts["days_back"],
            last_n_days_only=opts["recent_days"],
            min_points=opts["min_points"],
            z_thresh_low=opts["z_low"],
            z_thresh_med=opts["z_med"],
            z_thresh_high=opts["z_high"],
            max_recent_days_per_item=opts["max_recent_days_per_item"],
            sparse_abs_min_qty=opts["sparse_abs_min_qty"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Detected {summary['detected']} anomalies. "
            f"New records: {summary['created']}. "
            f"Obsolete rows removed: {summary['pruned']}. "
            f"Notifications cleared: {summary['notifications_pruned']}."
        ))