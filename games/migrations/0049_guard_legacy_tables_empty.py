from django.db import migrations


def guard_legacy_tables_empty(apps, schema_editor):
    """Refuse to proceed if either legacy table still holds a row.

    This is the load-bearing check between a stale deployment and silent
    data loss: the next two migrations drop these tables outright. A
    database reaching this migration must already have applied 0033, 0045
    and 0048 while they were still live (they are neutralized as of this
    branch) -- see the deployment precondition in the CLEAN-02 spec.
    """
    PlayEvent = apps.get_model("games", "PlayEvent")
    GameStatusChange = apps.get_model("games", "GameStatusChange")
    if PlayEvent.objects.exists():
        raise RuntimeError(
            "This database still holds PlayEvent rows. Deploy the release "
            "that runs 0033/0045/0048 against this database before this one."
        )
    if GameStatusChange.objects.exists():
        raise RuntimeError(
            "This database still holds GameStatusChange rows. Deploy the "
            "release that runs 0033/0045/0048 against this database before "
            "this one."
        )


class Migration(migrations.Migration):
    dependencies = [("games", "0048_playthrough_start_repair")]

    operations = [
        migrations.RunPython(guard_legacy_tables_empty, migrations.RunPython.noop),
    ]
