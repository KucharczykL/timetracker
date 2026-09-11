from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("games", "0047_playthrough_preset_completed")]

    operations = [
        migrations.RunPython(
            migrations.RunPython.noop,
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
