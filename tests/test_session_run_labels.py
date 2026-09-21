"""The run label a session row shows beside its game."""

import uuid
from datetime import UTC, datetime

import pytest
from django.utils import timezone
from session_rows import timed_row, tracked_run

from games.models import (
    Game,
    PlayerGame,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
)
from games.reads.session_run_labels import (
    IMPORTED_HISTORY_LABEL,
    ambiguous_run_labels,
    every_run_label,
)

pytestmark = pytest.mark.django_db

STARTED_AT = datetime(2026, 3, 5, 10, tzinfo=UTC)


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def another_run(library, game, *, kind=PlaythroughKind.ORDINARY, name=""):
    return Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=library,
        player_game=PlayerGame.objects.get(library=library, game=game),
        kind=kind,
        name=name,
        created_at=timezone.now(),
    )


def page_sessions(library) -> list[PlayerSession]:
    """The rows a page holds, each carrying its run."""
    return list(
        PlayerSession.objects.filter(library=library).select_related("playthrough")
    )


def test_every_run_label_names_the_run_a_sole_session_sits_on(owned_library, game):
    run = tracked_run(owned_library, game)
    timed_row(run, STARTED_AT, None)

    assert every_run_label(owned_library, page_sessions(owned_library)) == {
        run.pk: "Playthrough 1"
    }


def test_the_narrow_reader_leaves_a_sole_run_unnamed(owned_library, game):
    timed_row(tracked_run(owned_library, game), STARTED_AT, None)

    assert ambiguous_run_labels(owned_library, page_sessions(owned_library)) == {}


def test_every_run_label_names_a_bucket(owned_library, game):
    tracked_run(owned_library, game)
    bucket = another_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    timed_row(bucket, STARTED_AT, None)

    labels = every_run_label(owned_library, page_sessions(owned_library))

    assert labels[bucket.pk] == IMPORTED_HISTORY_LABEL


def test_both_readers_name_every_run_of_a_game_holding_two(owned_library, game):
    first = tracked_run(owned_library, game)
    second = another_run(owned_library, game, name="Second run")
    timed_row(first, STARTED_AT, None)
    timed_row(second, STARTED_AT, None)

    sessions = page_sessions(owned_library)

    expected = {first.pk: "Playthrough 1", second.pk: "Second run"}
    assert every_run_label(owned_library, sessions) == expected
    assert ambiguous_run_labels(owned_library, sessions) == expected


def test_a_bucket_beside_a_live_run_is_named_by_both_readers(owned_library, game):
    run = tracked_run(owned_library, game)
    bucket = another_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    timed_row(run, STARTED_AT, None)
    timed_row(bucket, STARTED_AT, None)

    sessions = page_sessions(owned_library)

    expected = {run.pk: "Playthrough 1", bucket.pk: IMPORTED_HISTORY_LABEL}
    assert every_run_label(owned_library, sessions) == expected
    assert ambiguous_run_labels(owned_library, sessions) == expected
