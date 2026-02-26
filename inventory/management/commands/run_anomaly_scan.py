from django.core.management.base import BaseCommand
from inventory.ml.anomaly import detect_sales_anomalies, save_anomalies
from django.urls import reverse


class Command(BaseCommand):
    help = "Run demand anomaly detection (robust MAD z-score) and store results."

    def add_arguments(self, parser):
        parser.add_argument("--recent-days", type=int, default=180)
        parser.add_argument("--min-points", type=int, default=10)
        parser.add_argument("--z-low", type=float, default=2.5)
        parser.add_argument("--z-med", type=float, default=3.5)
        parser.add_argument("--z-high", type=float, default=4.5)

    def handle(self, *args, **opts):
        results = detect_sales_anomalies(
            days_back=opts["days_back"],
            last_n_days_only=opts["recent_days"],
            min_points=opts["min_points"],
            z_thresh_low=opts["z_low"],
            z_thresh_med=opts["z_med"],
            z_thresh_high=opts["z_high"],
        )
        created, created_objs = save_anomalies(results)

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

            for a in list(best_by_item.values())[:25]:
                msg = (
                    f"Demand anomaly ({a.severity}): {a.item.name} on {a.date:%d/%m/%Y} "
                    f"(Qty {a.quantity}, Score {a.score:.2f})"
                )
                for u in recipients:
                    link = reverse("anomaly_list")  # or whatever your anomalies page url name is
                    Notification.objects.create(user=u, message=msg, url=link)

        self.stdout.write(self.style.SUCCESS(
            f"Detected {len(results)} anomalies. New records created: {created}."
        ))