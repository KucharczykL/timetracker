"""Statistics read the row, not the column."""

import pytest
from django.contrib.auth import get_user_model
from entries import record_entry
from graphs import default_graph

from games.models import Game, PlayerGame, PlayerGameStatus
from games.views.stats_data import compute_stats
from timetracker.temporal import TemporalValue

YEAR = 2024


@pytest.fixture
def a_bought_game(db):
    library = get_user_model().objects.create_user(username="stats-cutover").library
    game = Game.objects.create(library=library, name="Outer Wilds")
    record_entry(
        library,
        default_graph(game, library).release,
        acquired=TemporalValue.parse(f"{YEAR}-01-05"),
    )
    return library, game


def test_a_completed_row_leaves_the_backlog(a_bought_game):
    library, game = a_bought_game
    assert compute_stats(library, YEAR)["purchased_unfinished_count"] == 1

    PlayerGame.objects.filter(library=library, game=game).update(
        status=PlayerGameStatus.COMPLETED
    )

    assert compute_stats(library, YEAR)["purchased_unfinished_count"] == 0


def test_an_abandoned_row_is_dropped(a_bought_game):
    library, game = a_bought_game
    PlayerGame.objects.filter(library=library, game=game).update(
        status=PlayerGameStatus.ABANDONED
    )

    assert compute_stats(library, YEAR)["dropped_count"] == 1


def test_a_retired_row_leaves_the_backlog(a_bought_game):
    """Retired means done, so not waiting."""
    library, game = a_bought_game
    PlayerGame.objects.filter(library=library, game=game).update(
        status=PlayerGameStatus.RETIRED
    )

    assert compute_stats(library, YEAR)["purchased_unfinished_count"] == 0


def test_a_retired_row_is_finished(a_bought_game):
    """It used to arrive nowhere."""
    library, game = a_bought_game
    assert compute_stats(library)["backlog_decrease_count"] == 0

    PlayerGame.objects.filter(library=library, game=game).update(
        status=PlayerGameStatus.RETIRED
    )

    assert compute_stats(library)["backlog_decrease_count"] == 1


def test_a_retired_row_is_not_dropped(a_bought_game):
    library, game = a_bought_game
    PlayerGame.objects.filter(library=library, game=game).update(
        status=PlayerGameStatus.RETIRED
    )

    assert compute_stats(library, YEAR)["dropped_count"] == 0
