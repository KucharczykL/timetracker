"""What the session readers answer."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from session_rows import timed_row, tracked_run

from games.filters import SESSION_GAME, PlayerSessionFilter
from games.models import Game
from games.reads.player_sessions import library_sessions, sole_game

pytestmark = pytest.mark.django_db

ZONEINFO = ZoneInfo(settings.TIME_ZONE)


def _played(library, name, count=1):
    """A game with that many sessions on its run."""
    game = Game.objects.create(library=library, name=name, sort_name=name)
    run = tracked_run(library, game)
    for hour in range(count):
        moment = datetime(2025, 6, 1, 8 + hour, tzinfo=ZONEINFO)
        timed_row(run, moment, moment + timedelta(minutes=30))
    return game


def test_an_empty_list_names_no_game(owned_library):
    assert sole_game(library_sessions(owned_library)) is None


def test_two_games_name_no_game(owned_library):
    _played(owned_library, "Anodyne")
    _played(owned_library, "Outer Wilds")

    assert sole_game(library_sessions(owned_library)) is None


def test_one_game_with_several_sessions_names_itself(owned_library):
    """The answer is the game, not the row count."""
    game = _played(owned_library, "Outer Wilds", count=3)

    assert sole_game(library_sessions(owned_library)) == game.pk


def test_a_filter_that_narrows_to_one_game_names_it(owned_library):
    wanted = _played(owned_library, "Outer Wilds", count=2)
    _played(owned_library, "Anodyne", count=2)

    narrowed = library_sessions(owned_library).filter(**{SESSION_GAME: wanted})

    assert sole_game(narrowed) == wanted.pk


def test_a_one_game_library_names_it_with_no_filter_at_all(owned_library):
    game = _played(owned_library, "Outer Wilds", count=2)

    assert sole_game(library_sessions(owned_library)) == game.pk


def test_an_ordered_queryset_still_names_one_game(owned_library):
    """Ordering joins the DISTINCT list; the read clears it."""
    game = _played(owned_library, "Outer Wilds", count=3)

    ordered = library_sessions(owned_library).order_by("sort_instant", "id")

    assert sole_game(ordered) == game.pk


def test_the_answer_is_one_query(owned_library, django_assert_num_queries):
    _played(owned_library, "Outer Wilds", count=5)

    with django_assert_num_queries(1):
        sole_game(library_sessions(owned_library))


def test_the_filters_own_game_criterion_narrows_the_same_way(owned_library):
    wanted = _played(owned_library, "Outer Wilds")
    _played(owned_library, "Anodyne")

    narrowed = library_sessions(owned_library).filter(
        PlayerSessionFilter.where(game=[wanted.id]).to_q()
    )

    assert sole_game(narrowed) == wanted.pk
