from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0040_userpreference_default_table_density"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreference",
            name="clock_format",
            field=models.CharField(
                choices=[("12h", "12-hour (e.g. 1:30 PM)"), ("24h", "24-hour (e.g. 13:30)")],
                default="24h",
                max_length=4,
            ),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="confirm_destructive_actions",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="date_format_style",
            field=models.CharField(
                choices=[
                    ("dmy", "4 Jan 2026 (day month year)"),
                    ("mdy", "Jan 4, 2026 (month day year)"),
                    ("iso", "2026-01-04 (ISO)"),
                ],
                default="dmy",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="default_currency",
            field=models.CharField(
                choices=[
                    ("EUR", "EUR - Euro"),
                    ("USD", "USD - US Dollar"),
                    ("GBP", "GBP - British Pound"),
                ],
                default="EUR",
                max_length=3,
            ),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="default_landing",
            field=models.CharField(
                choices=[
                    ("dashboard", "Dashboard"),
                    ("item_list", "Stock"),
                    ("location_list", "Locations"),
                    ("order_list", "Orders"),
                    ("contacts_list", "Contacts"),
                    ("alerts_list", "Alerts"),
                    ("anomaly_list", "Anomalies"),
                    ("settings", "Settings"),
                ],
                default="dashboard",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="default_unit_of_measure",
            field=models.CharField(blank=True, default="pcs", max_length=20),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="keyboard_shortcuts_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="language_code",
            field=models.CharField(default="en", max_length=10),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="timezone_name",
            field=models.CharField(default="UTC", max_length=64),
        ),
    ]
