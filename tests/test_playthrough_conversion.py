"""What the legacy rows become. Issue #684."""

import importlib
import json
import uuid
from datetime import UTC, date, datetime

import pytest
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from games.backfill.playergame import backfill_library
from games.backfill.playthrough import (
    _VERDICT_FIELD,
    NO_COUNTS,
    ConversionCounts,
    Mismatch,
    MismatchCode,
    convert_library,
    convert_row,
    ordering_violations,
    reconcile,
)
from games.events.rebuild import RebuildMode, rebuild_projections
from games.models import (
    Game,
    GameStatusChange,
    LibraryEvent,
    PlayerGame,
    PlayEvent,
    Playthrough,
    UserLibrary,
)
from games.preflight.playthrough import RowVerdict
from games.reads.playthrough_numbering import with_display_number
from games.removal import remove
from timetracker.temporal import TemporalValue

#: A digit-first module name needs importlib.
_migration = importlib.import_module(
    "games.migrations.0045_playthrough_conversion_backfill"
)
MACHINE_PREFIX = _migration.MACHINE_PREFIX
convert_legacy_playevents = _migration.convert_legacy_playevents

#: backfill_library() and the conftest fixture write the
#: same row, so the two collide on the unique key.
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
    #: The marker is the act, not the day.
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


def test_a_completion_only_row_states_the_end_alone(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, ended=date(2024, 3, 4))
    counts = _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    assert run.started_lower is None
    assert run.completed_lower == date(2024, 3, 4)
    #: Both acts happened; only one of them has a day.
    assert run.start_recorded_at is not None
    assert run.completion_recorded_at is not None
    assert counts.clean_end_only == 1


def test_every_verdict_is_counted(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 2))
    _row(game, started=date(2024, 1, 3))
    _row(game, ended=date(2024, 1, 4))
    _row(game)
    _row(game, started=date(2024, 1, 6), ended=date(2024, 1, 5))
    counts = convert_library(owned_library)

    assert counts.clean_both == 1
    assert counts.clean_start_only == 1
    assert counts.clean_end_only == 1
    assert counts.no_known_endpoint == 1
    assert counts.reversed_endpoints == 1
    assert counts.runs_converted == 5


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


def test_a_removed_run_keeps_what_the_row_said(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2021, 5, 1), ended=date(2021, 6, 1), note="Dropped")
    remove(row)
    row.refresh_from_db()
    _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    #: #771 takes the row away, so the run is the record.
    assert run.started_lower == date(2021, 5, 1)
    assert run.completed_lower == date(2021, 6, 1)
    assert run.note == "Dropped"


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
    #: A UUIDv7 carries its instant up front.
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


def test_every_verdict_names_a_counts_field():
    #: convert_row indexes this map, so a sixth verdict
    #: would raise KeyError on the row that first held it.
    assert set(_VERDICT_FIELD) == set(RowVerdict)
    assert set(_VERDICT_FIELD.values()) <= set(NO_COUNTS.as_dict())


def _finished_on(game, day):
    """#676 turns this into a completion event."""
    game.status = Game.Status.FINISHED
    game.save()
    return GameStatusChange.objects.create(
        game=game,
        old_status=Game.Status.PLAYED,
        new_status=Game.Status.FINISHED,
        #: Local noon: the backfill reads localtime().
        timestamp=datetime(
            day.year, day.month, day.day, 12, tzinfo=timezone.get_current_timezone()
        ),
    )


