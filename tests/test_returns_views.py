"""Mutating views honour a carried origin and fall back correctly."""

import pytest
from django.urls import reverse

from common.returns import action_url
from games.models import Game

GAME_FORM = {"name": "Renamed", "status": "u"}

#: Transactional, because a switched view dispatches a command and
#: run_in_transaction refuses to open a transaction inside the rolled-back one
#: pytest-django wraps a test in. The db fixture defers to transactional_db
#: when both are requested, so no fixture needs an edit.
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Test Game")


def test_edit_game_falls_back_to_the_games_list(logged_in, game):
    response = logged_in.post(reverse("games:edit_game", args=[game.id]), GAME_FORM)
    assert response["Location"] == reverse("games:list_games")


def test_edit_game_returns_to_the_carried_origin(logged_in, game):
    origin = f"{reverse('games:list_games')}?page=3"
    response = logged_in.post(
        action_url("games:edit_game", game.id, origin=origin), GAME_FORM
    )
    assert response["Location"] == origin


def test_a_chained_form_forwards_the_origin(logged_in, db):
    origin = f"{reverse('games:list_games')}?page=3"
    response = logged_in.post(
        action_url("games:add_game", origin=origin),
        {"name": "Chained", "status": "u", "submit_and_create_session": "1"},
    )
    created = Game.objects.get(name="Chained")
    assert response["Location"] == action_url(
        "games:add_session_for_game", game_id=created.id, origin=origin
    )


def test_the_origin_survives_the_login_redirect(client, owned_user, game):
    origin = f"{reverse('games:list_games')}?page=3"
    target = action_url("games:edit_game", game.id, origin=origin)
    anonymous = client.get(target)
    assert anonymous.status_code == 302
    login_url = anonymous["Location"]

    client.post(login_url, {"username": owned_user.username, "password": "p"})
    assert client.get(target).status_code == 200
    assert client.post(target, GAME_FORM)["Location"] == origin


@pytest.mark.parametrize(
    "url_name",
    [
        "games:drop_purchase",
        "games:finish_purchase",
        "games:view_game_start_session_from_session",
    ],
)
def test_the_get_mutating_routes_are_gone(url_name):
    from django.urls import NoReverseMatch

    with pytest.raises(NoReverseMatch):
        reverse(url_name, args=[1])
