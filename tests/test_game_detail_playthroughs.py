"""#1012: the Game detail section reads runs."""

import pytest
from django.urls import reverse
from django.utils import timezone

from games.models import Game, Playthrough

pytestmark = pytest.mark.django_db


@pytest.fixture
def game(owned_library) -> Game:
    #: The fixture states the run #679 gives.
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def detail(logged_in, game) -> str:
    return logged_in.get(game.get_absolute_url()).content.decode()


def section(logged_in, game) -> str:
    """The Playthrough section alone.

    The page renders `Unknown` elsewhere too.
    """
    body = detail(logged_in, game)
    start = body.index('id="playthroughs-container"')
    return body[start : body.index('id="history-container"', start)]


def test_the_section_renders_the_run_a_tracked_game_holds(logged_in, game):
    """No act yet, and still a row."""
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


def test_played_reads_zero_for_a_game_with_no_completion(logged_in, game):
    """The run tracking states is no time played."""
    body = detail(logged_in, game)

    assert '<span data-count="">0</span> times' in body


def test_played_counts_a_completion_whose_day_is_unknown(logged_in, game):
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(
        completion_recorded_at=timezone.now(), completed=None
    )

    body = detail(logged_in, game)

    assert '<span data-count="">1</span> times' in body


def test_played_skips_a_started_run_with_no_completion(logged_in, game):
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(start_recorded_at=timezone.now())

    body = detail(logged_in, game)

    assert '<span data-count="">0</span> times' in body


def test_the_removal_confirmation_counts_every_live_ordinary_run(logged_in, game):
    """The line says what leaves the screen."""
    body = logged_in.get(reverse("games:remove_game", args=[game.id])).content.decode()

    assert "1 playthrough(s)" in body


def test_the_section_links_its_actions_at_the_run(logged_in, game):
    run = Playthrough.objects.get(player_game__game=game)

    body = detail(logged_in, game)

    assert reverse("games:edit_playthrough", args=[run.pk]) in body
    assert reverse("games:remove_playthrough", args=[run.pk]) in body
