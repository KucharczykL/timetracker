"""Add game opened from "Add-on of"'s +."""

import re
from html import escape
from urllib.parse import urlencode

import pytest
from django.urls import reverse
from pickers import held

from games.models import ADDON_KINDS, Game, GameKind

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _add_game(query: dict[str, str]) -> str:
    return f"{reverse('games:add_game')}?{urlencode(query)}"


def _title(html: str) -> str:
    found = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    assert found
    return found.group(1).strip().removeprefix("Timetracker - ")


def _row(html: str, field: str) -> str:
    start = html.index(f'data-field-row="{field}"')
    end = html.find("data-field-row=", start + 1)
    return html[start : end if end != -1 else None]


def test_a_stated_kind_renders_a_row_and_no_parent(logged_in):
    html = logged_in.get(_add_game({"kind": "main"})).content.decode()

    assert "Main game</dd>" in _row(html, "kind")
    assert re.search(r'<search-select[^>]*\bname="kind"', html) is None
    assert 'data-field-row="parent"' not in html
    assert re.search(r'<search-select[^>]*\bname="parent"', html) is None
    assert "<game-addon" not in html


def test_the_title_names_the_addon(logged_in):
    html = logged_in.get(
        _add_game({"kind": "main", "addon": "Dawnguard"})
    ).content.decode()

    assert _title(html).startswith("Add the main game of Dawnguard")


def test_the_addon_text_is_cleaned(logged_in):
    html = logged_in.get(
        _add_game({"kind": "main", "addon": "  Dawn\nguard\t\x07 Pass  "})
    ).content.decode()

    assert _title(html).startswith("Add the main game of Dawn guard Pass")


def test_the_addon_text_is_cut(logged_in):
    html = logged_in.get(
        _add_game({"kind": "main", "addon": "x" * 400})
    ).content.decode()

    assert "x" * 255 in _title(html)
    assert "x" * 256 not in _title(html)


@pytest.mark.parametrize(
    "query",
    [{}, {"kind": "main"}, {"addon": "Dawnguard"}, {"kind": "dlc", "addon": "X"}],
    ids=["nothing", "no addon", "no kind", "addon kind"],
)
def test_otherwise_the_title_is_plain(logged_in, query):
    html = logged_in.get(_add_game(query)).content.decode()

    assert _title(html) == "Add New Game"


@pytest.mark.parametrize("kind", sorted(ADDON_KINDS))
def test_a_stated_addon_kind_keeps_the_parent_picker(logged_in, kind):
    html = logged_in.get(_add_game({"kind": kind})).content.decode()

    assert f"{GameKind(kind).label}</dd>" in _row(html, "kind")
    assert re.search(r'<search-select[^>]*\bname="parent"', html)


def test_the_addon_name_is_escaped(logged_in):
    html = logged_in.get(
        _add_game({"kind": "main", "addon": "<b>Pass</b>"})
    ).content.decode()

    assert "<b>Pass</b>" not in html
    assert escape("Add the main game of <b>Pass</b>") in html


def test_a_refused_post_keeps_the_stated_row_and_title(logged_in, game_post):
    response = logged_in.post(
        _add_game({"kind": "main", "addon": "Dawnguard"}), data=game_post("")
    )

    html = response.content.decode()
    assert response.status_code == 200
    assert "Main game</dd>" in _row(html, "kind")
    assert _title(html) == "Add the main game of Dawnguard"


def test_a_posted_kind_cannot_override_the_fact(logged_in, owned_user, game_post):
    base = Game.objects.create(library=owned_user.library, name="Base")

    response = logged_in.post(
        _add_game({"kind": "main", "addon": "Dawnguard"}),
        data=game_post("Skyrim", kind="dlc", parent=str(base.pk)),
    )

    assert response.status_code == 302
    saved = Game.objects.get(name="Skyrim")
    assert (saved.kind, saved.parent_id) == (GameKind.MAIN, None)


def test_edit_game_takes_no_facts(logged_in, owned_user):
    base = Game.objects.create(library=owned_user.library, name="Base")
    addon = Game.objects.create(library=owned_user.library, name="Addon")
    Game.objects.filter(pk=addon.pk).update(kind=GameKind.DLC, parent=base)

    html = logged_in.get(
        reverse("games:edit_game", args=[addon.pk]) + "?kind=main"
    ).content.decode()

    assert held(html, "kind") == "dlc"
