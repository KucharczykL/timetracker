"""The sessions a library counts."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from django.utils import timezone
from session_rows import (
    corrected_row,
    duration_only_row,
    timed_row,
    tracked_run,
)

from games.models import (
    Game,
    PlayerGame,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
)
from games.reads.player_sessions import library_sessions
from games.removal import remove

START = datetime(2026, 1, 1, 20, 0, tzinfo=UTC)


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def run(owned_library, game) -> Playthrough:
    return tracked_run(owned_library, game)


def a_session(run: Playthrough) -> PlayerSession:
    return timed_row(run, START, START + timedelta(hours=1))


@pytest.mark.django_db
def test_the_scope_counts_a_live_session_of_each_mode(owned_library, run):
    rows = {
        timed_row(run, START, START + timedelta(hours=1)).pk,
        duration_only_row(run, date(2026, 3, 5), timedelta(minutes=90)).pk,
        corrected_row(run, START, START + timedelta(hours=1), timedelta(minutes=30)).pk,
    }

    assert set(library_sessions(owned_library).values_list("pk", flat=True)) == rows


@pytest.mark.django_db
def test_the_scope_hides_a_removed_session(owned_library, run):
    session = a_session(run)
    PlayerSession.objects.filter(pk=session.pk).update(removed_at=timezone.now())

    assert not library_sessions(owned_library).exists()


@pytest.mark.django_db
def test_the_scope_hides_a_session_under_a_removed_run(owned_library, run):
    a_session(run)
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    assert not library_sessions(owned_library).exists()


@pytest.mark.django_db
def test_the_scope_hides_a_session_under_a_removed_tracked_game(owned_library, run):
    a_session(run)
    PlayerGame.objects.filter(pk=run.player_game_id).update(removed_at=timezone.now())

    assert not library_sessions(owned_library).exists()


@pytest.mark.django_db
def test_the_scope_hides_a_session_under_a_removed_catalog_game(
    owned_library, game, run
):
    a_session(run)
    remove(game)

    assert not library_sessions(owned_library).exists()


@pytest.mark.django_db
def test_the_scope_counts_a_session_in_the_imported_history_bucket(owned_library, run):
    bucket = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )
    session = a_session(bucket)

    assert list(library_sessions(owned_library)) == [session]


@pytest.mark.django_db
def test_the_scope_reads_one_library(owned_library, run, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    #: Stranger's session library, our run.
    a_session(run)
    PlayerSession.objects.update(library=stranger.library)

    assert not library_sessions(owned_library).exists()
    assert not library_sessions(stranger.library).exists()


def test_the_scope_reads_the_tracked_games_library(
    owned_library, run, django_user_model
):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    a_session(run)
    #: Our session and run, the stranger's tracked game.
    PlayerGame.objects.filter(pk=run.player_game_id).update(library=stranger.library)

    assert not library_sessions(owned_library).exists()
