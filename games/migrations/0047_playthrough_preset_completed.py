"""#1013 renamed the endpoint.

A saved preset stores the old word, in a criterion and in
a sort. `ended` is a common word, so the walk is scoped to
the two places a run's filter can sit.
"""

from django.db import migrations

#: The one key, forward.
_KEYS = {"ended": "completed"}

#: The keys a nested filter travels under.
_OPERATORS = ("AND", "OR", "NOT")


def _rename_run_keys(node, mapping):
    """Rewrite a run filter and operator children.

    A blob naming both spellings keeps the current one, as
    `OperatorFilter.rename_legacy_keys` does: the old key
    beside it is a stale copy, and renaming over the top of
    the current one would drop the criterion the person
    last saved.
    """
    if not isinstance(node, dict):
        return node
    renamed = {key: value for key, value in node.items() if key not in mapping}
    for old, new in mapping.items():
        if old in node and new not in node:
            renamed[new] = node[old]
    for operator in _OPERATORS:
        children = renamed.get(operator)
        if isinstance(children, list):
            renamed[operator] = [_rename_run_keys(child, mapping) for child in children]
    return renamed


def _rename_in_games(node, mapping):
    """Reach a games filter's run subtrees only."""
    if not isinstance(node, dict):
        return node
    result = dict(node)
    subtree = result.get("playthrough_filter")
    if isinstance(subtree, dict):
        result["playthrough_filter"] = _rename_run_keys(subtree, mapping)
    for operator in _OPERATORS:
        children = result.get(operator)
        if isinstance(children, list):
            result[operator] = [_rename_in_games(child, mapping) for child in children]
    return result


def _rename_sort(find_filter, mapping):
    """Rewrite the sort tokens, keeping each sign.

    `renamed_fields` is read by `from_json` over the criterion
    blob alone, while a sort travels here and is matched against
    the sort map. A preset nobody rewrites loads with an
    unknown-sort toast every time and falls back to the default.
    """
    if not isinstance(find_filter, dict):
        return find_filter
    sort = find_filter.get("sort")
    if not isinstance(sort, str) or not sort:
        return find_filter
    tokens = []
    for token in sort.split(","):
        descending = token.startswith("-")
        key = token[1:] if descending else token
        tokens.append(("-" if descending else "") + mapping.get(key, key))
    return {**find_filter, "sort": ",".join(tokens)}


def _rename(apps, mapping):
    """Rewrite every preset naming the old word.

    The count is printed, so an operator can tell a run
    that touched nothing from one against the wrong
    database.
    """
    preset_model = apps.get_model("games", "FilterPreset")
    presets = list(preset_model.objects.all())
    rewritten_count = 0
    for preset in presets:
        if preset.mode == "playthroughs":
            object_filter = _rename_run_keys(preset.object_filter, mapping)
            find_filter = _rename_sort(preset.find_filter, mapping)
        elif preset.mode == "games":
            object_filter = _rename_in_games(preset.object_filter, mapping)
            find_filter = preset.find_filter
        else:
            continue
        if (object_filter, find_filter) == (preset.object_filter, preset.find_filter):
            continue
        preset.object_filter = object_filter
        preset.find_filter = find_filter
        preset.save(update_fields=["object_filter", "find_filter"])
        rewritten_count += 1
    print(f"  presets rewritten: {rewritten_count}/{len(presets)}")


def rename_forward(apps, schema_editor):
    """ended -> completed, in criterion and sort."""
    _rename(apps, _KEYS)


def rename_backward(apps, schema_editor):
    """The inverse, so a downgrade reads them."""
    _rename(apps, {new: old for old, new in _KEYS.items()})


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0046_playthrough_preset_mode"),
    ]

    operations = [
        migrations.RunPython(rename_forward, rename_backward),
    ]
