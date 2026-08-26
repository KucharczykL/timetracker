"""The first projection: one row per catalog game a library tracks."""

import uuid

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from games.checks import check_projection_models
from games.models import Game, PlayerGame


@pytest.fixture
def tracked_game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def other_library(django_user_model, db):
    other = django_user_model.objects.create_user(username="other-owner", password="p")
    return other.library


def test_playergame_is_a_pure_projection():
    """Nothing in the row may come from anywhere but the event."""
    complaints = [
        str(message.id)
        for message in check_projection_models()
        if message.obj is PlayerGame
    ]

    assert complaints == []


def test_the_identity_has_no_default():
    #: UUIDv7Field mints one unless told not to. A projection key is the
    #: event's aggregate_id, so a rebuild reproduces the identity it had.
    assert PlayerGame().id is None


def test_a_library_tracks_one_game_once(owned_library, tracked_game):
    PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=tracked_game,
        tracked_at=timezone.now(),
    )

    #: The savepoint is not decoration: an IntegrityError marks the test's
    #: surrounding atomic block for rollback, and every later query in the
    #: test would raise TransactionManagementError instead of running.
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
