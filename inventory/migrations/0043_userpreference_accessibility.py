from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0042_userpreference_font_size"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreference",
            name="reduce_motion",
            field=models.BooleanField(
                default=False,
                help_text="Minimise transitions and animations (also respects system reduced-motion).",
            ),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="underline_links",
            field=models.BooleanField(
                default=False,
                help_text="Underline body content links for easier spotting.",
            ),
        ),
    ]
