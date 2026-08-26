"""One row per catalog game a library tracks."""

import uuid

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from games.checks import check_projection_models
from games.commands.playergame import TrackGame
from games.events.append import lock_stream
from games.events.dispatch import dispatch
from games.events.playergame import PLAYERGAME_CREATED
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.references import capture_reference
from games.events.replay import replay
from games.models import Game, PlayerGame


@pytest.fixture
def tracked_game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def other_library(django_user_model, db):
    other = django_user_model.objects.create_user(username="other-owner", password="p")
    return other.library


def test_playergame_is_a_pure_projection():
    """Nothing in the row predates the event."""
    complaints = [
        str(message.id)
        for message in check_projection_models()
        if message.obj is PlayerGame
    ]

    assert complaints == []


def test_the_identity_has_no_default():
    #: The key is the event's aggregate_id.
    assert PlayerGame().id is None


def test_a_library_tracks_one_game_once(owned_library, tracked_game):
    PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=tracked_game,
        tracked_at=timezone.now(),
    )

    #: The savepoint keeps later queries runnable.
    with transaction.atomic(), pytest.raises(IntegrityError):
        PlayerGame.objects.create(
            id=uuid.uuid7(),
            library=owned_library,
            game=tracked_game,
            tracked_at=timezone.now(),
        )


def test_two_libraries_track_one_shared_game_independently(
    owned_library, other_library
):
    #: No library: the shared catalog.
    shared = Game.objects.create(name="Outer Wilds")

    for library in (owned_library, other_library):
        PlayerGame.objects.create(
            id=uuid.uuid7(),
            library=library,
            game=shared,
            tracked_at=timezone.now(),
        )

    assert PlayerGame.objects.filter(game=shared).count() == 2


def append_created(library, actor, game, *, identity, key="track"):
    """Append one creation event, as dispatch would."""
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            [
                PLAYERGAME_CREATED.new(
                    aggregate_id=identity,
                    payload={"game": capture_reference(game)},
                )
            ],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )


@pytest.mark.django_db(transaction=True)
def test_the_creation_event_writes_the_tracked_row(
    owned_user, owned_library, tracked_game
):
    identity = uuid.uuid7()

    appended = append_created(
        owned_library, owned_user, tracked_game, identity=identity
    )

    row = PlayerGame.objects.get(pk=identity)
    assert row.library_id == owned_library.pk
    assert row.game_id == tracked_game.pk
    assert row.tracked_at == appended.events[0].recorded_at


@pytest.mark.django_db(transaction=True)
def test_folding_the_stream_again_writes_no_second_row(
    owned_user, owned_library, tracked_game
):
    #: Keyed on the event's own identity.
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)

    replay(owned_library)

    assert PlayerGame.objects.count() == 1
    assert PlayerGame.objects.get().pk == identity


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_leaves_later_deletes_alone(owned_user, owned_library, tracked_game):
    #: The twin outlives the temp table it names.
    dispatch(
        TrackGame(game_id=tracked_game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    Game.objects.create(library=owned_library, name="Untracked").delete()

    assert not Game.objects.filter(name="Untracked").exists()


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_reproduces_the_tracked_rows(owned_user, owned_library, tracked_game):
    """Replay parity: the rebuild changes nothing."""
    dispatch(
        TrackGame(game_id=tracked_game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    before = PlayerGame.objects.get()

    checked = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    drift = [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in checked.tables
    ]
    assert drift == [(0, 0, 0)]

    rebuilt = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert rebuilt.swapped is True
    after = PlayerGame.objects.get()
    assert (after.pk, after.game_id, after.library_id, after.tracked_at) == (
        before.pk,
        before.game_id,
        before.library_id,
        before.tracked_at,
    )
