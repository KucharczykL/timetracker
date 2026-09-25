"""The refund and split confirmations carry the origin to their POST and
return to it when done."""

from datetime import date

import pytest

from common.returns import action_url
from games.models import Game, Purchase

ORIGIN = "/tracker/purchase/list?page=2"

#: Transactional: a refund dispatches, and a dispatch cannot
#: nest in the transaction pytest-django rolls back. The db
#: fixture defers to transactional_db when both are asked for.
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def purchase(owned_library):
    game = Game.objects.create(library=owned_library, name="Bundled")
    other = Game.objects.create(library=owned_library, name="Also bundled")
    purchase = Purchase.objects.create(
        price_currency="CZK",
        library=owned_library,
        date_purchased=date(2024, 6, 1),
        type=Purchase.GAME,
        price=10,
    )
    purchase.games.set([game, other])
    return purchase


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


ENCODED_ORIGIN = "origin=%2Ftracker%2Fpurchase%2Flist%3Fpage%3D2"


@pytest.mark.parametrize("route", ["games:refund_purchase", "games:split_purchase"])
def test_the_confirmation_posts_with_the_origin(logged_in, purchase, route):
    body = logged_in.get(action_url(route, purchase.id, origin=ORIGIN)).content.decode()
    assert ENCODED_ORIGIN in body


@pytest.mark.parametrize("route", ["games:refund_purchase", "games:split_purchase"])
def test_the_act_redirects_to_the_origin(logged_in, purchase, route):
    response = logged_in.post(action_url(route, purchase.id, origin=ORIGIN))
    assert response.status_code == 302
    assert response["Location"] == ORIGIN
