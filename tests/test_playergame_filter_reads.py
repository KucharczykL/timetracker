"""The status and mastery filters select on the projection.

The read-parity suite was the only cover for these two fields, and it
compared each against a catalog column. It is gone with the column, so
they are stated here on their own terms.
"""

from datetime import date

import pytest

from common.filter_execution import execute_filter
from games.filters import (
    GameFilter,
    PurchaseFilter,
    filter_query_context_for_library,
)
from games.models import Game, PlayerGame, PlayerGameStatus, Purchase


@pytest.fixture
def one_game_per_word(owned_library):
    """A game per status word, mastered on every other one."""
    games = {}
    for index, status in enumerate(PlayerGameStatus):
        game = Game.objects.create(library=owned_library, name=f"Game {index}")
        PlayerGame.objects.filter(library=owned_library, game=game).update(
            status=status, mastered=index % 2 == 0
        )
        games[status] = game
    return games


def matching_games(library, game_filter):
    return execute_filter(
        game_filter,
        Game.objects.tracked_by(library),
        filter_query_context_for_library(library),
    )


def matching_purchases(library, purchase_filter):
    return execute_filter(
        purchase_filter,
        Purchase.objects.for_library(library),
        filter_query_context_for_library(library),
    )


def a_purchase_of(library, game):
    purchase = Purchase.objects.create(
        library=library,
        name=f"Order of {game.name}",
        date_purchased=date(2026, 1, 1),
        price=0,
        price_currency="CZK",
    )
    purchase.games.add(game)
    return purchase


@pytest.mark.django_db
@pytest.mark.parametrize("status", list(PlayerGameStatus))
def test_a_word_selects_its_game(owned_library, one_game_per_word, status):
    #: Shelved among them: no letter states it, so the old suite
    #: had to leave the one word out that only a word can hold.
    matched = matching_games(owned_library, GameFilter.where(status=[status]))

    assert list(matched) == [one_game_per_word[status]]


@pytest.mark.django_db
def test_two_words_select_two_games(owned_library, one_game_per_word):
    matched = matching_games(
        owned_library,
        GameFilter.where(status=[PlayerGameStatus.SHELVED, PlayerGameStatus.COMPLETED]),
    )

    assert set(matched) == {
        one_game_per_word[PlayerGameStatus.SHELVED],
        one_game_per_word[PlayerGameStatus.COMPLETED],
    }


@pytest.mark.django_db
@pytest.mark.parametrize("mastered", [True, False])
def test_mastery_selects_the_rows_that_hold_it(
    owned_library, one_game_per_word, mastered
):
    matched = matching_games(owned_library, GameFilter.where(mastered=mastered))

    assert set(matched) == {
        row.game
        for row in PlayerGame.objects.filter(
            library=owned_library, mastered=mastered
        ).select_related("game")
    }


@pytest.mark.django_db
def test_a_purchase_is_found_by_the_word_its_game_holds(
    owned_library, one_game_per_word
):
    #: The purchase side reads the projection through a subquery.
    shelved = a_purchase_of(owned_library, one_game_per_word[PlayerGameStatus.SHELVED])
    a_purchase_of(owned_library, one_game_per_word[PlayerGameStatus.PLAYED])

    matched = matching_purchases(
        owned_library,
        PurchaseFilter(game_filter=GameFilter.where(status=[PlayerGameStatus.SHELVED])),
    )

    assert list(matched) == [shelved]


@pytest.mark.django_db
def test_a_negated_word_leaves_the_other_purchase(owned_library, one_game_per_word):
    a_purchase_of(owned_library, one_game_per_word[PlayerGameStatus.SHELVED])
    played = a_purchase_of(owned_library, one_game_per_word[PlayerGameStatus.PLAYED])

    matched = matching_purchases(
        owned_library,
        PurchaseFilter(
            NOT=[
                PurchaseFilter(
                    game_filter=GameFilter.where(status=[PlayerGameStatus.SHELVED])
                )
            ]
        ),
    )

    assert list(matched) == [played]
