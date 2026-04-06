from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0041_userpreference_regional_and_behaviour"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreference",
            name="font_size",
            field=models.CharField(
                choices=[
                    ("small", "Small"),
                    ("medium", "Medium"),
                    ("large", "Large"),
                ],
                default="medium",
                max_length=10,
            ),
        ),
    ]
