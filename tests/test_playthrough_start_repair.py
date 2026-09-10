"""What the empty runs come to state. Issue #1038."""

import uuid
from datetime import UTC, datetime

import pytest

from games.backfill.playergame import backfill_library
from games.backfill.playthrough import convert_library
from games.backfill.playthrough_start import runs_in_scope
from games.models import Game, Playthrough
from games.removal import remove
from games.writes.playthrough import RunDraft, record_run

#: backfill_library() and the conftest fixture write the
#: same row, so the two collide on the unique key.
pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.untracked_games,
]


def _game(library, name="Chrono Trigger"):
    return Game.objects.create(library=library, name=name)


def _converted(library):
    """The state #684 leaves: tracked, and one empty run each."""
    backfill_library(library)
    convert_library(library)


def test_a_default_run_is_in_scope(owned_library):
    game = _game(owned_library)
    _converted(owned_library)

    scope = runs_in_scope(owned_library)

    assert len(scope) == 1
    assert scope[0].game_id == game.pk


def test_a_blank_run_a_person_created_is_left_alone(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        removed_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    record_run(
        owned_library.user,
        game,
        RunDraft(started=None, completed=None, note=""),
        correlation_id=uuid.uuid7(),
    )

    scope = runs_in_scope(owned_library)

    assert scope == []


def test_a_run_stating_either_act_is_left_alone(owned_library):
    _game(owned_library)
    _converted(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        start_recorded_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert runs_in_scope(owned_library) == []


def test_a_removed_run_is_left_alone(owned_library):
    _game(owned_library)
    _converted(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        removed_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert runs_in_scope(owned_library) == []


def test_a_run_at_a_removed_game_is_left_alone(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    remove(game)

    assert runs_in_scope(owned_library) == []
