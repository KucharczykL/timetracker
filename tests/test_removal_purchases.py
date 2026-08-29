"""A purchase lives while one of its games lives."""

from datetime import date

import pytest

from games.models import Game, Purchase
from games.removal import remove, restore

pytestmark = pytest.mark.django_db


def make_game(library, name="Outer Wilds"):
    return Game.objects.create(library=library, name=name)


def make_purchase(library, games):
    purchase = Purchase.objects.create(
        library=library,
        price_currency="CZK",
        date_purchased=date(2024, 6, 1),
        type=Purchase.GAME,
    )
    purchase.games.set(games)
    return purchase


def test_a_bundle_stays_while_one_game_stays(owned_library):
    kept, gone = make_game(owned_library), make_game(owned_library, name="Other")
    purchase = make_purchase(owned_library, games=[kept, gone])

    remove(gone)

    assert Purchase.objects.for_library(owned_library).count() == 1
    purchase.refresh_from_db()
    assert purchase.num_purchases == 1


def test_a_purchase_leaves_with_its_last_game(owned_library):
    game = make_game(owned_library)
    purchase = make_purchase(owned_library, games=[game])

    remove(game)

    assert not Purchase.objects.for_library(owned_library).exists()
    assert Purchase.objects.filter(pk=purchase.pk).exists()


def test_restoring_the_game_brings_the_purchase_back(owned_library):
    game = make_game(owned_library)
    make_purchase(owned_library, games=[game])
    remove(game)

    restore(game)

    assert Purchase.objects.for_library(owned_library).count() == 1
