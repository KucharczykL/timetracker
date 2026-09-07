"""#687 renamed the play event, and a saved preset stores the old word."""

from django.db import migrations, models


def _rewrite(value, mapping):
    """Rename criterion keys at every depth of a stored filter."""
    if isinstance(value, dict):
        return {
            mapping.get(key, key): _rewrite(item, mapping)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite(item, mapping) for item in value]
    return value


#: The two criterion keys the rename moved, forward.
_KEYS = {
    "playevent_count": "playthrough_count",
    "playevent_filter": "playthrough_filter",
}


def _rename(apps, keys, *, mode_from, mode_to):
    """Rewrite every saved preset that names the old word.

    A plain queryset walk, not `.iterator()`: a server-side cursor is
    refused (`tests/test_iterator_guard.py`), and a preset table holds
    tens of rows.
    """
    preset_model = apps.get_model("games", "FilterPreset")
    for preset in preset_model.objects.all():
        rewritten = _rewrite(preset.object_filter, keys)
        mode = mode_to if preset.mode == mode_from else preset.mode
        if (rewritten, mode) == (preset.object_filter, preset.mode):
            continue
        preset.object_filter = rewritten
        preset.mode = mode
        preset.save(update_fields=["object_filter", "mode"])


def rename_forward(apps, schema_editor):
    """playevents -> playthroughs, in the mode and in the stored filter."""
    _rename(apps, _KEYS, mode_from="playevents", mode_to="playthroughs")


def rename_backward(apps, schema_editor):
    """The inverse, so a downgrade reads its own presets."""
    _rename(
        apps,
        {new: old for old, new in _KEYS.items()},
        mode_from="playthroughs",
        mode_to="playevents",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0045_playthrough_conversion_backfill"),
    ]

    operations = [
        migrations.AlterField(
            model_name="filterpreset",
            name="mode",
            field=models.CharField(
                choices=[
                    ("games", "Games"),
                    ("sessions", "Sessions"),
                    ("purchases", "Purchases"),
                    ("playthroughs", "Playthroughs"),
                    ("devices", "Devices"),
                    ("platforms", "Platforms"),
                ],
                default="games",
                max_length=50,
            ),
        ),
        migrations.RunPython(rename_forward, rename_backward),
    ]
