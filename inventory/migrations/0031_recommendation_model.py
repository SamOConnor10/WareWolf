from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0030_orderline"),
    ]

    operations = [
        migrations.CreateModel(
            name="Recommendation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "recommendation_type",
                    models.CharField(
                        choices=[
                            ("PURCHASE_DEMAND", "Purchase recommendation"),
                            ("SALES_OVERSTOCK", "Sales recommendation"),
                            ("DORMANT_STOCK", "Dormant stock"),
                            ("OVERSTOCK_ALERT", "Overstock alert"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ACTIVE", "Active"),
                            ("DISMISSED", "Dismissed"),
                            ("ACCEPTED", "Accepted"),
                            ("EXPIRED", "Expired"),
                        ],
                        default="ACTIVE",
                        max_length=16,
                    ),
                ),
                (
                    "priority",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (1, "Critical"),
                            (2, "High"),
                            (3, "Medium"),
                            (4, "Low"),
                        ],
                        default=3,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("reason", models.TextField(blank=True)),
                (
                    "suggested_quantity",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                ("target_date", models.DateField(blank=True, null=True)),
                (
                    "source_hash",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                (
                    "stock_value",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=12, null=True
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recommendations",
                        to="inventory.item",
                    ),
                ),
                (
                    "suggested_customer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="recommendations",
                        to="inventory.client",
                    ),
                ),
                (
                    "suggested_supplier",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="recommendations",
                        to="inventory.supplier",
                    ),
                ),
            ],
            options={
                "ordering": ["priority", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="recommendation",
            index=models.Index(
                fields=["recommendation_type", "status"],
                name="inventory_r_recomme_56b0c8_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="recommendation",
            index=models.Index(
                fields=["item", "recommendation_type", "status"],
                name="inventory_r_item_id_aa3b4d_idx",
            ),
        ),
    ]

