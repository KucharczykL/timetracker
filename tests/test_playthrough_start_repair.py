"""What the empty runs come to state. #1038."""

import importlib
import io
import json
import uuid
from datetime import UTC, date, datetime

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction

from games.backfill.mismatch import Mismatch
from games.backfill.playergame import backfill_library
from games.backfill.playthrough import MismatchCode, convert_library, reconcile
from games.backfill.playthrough_start import (
    Evidence,
    RepairResult,
    RunInScope,
    StartMismatchCode,
    StartSource,
    StatusDay,
    evidence_for,
    gate,
    repair_library,
    report_library,
    runs_in_scope,
    session_days,
    snapshot,
    status_days,
)
from games.commands.playthrough import ActStatement
from games.events.playthrough import PLAYTHROUGH_STARTED
from games.events.rebuild import RebuildMode, rebuild_projections
from games.models import (
    Game,
    GameStatusChange,
    LibraryEvent,
    PlayerGame,
    PlayerGameStatus,
    PlayEvent,
    Playthrough,
    PlaythroughKind,
    Session,
    UserLibrary,
)
from games.reads.playthrough_activity import RunActivity
from games.reads.playthrough_runs import run_to_adopt, runs_with_condition
from games.removal import remove
from games.views.playthrough_rows import _act_members
from games.writes.playthrough import RunDraft, record_run
from timetracker.temporal import TemporalValue

_migration = importlib.import_module("games.migrations.0048_playthrough_start_repair")
MACHINE_PREFIX = _migration.MACHINE_PREFIX
repair_playthrough_starts = _migration.repair_playthrough_starts

_report = importlib.import_module("games.management.commands.report_playthrough_starts")
REPORT_MACHINE_PREFIX = _report.MACHINE_PREFIX
GENERATED_PREFIX = _report.GENERATED_PREFIX

#: Both write the row, so they collide.
pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.untracked_games,
]


def _game(library, name="Chrono Trigger"):
    return Game.objects.create(library=library, name=name)


def _converted(library):
    """What #684 leaves: tracked, one empty run."""
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


