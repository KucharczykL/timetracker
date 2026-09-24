"""State every device as the events that make it, then check the replay.

Live code, not the historical models: the pass appends through the
event store, which only the live classes know. Elidable, so a squash
drops it once every deployment has run it.
"""

from django.db import migrations


def convert(apps, schema_editor):
    from games.backfill.device import convert_devices, require_replay_parity

    conversion = convert_devices()
    #: A library the pass stated nothing for is not replayed, so a
    #: fresh database never runs today's replay against its schema.
    require_replay_parity(conversion.libraries)


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0014_device_projection"),
    ]

    operations = [
        migrations.RunPython(convert, migrations.RunPython.noop, elidable=True),
    ]
