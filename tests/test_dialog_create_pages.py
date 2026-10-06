"""Every form game picker offers a +."""

import re

import pytest
from django.test import Client
from django.urls import reverse
from tracked_games import create_tracked_game

from games.models import Playthrough

NEW_GAME_LINK = re.compile(r'<a href="([^"]*)"[^>]*data-form-dialog=""[^>]*>')


@pytest.fixture
def logged_in(owned_user) -> Client:
    client = Client()
    client.force_login(owned_user)
    return client


def _picker(html: str, name: str) -> str:
    """The `<search-select>` posting ``name``."""
    found = re.search(rf'<search-select[^>]*\bname="{name}"', html)
    assert found is not None, f"no {name} picker"
    return html[found.start() : html.index("</search-select>", found.start())]


def _offers_new_game(html: str, name: str) -> bool:
    if name == "parent":
        href, label = f"{reverse('games:add_game')}?kind=main", "New main game"
    else:
        href, label = reverse("games:add_game"), "New game"
    return any(
        link.group(1) == href and f'aria-label="{label}"' in link.group(0)
        for link in NEW_GAME_LINK.finditer(_picker(html, name))
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route", "field"),
    [
        ("add_session", "game"),
        ("add_session_for_game", "game"),
        ("add_to_library", "game"),
        ("add_game", "parent"),
        ("edit_game", "parent"),
        ("add_playthrough", "game"),
        ("add_playthrough_for_game", "game"),
        ("edit_playthrough", "game"),
    ],
)
def test_the_game_picker_offers_a_new_game(logged_in, owned_library, route, field):
    game = create_tracked_game(owned_library, "Outer Wilds")
    run = Playthrough.objects.get(library=owned_library, player_game__game=game)
    args = {
        "add_session_for_game": [game.pk],
        "edit_game": [game.pk],
        "add_playthrough_for_game": [game.pk],
        "edit_playthrough": [run.pk],
    }.get(route, [])

    html = logged_in.get(reverse(f"games:{route}", args=args)).content.decode()

    assert _offers_new_game(html, field)


@pytest.mark.django_db
def test_a_copy_of_a_named_game_has_no_game_picker(logged_in, owned_library):
    game = create_tracked_game(owned_library, "Outer Wilds")

    html = logged_in.get(
        reverse("games:add_library_entry", kwargs={"game_id": game.pk})
    ).content.decode()

    assert re.search(r'<search-select[^>]*\bname="game"', html) is None


def test_edit_session_shares_the_add_form():
    from games.forms import NEW_GAME, SessionForm

    assert SessionForm.base_fields["game"].widget.dialog_create is NEW_GAME
