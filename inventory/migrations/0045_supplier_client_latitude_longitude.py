from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0044_userpreference_smart_accessibility_voice"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplier",
            name="latitude",
            field=models.DecimalField(
                blank=True, decimal_places=6, help_text="GPS latitude (e.g. for maps)",
                max_digits=9, null=True,
            ),
        ),
        migrations.AddField(
            model_name="supplier",
            name="longitude",
            field=models.DecimalField(
                blank=True, decimal_places=6, help_text="GPS longitude (e.g. for maps)",
                max_digits=9, null=True,
            ),
        ),
        migrations.AddField(
            model_name="client",
            name="latitude",
            field=models.DecimalField(
                blank=True, decimal_places=6, help_text="GPS latitude (e.g. for maps)",
                max_digits=9, null=True,
            ),
        ),
        migrations.AddField(
            model_name="client",
            name="longitude",
            field=models.DecimalField(
                blank=True, decimal_places=6, help_text="GPS longitude (e.g. for maps)",
                max_digits=9, null=True,
            ),
        ),
    ]
