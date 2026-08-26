"""Tracking a game: the first command that is not a placeholder."""

import uuid

import pytest

from games.commands.playergame import TrackGame
from games.events.dispatch import CommandRejected, dispatch
from games.models import Game, LibraryEvent, PlayerGame
from games.retention import purging_library


@pytest.fixture
def other_user(django_user_model, db):
    return django_user_model.objects.create_user(username="other-owner", password="p")


@pytest.fixture
def other_library(other_user):
    return other_user.library


@pytest.fixture
def shared_game(db):
    #: No library: the shared catalog.
    return Game.objects.create(name="Outer Wilds")


@pytest.mark.django_db(transaction=True)
def test_tracking_a_game_records_it_and_projects_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    result = dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-outer-wilds",
    )

    assert result.replayed is False
    event = LibraryEvent.objects.get(library=owned_library)
    assert event.event_type == "library.playergame.created"
    assert event.payload["game"]["id"] == str(game.pk)

    row = PlayerGame.objects.get()
    assert (row.pk, row.game_id, row.library_id) == (
        event.aggregate_id,
        game.pk,
        owned_library.pk,
    )


@pytest.mark.django_db(transaction=True)
def test_two_libraries_track_one_shared_game_independently(
    owned_user, owned_library, other_user, other_library, shared_game
):
    for actor, library in ((owned_user, owned_library), (other_user, other_library)):
        dispatch(
            TrackGame(game_id=shared_game.pk),
            actor=actor,
            library=library,
            idempotency_key="track-shared",
        )

    assert PlayerGame.objects.filter(game=shared_game).count() == 2
    assert PlayerGame.objects.filter(library=owned_library).count() == 1
    #: One shared row, two private facts about it.
    assert Game.objects.filter(pk=shared_game.pk).count() == 1


@pytest.mark.django_db(transaction=True)
def test_another_librarys_private_game_cannot_be_tracked(
    owned_user, owned_library, other_library
):
    theirs = Game.objects.create(library=other_library, name="Their Secret")

    with pytest.raises(CommandRejected):
        dispatch(
            TrackGame(game_id=theirs.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-theirs",
        )

    assert not PlayerGame.objects.exists()
    assert not LibraryEvent.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_an_archived_game_cannot_be_tracked(owned_user, owned_library):
    from django.utils import timezone

    game = Game.objects.create(
        library=owned_library, name="Retired", archived_at=timezone.now()
    )

    with pytest.raises(CommandRejected):
        dispatch(
            TrackGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-retired",
        )


@pytest.mark.django_db(transaction=True)
def test_a_game_nobody_has_cannot_be_tracked(owned_user, owned_library):
    with pytest.raises(CommandRejected):
        dispatch(
            TrackGame(game_id=uuid.uuid7()),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-nothing",
        )


@pytest.mark.django_db(transaction=True)
def test_tracking_the_same_game_twice_is_refused(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-first",
    )

    #: A different key, so this is a second intent rather than a repeat.
    with pytest.raises(CommandRejected):
        dispatch(
            TrackGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-again",
        )

    assert PlayerGame.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_repeating_the_key_replays_rather_than_tracking_twice(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    command = TrackGame(game_id=game.pk)
    first = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="once"
    )
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="once"
    )

    assert second.replayed is True
    assert (second.first_sequence, second.last_sequence) == (
        first.first_sequence,
        first.last_sequence,
    )
    assert PlayerGame.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_purging_the_library_takes_the_tracked_row_with_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )

    #: RESTRICT refuses collateral, not a purge: the library, its games and its
    #: projections are collected in one cascade.
    with purging_library():
        owned_user.delete()

    assert not PlayerGame.objects.exists()
