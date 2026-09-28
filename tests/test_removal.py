"""Removal takes a record out, destroying nothing."""

from datetime import timedelta

import pytest
from django.utils import timezone
from session_rows import session_row
from stated_runs import another_run

from games.models import Game, PlayerSession, Playthrough
from games.reads.player_sessions import library_sessions
from games.reads.playtime import game_playtime
from games.removal import remove, restore

pytestmark = pytest.mark.django_db


def make_game(library, name="Outer Wilds"):
    return Game.objects.create(library=library, name=name)


def test_removing_a_game_keeps_its_sessions(owned_library):
    game = make_game(owned_library)
    started = timezone.now()
    session = session_row(
        game, started_at=started, ended_at=started + timedelta(hours=1)
    )

    remove(game)

    assert PlayerSession.objects.filter(pk=session.pk).exists()
    assert not library_sessions(owned_library).exists()


def test_restoring_a_game_brings_its_sessions_back(owned_library):
    game = make_game(owned_library)
    session_row(game, started_at=timezone.now())
    remove(game)

    restore(game)

    assert library_sessions(owned_library).count() == 1


def test_a_session_removed_by_itself_stays_removed(owned_library):
    """The projector's mark outlives the game's."""
    game = make_game(owned_library)
    session = session_row(game, started_at=timezone.now())
    PlayerSession.objects.filter(pk=session.pk).update(removed_at=timezone.now())
    remove(game)

    restore(game)

    assert not library_sessions(owned_library).exists()


def test_removing_a_session_drops_the_playtime(owned_library):
    """The projector's mark, as `RemoveSession` leaves it."""
    game = make_game(owned_library)
    started = timezone.now()
    row = session_row(game, started_at=started, ended_at=started + timedelta(hours=2))
    assert game_playtime(owned_library, game).total == timedelta(hours=2)

    PlayerSession.objects.filter(pk=row.pk).update(removed_at=timezone.now())

    assert game_playtime(owned_library, game).total == timedelta(0)


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
