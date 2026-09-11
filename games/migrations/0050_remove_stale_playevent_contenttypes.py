from django.db import migrations


def remove_stale_contenttypes(apps, schema_editor):
    """Django leaves a deleted model's ContentType row stale by design.

    Run after the DeleteModel migration, so models.py no longer defines
    either class and post_migrate's ContentType sync cannot recreate what
    this deletes. Permission rows cascade: Permission.content_type is
    on_delete=CASCADE.
    """
    ContentType = apps.get_model("contenttypes", "ContentType")
    ContentType.objects.filter(
        app_label="games", model__in=["playevent", "gamestatuschange"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0049_delete_playevent_gamestatuschange"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(remove_stale_contenttypes, migrations.RunPython.noop),
    ]
