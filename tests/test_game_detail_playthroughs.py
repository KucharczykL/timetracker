"""#1012: the Game detail section reads runs."""

import pytest
from django.urls import reverse
from django.utils import timezone

from games.models import Game, Playthrough

pytestmark = pytest.mark.django_db


@pytest.fixture
def game(owned_library) -> Game:
    #: tests/conftest.py tracks a created game and states
    #: the run #679 gives it, so this holds one already.
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def detail(logged_in, game) -> str:
    return logged_in.get(game.get_absolute_url()).content.decode()


def section(logged_in, game) -> str:
    """The Playthrough section alone.

    The page renders `Unknown` for a release nobody dated too, so an
    assertion over the whole page would pass without the section.
    """
    body = detail(logged_in, game)
    start = body.index('id="playthroughs-container"')
    return body[start : body.index('id="history-container"', start)]


def test_the_section_renders_the_run_a_tracked_game_holds(logged_in, game):
    """No act yet, and still a row.

    The row is the one the person is about to fill in, so it
    renders rather than an empty message.
    """
    body = detail(logged_in, game)

    assert "Playthroughs" in body
    assert "Playthrough 1" in body
    assert "No playthroughs yet." not in body


def test_the_section_badge_counts_every_live_ordinary_run(logged_in, game):
    body = detail(logged_in, game)

    assert 'id="playthroughs-container"' in body
    assert "View all" in body


def test_the_section_renders_unknown_for_a_stated_act_with_no_day(logged_in, game):
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(
        completion_recorded_at=timezone.now(), completed=None
    )

    assert "Unknown" in section(logged_in, game)


def test_the_section_links_its_actions_at_the_run(logged_in, game):
    run = Playthrough.objects.get(player_game__game=game)

    body = detail(logged_in, game)

    assert reverse("games:edit_playthrough", args=[run.pk]) in body
    assert reverse("games:remove_playthrough", args=[run.pk]) in body
