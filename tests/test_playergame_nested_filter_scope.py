"""A nested game filter resolves from the library's tracked games."""

import pytest
from entries import record_entry
from graphs import default_graph
from purchases import record_purchase

from common.criteria import Modifier, StringCriterion
from common.filter_execution import execute_filter
from games.filters import (
    GameFilter,
    PurchaseFilter,
    filter_query_context_for_library,
)
from games.models import Game
from games.reads.purchases import library_purchases


def a_purchase_of(library, game):
    graph = default_graph(game, library)
    return record_purchase(record_entry(library, graph.release), name="Order")


def named_outer_wilds():
    """A non-empty sub-filter, so the compiler builds the subquery."""
    return PurchaseFilter(
        game_filter=GameFilter(
            name=StringCriterion(value="Outer", modifier=Modifier.INCLUDES)
        )
    )


@pytest.mark.django_db
def test_a_tracked_game_matches(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    purchase = a_purchase_of(owned_library, game)

    matched = execute_filter(
        named_outer_wilds(),
        library_purchases(owned_library),
        filter_query_context_for_library(owned_library),
    )

    assert list(matched) == [purchase]


@pytest.mark.django_db
def test_the_context_queryset_carries_the_annotation(owned_library):
    Game.objects.create(library=owned_library, name="Outer Wilds")

    queryset = filter_query_context_for_library(owned_library).queryset_for(Game)

    assert queryset.get().tracked_status is not None