def test_a_tracked_game_with_no_rows_receives_one_default(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    counts = convert_library(owned_library)

    tracked = _tracked(owned_library, game)
    run = Playthrough.objects.get(player_game=tracked)
    assert counts.runs_default == 1
    assert counts.tracked == 1
    assert run.created_at == tracked.tracked_at
    assert run.start_recorded_at is None
    assert run.completion_recorded_at is None


def test_a_game_whose_only_row_was_removed_still_receives_a_default(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    remove(_row(game, started=date(2024, 1, 1)))
    counts = convert_library(owned_library)

    runs = Playthrough.objects.filter(player_game__game=game)
    assert counts.runs_converted == 1
    assert counts.runs_default == 1
    assert runs.filter(removed_at__isnull=True).count() == 1


def test_a_game_holding_a_live_row_receives_no_default(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    counts = convert_library(owned_library)

    assert counts.runs_default == 0
    assert Playthrough.objects.filter(player_game__game=game).count() == 1


def test_a_tracked_game_on_a_removed_catalog_row_is_skipped(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    remove(game)
    counts = convert_library(owned_library)

    assert counts.tracked_on_removed_game == 1
    assert counts.runs_converted == 0
    assert counts.runs_default == 0


def test_a_row_on_a_game_no_projection_names_is_left_alone(owned_library):
    _game(owned_library)
    backfill_library(owned_library)
    #: Made after the backfill, so no PlayerGame names it.
    untracked = _game(owned_library, name="Untracked")
    _row(untracked, started=date(2024, 1, 1))
    counts = convert_library(owned_library)

    assert Playthrough.objects.filter(player_game__game=untracked).count() == 0
    #: Outside the walk's scope, so no residual to report.
    assert counts.rows_unreached == 0
    assert reconcile(owned_library) == []


def test_a_row_on_an_untracked_game_is_left_alone(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    #: The projector's mark, so no removal helper states it.
    PlayerGame.objects.filter(library=owned_library, game=game).update(
        removed_at=timezone.now()
    )
    counts = convert_library(owned_library)

    assert counts.tracked == 0
    assert counts.rows_total == 0
    assert counts.rows_unreached == 0
    assert Playthrough.objects.count() == 0
    assert reconcile(owned_library) == []


def test_an_unambiguous_endpoint_adopts_the_status_event_correlation(owned_library):
    game = _game(owned_library, name="Celeste")
    _finished_on(game, date(2024, 1, 9))
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9))
    counts = convert_library(owned_library)

    status_event = LibraryEvent.objects.get(
        library=owned_library, event_type="library.playergame.status_changed"
    )
    completion = LibraryEvent.objects.get(
        library=owned_library, event_type="library.playthrough.completed"
    )
    assert completion.correlation_id == status_event.correlation_id
    assert counts.endpoints_paired == 1
    #: No `played` transition behind the start.
    assert counts.endpoints_absent == 1
    assert counts.endpoints_ambiguous == 0


def test_an_ambiguous_group_adopts_nothing(owned_library):
    game = _game(owned_library, name="Hades")
    _finished_on(game, date(2024, 1, 9))
    backfill_library(owned_library)
    #: Two rows on one day pair nothing.
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9))
    _row(game, started=date(2024, 1, 2), ended=date(2024, 1, 9))
    counts = convert_library(owned_library)

    assert counts.endpoints_paired == 0
    #: The two completions contest one event; the two
    #: starts have no candidate at all.
    assert counts.endpoints_ambiguous == 2
    assert counts.endpoints_absent == 2


def test_a_dayless_endpoint_pairs_nothing(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game)
    counts = convert_library(owned_library)

    assert counts.endpoints_dayless == 2
    assert counts.endpoints_paired == 0


def test_a_removed_row_joins_the_pairing_set(owned_library):
    game = _game(owned_library, name="Tunic")
    _finished_on(game, date(2024, 1, 9))
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9))
    remove(_row(game, started=date(2024, 1, 2), ended=date(2024, 1, 9)))
    counts = convert_library(owned_library)

    #: Both rows join the group, so the day is contested.
    assert counts.endpoints_paired == 0
    assert counts.endpoints_ambiguous == 2


def test_a_second_pass_over_a_library_appends_nothing(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    convert_library(owned_library)
    repeat = convert_library(owned_library)

    assert repeat.events_appended == 0
    assert Playthrough.objects.count() == 1


def test_a_second_pass_states_no_second_default(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    convert_library(owned_library)
    repeat = convert_library(owned_library)

    assert repeat.runs_default == 0
    assert repeat.runs_default_present == 1
    assert repeat.events_appended == 0
    assert Playthrough.objects.filter(player_game__game=game).count() == 1


def test_a_run_that_already_stands_stops_the_default(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    tracked = _tracked(owned_library, game)
    #: What #679 leaves behind: a run stating no act.
    Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=tracked,
        kind="ordinary",
        created_at=tracked.tracked_at,
    )
    counts = convert_library(owned_library)

    assert counts.runs_default == 0
    assert counts.runs_default_present == 1
    assert Playthrough.objects.filter(player_game=tracked).count() == 1
    assert reconcile(owned_library) == []


def test_a_converted_library_replays_into_the_same_rows(owned_library):
    game = _game(owned_library)
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9), note="One")
    _row(game)
    remove(_row(game, started=date(2023, 1, 1)))
    _game(owned_library, name="Untouched")
    backfill_library(owned_library)
    convert_library(owned_library)

    checked = rebuild_projections(owned_library, mode=RebuildMode.CHECK)
    drift = [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in checked.tables
    ]
    assert drift == [
        ("games_playergame", 0, 0, 0),
        ("games_playthrough", 0, 0, 0),
    ]


def test_a_shared_game_converts_once_per_library(owned_library, django_user_model):
    shared = Game.objects.create(library=None, name="Shared")
    _row(shared, started=date(2024, 1, 1))
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    for library in (owned_library, stranger.library):
        PlayerGame.objects.create(
            pk=uuid.uuid7(),
            library=library,
            game=shared,
            tracked_at=timezone.now(),
        )
        convert_library(library)

    assert Playthrough.objects.filter(player_game__library=owned_library).count() == 1
    assert (
        Playthrough.objects.filter(player_game__library=stranger.library).count() == 1
    )
    for run in Playthrough.objects.all():
        assert run.library_id == run.player_game.library_id


