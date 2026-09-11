from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("games", "0044_playthrough_endpoint_columns")]

    operations = [
        migrations.RunPython(
            migrations.RunPython.noop,
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
