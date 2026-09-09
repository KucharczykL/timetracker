"""A purchase can name no game, and the list still renders it."""

import pytest
from completed_runs import make_purchase
from django.urls import reverse

from games.models import Game
from games.removal import remove

pytestmark = pytest.mark.untracked_games


@pytest.fixture
def logged_client(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.mark.django_db
def test_the_list_renders_a_purchase_naming_no_game(logged_client, owned_library):
    purchase = make_purchase(owned_library, name="Bundle")

    response = logged_client.get(reverse("games:list_purchases"))

    assert response.status_code == 200
    assert f'id="purchase-row-{purchase.pk}"' in response.content.decode()


@pytest.mark.django_db
def test_a_nameless_purchase_naming_no_game_says_so(logged_client, owned_library):
    purchase = make_purchase(owned_library, name="")

    response = logged_client.get(reverse("games:list_purchases"))

    assert response.status_code == 200
    body = response.content.decode()
    assert f'id="purchase-row-{purchase.pk}"' in body
    assert "No games" in body


@pytest.mark.django_db
def test_removing_the_last_game_hides_the_purchase(logged_client, owned_library):
    """Not the path here: a purchase naming a removed game is not live.

    A purchase is live while any of its games is, or while it
    names none. Removing the only game satisfies neither, so the
    list leaves it out rather than rendering a gameless row.
    """
    purchase = make_purchase(owned_library, name="Bundle")
    game = Game.objects.create(library=owned_library, name="Only")
    purchase.games.add(game)

    remove(game)

    response = logged_client.get(reverse("games:list_purchases"))

    assert response.status_code == 200
    assert f'id="purchase-row-{purchase.pk}"' not in response.content.decode()
