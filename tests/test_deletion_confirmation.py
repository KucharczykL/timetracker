"""Deletes confirm on GET, act on POST, and return to where they started."""

from datetime import datetime, timezone

import pytest
from django.urls import reverse

from common.returns import action_url
from games.models import Game, Platform, Session


@pytest.fixture
def logged_in(client, django_user_model, db):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    return client


@pytest.fixture
def game(db):
    game = Game.objects.create(
        name="Test Game", platform=Platform.objects.create(name="PC")
    )
    Session.objects.create(
        game=game, timestamp_start=datetime(2024, 6, 1, 12, tzinfo=timezone.utc)
    )
    return game


def test_get_confirms_without_deleting(logged_in, game):
    response = logged_in.get(reverse("games:delete_game", args=[game.id]))
    assert response.status_code == 200
    assert "Test Game" in response.content.decode()
    assert Game.objects.filter(id=game.id).exists()


def test_post_deletes_and_returns_to_the_origin(logged_in, game):
    origin = f"{reverse('games:list_games')}?page=2"
    response = logged_in.post(action_url("games:delete_game", game.id, origin=origin))
    assert response["Location"] == origin
    assert not Game.objects.filter(id=game.id).exists()


def test_post_drops_an_origin_naming_the_deleted_game(logged_in, game):
    origin = reverse("games:view_game", args=[game.id])
    response = logged_in.post(action_url("games:delete_game", game.id, origin=origin))
    assert response["Location"] == reverse("games:list_games")


def test_the_confirmation_form_keeps_the_origin(logged_in, game):
    origin = f"{reverse('games:list_games')}?page=2"
    body = logged_in.get(
        action_url("games:delete_game", game.id, origin=origin)
    ).content.decode()
    assert "origin=%2Ftracker%2Fgame%2Flist%3Fpage%3D2" in body
