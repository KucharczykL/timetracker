from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0035_idempotency_record_optional_range"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="removed_at",
            field=models.DateTimeField(
                blank=True, default=None, editable=False, null=True
            ),
        ),
        migrations.AddField(
            model_name="playevent",
            name="removed_at",
            field=models.DateTimeField(
                blank=True, default=None, editable=False, null=True
            ),
        ),
        migrations.AddField(
            model_name="purchase",
            name="removed_at",
            field=models.DateTimeField(
                blank=True, default=None, editable=False, null=True
            ),
        ),
        migrations.AddField(
            model_name="filterpreset",
            name="removed_at",
            field=models.DateTimeField(
                blank=True, default=None, editable=False, null=True
            ),
        ),
        #: Without the condition a removed preset holds its own name.
        migrations.RemoveConstraint(
            model_name="filterpreset",
            name="unique_library_mode_name_preset",
        ),
        migrations.AddConstraint(
            model_name="filterpreset",
            constraint=models.UniqueConstraint(
                condition=models.Q(("removed_at__isnull", True)),
                fields=("library", "mode", "name"),
                name="unique_library_mode_name_preset",
            ),
        ),
    ]
