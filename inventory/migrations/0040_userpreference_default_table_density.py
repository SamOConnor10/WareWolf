from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0039_restrict_audit_model_permissions"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreference",
            name="default_table_density",
            field=models.CharField(
                choices=[("comfortable", "Comfortable"), ("compact", "Compact")],
                default="comfortable",
                max_length=12,
            ),
        ),
    ]
