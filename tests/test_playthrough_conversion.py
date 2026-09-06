"""What the legacy rows become. Issue #684."""

import uuid
from datetime import UTC, date, datetime

import pytest

from games.backfill.playergame import backfill_library
from games.backfill.playthrough import NO_COUNTS, ConversionCounts, convert_row
from games.models import Game, PlayerGame, PlayEvent, Playthrough
from games.removal import remove

#: backfill_library() appends the creation event the conftest fixture
#: would have written by hand, so the two collide on the unique key.
pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.untracked_games,
]


def _game(library, name="Chrono Trigger"):
    return Game.objects.create(library=library, name=name)


def _row(game, started=None, ended=None, note=""):
    return PlayEvent.objects.create(game=game, started=started, ended=ended, note=note)


def _tracked(library, game):
    return PlayerGame.objects.get(library=library, game=game)


def _convert(library, row, tracked):
    return convert_row(
        row,
        library=library,
        actor=library.user,
        tracked_id=tracked.pk,
        pairings={},
    )


def test_a_dated_row_states_both_days(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2014, 6, 7), ended=date(2014, 6, 17))
    _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    assert run.started_lower == date(2014, 6, 7)
    assert run.completed_lower == date(2014, 6, 17)
    assert run.start_recorded_at is not None
    assert run.completion_recorded_at is not None
    assert run.kind == "ordinary"
    assert run.created_at == row.created_at


def test_an_endpoint_less_row_states_both_acts_and_no_days(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game)
    _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    assert run.started_lower is None
    assert run.completed_lower is None
    #: The marker is the act; the null day is only an unknown day.
    assert run.start_recorded_at is not None
    assert run.completion_recorded_at is not None


def test_a_reversed_row_is_recorded_as_it_stands(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2024, 5, 9), ended=date(2024, 5, 1))
    _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    assert run.started_lower == date(2024, 5, 9)
    assert run.completed_lower == date(2024, 5, 1)


def test_a_note_becomes_the_run_note(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2024, 1, 1), note="First playthrough")
    counts = _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    assert run.note == "First playthrough"
    assert run.start_note == ""
    assert counts.notes == 1


def test_a_blank_note_appends_nothing(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2024, 1, 1))
    counts = _convert(owned_library, row, _tracked(owned_library, game))

    assert counts.notes == 0


def test_a_removed_row_becomes_a_removed_run(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2024, 1, 1))
    remove(row)
    row.refresh_from_db()
    counts = _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    assert run.removed_at == row.removed_at
    assert counts.rows_removed_converted == 1


def test_an_identity_sorts_by_the_row_it_came_from(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2014, 1, 1))
    PlayEvent.objects.filter(pk=row.pk).update(
        created_at=datetime(2014, 1, 1, 12, 0, tzinfo=UTC)
    )
    row.refresh_from_db()
    _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    #: A UUIDv7 carries its instant in the high bits.
    assert run.pk < uuid.uuid7()
    assert run.created_at == datetime(2014, 1, 1, 12, 0, tzinfo=UTC)


def test_a_second_pass_over_one_row_appends_nothing(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2024, 1, 1))
    tracked = _tracked(owned_library, game)
    _convert(owned_library, row, tracked)
    repeat = _convert(owned_library, row, tracked)

    assert repeat.events_appended == 0
    assert Playthrough.objects.filter(player_game=tracked).count() == 1


def test_counts_add_field_by_field():
    total = ConversionCounts(live_rows=1) + ConversionCounts(live_rows=2, notes=1)

    assert total.live_rows == 3
    assert total.notes == 1
    assert NO_COUNTS.live_rows == 0
