"""What the empty runs come to state. Issue #1038."""

import importlib
import json
import uuid
from datetime import UTC, date, datetime

import pytest

from games.backfill.playergame import backfill_library
from games.backfill.playthrough import MismatchCode, convert_library, reconcile
from games.backfill.playthrough_start import (
    Evidence,
    RepairResult,
    StartMismatchCode,
    StartRepairCounts,
    StartSource,
    evidence_for,
    gate,
    repair_library,
    runs_in_scope,
    session_days,
    snapshot,
    status_days,
)
from games.events.playthrough import PLAYTHROUGH_STARTED
from games.events.rebuild import RebuildMode, rebuild_projections
from games.models import (
    Game,
    GameStatusChange,
    LibraryEvent,
    PlayerGame,
    PlayEvent,
    Playthrough,
    Session,
)
from games.removal import remove
from games.writes.playthrough import RunDraft, record_run
from timetracker.temporal import TemporalValue

_migration = importlib.import_module("games.migrations.0048_playthrough_start_repair")
MACHINE_PREFIX = _migration.MACHINE_PREFIX
repair_playthrough_starts = _migration.repair_playthrough_starts

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


def test_a_session_states_the_viewers_day_not_the_servers(
    owned_user, owned_library, set_user_setting
):
    game = _game(owned_library)
    _converted(owned_library)
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Pacific/Kiritimati")
    #: Late enough in UTC that Kiritimati reads tomorrow.
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 5, 23, 30, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 6, 0, 30, tzinfo=UTC),
    )

    assert session_days(owned_library)[game.pk] == date(2026, 1, 6)


def test_a_removed_session_states_no_day(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    session = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 5, 11, 0, tzinfo=UTC),
    )
    remove(session)

    assert session_days(owned_library) == {}


def test_a_session_on_a_removed_game_states_no_day(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 5, 11, 0, tzinfo=UTC),
    )
    remove(game)

    assert session_days(owned_library) == {}


