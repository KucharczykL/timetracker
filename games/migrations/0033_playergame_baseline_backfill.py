from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("games", "0032_playergame_removed_at")]

    operations = [
        migrations.RunPython(
            migrations.RunPython.noop,
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
