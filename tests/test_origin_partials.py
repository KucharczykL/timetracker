"""Htmx partials carry the origin too — the parity backstop cannot see them,
because the page they render into is not the page they were requested from."""

from datetime import date

import pytest

from common.returns import action_url
from games.models import Game, Purchase

ORIGIN = "/tracker/purchase/list?page=2"


@pytest.fixture
def purchase(db):
    game = Game.objects.create(name="Bundled")
    other = Game.objects.create(name="Also bundled")
    purchase = Purchase.objects.create(
        date_purchased=date(2024, 6, 1), type=Purchase.GAME, price=10
    )
    purchase.games.set([game, other])
    return purchase


@pytest.fixture
def logged_in(client, django_user_model, db):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    return client


def test_the_refund_modal_posts_with_the_origin(logged_in, purchase):
    body = logged_in.get(
        action_url("games:refund_purchase_confirmation", purchase.id, origin=ORIGIN)
    ).content.decode()
    assert "origin=%2Ftracker%2Fpurchase%2Flist%3Fpage%3D2" in body


def test_the_refunded_row_keeps_the_origin(logged_in, purchase):
    body = logged_in.post(
        action_url("games:refund_purchase", purchase.id, origin=ORIGIN)
    ).content.decode()
    assert "origin=%2Ftracker%2Fpurchase%2Flist%3Fpage%3D2" in body


def test_split_redirects_to_the_origin(logged_in, purchase):
    response = logged_in.post(
        action_url("games:split_purchase", purchase.id, origin=ORIGIN)
    )
    assert response["HX-Redirect"] == ORIGIN
