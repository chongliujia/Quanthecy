from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agents", "0003_validation_diagnostics")]

    operations = [
        migrations.AddField(
            model_name="modelconfiguration",
            name="context_window_tokens",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="modelconfiguration",
            name="enable_thinking",
            field=models.BooleanField(default=False),
        ),
    ]