def test_a_run_under_a_removed_player_game_is_left_alone(owned_library):
    _game(owned_library)
    _converted(owned_library)
    PlayerGame.objects.filter(library=owned_library).update(
        removed_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert runs_in_scope(owned_library) == []


def test_an_imported_history_run_is_left_alone(owned_library):
    _game(owned_library)
    _converted(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        kind=PlaythroughKind.IMPORTED_HISTORY
    )

    assert runs_in_scope(owned_library) == []


def test_a_session_states_the_viewers_day_not_the_servers(
    owned_user, owned_library, set_user_setting
):
    game = _game(owned_library)
    _converted(owned_library)
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Pacific/Kiritimati")
    #: Late enough that Kiritimati reads tomorrow.
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

    assert status_days(owned_library)[tracked.pk] == StatusDay(
        date(2026, 1, 4), PlayerGameStatus.PLAYED
    )


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


def test_the_status_wins_where_it_is_the_earlier(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="a",
        timestamp=datetime(2026, 1, 4, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 9, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 9, 11, 0, tzinfo=UTC),
    )
    run = runs_in_scope(owned_library)[0]

    found = evidence_for(
        run,
        status=status_days(owned_library),
        session=session_days(owned_library),
    )

    #: An ending status dates a start here.
    assert found == Evidence(
        date(2026, 1, 4), StartSource.STATUS, PlayerGameStatus.ABANDONED
    )


def test_the_session_wins_where_the_two_days_agree():
    run = RunInScope(
        run_id=uuid.uuid7(), player_game_id=uuid.uuid7(), game_id=uuid.uuid7()
    )
    day = date(2026, 1, 4)

    found = evidence_for(
        run,
        status={run.player_game_id: StatusDay(day, PlayerGameStatus.PLAYED)},
        session={run.game_id: day},
    )

    assert found == Evidence(day, StartSource.SESSION)


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


def test_the_pass_dates_every_run_it_reads(owned_library):
    for offset, name in enumerate(("Chrono Trigger", "Terranigma", "Illusion of Gaia")):
        game = _game(owned_library, name=name)
        Session.objects.create(
            game=game,
            timestamp_start=datetime(2026, 1, 4 + offset, 10, 0, tzinfo=UTC),
            timestamp_end=datetime(2026, 1, 4 + offset, 11, 0, tzinfo=UTC),
        )
    _converted(owned_library)

    result = repair_library(owned_library)

    assert result.counts.runs_in_scope == 3
    assert result.counts.events_appended == 3
    assert sorted(
        Playthrough.objects.filter(library=owned_library).values_list(
            "started_lower", flat=True
        )
    ) == [date(2026, 1, 4), date(2026, 1, 5), date(2026, 1, 6)]


def test_the_pass_counts_a_pair_the_two_clocks_may_have_moved(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="p",
        timestamp=datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    counts = repair_library(owned_library).counts

    assert counts.both == 1
    assert counts.both_agree == 0
    assert counts.both_off_by_one == 1


def test_the_event_names_the_status_that_dated_it(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="a",
        timestamp=datetime(2026, 1, 4, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)

    repair_library(owned_library)
    event = LibraryEvent.objects.get(
        library=owned_library,
        event_type=PLAYTHROUGH_STARTED.event_type,
    )

    assert event.source_metadata == {
        "origin": "backfill",
        "issue": 1038,
        "source": "status",
        "status": "abandoned",
    }


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
    #: A repaired run still counts as blank.
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
    #: The row says a day nothing stated.
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
    #: A converted run moves, untouched by this.
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


def test_the_gate_reads_an_actless_run_that_appeared(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    before = snapshot(owned_library)
    result = repair_library(owned_library)
    #: One more run states no act than the gate expects.
    record_run(
        owned_library.user,
        game,
        RunDraft(started=None, completed=None, note=""),
        correlation_id=uuid.uuid7(),
    )

    codes = [mismatch.code for mismatch in gate(owned_library, before, result)]

    assert StartMismatchCode.ACTLESS_DRIFT in codes


def test_the_gate_reads_a_scope_that_matched_nothing(owned_library):
    _game(owned_library)
    _converted(owned_library)
    before = snapshot(owned_library)
    result = repair_library(owned_library)
    #: The metadata moves out from under the filter.
    for event in LibraryEvent.objects.filter(
        library=owned_library, source_metadata__issue=684
    ):
        LibraryEvent.objects.filter(pk=event.pk).update(
            source_metadata=event.source_metadata | {"issue": 999}
        )

    codes = [mismatch.code for mismatch in gate(owned_library, before, result)]

    assert StartMismatchCode.SCOPE_BLIND in codes


def test_the_gate_says_nothing_of_a_library_no_pass_converted(owned_library):
    """A library holding no backfilled run owes none."""
    _game(owned_library)
    backfill_library(owned_library)
    before = snapshot(owned_library)

    result = repair_library(owned_library)

    assert gate(owned_library, before, result) == []


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


def _lying(library):
    """A pass stating a day the row does not hold."""
    result = repair_library(library)
    return RepairResult(
        counts=result.counts,
        stated={
            run_id: Evidence(date(1999, 1, 1), evidence.source)
            for run_id, evidence in result.stated.items()
        },
        left_alone=result.left_alone,
    )


def test_the_migration_refuses_a_mismatched_day(owned_library, monkeypatch):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    monkeypatch.setattr("games.backfill.playthrough_start.repair_library", _lying)
    with pytest.raises(RuntimeError, match="start_day_disagreement"):
        repair_playthrough_starts(None, None)


def test_a_mismatch_leaves_the_repair_rolled_back(owned_library, monkeypatch):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    monkeypatch.setattr("games.backfill.playthrough_start.repair_library", _lying)
    before = (
        LibraryEvent.objects.count(),
        Playthrough.objects.filter(start_recorded_at__isnull=False).count(),
    )

    #: What the migration framework wraps this in.
    with pytest.raises(RuntimeError), transaction.atomic():
        repair_playthrough_starts(None, None)

    assert (
        LibraryEvent.objects.count(),
        Playthrough.objects.filter(start_recorded_at__isnull=False).count(),
    ) == before


def test_the_sample_fixture_states_a_start_where_it_holds_one(owned_user):
    call_command("load_sample_data", "--user", owned_user.username, verbosity=0)
    library = UserLibrary.objects.get(user=owned_user)
    live = Playthrough.objects.filter(library=library, removed_at__isnull=True)

    assert live.filter(start_recorded_at__isnull=False).exists()
    assert reconcile(library) == []
    assert runs_in_scope(library) == [] or all(
        evidence_for(
            run,
            status=status_days(library),
            session=session_days(library),
        )
        is None
        for run in runs_in_scope(library)
    )


def _report_output(username):
    """The report without the two values that move."""
    buffer = io.StringIO()
    call_command(
        "report_playthrough_starts", "--user", username, stdout=buffer, verbosity=0
    )
    text = buffer.getvalue()
    line = next(
        line for line in text.splitlines() if line.startswith(REPORT_MACHINE_PREFIX)
    )
    payload = json.loads(line[len(REPORT_MACHINE_PREFIX) :])
    del payload["generated_at"]
    lines = [
        line
        for line in text.splitlines()
        if not line.startswith((REPORT_MACHINE_PREFIX, GENERATED_PREFIX))
    ]
    return json.dumps(payload, sort_keys=True), lines


def test_the_report_states_what_the_pass_would_do(owned_library):
    played = _game(owned_library, name="Chrono Trigger")
    _game(owned_library, name="Terranigma")
    _converted(owned_library)
    Session.objects.create(
        game=played,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    report = report_library(owned_library, sample_size=20)

    assert report.counts.runs_in_scope == 2
    assert report.counts.session_only == 1
    assert report.counts.no_evidence == 1
    assert report.counts.from_session == 1
    assert len(report.samples) == 1
    assert report.samples[0].game_name == "Chrono Trigger"
    assert report.samples[0].day == date(2026, 1, 4)
    assert report.samples[0].source == "session"
    assert report.samples[0].status == ""
    #: The run that keeps printing a dash is named.
    assert [sample.game_name for sample in report.empty_samples] == ["Terranigma"]


def test_the_report_names_the_status_behind_a_day(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="a",
        timestamp=datetime(2026, 1, 4, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)

    report = report_library(owned_library, sample_size=20)

    assert report.samples[0].source == "status"
    assert report.samples[0].status == "abandoned"


def test_the_report_reads_every_library(owned_library, capsys):
    _game(owned_library)
    _converted(owned_library)

    call_command("report_playthrough_starts", "--all-libraries", verbosity=0)

    printed = capsys.readouterr().out
    assert str(owned_library.pk) in printed


def test_the_report_reads_one_library_by_id(owned_library, capsys):
    _game(owned_library)
    _converted(owned_library)

    call_command("report_playthrough_starts", "--library", str(owned_library.pk))

    assert str(owned_library.pk) in capsys.readouterr().out


def test_the_report_refuses_a_library_that_is_no_uuid():
    with pytest.raises(CommandError, match="is no UUID"):
        call_command("report_playthrough_starts", "--library", "nonsense")


def test_the_report_refuses_a_negative_sample_size(owned_library):
    with pytest.raises(CommandError, match="counts runs"):
        call_command(
            "report_playthrough_starts",
            "--user",
            owned_library.user.username,
            "--sample-size",
            "-1",
        )


def test_the_report_states_nothing(owned_library):
    played = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=played,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    report_library(owned_library, sample_size=20)

    assert Playthrough.objects.get(library=owned_library).start_recorded_at is None


def test_the_report_prints_the_same_bytes_twice(owned_library):
    for name in ("Chrono Trigger", "Terranigma", "Illusion of Gaia"):
        game = _game(owned_library, name=name)
        Session.objects.create(
            game=game,
            timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
            timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
        )
    _converted(owned_library)

    first = _report_output(owned_library.user.username)
    second = _report_output(owned_library.user.username)

    assert first == second


def test_the_report_refuses_a_scope_it_cannot_resolve():
    with pytest.raises(CommandError, match="No user is named"):
        call_command("report_playthrough_starts", "--user", "nobody", verbosity=0)


def test_a_repaired_run_is_no_longer_adopted(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    repair_library(owned_library)
    tracked = PlayerGame.objects.get(library=owned_library, game=game)

    #: Filled in, so a statement makes another.
    assert run_to_adopt(owned_library, tracked) is None


def test_a_repaired_run_offers_the_completion_press(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    repair_library(owned_library)
    run = Playthrough.objects.get(library=owned_library)

    members = _act_members(run, None, "token")

    assert len(members) == 1
    assert members[0]["title"].startswith("Completed today")


def test_a_repaired_run_dated_long_ago_reads_dormant(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="p",
        timestamp=datetime(2023, 5, 1, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)

    repair_library(owned_library)
    run = runs_with_condition(owned_library).get()

    assert run.activity == RunActivity.DORMANT


def test_the_migration_leaves_a_standing_mismatch_alone(owned_library, capsys):
    """A start a person stated is #684's to answer."""
    game = _game(owned_library)
    _converted(owned_library)
    #: A day nobody wrote down, as pressed.
    record_run(
        owned_library.user,
        game,
        RunDraft(started=ActStatement(when=None), completed=None, note=""),
        correlation_id=uuid.uuid7(),
    )
    standing = reconcile(owned_library)
    assert standing

    repair_playthrough_starts(None, None)

    machine = [
        line
        for line in capsys.readouterr().err.splitlines()
        if line.startswith(MACHINE_PREFIX)
    ]
    payload = json.loads(machine[0][len(MACHINE_PREFIX) :])
    assert payload["summary"]["mismatches"] == 0
    assert payload["summary"]["preexisting"] == len(standing)


def test_the_migration_still_refuses_a_mismatch_it_adds(owned_library, monkeypatch):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    added = MismatchCode.RUN_DISAGREEMENT
    calls = []

    def complaining(library):
        calls.append(1)
        if len(calls) == 1:
            return []
        return [
            Mismatch(
                code=added,
                subject=str(library.pk),
                detail="a mismatch the pass added",
            )
        ]

    monkeypatch.setattr("games.backfill.playthrough.reconcile", complaining)
    with pytest.raises(RuntimeError, match="a mismatch the pass added"):
        repair_playthrough_starts(None, None)
