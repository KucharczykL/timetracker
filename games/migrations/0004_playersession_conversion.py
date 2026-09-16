from django.db import migrations


class Migration(migrations.Migration):
    """The legacy session conversion ran here once."""

    dependencies = [("games", "0003_remove_game_playtime")]

    operations = [
        migrations.RunPython(
            migrations.RunPython.noop,
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
