from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0043_userpreference_accessibility"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreference",
            name="accessibility_mode",
            field=models.CharField(
                choices=[
                    ("auto", "Auto — adapt from device (motion & contrast)"),
                    ("basic", "Basic — standard layout"),
                    ("enhanced", "Enhanced — larger controls, clearer focus"),
                    ("assistive", "Assistive — simplified panels, maximum spacing"),
                ],
                default="basic",
                help_text="Adaptive UX tier; Auto uses prefers-reduced-motion and prefers-contrast.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="voice_feedback_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Allow speech synthesis for page content and alerts (browser Web Speech API).",
            ),
        ),
    ]
