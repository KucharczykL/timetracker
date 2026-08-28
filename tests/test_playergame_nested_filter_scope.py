"""A nested game filter resolves from the library's tracked games."""

from datetime import date

import pytest

from common.criteria import Modifier, StringCriterion
from common.filter_execution import execute_filter
from games.filters import (
    GameFilter,
    PurchaseFilter,
    filter_query_context_for_library,
)
from games.models import Game, Purchase


def a_purchase_of(library, game):
    purchase = Purchase.objects.create(
        library=library,
        name="Order",
        date_purchased=date(2026, 1, 1),
        price=0,
        price_currency="CZK",
    )
    purchase.games.add(game)
    return purchase


def named_outer_wilds():
    """A non-empty sub-filter, so the compiler builds the subquery."""
    return PurchaseFilter(
        game_filter=GameFilter(
            name=StringCriterion(value="Outer", modifier=Modifier.INCLUDES)
        )
    )


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_an_untracked_game_matches_no_nested_filter(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    a_purchase_of(owned_library, game)

    matched = execute_filter(
        named_outer_wilds(),
        Purchase.objects.for_library(owned_library),
        filter_query_context_for_library(owned_library),
    )

    assert not matched.exists()


@pytest.mark.django_db
def test_a_tracked_game_matches(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    purchase = a_purchase_of(owned_library, game)

    matched = execute_filter(
        named_outer_wilds(),
        Purchase.objects.for_library(owned_library),
        filter_query_context_for_library(owned_library),
    )

    assert list(matched) == [purchase]


@pytest.mark.django_db
def test_the_context_queryset_carries_the_annotation(owned_library):
    Game.objects.create(library=owned_library, name="Outer Wilds")

    queryset = filter_query_context_for_library(owned_library).queryset_for(Game)

    assert queryset.get().tracked_status is not None
