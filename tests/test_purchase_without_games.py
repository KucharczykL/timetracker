"""A purchase naming no game still renders."""

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
    """A purchase naming a removed game hides.

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


@pytest.mark.django_db
def test_a_game_with_no_name_prints_words_in_its_place(
    logged_client, owned_library, capture_games_logger
):
    """One cell degrades; the list still renders.

    `Game.name` is not blank, so this row is one nothing
    here wrote. The cell said nothing at all, and the
    component raised over it, which stopped the page.
    """
    purchase = make_purchase(owned_library, name="")
    game = Game.objects.create(library=owned_library, name="")
    purchase.games.add(game)

    with capture_games_logger() as caplog:
        response = logged_client.get(reverse("games:list_purchases"))

    assert response.status_code == 200
    assert "Untitled game" in response.content.decode()
    assert str(purchase.pk) in caplog.text
