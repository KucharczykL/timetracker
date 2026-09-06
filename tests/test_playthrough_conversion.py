"""What the legacy rows become. Issue #684."""

import importlib
import json
import uuid
from datetime import UTC, date, datetime

import pytest
from django.utils import timezone

from games.backfill.playergame import backfill_library
from games.backfill.playthrough import (
    NO_COUNTS,
    ConversionCounts,
    Mismatch,
    convert_library,
    convert_row,
    ordering_violations,
    reconcile,
)
from games.models import (
    Game,
    GameStatusChange,
    LibraryEvent,
    PlayerGame,
    PlayEvent,
    Playthrough,
)
from games.reads.playthrough_numbering import with_display_number
from games.removal import remove
from timetracker.temporal import TemporalValue

#: A module name beginning with a digit cannot be imported by the
#: `from ... import` form.
_migration = importlib.import_module(
    "games.migrations.0045_playthrough_conversion_backfill"
)
MACHINE_PREFIX = _migration.MACHINE_PREFIX
convert_legacy_playevents = _migration.convert_legacy_playevents

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


def _finished_on(game, day):
    """#676 turns this into a dated completion event."""
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
    assert counts.endpoints_fresh == 1


def test_an_ambiguous_group_mints_fresh_ids(owned_library):
    game = _game(owned_library, name="Hades")
    _finished_on(game, date(2024, 1, 9))
    backfill_library(owned_library)
    #: Two rows completed on one day: the group pairs nothing.
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9))
    _row(game, started=date(2024, 1, 2), ended=date(2024, 1, 9))
    counts = convert_library(owned_library)

    assert counts.endpoints_paired == 0
    assert counts.endpoints_fresh == 4


def test_a_dayless_endpoint_mints_a_fresh_id(owned_library):
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

    #: The preflight, which sees live rows only, would call this
    #: unambiguous. This run sees both, so the group pairs nothing.
    assert counts.endpoints_paired == 0


def test_a_second_pass_over_a_library_appends_nothing(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    convert_library(owned_library)
    repeat = convert_library(owned_library)

    assert repeat.events_appended == 0
    assert Playthrough.objects.count() == 1


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
    #: A legacy row nothing replayed: the source now says more than the
    #: events do.
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
    assert "removed_run_missing" in codes


def test_a_tracked_game_with_no_live_run_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    convert_library(owned_library)
    Playthrough.objects.update(removed_at=timezone.now())

    codes = {mismatch.code for mismatch in reconcile(owned_library)}
    assert "no_live_run" in codes


def test_the_display_order_follows_the_legacy_order(owned_library):
    #: The Dark Souls 2 shape: one dated run and two nobody dated.
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
    #: The sample fixture's shape: its anonymizer stamps every undated
    #: row one instant, so nothing the projection carries tells the two
    #: apart and the gate must not fail on it.
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


def test_a_display_order_disagreement_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    _row(game, started=date(2024, 2, 1))
    convert_library(owned_library)
    #: The earlier run now claims the later day, so the sequence no
    #: longer matches the rows.
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
    #: A key minted now against a created_at from a year earlier.
    Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=_tracked(owned_library, game),
        kind="ordinary",
        created_at=datetime(2013, 1, 1, tzinfo=UTC),
    )

    codes = {mismatch.code for mismatch in ordering_violations()}
    assert "identity_ordering" in codes


def test_the_migration_converts_and_reports(owned_library, capsys):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9))
    convert_legacy_playevents(None, None)

    line = next(
        text
        for text in capsys.readouterr().out.splitlines()
        if text.startswith(MACHINE_PREFIX)
    )
    payload = json.loads(line[len(MACHINE_PREFIX) :])
    assert payload["mismatches"] == []
    assert payload["summary"]["runs_converted"] == 1
    assert payload["summary"]["libraries"] == 1


def test_the_migration_raises_on_a_mismatch(owned_library, monkeypatch):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    #: The migration reads the module by name at call time, so the gate
    #: is patched where it is written.
    monkeypatch.setattr(
        "games.backfill.playthrough.reconcile",
        lambda library: [Mismatch(code="test", game_id=str(game.pk), detail="x")],
    )
    with pytest.raises(RuntimeError, match="1 mismatch"):
        convert_legacy_playevents(None, None)
