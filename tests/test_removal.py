"""Removal takes a record out, destroying nothing."""

from datetime import timedelta

import pytest
from django.utils import timezone

from games.backfill.playthrough import convert_library
from games.models import Game, PlayEvent, Session
from games.reads.playthrough_provenance import run_for_row
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


def test_a_session_removed_by_itself_stays_removed(owned_library):
    game = make_game(owned_library)
    session = Session.objects.create(game=game, timestamp_start=timezone.now())
    remove(session)
    remove(game)

    restore(game)

    assert not Session.objects.for_library(owned_library).exists()


def test_removing_a_session_drops_the_playtime(owned_library):
    game = make_game(owned_library)
    started = timezone.now()
    Session.objects.create(
        game=game, timestamp_start=started, timestamp_end=started + timedelta(hours=2)
    )
    game.refresh_from_db()
    assert game.playtime == timedelta(hours=2)

    remove(Session.objects.get(game=game))

    game.refresh_from_db()
    assert game.playtime == timedelta(0)


@pytest.mark.django_db(transaction=True)
def test_the_api_removes_a_playthrough_rather_than_destroying_it(client, owned_user):
    """DELETE is the transport's word, not ours.

    #687 removes the run the row became, so the mark lands
    on the projection and the legacy row keeps its own. A
    second row, so the game keeps one.
    """
    game = make_game(owned_user.library)
    play_event = PlayEvent.objects.create(game=game)
    PlayEvent.objects.create(game=game)
    convert_library(owned_user.library)
    run = run_for_row(owned_user.library, play_event.pk).run
    assert run is not None
    client.force_login(owned_user)

    response = client.delete(f"/api/playthrough/{play_event.pk}")

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.removed_at is not None
    play_event.refresh_from_db()
    assert play_event.removed_at is None
