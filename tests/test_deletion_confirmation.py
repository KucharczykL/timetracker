"""Deletes confirm on GET, act on POST, and return to where they started."""

from datetime import UTC, datetime

import pytest
from django.urls import reverse

from common.returns import action_url
from games.models import Game, Platform, PlayEvent, Session


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def game(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Test Game",
        platform=Platform.objects.create(name="PC"),
    )
    Session.objects.create(
        game=game, timestamp_start=datetime(2024, 6, 1, 12, tzinfo=UTC)
    )
    return game


def test_get_confirms_without_deleting(logged_in, game):
    response = logged_in.get(reverse("games:delete_game", args=[game.id]))
    assert response.status_code == 200
    assert "Test Game" in response.content.decode()
    assert Game.objects.filter(id=game.id).exists()


@pytest.mark.untracked_games
def test_post_acts_and_returns_to_the_origin(logged_in, game):
    origin = f"{reverse('games:list_games')}?page=2"
    response = logged_in.post(action_url("games:delete_game", game.id, origin=origin))
    assert response["Location"] == origin
    assert not Game.objects.for_library(game.library).filter(id=game.id).exists()


@pytest.mark.untracked_games
def test_post_drops_an_origin_naming_the_deleted_game(logged_in, game):
    origin = game.get_absolute_url()
    response = logged_in.post(action_url("games:delete_game", game.id, origin=origin))
    assert response["Location"] == reverse("games:list_games")


def test_the_confirmation_form_keeps_the_origin(logged_in, game):
    origin = f"{reverse('games:list_games')}?page=2"
    body = logged_in.get(
        action_url("games:delete_game", game.id, origin=origin)
    ).content.decode()
    assert "origin=%2Ftracker%2Fgame%2Flist%3Fpage%3D2" in body


@pytest.fixture
def deletables(owned_library):
    from datetime import date

    from games.models import Device, Purchase

    platform = Platform.objects.create(name="Console")
    owned = Game.objects.create(
        library=owned_library, name="Deletable", platform=platform
    )
    purchase = Purchase.objects.create(
        library=owned_library,
        price_currency="CZK",
        date_purchased=date(2024, 6, 1),
        type=Purchase.GAME,
    )
    purchase.games.set([owned])
    return {
        "game": owned,
        "session": Session.objects.create(
            game=owned, timestamp_start=datetime(2024, 6, 1, 12, tzinfo=UTC)
        ),
        "purchase": purchase,
        "platform": Platform.objects.create(library=owned_library, name="Doomed"),
        "device": Device.objects.create(library=owned_library, name="Doomed"),
        "playevent": PlayEvent.objects.create(game=owned),
    }


@pytest.mark.parametrize(
    "url_name,key,fallback",
    [
        ("games:delete_session", "session", "games:list_sessions"),
        ("games:delete_purchase", "purchase", "games:list_purchases"),
    ],
)
def test_every_delete_confirms_first(logged_in, deletables, url_name, key, fallback):
    instance = deletables[key]
    url = reverse(url_name, args=[instance.pk])
    assert logged_in.get(url).status_code == 200
    assert type(instance).objects.filter(pk=instance.pk).exists()
    response = logged_in.post(url)
    assert response["Location"] == reverse(fallback)
    assert not type(instance).objects.filter(pk=instance.pk).exists()


@pytest.mark.parametrize(
    "url_name,key,fallback",
    [
        ("games:delete_platform", "platform", "games:list_platforms"),
        ("games:delete_device", "device", "games:list_devices"),
    ],
)
def test_every_removal_confirms_first(
    logged_in, owned_library, deletables, url_name, key, fallback
):
    """The row stays; the library stops showing it."""
    instance = deletables[key]
    url = reverse(url_name, args=[instance.pk])
    assert logged_in.get(url).status_code == 200
    response = logged_in.post(url)
    assert response["Location"] == reverse(fallback)
    manager = type(instance).objects
    assert manager.filter(pk=instance.pk).exists()
    assert not manager.for_library(owned_library).filter(pk=instance.pk).exists()


@pytest.mark.parametrize(
    "url_name,key",
    [
        ("games:delete_playevent", "playevent"),
    ],
)
def test_every_delete_confirms_first_with_owning_game_fallback(
    logged_in, deletables, url_name, key
):
    """This one falls back to the game."""
    instance = deletables[key]
    owning_game = deletables["game"]
    url = reverse(url_name, args=[instance.pk])
    assert logged_in.get(url).status_code == 200
    assert type(instance).objects.filter(pk=instance.pk).exists()
    response = logged_in.post(url)
    assert response["Location"] == owning_game.get_absolute_url()
    assert not type(instance).objects.filter(pk=instance.pk).exists()
