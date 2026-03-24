from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0033_supplier_client_extended_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userpreference",
            name="theme",
            field=models.CharField(
                choices=[("light", "Light"), ("dark", "Dark"), ("auto", "Auto")],
                default="light",
                max_length=10,
            ),
        ),
    ]
