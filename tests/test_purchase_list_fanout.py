"""One purchase, one row, whatever joined."""

import json

import pytest
from django.urls import reverse
from entries import record_entry
from graphs import default_graph
from purchases import record_purchase

from common.criteria import Modifier, StringCriterion
from games.filters import GameFilter, PurchaseFilter
from games.models import Game
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games


@pytest.fixture
def two_copies(owned_library):
    """One game, two copies, a purchase each."""
    graph = default_graph(Game(library=owned_library, name="Tunic"), owned_library)
    return [
        record_purchase(
            record_entry(owned_library, graph.release),
            purchased=TemporalValue.parse("2020-01-01"),
        )
        for _ in range(2)
    ]


def every_game_filter():
    """A `game_filter` matching the game."""
    return json.dumps(
        PurchaseFilter(
            game_filter=GameFilter(
                name=StringCriterion(modifier=Modifier.NOT_EQUALS, value="zzz")
            )
        ).to_json()
    )


@pytest.mark.django_db
@pytest.mark.parametrize("sort", ["purchased", "finished", "name", "amount"])
def test_each_purchase_answers_one_row(client, owned_user, two_copies, sort):
    client.force_login(owned_user)

    response = client.get(
        reverse("games:list_purchases"),
        {"filter": every_game_filter(), "sort": sort},
    )

    assert response.status_code == 200
    body = response.content.decode()
    for purchase in two_copies:
        assert body.count(f'id="purchase-row-{purchase.pk}"') == 1