def test_a_converted_library_reconciles_clean(owned_library):
    game = _game(owned_library)
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9), note="One")
    _row(game, started=date(2024, 2, 1))
    _row(game, ended=date(2024, 3, 1))
    _row(game)
    remove(_row(game, started=date(2023, 1, 1)))
    _game(owned_library, name="Untouched")
    backfill_library(owned_library)
    convert_library(owned_library)

    assert reconcile(owned_library) == []
    assert ordering_violations() == []


def test_a_row_the_conversion_never_saw_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    convert_library(owned_library)
    #: A row nothing replayed: the source says more.
    _row(game, started=date(2024, 2, 1))

    codes = {mismatch.code for mismatch in reconcile(owned_library)}
    assert "run_disagreement" in codes


def test_a_missing_marker_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    convert_library(owned_library)
    Playthrough.objects.update(completion_recorded_at=None)

    codes = {mismatch.code for mismatch in reconcile(owned_library)}
    assert "missing_marker" in codes


def test_a_note_disagreement_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1), note="First playthrough")
    convert_library(owned_library)
    Playthrough.objects.update(note="Something else")

    codes = {mismatch.code for mismatch in reconcile(owned_library)}
    assert "run_disagreement" in codes


def test_a_removed_row_without_a_removed_run_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    remove(_row(game, started=date(2024, 1, 1)))
    convert_library(owned_library)
    Playthrough.objects.filter(removed_at__isnull=False).update(removed_at=None)

    codes = {mismatch.code for mismatch in reconcile(owned_library)}
    assert "removed_run_disagreement" in codes


def test_a_tracked_game_with_no_live_run_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    convert_library(owned_library)
    Playthrough.objects.update(removed_at=timezone.now())

    codes = {mismatch.code for mismatch in reconcile(owned_library)}
    assert "no_live_run" in codes


def test_the_display_order_follows_the_legacy_order(owned_library):
    #: The Dark Souls 2 shape: one dated, two not.
    game = _game(owned_library, name="Dark Souls 2")
    backfill_library(owned_library)
    _row(game, started=date(2014, 6, 7), ended=date(2014, 6, 17))
    _row(game)
    _row(game)
    convert_library(owned_library)

    numbered = with_display_number(Playthrough.objects.filter(player_game__game=game))
    by_number = sorted(numbered, key=lambda run: run.display_number)
    assert [run.display_number for run in by_number] == [1, 2, 3]
    assert by_number[0].started_lower == date(2014, 6, 7)
    assert reconcile(owned_library) == []


def test_rows_sharing_an_instant_are_numbered_in_either_order(owned_library):
    #: The sample fixture's shape: its anonymizer stamps
    #: every undated row one instant, so nothing the
    #: projection carries tells the two apart.
    game = _game(owned_library, name="Witcher")
    backfill_library(owned_library)
    _row(game)
    _row(game)
    PlayEvent.objects.filter(game=game).update(
        created_at=datetime(2020, 1, 1, tzinfo=UTC)
    )
    convert_library(owned_library)

    numbered = with_display_number(Playthrough.objects.filter(player_game__game=game))
    assert sorted(run.display_number for run in numbered) == [1, 2]
    assert reconcile(owned_library) == []


def test_two_rows_sharing_a_day_are_read_in_written_order(owned_library):
    #: The one shape where legacy_order_key and the window part:
    #: equal days, and created_at against the row ids. A fixture
    #: load makes it, and check 4 must not call it a disagreement.
    game = _game(owned_library, name="Hollow Knight")
    backfill_library(owned_library)
    rows = sorted(
        (_row(game, started=date(2024, 1, 1)), _row(game, started=date(2024, 1, 1))),
        key=lambda row: row.pk,
    )
    stamps = (datetime(2021, 1, 1, tzinfo=UTC), datetime(2020, 1, 1, tzinfo=UTC))
    for row, stamp in zip(rows, stamps, strict=True):
        PlayEvent.objects.filter(pk=row.pk).update(created_at=stamp)
    convert_library(owned_library)

    numbered = with_display_number(Playthrough.objects.filter(player_game__game=game))
    by_number = sorted(numbered, key=lambda run: run.display_number)
    assert [run.created_at for run in by_number] == sorted(stamps)
    assert reconcile(owned_library) == []


def test_a_display_order_disagreement_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    _row(game, started=date(2024, 2, 1))
    convert_library(owned_library)
    #: The earlier run claims the later day.
    Playthrough.objects.filter(started_lower=date(2024, 1, 1)).update(
        started=TemporalValue.from_day(date(2024, 3, 1))
    )

    codes = {mismatch.code for mismatch in reconcile(owned_library)}
    assert "display_order_disagreement" in codes


