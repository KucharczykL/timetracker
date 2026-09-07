"""#687 renamed the play event.

A saved preset stores the old word.
"""

from django.db import migrations, models


def _rewrite(value, mapping):
    """Rename criterion keys at any depth."""
    if isinstance(value, dict):
        return {
            mapping.get(key, key): _rewrite(item, mapping)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite(item, mapping) for item in value]
    return value


#: The two criterion keys, forward.
_KEYS = {
    "playevent_count": "playthrough_count",
    "playevent_filter": "playthrough_filter",
}


def _rename(apps, keys, *, mode_from, mode_to):
    """Rewrite every preset naming the old word.

    A plain walk, not `.iterator()`: a server-side cursor
    is refused, and a preset table holds tens of rows.

    The count is printed, so an operator can tell a run
    that touched nothing from one against the wrong
    database, which looks the same otherwise.
    """
    preset_model = apps.get_model("games", "FilterPreset")
    presets = list(preset_model.objects.all())
    rewritten_count = 0
    for preset in presets:
        rewritten = _rewrite(preset.object_filter, keys)
        mode = mode_to if preset.mode == mode_from else preset.mode
        if (rewritten, mode) == (preset.object_filter, preset.mode):
            continue
        preset.object_filter = rewritten
        preset.mode = mode
        preset.save(update_fields=["object_filter", "mode"])
        rewritten_count += 1
    print(f"  presets rewritten: {rewritten_count}/{len(presets)}")


def rename_forward(apps, schema_editor):
    """playevents -> playthroughs, in mode and filter."""
    _rename(apps, _KEYS, mode_from="playevents", mode_to="playthroughs")


def rename_backward(apps, schema_editor):
    """The inverse, so a downgrade reads them."""
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
