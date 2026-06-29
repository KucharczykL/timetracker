import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("games", "0020_remove_purchase_related_purchase_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="filterpreset",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="filter_presets",
                to=settings.AUTH_USER_MODEL,
            ),
            # Non-null with no default is safe: the FilterPreset table has no rows
            # (feature still in-dev). preserve_default=False keeps the field
            # definition free of a phantom default.
            preserve_default=False,
        ),
    ]