def test_an_identity_out_of_order_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2014, 1, 1))
    convert_library(owned_library)
    Playthrough.objects.update(created_at=datetime(2014, 1, 1, tzinfo=UTC))
    #: A key minted now, dated a year back.
    Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=_tracked(owned_library, game),
        kind="ordinary",
        created_at=datetime(2013, 1, 1, tzinfo=UTC),
    )

    codes = {mismatch.code for mismatch in ordering_violations()}
    assert "identity_ordering" in codes


def _machine_payload(capsys):
    """The migration's one machine-readable line, off stderr."""
    line = next(
        text
        for text in capsys.readouterr().err.splitlines()
        if text.startswith(MACHINE_PREFIX)
    )
    return json.loads(line[len(MACHINE_PREFIX) :])


def test_the_migration_converts_and_reports(owned_library, capsys):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9))
    convert_legacy_playevents(None, None)

    payload = _machine_payload(capsys)
    assert payload["mismatches"] == []
    assert payload["summary"]["runs_converted"] == 1
    assert payload["summary"]["libraries"] == 1
    assert payload["summary"]["rows_unreached"] == 0


def _one_mismatch(game):
    return [
        Mismatch(
            code=MismatchCode.RUN_DISAGREEMENT, subject=str(game.pk), detail="stated"
        )
    ]


def test_the_migration_raises_on_a_mismatch(owned_library, monkeypatch):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    #: The migration reads it at call time.
    monkeypatch.setattr(
        "games.backfill.playthrough.reconcile", lambda library: _one_mismatch(game)
    )
    with pytest.raises(RuntimeError, match="1 mismatch"):
        convert_legacy_playevents(None, None)


def test_the_migration_names_the_mismatch_it_raises_on(owned_library, monkeypatch):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    monkeypatch.setattr(
        "games.backfill.playthrough.reconcile", lambda library: _one_mismatch(game)
    )
    #: The count alone says nothing to whoever reads this.
    with pytest.raises(RuntimeError, match=f"run_disagreement {game.pk}: stated"):
        convert_legacy_playevents(None, None)


def test_a_mismatch_leaves_the_conversion_rolled_back(owned_library, monkeypatch):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    monkeypatch.setattr(
        "games.backfill.playthrough.reconcile", lambda library: _one_mismatch(game)
    )
    before = (LibraryEvent.objects.count(), Playthrough.objects.count())

    #: What the migration framework wraps this in.
    with pytest.raises(RuntimeError), transaction.atomic():
        convert_legacy_playevents(None, None)

    assert (LibraryEvent.objects.count(), Playthrough.objects.count()) == before


def test_the_migration_reports_a_second_pass_that_appends(owned_library, monkeypatch):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    passes = []

    def drifting(library):
        counts = convert_library(library)
        passes.append(library)
        #: The migration's second call over one library.
        if len(passes) % 2 == 0:
            return counts + ConversionCounts(events_appended=1)
        return counts

    monkeypatch.setattr("games.backfill.playthrough.convert_library", drifting)
    with pytest.raises(RuntimeError, match="count_drift"):
        convert_legacy_playevents(None, None)


def test_the_migration_reports_a_row_the_walk_left_behind(owned_library, monkeypatch):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))

    def short(library):
        #: One row in scope the walk never converted.
        return convert_library(library) + ConversionCounts(rows_unreached=1)

    monkeypatch.setattr("games.backfill.playthrough.convert_library", short)
    with pytest.raises(RuntimeError, match="rows_unreached"):
        convert_legacy_playevents(None, None)


def test_the_sample_fixture_leaves_every_tracked_game_holding_a_run(owned_user):
    call_command("load_sample_data", "--user", owned_user.username, verbosity=0)
    library = UserLibrary.objects.get(user=owned_user)
    tracked = PlayerGame.objects.filter(library=library, removed_at__isnull=True)
    with_runs = tracked.filter(
        playthroughs__removed_at__isnull=True, playthroughs__kind="ordinary"
    ).distinct()

    assert tracked.count() > 0
    assert with_runs.count() == tracked.count()
    assert reconcile(library) == []
    #: Every key the fixture's past instants minted still sorts.
    assert ordering_violations() == []


def test_the_shared_pieces_are_importable_on_their_own():
    """#1038 imports both; importing back is a cycle."""
    from games.backfill.appending import append_one
    from games.backfill.mismatch import Mismatch as SharedMismatch

    #: Re-exported, so every existing import still reads.
    from games.backfill.playthrough import Mismatch as ConversionMismatch

    assert ConversionMismatch is SharedMismatch
    assert callable(append_one)
