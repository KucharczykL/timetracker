"""Convert devices to events, then check replay."""

from django.db import migrations


def convert(apps, schema_editor):
    from games.backfill.device import convert_devices, require_replay_parity

    conversion = convert_devices()
    #: Replay only libraries the pass touched.
    require_replay_parity(conversion.libraries)


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0014_device_projection"),
    ]

    operations = [
        migrations.RunPython(convert, migrations.RunPython.noop, elidable=True),
    ]
