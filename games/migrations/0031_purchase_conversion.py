"""Convert legacy purchases into copies and purchases."""

from django.db import migrations


def convert(apps, schema_editor):
    """Only a partial history reaches this."""
    raise RuntimeError(
        "The purchase conversion is gone; drop and rebuild this database."
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
