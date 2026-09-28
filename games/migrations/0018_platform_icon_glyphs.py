"""Stored platform icons name listed glyphs.

Slugs copied, not imported: the meaning stays fixed.
"""

from django.db import migrations, models

#: The icons listed when this was written.
KNOWN_ICONS = frozenset(
    {
        "unspecified",
        "battlenet",
        "bethesda",
        "eaorigin",
        "egs",
        "gog",
        "itchio",
        "microsoft",
        "nintendo",
        "nintendo-switch",
        "physical",
        "playstation",
        "ps3",
        "ps4",
        "ps5",
        "steam",
        "ubisoft",
        "xbox-gamepass",
        "yuzu",
    }
)

#: Slugs that copied a glyph, and that glyph.
RETIRED_ICONS = {
    "nintendo-3ds": "nintendo",
    "physical-media": "physical",
    "ps1": "playstation",
}


def _canonical(slug: object) -> object:
    """A known slug, its glyph, or Unspecified."""
    if slug in KNOWN_ICONS:
        return slug
    return RETIRED_ICONS.get(str(slug), "unspecified")


def name_glyphs(apps, schema_editor):
    Platform = apps.get_model("games", "Platform")
    BatchChange = apps.get_model("games", "BatchChange")
    held = Platform.objects.exclude(icon__in=KNOWN_ICONS)
    for icon in set(held.values_list("icon", flat=True)):
        held.filter(icon=icon).update(icon=_canonical(icon))
    ledger = BatchChange.objects.filter(model_label="games.platform", field="icon")
    for change in ledger:
        earlier, stated = _canonical(change.earlier), _canonical(change.stated)
        if (earlier, stated) != (change.earlier, change.stated):
            ledger.filter(pk=change.pk).update(earlier=earlier, stated=stated)


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0017_batch_change"),
    ]

    operations = [
        migrations.AlterField(
            model_name="platform",
            name="icon",
            field=models.SlugField(default="unspecified"),
        ),
        migrations.RunPython(name_glyphs, migrations.RunPython.noop),
    ]
