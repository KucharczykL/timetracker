"""Statistics read the row, not the column."""

from datetime import UTC, datetime

import pytest
from django.contrib.auth import get_user_model

from games.models import Game, PlayerGame, PlayerGameStatus, Purchase
from games.views.stats_data import compute_stats

YEAR = 2024


@pytest.fixture
def a_bought_game(db):
    library = get_user_model().objects.create_user(username="stats-cutover").library
    game = Game.objects.create(library=library, name="Outer Wilds")
    purchase = Purchase.objects.create(
        library=library,
        price_currency="CZK",
        type=Purchase.GAME,
        date_purchased=datetime(YEAR, 1, 5, tzinfo=UTC),
    )
    purchase.games.set([game])
    return library, game


def test_a_completed_row_leaves_the_backlog(a_bought_game):
    library, game = a_bought_game
    assert compute_stats(library, YEAR)["purchased_unfinished_count"] == 1

    PlayerGame.objects.filter(library=library, game=game).update(
        status=PlayerGameStatus.COMPLETED
    )

    assert compute_stats(library, YEAR)["purchased_unfinished_count"] == 0


def test_a_completed_column_the_row_denies_counts_for_nothing(a_bought_game):
    library, game = a_bought_game
    #: The only test that writes the column.
    Game.objects.filter(pk=game.pk).update(status="f")

    assert compute_stats(library, YEAR)["purchased_unfinished_count"] == 1


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
