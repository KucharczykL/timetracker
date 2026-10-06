"""Add pages opened with a stated game."""

import re

import pytest
from calendar_days import library_noon
from django.test import Client
from django.urls import reverse
from tracked_games import create_tracked_game

from games.models import PlayerGameStatus, Playthrough

pytestmark = pytest.mark.django_db

ADD_PAGES = ["games:add_session", "games:add_playthrough", "games:add_to_library"]


@pytest.fixture
def logged_in(owned_user) -> Client:
    client = Client()
    client.force_login(owned_user)
    return client


def _page(client: Client, url_name: str, game=None) -> str:
    query = f"?game={game.pk}" if game is not None else ""
    return client.get(reverse(url_name) + query).content.decode()


def _game_picker(html: str) -> bool:
    return re.search(r'<search-select[^>]*\bname="game"', html) is not None


@pytest.mark.parametrize("url_name", ADD_PAGES)
def test_a_stated_game_is_a_row(logged_in, owned_library, url_name):
    game = create_tracked_game(owned_library, "Outer Wilds")

    html = _page(logged_in, url_name, game)

    assert not _game_picker(html)
    row = re.search(r'<div data-field-row="game">.*?</dd>', html, re.DOTALL)
    assert row and "Outer Wilds" in row.group(0)
    assert f'<input name="game" value="{game.pk}" type="hidden">' in html


@pytest.mark.parametrize("url_name", ADD_PAGES)
def test_no_stated_game_offers_the_picker(logged_in, url_name):
    assert _game_picker(_page(logged_in, url_name))


def test_add_session_seeds_the_sole_run(logged_in, owned_library):
    game = create_tracked_game(owned_library, "Outer Wilds")
    run = Playthrough.objects.get(library=owned_library, player_game__game=game)

    html = _page(logged_in, "games:add_session", game)

    picker = html[html.index('name="playthrough"') :]
    assert f'value="{run.pk}"' in picker[: picker.index("</search-select>")]


def test_add_playthrough_leaves_out_played_for_a_played_game(logged_in, owned_library):
    game = create_tracked_game(
        owned_library, "Outer Wilds", status=PlayerGameStatus.PLAYED
    )

    assert 'name="also_mark_played"' not in _page(
        logged_in, "games:add_playthrough", game
    )
    assert 'name="also_mark_played"' in _page(logged_in, "games:add_playthrough")


def test_add_to_library_cancels_to_the_stated_game(logged_in, owned_library):
    game = create_tracked_game(owned_library, "Outer Wilds")

    html = _page(logged_in, "games:add_to_library", game)

    assert f'href="{game.get_absolute_url()}"' in html


def test_add_to_library_on_a_shared_game_offers_no_release_create(
    logged_in, owned_library
):
    from games.models import Game

    shared = Game.objects.create(name="Celeste")

    html = _page(logged_in, "games:add_to_library", shared)

    release = html[html.index('name="release"') :]
    assert 'create="post"' not in release[: release.index(">")]


def _session_post(run, **overrides) -> dict[str, str]:
    return {
        "playthrough": str(run.pk),
        "started_at": "2026-03-05 12:00",
        "started_at_zone": "",
        "ended_at": "",
        "ended_at_zone": "",
        "duration": "",
        "note": "",
        **overrides,
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("body_game", ["omitted", "another"])
def test_add_session_records_on_the_stated_game(logged_in, owned_library, body_game):
    from games.models import PlayerSession

    stated = create_tracked_game(owned_library, "Outer Wilds")
    other = create_tracked_game(owned_library, "Hades")
    run = Playthrough.objects.get(library=owned_library, player_game__game=stated)
    extra = {"game": str(other.pk)} if body_game == "another" else {}

    response = logged_in.post(
        f"{reverse('games:add_session')}?game={stated.pk}",
        _session_post(run, **extra),
    )

    assert response.status_code == 302
    assert PlayerSession.objects.get().playthrough_id == run.pk


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("body_game", ["omitted", "another"])
def test_add_playthrough_records_on_the_stated_game(
    logged_in, owned_library, body_game
):
    stated = create_tracked_game(owned_library, "Outer Wilds")
    other = create_tracked_game(owned_library, "Hades")
    extra = {"game": str(other.pk)} if body_game == "another" else {}

    response = logged_in.post(
        f"{reverse('games:add_playthrough')}?game={stated.pk}",
        {"started": "2026-01-02", "ended": "", "note": "", **extra},
    )

    assert response.status_code == 302
    #: A recorded start adopts the placeholder run.
    assert Playthrough.objects.get(player_game__game=stated).start_recorded_at
    assert not Playthrough.objects.get(player_game__game=other).start_recorded_at


@pytest.mark.parametrize("url_name", ADD_PAGES)
@pytest.mark.parametrize("raw", ["not-a-uuid", "foreign"])
def test_a_bad_game_link_offers_the_picker(logged_in, django_user_model, url_name, raw):
    from games.models import Game

    if raw == "foreign":
        stranger = django_user_model.objects.create_user(username="stranger")
        raw = str(Game.objects.create(library=stranger.library, name="Theirs").pk)

    response = logged_in.get(f"{reverse(url_name)}?game={raw}")

    html = response.content.decode()
    assert response.status_code == 200
    assert _game_picker(html)
    assert "this form cannot use. Pick one." in html
    assert "Theirs" not in html


@pytest.mark.parametrize("url_name", ["games:edit_session", "games:edit_playthrough"])
def test_an_edit_page_ignores_a_stated_game(logged_in, owned_library, url_name):
    from session_rows import session_row

    game = create_tracked_game(owned_library, "Outer Wilds")
    other = create_tracked_game(owned_library, "Hades")
    run = Playthrough.objects.get(library=owned_library, player_game__game=game)
    target = (
        session_row(game, started_at=library_noon(owned_library)).pk
        if url_name == "games:edit_session"
        else run.pk
    )

    html = logged_in.get(
        f"{reverse(url_name, args=[target])}?game={other.pk}"
    ).content.decode()

    assert _game_picker(html)
    assert 'data-field-row="game"><dl' not in html
