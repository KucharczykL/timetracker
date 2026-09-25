"""Refund and split refuse what they cannot do."""

from datetime import date

import pytest
from django.urls import reverse

from common.returns import action_url
from games.models import Game, Purchase
from games.removal import remove

#: Transactional: a refund dispatches.
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def bundle(library, *names):
    purchase = Purchase.objects.create(
        price_currency="CZK",
        library=library,
        date_purchased=date(2024, 6, 1),
        type=Purchase.GAME,
        price=10,
    )
    purchase.games.set(
        [Game.objects.create(library=library, name=name) for name in names]
    )
    return purchase


def test_a_refunded_purchase_refuses_a_second_refund(logged_in, owned_library):
    purchase = bundle(owned_library, "Tunic")
    refunded_at = date(2024, 6, 2)
    Purchase.objects.filter(pk=purchase.pk).update(date_refunded=refunded_at)

    response = logged_in.post(reverse("games:refund_purchase", args=[purchase.id]))

    assert response.status_code == 409
    assert "This purchase is already refunded." in response.content.decode()
    purchase.refresh_from_db()
    assert purchase.date_refunded == refunded_at


def test_a_refund_says_so_on_the_page_it_lands_on(logged_in, owned_library):
    purchase = bundle(owned_library, "Tunic")

    response = logged_in.post(
        reverse("games:refund_purchase", args=[purchase.id]), follow=True
    )

    assert "Purchase refunded" in response.content.decode()


def test_a_split_says_so_on_the_page_it_lands_on(logged_in, owned_library):
    purchase = bundle(owned_library, "Tunic", "Outer Wilds")

    response = logged_in.post(
        reverse("games:split_purchase", args=[purchase.id]), follow=True
    )

    assert "Split into 2 purchases" in response.content.decode()


def test_a_split_never_returns_to_the_bundles_own_page(logged_in, owned_library):
    purchase = bundle(owned_library, "Tunic", "Outer Wilds")
    own_page = reverse("games:view_purchase", args=[purchase.id])

    response = logged_in.post(
        action_url("games:split_purchase", purchase.id, origin=own_page)
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("games:list_purchases")


def test_the_split_counts_what_it_splits(logged_in, owned_library):
    purchase = bundle(owned_library, "Tunic", "Outer Wilds", "Celeste")
    remove(purchase.games.get(name="Celeste"))
    own_page = reverse("games:view_purchase", args=[purchase.id])
    url = action_url("games:split_purchase", purchase.id, origin=own_page)

    assert "Creates 3 separate purchases" in logged_in.get(url).content.decode()
    response = logged_in.post(url)

    assert response["Location"] == reverse("games:list_purchases")
    parts = Purchase.objects.filter(library=owned_library, removed_at__isnull=True)
    assert parts.count() == 3
