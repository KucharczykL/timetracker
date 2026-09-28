"""The icon picker: a dropdown grid of icon radios."""

import re
from pathlib import Path

import pytest

from common.components.icon_picker import IconChoice, IconPicker
from common.components.icons_generated import ICON_NODES
from common.components.platform_icons import (
    PLATFORM_ICONS,
    RETIRED_ICONS,
    canonical_icon,
)
from games.forms import PlatformForm
from games.models import Platform

pytestmark = pytest.mark.django_db

ICON_SNIPPETS = Path(__file__).resolve().parent.parent / "games/templates/icons"


def _picker(value: str, *, keep: bool = False) -> str:
    choices = [IconChoice(slug, label) for slug, label in PLATFORM_ICONS.items()]
    if keep:
        choices.insert(0, IconChoice("", "Keep: mixed"))
    return str(
        IconPicker(name="icon", label="Icon", choices=choices, value=value, id="icon")
    )


def test_every_platform_icon_is_a_named_snippet():
    assert set(PLATFORM_ICONS) <= set(ICON_NODES)
    assert all(label.strip() for label in PLATFORM_ICONS.values())


def test_a_listed_icon_names_itself():
    assert canonical_icon("steam") == "steam"


@pytest.mark.parametrize(("alias", "glyph"), RETIRED_ICONS.items())
def test_a_retired_alias_names_its_glyph(alias, glyph):
    assert canonical_icon(alias) == glyph


@pytest.mark.parametrize("slug", ["", "playstation-5", "pc"])
def test_any_other_slug_names_unspecified(slug):
    assert canonical_icon(slug) == "unspecified"


def test_a_retired_alias_is_no_listed_icon():
    assert not set(RETIRED_ICONS) & set(PLATFORM_ICONS)
    assert set(RETIRED_ICONS.values()) <= set(PLATFORM_ICONS)


def test_no_two_snippets_draw_one_glyph():
    glyphs = [
        re.sub(r"<title>.*?</title>|\s+", "", snippet.read_text())
        for snippet in ICON_SNIPPETS.glob("*.html")
    ]

    assert len(set(glyphs)) == len(glyphs)


def test_every_icon_is_a_radio_named_for_a_person():
    html = _picker("steam")

    assert html.count('type="radio"') == len(PLATFORM_ICONS)
    assert 'aria-label="Epic Games Store"' in html
    assert 'behavior="choice-grid"' in html
    assert 'aria-haspopup="dialog"' in html


def test_the_current_icon_is_checked_and_on_the_trigger():
    html = _picker("steam")

    checked = [tag for tag in re.findall(r"<input[^>]*>", html) if " checked" in tag]
    assert len(checked) == 1
    assert 'value="steam"' in checked[0]
    assert ">Steam<" in html


def test_the_keep_tile_leads_and_names_what_it_keeps():
    html = _picker("", keep=True)

    assert html.index('value=""') < html.index('value="unspecified"')
    assert ">Keep: mixed<" in html


def test_the_platform_form_starts_on_the_current_icon(owned_library):
    platform = Platform.objects.create(
        library=owned_library, name="Amiga", icon="physical"
    )

    html = str(PlatformForm(instance=platform, library=owned_library)["icon"])

    assert ">Physical media<" in html


def test_an_older_slug_stays_pickable(owned_library):
    platform = Platform.objects.create(
        library=owned_library, name="Amiga", icon="amiga"
    )
    form = PlatformForm(
        {"name": "Amiga", "icon": "amiga", "group": ""},
        instance=platform,
        library=owned_library,
    )

    assert form.is_valid(), form.errors


def test_the_platform_form_saves_a_picked_icon(owned_library):
    form = PlatformForm(
        {"name": "Amiga", "icon": "gog", "group": ""}, library=owned_library
    )

    assert form.is_valid(), form.errors
    assert form.save().icon == "gog"