def test_the_earliest_session_wins(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    for day in (7, 3, 9):
        Session.objects.create(
            game=game,
            timestamp_start=datetime(2026, 1, day, 10, 0, tzinfo=UTC),
            timestamp_end=datetime(2026, 1, day, 11, 0, tzinfo=UTC),
        )

    assert session_days(owned_library)[game.pk] == date(2026, 1, 3)


def test_a_status_change_states_its_day(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="p",
        timestamp=datetime(2026, 1, 4, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)
    tracked = PlayerGame.objects.get(library=owned_library, game=game)

    assert status_days(owned_library)[tracked.pk] == date(2026, 1, 4)


def test_the_earlier_of_the_two_wins_and_names_its_source(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="p",
        timestamp=datetime(2026, 1, 9, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    run = runs_in_scope(owned_library)[0]

    found = evidence_for(
        run,
        status=status_days(owned_library),
        session=session_days(owned_library),
    )

    assert found == Evidence(date(2026, 1, 4), StartSource.SESSION)


def test_a_run_holding_neither_reads_nothing(owned_library):
    _game(owned_library)
    _converted(owned_library)
    run = runs_in_scope(owned_library)[0]

    assert evidence_for(run, status={}, session={}) is None


def test_the_pass_states_the_day_a_session_proves(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    result = repair_library(owned_library)
    run = Playthrough.objects.get(library=owned_library)

    assert result.counts.events_appended == 1
    assert result.counts.from_session == 1
    assert run.start_recorded_at is not None
    assert run.started_lower == date(2026, 1, 4)
    assert run.started == TemporalValue.from_day(date(2026, 1, 4))
    assert run.start_note == ""


def test_the_pass_states_no_completion_for_an_abandoned_game(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="a",
        timestamp=datetime(2026, 1, 4, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)

    repair_library(owned_library)
    run = Playthrough.objects.get(library=owned_library)

    assert run.start_recorded_at is not None
    assert run.completion_recorded_at is None


def test_a_run_holding_no_evidence_still_states_no_act(owned_library):
    _game(owned_library)
    _converted(owned_library)

    result = repair_library(owned_library)
    run = Playthrough.objects.get(library=owned_library)

    assert result.counts.no_evidence == 1
    assert result.counts.events_appended == 0
    assert run.start_recorded_at is None
    assert run.completion_recorded_at is None


def test_a_second_pass_appends_nothing(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    first = repair_library(owned_library)
    second = repair_library(owned_library)

    assert first.counts.events_appended == 1
    assert second.counts.events_appended == 0
    assert second.counts.runs_in_scope == 0


def test_the_event_names_the_source_that_won(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    repair_library(owned_library)
    event = LibraryEvent.objects.get(
        library=owned_library,
        event_type=PLAYTHROUGH_STARTED.event_type,
    )

    assert event.source_metadata == {
        "origin": "backfill",
        "issue": 1038,
        "source": "session",
    }


def test_the_pass_replays_to_the_same_row(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    repair_library(owned_library)

    checked = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    drift = [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in checked.tables
    ]
    assert drift == [
        ("games_playergame", 0, 0, 0),
        ("games_playthrough", 0, 0, 0),
    ]


def test_reconcile_is_clean_after_a_repair(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    repair_library(owned_library)

    assert reconcile(owned_library) == []


def test_reconcile_still_reads_a_converted_row_beside_a_repaired_run(owned_library):
    played = _game(owned_library, name="Chrono Trigger")
    recorded = _game(owned_library, name="Terranigma")
    PlayEvent.objects.create(
        game=recorded, started=date(2014, 6, 7), ended=date(2014, 6, 17)
    )
    _converted(owned_library)
    Session.objects.create(
        game=played,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    repair_library(owned_library)

    assert reconcile(owned_library) == []


def test_reconcile_still_reports_a_second_empty_run(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    repair_library(owned_library)
    #: One blank beside the repaired run is one too many:
    #: a repaired run still counts as stating no act.
    record_run(
        owned_library.user,
        game,
        RunDraft(started=None, completed=None, note=""),
        correlation_id=uuid.uuid7(),
    )

    codes = [mismatch.code for mismatch in reconcile(owned_library)]

    assert MismatchCode.SURPLUS_ACTLESS_RUN in codes


def test_the_gate_is_clean_on_a_good_pass(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    before = snapshot(owned_library)

    result = repair_library(owned_library)

    assert gate(owned_library, before, result) == []


def test_the_gate_reads_a_day_that_moved(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    before = snapshot(owned_library)
    result = repair_library(owned_library)
    #: The projection now says a day the pass never stated.
    Playthrough.objects.filter(library=owned_library).update(
        started=TemporalValue.from_day(date(1999, 1, 1))
    )

    codes = [mismatch.code for mismatch in gate(owned_library, before, result)]

    assert StartMismatchCode.START_DAY_DISAGREEMENT in codes


def test_the_gate_reads_a_completion_this_pass_must_not_have_stated(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    before = snapshot(owned_library)
    result = repair_library(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        completion_recorded_at=datetime(2026, 2, 1, tzinfo=UTC)
    )

    codes = [mismatch.code for mismatch in gate(owned_library, before, result)]

    assert StartMismatchCode.COMPLETION_DRIFT in codes


def test_the_gate_reads_a_start_that_appeared_outside_the_scope(owned_library):
    played = _game(owned_library, name="Chrono Trigger")
    other = _game(owned_library, name="Terranigma")
    PlayEvent.objects.create(game=other, started=date(2014, 6, 7))
    _converted(owned_library)
    Session.objects.create(
        game=played,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    before = snapshot(owned_library)
    result = repair_library(owned_library)
    #: A converted run's day moves, which the pass never touches.
    Playthrough.objects.filter(library=owned_library, player_game__game=other).update(
        started=TemporalValue.from_day(date(1999, 1, 1))
    )

    codes = [mismatch.code for mismatch in gate(owned_library, before, result)]

    assert StartMismatchCode.START_MOVED in codes


def test_the_gate_reads_a_run_left_alone_that_gained_an_act(owned_library):
    _game(owned_library)
    _converted(owned_library)
    before = snapshot(owned_library)
    result = repair_library(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        start_recorded_at=datetime(2026, 2, 1, tzinfo=UTC)
    )

    codes = [mismatch.code for mismatch in gate(owned_library, before, result)]

    assert StartMismatchCode.UNEXPECTED_ACT in codes


def test_the_migration_states_the_starts_and_reports(owned_library, capsys):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    repair_playthrough_starts(None, None)

    run = Playthrough.objects.get(library=owned_library)
    assert run.started_lower == date(2026, 1, 4)
    machine = [
        line
        for line in capsys.readouterr().err.splitlines()
        if line.startswith(MACHINE_PREFIX)
    ]
    payload = json.loads(machine[0][len(MACHINE_PREFIX) :])
    assert payload["summary"]["events_appended"] == 1
    assert payload["summary"]["mismatches"] == 0


def test_the_migration_refuses_a_second_pass_that_appends(owned_library, monkeypatch):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    passes = []

    def drifting(library):
        result = repair_library(library)
        passes.append(1)
        if len(passes) % 2 == 0:
            return RepairResult(
                counts=result.counts + StartRepairCounts(events_appended=1),
                stated=result.stated,
                left_alone=result.left_alone,
            )
        return result

    monkeypatch.setattr("games.backfill.playthrough_start.repair_library", drifting)
    with pytest.raises(RuntimeError, match="count_drift"):
        repair_playthrough_starts(None, None)


def test_the_migration_refuses_a_mismatched_day(owned_library, monkeypatch):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    def lying(library):
        result = repair_library(library)
        return RepairResult(
            counts=result.counts,
            stated={
                run_id: Evidence(date(1999, 1, 1), evidence.source)
                for run_id, evidence in result.stated.items()
            },
            left_alone=result.left_alone,
        )

    monkeypatch.setattr("games.backfill.playthrough_start.repair_library", lying)
    with pytest.raises(RuntimeError, match="start_day_disagreement"):
        repair_playthrough_starts(None, None)
