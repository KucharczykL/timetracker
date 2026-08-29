"""A status travels as a word from the widget to the projection."""

import uuid

import pytest
from django.urls import reverse
from django.utils import timezone

from games.models import Game, PlayerGame, PlayerGameStatus


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def test_every_word_is_settable():
    assert [value for value, _label in PlayerGameStatus.choices] == [
        PlayerGameStatus.UNPLAYED,
        PlayerGameStatus.PLAYED,
        PlayerGameStatus.COMPLETED,
        PlayerGameStatus.RETIRED,
        PlayerGameStatus.SHELVED,
        PlayerGameStatus.ABANDONED,
    ]


@pytest.mark.django_db(transaction=True)
def test_the_form_posts_a_word(logged_in, owned_library):
    response = logged_in.post(
        reverse("games:add_game"),
        {
            "name": "Outer Wilds",
            "status": "completed",
            "mastered": "on",
            "wikidata": "",
        },
    )

    assert response.status_code == 302
    game = Game.objects.get(name="Outer Wilds")
    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert row.status == PlayerGameStatus.COMPLETED
    assert row.mastered is True
    #: An add states the facts to the row, and to nothing else.
    game.refresh_from_db()
    assert (game.status, game.mastered) == ("u", False)


@pytest.mark.django_db(transaction=True)
def test_the_endpoint_takes_a_word(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    response = logged_in.patch(
        f"/api/games/{game.pk}/status",
        {"status": "played"},
        content_type="application/json",
    )

    assert response.status_code == 204
    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert row.status == PlayerGameStatus.PLAYED


@pytest.mark.django_db(transaction=True)
def test_the_endpoint_takes_the_word_no_letter_held(logged_in, owned_library):
    #: Shelved was refused for as long as a letter had to hold it.
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    response = logged_in.patch(
        f"/api/games/{game.pk}/status",
        {"status": "shelved"},
        content_type="application/json",
    )

    assert response.status_code == 204
    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert row.status == PlayerGameStatus.SHELVED


@pytest.mark.django_db(transaction=True)
@pytest.mark.untracked_games
def test_the_endpoint_refuses_a_game_no_row_names(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    response = logged_in.patch(
        f"/api/games/{game.pk}/status",
        {"status": "played"},
        content_type="application/json",
    )

    assert response.status_code == 404
    assert not PlayerGame.objects.filter(game=game).exists()


@pytest.mark.django_db(transaction=True)
def test_the_endpoint_takes_a_shared_game_this_library_tracks(logged_in, owned_library):
    shared = Game.objects.create(library=None, name="Shared")
    PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        game=shared,
        tracked_at=timezone.now(),
    )

    response = logged_in.patch(
        f"/api/games/{shared.pk}/status",
        {"status": "played"},
        content_type="application/json",
    )

    assert response.status_code == 204
    row = PlayerGame.objects.get(library=owned_library, game=shared)
    assert row.status == PlayerGameStatus.PLAYED


@pytest.mark.django_db(transaction=True)
def test_a_session_marks_an_unplayed_game_played(logged_in, owned_library):
    """_record_played reads the row, not the catalog column.

    The catalog says played and the projection says unplayed, so a
    view that still read the column would record nothing.
    """
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    Game.objects.filter(pk=game.pk).update(status="p")
    started = timezone.now().replace(microsecond=0)

    logged_in.post(
        reverse("games:add_session"),
        {
            "game": str(game.pk),
            "timestamp_start": started.strftime("%Y-%m-%d %H:%M"),
            "timestamp_start_timezone": "",
            "timestamp_end": "",
            "timestamp_end_timezone": "",
            "duration_manual": "",
            "note": "",
            "mark_as_played": "on",
        },
    )

    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert row.status == PlayerGameStatus.PLAYED
