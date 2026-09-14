"""Removal takes a record out, destroying nothing."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from stated_runs import another_run

from games.models import Game, Playthrough, Session
from games.reads.playtime import game_playtime
from games.removal import _AFTER_STAMP, remove, restore

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
    assert game_playtime(owned_library, game) == timedelta(hours=2)

    remove(Session.objects.get(game=game))

    assert game_playtime(owned_library, game) == timedelta(0)


def test_removing_a_session_stamps_its_mark_and_nothing_else(owned_library):
    game = make_game(owned_library)
    session = Session.objects.create(game=game, timestamp_start=timezone.now())

    with CaptureQueriesContext(connection) as queries:
        remove(session)

    assert Session not in _AFTER_STAMP
    writes = [
        query["sql"]
        for query in queries.captured_queries
        if query["sql"].startswith(("UPDATE", "INSERT", "DELETE"))
    ]
    assert len(writes) == 1
    assert writes[0].startswith('UPDATE "games_session"')


@pytest.mark.django_db(transaction=True)
def test_the_api_removes_a_playthrough_rather_than_destroying_it(client, owned_user):
    """DELETE is the transport's word, not ours.

    The mark lands on the run and the row stays. A second
    run, so removal is not taking the game's last one.
    """
    game = make_game(owned_user.library)
    run = another_run(owned_user, game, note="removed")
    client.force_login(owned_user)

    response = client.delete(f"/api/playthrough/{run.pk}")

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.removed_at is not None
    assert Playthrough.objects.filter(pk=run.pk).exists()
