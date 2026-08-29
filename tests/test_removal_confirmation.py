"""Confirm on GET, act on POST, return."""

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


def test_get_confirms_without_removing(logged_in, game):
    response = logged_in.get(reverse("games:remove_game", args=[game.id]))
    assert response.status_code == 200
    assert "Test Game" in response.content.decode()
    assert Game.objects.for_library(game.library).filter(id=game.id).exists()


#: A dispatch opens its own transaction.
@pytest.mark.django_db(transaction=True)
@pytest.mark.untracked_games
def test_post_acts_and_returns_to_the_origin(logged_in, game):
    origin = f"{reverse('games:list_games')}?page=2"
    response = logged_in.post(action_url("games:remove_game", game.id, origin=origin))
    assert response["Location"] == origin
    assert not Game.objects.for_library(game.library).filter(id=game.id).exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.untracked_games
def test_post_drops_an_origin_naming_the_removed_game(logged_in, game):
    origin = game.get_absolute_url()
    response = logged_in.post(action_url("games:remove_game", game.id, origin=origin))
    assert response["Location"] == reverse("games:list_games")


def test_the_confirmation_form_keeps_the_origin(logged_in, game):
    origin = f"{reverse('games:list_games')}?page=2"
    body = logged_in.get(
        action_url("games:remove_game", game.id, origin=origin)
    ).content.decode()
    assert "origin=%2Ftracker%2Fgame%2Flist%3Fpage%3D2" in body


@pytest.fixture
def removables(owned_library):
    from datetime import date

    from games.models import Device, Purchase

    platform = Platform.objects.create(name="Console")
    owned = Game.objects.create(
        library=owned_library, name="Removable", platform=platform
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
        ("games:remove_session", "session", "games:list_sessions"),
        ("games:remove_purchase", "purchase", "games:list_purchases"),
        ("games:remove_platform", "platform", "games:list_platforms"),
        ("games:remove_device", "device", "games:list_devices"),
    ],
)
def test_every_removal_confirms_first(
    logged_in, owned_library, removables, url_name, key, fallback
):
    """The row stays; the library hides it."""
    instance = removables[key]
    manager = type(instance).objects
    url = reverse(url_name, args=[instance.pk])
    assert logged_in.get(url).status_code == 200
    assert manager.for_library(owned_library).filter(pk=instance.pk).exists()
    response = logged_in.post(url)
    assert response["Location"] == reverse(fallback)
    assert manager.filter(pk=instance.pk).exists()
    assert not manager.for_library(owned_library).filter(pk=instance.pk).exists()


def test_removal_confirms_first_with_owning_game_fallback(
    logged_in, owned_library, removables
):
    """This one falls back to the game."""
    instance = removables["playevent"]
    owning_game = removables["game"]
    visible = PlayEvent.objects.for_library(owned_library)
    url = reverse("games:remove_playevent", args=[instance.pk])
    assert logged_in.get(url).status_code == 200
    assert visible.filter(pk=instance.pk).exists()
    response = logged_in.post(url)
    assert response["Location"] == owning_game.get_absolute_url()
    assert PlayEvent.objects.filter(pk=instance.pk).exists()
    assert not visible.filter(pk=instance.pk).exists()
