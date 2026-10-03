"""The retired purchase conversion; refuses to run."""

from django.db import migrations


def convert(apps, schema_editor):
    """Reached only below the squash."""
    if apps.get_model("games", "LegacyPurchase").objects.exists():
        raise RuntimeError(
            "The purchase conversion is gone. A deployment migrates with "
            "the image before the squash first; a development database is "
            "dropped and rebuilt."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0030_purchasevaluation"),
        #: The revaluation request enqueues a task.
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [
        migrations.RunPython(convert, migrations.RunPython.noop, elidable=True),
    ]
