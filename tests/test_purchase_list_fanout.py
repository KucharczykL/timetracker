"""One purchase, one row, whatever joined."""

import json
from datetime import UTC, datetime

import pytest
from django.urls import reverse

from common.criteria import Modifier, StringCriterion
from games.filters import GameFilter, PurchaseFilter
from games.models import Game, Purchase


@pytest.fixture
def bundle(owned_library):
    """One purchase naming two games."""
    purchase = Purchase.objects.create(
        library=owned_library,
        name="Bundle",
        date_purchased=datetime(2020, 1, 1, tzinfo=UTC),
        price=0,
        price_currency="USD",
    )
    purchase.games.set(
        [
            Game.objects.create(library=owned_library, name="Early"),
            Game.objects.create(library=owned_library, name="Late"),
        ]
    )
    return purchase


def every_game_filter():
    """A `game_filter` matching both games."""
    return json.dumps(
        PurchaseFilter(
            game_filter=GameFilter(
                name=StringCriterion(modifier=Modifier.NOT_EQUALS, value="zzz")
            )
        ).to_json()
    )


@pytest.mark.django_db
@pytest.mark.parametrize("sort", ["purchased", "finished", "name"])
def test_a_game_filter_answers_one_row_per_purchase(client, owned_user, bundle, sort):
    client.force_login(owned_user)

    response = client.get(
        reverse("games:list_purchases"),
        {"filter": every_game_filter(), "sort": sort},
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert body.count(f'id="purchase-row-{bundle.pk}"') == 1
