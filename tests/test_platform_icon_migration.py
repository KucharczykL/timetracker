"""The migration naming each stored icon's glyph."""

import uuid
from importlib import import_module

import pytest
from django.apps import apps

from common.platform_icons import PLATFORM_ICONS
from games.batch_ledger import record
from games.models import BatchChange, Platform

pytestmark = pytest.mark.django_db

migration = import_module("games.migrations.0018_platform_icon_glyphs")


def _stored(library, name: str, icon: str) -> Platform:
    """A row holding what `clean()` would refuse."""
    platform = Platform.objects.create(library=library, name=name)
    Platform.objects.filter(pk=platform.pk).update(icon=icon)
    return platform


def _icon_after(platform: Platform) -> str:
    return Platform.objects.get(pk=platform.pk).icon


@pytest.mark.parametrize(
    ("stored", "named"),
    [
        ("nintendo-3ds", "nintendo"),
        ("physical-media", "physical"),
        ("ps1", "playstation"),
        ("", "unspecified"),
        ("playstation-5", "unspecified"),
        ("steam", "steam"),
    ],
)
def test_a_stored_icon_names_its_glyph(owned_library, stored, named):
    platform = _stored(owned_library, "Amiga", stored)

    migration.name_glyphs(apps, None)

    assert _icon_after(platform) == named


def test_a_ledger_row_names_its_glyphs(owned_library):
    platform = _stored(owned_library, "Amiga", "steam")
    batch = uuid.uuid7()
    for field, earlier, stated in [("icon", "ps1", "steam"), ("group", "ps1", "")]:
        record(
            owned_library,
            batch=batch,
            act="platform.edit",
            row=platform,
            field=field,
            earlier=earlier,
            stated=stated,
        )

    migration.name_glyphs(apps, None)

    changes = {
        change.field: (change.earlier, change.stated)
        for change in BatchChange.objects.filter(batch=batch)
    }
    assert changes == {"icon": ("playstation", "steam"), "group": ("ps1", "")}


def test_every_slug_it_writes_is_listed():
    written = migration.KNOWN_ICONS | set(migration.RETIRED_ICONS.values())

    assert written <= set(PLATFORM_ICONS)
