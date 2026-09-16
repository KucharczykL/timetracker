from django.db import migrations


class Migration(migrations.Migration):
    """The conversion of every legacy session row ran here once.

    Every deployment applied it; a database that has not is fresh and
    holds no row to convert. The operation stays so the history keeps
    its shape and a squash can elide it.
    """

    dependencies = [("games", "0003_remove_game_playtime")]

    operations = [
        migrations.RunPython(
            migrations.RunPython.noop,
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
