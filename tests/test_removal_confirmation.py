"""Confirm on GET, act on POST, return."""

from datetime import UTC, datetime

import pytest
from devices import create_device
from django.urls import reverse
from session_rows import session_row
from stated_runs import another_run

from common.returns import action_url
from games.models import Game, Platform, PlayerSession
from games.reads.player_sessions import library_sessions


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
    session_row(game, started_at=datetime(2024, 6, 1, 12, tzinfo=UTC))
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

    from games.models import Purchase

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
        "session": session_row(owned, started_at=datetime(2024, 6, 1, 12, tzinfo=UTC)),
        "purchase": purchase,
        "platform": Platform.objects.create(library=owned_library, name="Doomed"),
        "device": create_device(library=owned_library, name="Doomed"),
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
@pytest.mark.django_db(transaction=True)
def test_every_removal_confirms_first(
    logged_in, owned_library, removables, url_name, key, fallback
):
    """The row stays; the library hides it."""
    instance = removables[key]
    manager = type(instance).objects
    url = reverse(url_name, args=[instance.pk])
    assert logged_in.get(url).status_code == 200
    assert _visible(owned_library, instance).exists()
    response = logged_in.post(url)
    assert response["Location"] == reverse(fallback)
    assert manager.filter(pk=instance.pk).exists()
    assert not _visible(owned_library, instance).exists()


def _visible(library, instance):
    """The library's own scope for the row's model."""
    if isinstance(instance, PlayerSession):
        return library_sessions(library).filter(pk=instance.pk)
    return type(instance).objects.for_library(library).filter(pk=instance.pk)


@pytest.mark.django_db(transaction=True)
def test_removal_confirms_first_with_owning_game_fallback(
    logged_in, owned_user, removables
):
    """This one falls back to the game.

    A second run, so removal is not taking the game's
    last one, and the mark lands on the run itself.
    """
    owning_game = removables["game"]
    run = another_run(owned_user, owning_game, note="the named run")
    url = reverse("games:remove_playthrough", args=[run.pk])
    assert logged_in.get(url).status_code == 200

    response = logged_in.post(url)

    assert response["Location"] == owning_game.get_absolute_url()
    run.refresh_from_db()
    assert run.removed_at is not None


def _notices(response):
    from django.contrib.messages import get_messages

    return [
        (message.level_tag, message.message, message.extra_tags)
        for message in get_messages(response.wsgi_request)
    ]


@pytest.mark.parametrize(
    "url_name,key,restore_name,sentence",
    [
        (
            "games:remove_session",
            "session",
            "games:restore_session",
            "Session removed.",
        ),
        (
            "games:remove_purchase",
            "purchase",
            "games:restore_purchase",
            "Purchase removed.",
        ),
        (
            "games:remove_platform",
            "platform",
            "games:restore_platform",
            "Doomed removed from your library.",
        ),
        (
            "games:remove_device",
            "device",
            "games:restore_device",
            "Doomed removed from your library.",
        ),
    ],
)
@pytest.mark.django_db(transaction=True)
def test_every_removal_offers_undo(
    logged_in, removables, url_name, key, restore_name, sentence
):
    """The success message names the restore route the toast posts to."""
    import json

    instance = removables[key]

    response = logged_in.post(reverse(url_name, args=[instance.pk]))

    assert response.status_code == 302
    (notice,) = _notices(response)
    assert notice[:2] == ("success", sentence)
    assert json.loads(notice[2]) == {
        "action": {"label": "Undo", "url": reverse(restore_name, args=[instance.pk])}
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.untracked_games
def test_removing_a_game_offers_undo(logged_in, game):
    import json

    response = logged_in.post(reverse("games:remove_game", args=[game.id]))

    (notice,) = _notices(response)
    assert notice[:2] == ("success", "Test Game removed from your library.")
    assert json.loads(notice[2])["action"]["url"] == reverse(
        "games:restore_game", args=[game.id]
    )


@pytest.mark.django_db(transaction=True)
def test_removing_a_playthrough_offers_undo(logged_in, owned_user, removables):
    import json

    run = another_run(owned_user, removables["game"], note="the named run")

    response = logged_in.post(reverse("games:remove_playthrough", args=[run.pk]))

    (notice,) = _notices(response)
    assert notice[:2] == ("success", "Playthrough removed.")
    assert json.loads(notice[2])["action"]["url"] == reverse(
        "games:restore_playthrough", args=[run.pk]
    )


@pytest.mark.django_db(transaction=True)
def test_a_refused_removal_queues_no_notice(logged_in, owned_user, removables):
    """The only run of a tracked game: refused, and no Undo offered."""
    from games.reads.playthrough_runs import tracked_game

    tracked = tracked_game(owned_user.library, removables["game"])
    (run,) = tracked.playthroughs.all()

    response = logged_in.post(reverse("games:remove_playthrough", args=[run.pk]))

    assert response.status_code == 409
    assert _notices(response) == []
