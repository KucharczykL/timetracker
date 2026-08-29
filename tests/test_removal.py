"""Removing a record takes it out; it destroys nothing."""

from datetime import timedelta

import pytest
from django.utils import timezone

from games.models import Game, Session
from games.removal import remove, restore

pytestmark = pytest.mark.django_db


def make_game(library, name="Outer Wilds"):
    return Game.objects.create(library=library, name=name)


def test_removing_a_game_keeps_its_sessions(owned_library):
    game = make_game(owned_library)
    session = Session.objects.create(
        game=game,
        timestamp_start=timezone.now(),
        timestamp_end=timezone.now() + timedelta(hours=1),
    )

    remove(game)

    assert Session.objects.filter(pk=session.pk).exists()
    assert not Session.objects.for_library(owned_library).exists()


def test_restoring_a_game_brings_its_sessions_back(owned_library):
    game = make_game(owned_library)
    Session.objects.create(game=game, timestamp_start=timezone.now())
    remove(game)

    restore(game)

    assert Session.objects.for_library(owned_library).count() == 1


@pytest.mark.xfail(reason="Session.removed_at arrives in Task 5", strict=True)
def test_a_session_removed_by_itself_stays_removed(owned_library):
    game = make_game(owned_library)
    session = Session.objects.create(game=game, timestamp_start=timezone.now())
    remove(session)
    remove(game)

    restore(game)

    assert not Session.objects.for_library(owned_library).exists()
