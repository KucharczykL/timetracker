"""What the legacy Session rows become. Issue #700."""

import importlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, migrations, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from session_rows import tracked_run
from test_playergame_playthrough_gate import UNREACHABLE_KINDS

from games.backfill import playersession as conversion
from games.backfill.playersession import (
    BUCKET_NAME,
    CENSUS_PAIRS,
    KEY_PREFIX,
    NO_COUNTS,
    SKIPPED_NOTE_PREFIX,
    BucketRun,
    ConversionCounts,
    ConversionRefused,
    Mismatch,
    MismatchCode,
    assignment_counts,
    convert_library,
    convert_row,
    display_zone_name,
    mode_counts,
    ordering_violations,
    reconcile,
    refuse_shared_game_rows,
)
from games.backfill.reporting import failure_sentence
from games.commands.playergame import TrackGame
from games.commands.playthrough import (
    CompletePlaythrough,
    CreatePlaythrough,
    StartPlaythrough,
)
from games.events.dispatch import Command, CommandOutcome, dispatch
from games.events.rebuild import RebuildReport, TableDiff
from games.identity_audit import IdentityModel, check_ordering, identity_models
from games.models import (
    Device,
    Game,
    LibraryEvent,
    LibraryIdempotencyRecord,
    PlayerGame,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
    Session,
    UserLibrary,
)
from games.preflight.session import (
    Assignment,
    AssignmentOutcome,
    TimingVerdict,
    report_zones,
)
from games.reads.playtime_parity import display_zone
from games.removal import remove
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)

PRAGUE = ZoneInfo("Europe/Prague")
START = datetime(2024, 3, 1, 10, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


def game_at(library: UserLibrary, name: str = "Chrono Trigger") -> Game:
    return Game.objects.create(library=library, name=name)


def legacy(game: Game, start: datetime = START, **columns: object) -> Session:
    """One row, read back with generated columns."""
    row = Session.objects.create(game=game, timestamp_start=start, **columns)
    return Session.objects.get(pk=row.pk)


def run_of(library: UserLibrary, game: Game) -> Playthrough:
    return tracked_run(library, game)


def sole(run: Playthrough) -> Assignment:
    return Assignment(AssignmentOutcome.SOLE_RUN, run.pk, None)


def convert(
    library: UserLibrary,
    row: Session,
    run: Playthrough,
    *,
    assignment: Assignment | None = None,
    day_zone: str = "Europe/Prague",
) -> ConversionCounts:
    return convert_row(
        Session.objects.get(pk=row.pk),
        library=library,
        actor=library.user,
        run_id=run.pk,
        assignment=sole(run) if assignment is None else assignment,
        day_zone=day_zone,
    )


def projection(row: Session) -> PlayerSession:
    return PlayerSession.objects.get(pk=row.pk)


# --- One row, one statement -------------------------------------------------


def test_a_timed_row_converts_to_a_timed_row(owned_library):
    game = game_at(owned_library)
    row = legacy(
        game,
        timestamp_end=START + HOUR,
        timestamp_start_timezone="Europe/Prague",
        timestamp_end_timezone="Europe/Prague",
    )
    counts = convert(owned_library, row, run_of(owned_library, game))

    projected = projection(row)
    assert projected.timing_mode == "timed"
    assert projected.started_at == START
    assert projected.ended_at == START + HOUR
    assert projected.started_at_zone == "Europe/Prague"
    assert projected.ended_at_zone == "Europe/Prague"
    assert projected.day_zone == "Europe/Prague"
    assert projected.stated_day is None
    assert projected.effective_duration == row.duration_total == HOUR
    assert projected.playthrough_id == run_of(owned_library, game).pk
    assert counts.timed == 1
    assert counts.live_rows == 1
    assert counts.events_appended == 1


def test_a_duration_only_row_states_the_day_in_the_display_zone(owned_library):
    game = game_at(owned_library)
    #: 23:30 UTC is the next day in Prague.
    row = legacy(
        game,
        start=datetime(2024, 3, 1, 23, 30, tzinfo=UTC),
        duration_manual=2 * HOUR,
    )
    counts = convert(owned_library, row, run_of(owned_library, game))

    projected = projection(row)
    assert projected.timing_mode == "duration_only"
    assert projected.stated_day == date(2024, 3, 2)
    assert projected.started_at is None
    assert projected.day_zone is None
    assert projected.effective_duration == row.duration_total == 2 * HOUR
    assert counts.duration_only == 1


def test_a_corrected_row_states_the_legacy_total_not_the_manual_part(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START + HOUR, duration_manual=2 * HOUR)
    counts = convert(owned_library, row, run_of(owned_library, game))

    projected = projection(row)
    assert projected.timing_mode == "corrected"
    assert projected.stated_duration == 3 * HOUR
    assert projected.effective_duration == row.duration_total == 3 * HOUR
    assert projected.started_at == START
    assert projected.ended_at == START + HOUR
    assert counts.corrected == 1


def test_a_removed_running_row_converts_as_a_timed_row_with_no_end_and_a_mark(
    owned_library,
):
    game = game_at(owned_library)
    row = legacy(game)
    remove(row)
    counts = convert(owned_library, row, run_of(owned_library, game))

    projected = projection(row)
    assert projected.timing_mode == "timed"
    assert projected.started_at == START
    assert projected.ended_at is None
    assert projected.effective_duration == timedelta(0)
    assert projected.removed_at == Session.objects.get(pk=row.pk).removed_at
    assert counts.running_removed == 1
    assert counts.rows_removed_converted == 1
    assert counts.events_appended == 2


def test_a_live_running_row_refuses(owned_library):
    game = game_at(owned_library)
    row = legacy(game)
    with pytest.raises(ConversionRefused, match=f"Session {row.pk} is still running"):
        convert(owned_library, row, run_of(owned_library, game))
    assert PlayerSession.objects.count() == 0


def test_a_negative_interval_refuses(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START - HOUR)
    with pytest.raises(ConversionRefused, match="ends before it starts"):
        convert(owned_library, row, run_of(owned_library, game))


def test_a_negative_manual_duration_refuses(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START + HOUR, duration_manual=-HOUR)
    with pytest.raises(ConversionRefused, match="negative manual duration"):
        convert(owned_library, row, run_of(owned_library, game))


def test_a_null_manual_duration_refuses(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START + HOUR)
    #: save() fills a null; UPDATE stores one.
    Session.objects.filter(pk=row.pk).update(duration_manual=None)
    with pytest.raises(ConversionRefused, match="no manual duration"):
        convert(owned_library, row, run_of(owned_library, game))


def test_an_unknown_display_zone_refuses(owned_library, monkeypatch):
    #: The resolver admits only Python's zones.
    monkeypatch.setattr(
        "games.backfill.playersession.resolve_str_for_user",
        lambda user, key: "Mars/Olympus",
    )
    with pytest.raises(ConversionRefused, match="Mars/Olympus"):
        display_zone_name(owned_library)


def test_an_end_zone_without_a_start_zone_is_kept_as_recorded(owned_library):
    game = game_at(owned_library)
    row = legacy(
        game,
        timestamp_end=START + HOUR,
        timestamp_start_timezone=None,
        timestamp_end_timezone="Europe/Prague",
    )
    convert(owned_library, row, run_of(owned_library, game))

    projected = projection(row)
    assert projected.started_at_zone is None
    assert projected.ended_at_zone == "Europe/Prague"


def test_a_blank_zone_becomes_none(owned_library):
    game = game_at(owned_library)
    row = legacy(
        game,
        timestamp_end=START + HOUR,
        timestamp_start_timezone="",
        timestamp_end_timezone="",
    )
    convert(owned_library, row, run_of(owned_library, game))

    projected = projection(row)
    assert projected.started_at_zone is None
    assert projected.ended_at_zone is None


def test_a_removed_device_converts_as_named(owned_library):
    game = game_at(owned_library)
    device = Device.objects.create(library=owned_library, name="Deck", type="PC")
    row = legacy(game, timestamp_end=START + HOUR, device=device)
    remove(device)
    counts = convert(owned_library, row, run_of(owned_library, game))

    assert projection(row).device_id == device.pk
    assert counts.devices == 1


def test_another_librarys_device_refuses(owned_library, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    game = game_at(owned_library)
    device = Device.objects.create(library=stranger.library, name="Deck", type="PC")
    row = legacy(game, timestamp_end=START + HOUR)
    #: save() refuses it; UPDATE states the drift.
    Session.objects.filter(pk=row.pk).update(device=device)
    with pytest.raises(ConversionRefused, match=f"device {device.pk} of library"):
        convert(owned_library, row, run_of(owned_library, game))


def test_a_padded_note_is_stripped(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START + HOUR, note="  Good run \n")
    counts = convert(owned_library, row, run_of(owned_library, game))

    assert projection(row).note == "Good run"
    assert counts.notes == 1


def test_a_note_holding_a_nul_byte_refuses(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START + HOUR)
    #: Text holds no NUL; amended in memory.
    row.note = "bad\x00note"
    with pytest.raises(ConversionRefused, match="NUL byte"):
        convert_row(
            row,
            library=owned_library,
            actor=owned_library.user,
            run_id=run_of(owned_library, game).pk,
            assignment=sole(run_of(owned_library, game)),
            day_zone="Europe/Prague",
        )


def test_the_identity_is_the_legacy_id_and_created_at_is_the_rows(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START + HOUR)
    written = datetime(2014, 1, 1, 12, 0, tzinfo=UTC)
    Session.objects.filter(pk=row.pk).update(created_at=written)
    convert(owned_library, row, run_of(owned_library, game))

    projected = projection(row)
    assert projected.pk == row.pk
    assert projected.created_at == written
    event = LibraryEvent.objects.get(event_type="library.playersession.created")
    assert event.aggregate_id == row.pk
    assert event.recorded_at == written
    #: The event key carries the instant it records.
    assert event.pk.time == int(written.timestamp() * 1000)


def test_a_removed_row_appends_created_then_removed_at_its_removed_at(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START + HOUR)
    remove(row)
    removed_at = Session.objects.get(pk=row.pk).removed_at
    convert(owned_library, row, run_of(owned_library, game))

    events = list(LibraryEvent.objects.filter(aggregate_id=row.pk).order_by("sequence"))
    assert [event.event_type for event in events] == [
        "library.playersession.created",
        "library.playersession.removed",
    ]
    assert events[1].recorded_at == removed_at
    assert events[0].correlation_id == events[1].correlation_id
    assert projection(row).removed_at == removed_at


def test_the_evidence_names_every_legacy_column(owned_library):
    game = game_at(owned_library)
    row = legacy(
        game,
        timestamp_end=START + HOUR + timedelta(microseconds=250),
        timestamp_end_timezone="Europe/Prague",
    )
    run = run_of(owned_library, game)
    convert(
        owned_library,
        row,
        run,
        assignment=Assignment(AssignmentOutcome.CONTAINED, run.pk, 1),
    )

    event = LibraryEvent.objects.get(event_type="library.playersession.created")
    assert event.source_metadata == {
        "origin": "backfill",
        "issue": 700,
        "legacy": {
            "timestamp_start": "2024-03-01T10:00:00+00:00",
            "timestamp_end": "2024-03-01T11:00:00.000250+00:00",
            "timestamp_start_timezone": None,
            "timestamp_end_timezone": "Europe/Prague",
            "duration_manual_microseconds": 0,
            "duration_calculated_microseconds": 3_600_000_250,
            "duration_total_microseconds": 3_600_000_250,
            "created_at": row.created_at.astimezone(UTC).isoformat(),
            "verdict": "timed",
            "assignment": "contained",
            "claimers": 1,
        },
    }


def test_a_sub_second_elapsed_interval_converts_and_its_evidence_keeps_it(
    owned_library,
):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START + timedelta(microseconds=400_000))
    convert(owned_library, row, run_of(owned_library, game))

    projected = projection(row)
    assert projected.effective_duration == timedelta(microseconds=400_000)
    event = LibraryEvent.objects.get(event_type="library.playersession.created")
    assert event.source_metadata["legacy"]["duration_total_microseconds"] == 400_000


def test_a_second_pass_over_one_row_appends_nothing(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START + HOUR)
    remove(row)
    run = run_of(owned_library, game)
    convert(owned_library, row, run)
    repeat = convert(owned_library, row, run)

    assert repeat.events_appended == 0
    assert repeat.timed == 1
    assert LibraryEvent.objects.filter(aggregate_id=row.pk).count() == 2
    assert PlayerSession.objects.count() == 1


def test_the_keys_name_the_issue_and_the_row(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START + HOUR)
    convert(owned_library, row, run_of(owned_library, game))

    event = LibraryEvent.objects.get(event_type="library.playersession.created")
    assert event.idempotency_key == f"{KEY_PREFIX}:playersession:created:{row.pk}"
    assert KEY_PREFIX == "backfill:700"


def test_counts_add_field_by_field():
    total = ConversionCounts(live_rows=1) + ConversionCounts(live_rows=2, notes=1)

    assert total.live_rows == 3
    assert total.notes == 1
    assert NO_COUNTS.live_rows == 0


def test_every_verdict_and_outcome_counts_one_field():
    for verdict in TimingVerdict:
        if verdict in (TimingVerdict.NEGATIVE_ELAPSED, TimingVerdict.NEGATIVE_MANUAL):
            with pytest.raises(ValueError, match=str(verdict)):
                mode_counts(verdict)
        else:
            assert sum(mode_counts(verdict).as_dict().values()) == 1
    for outcome in AssignmentOutcome:
        assert sum(assignment_counts(outcome).as_dict().values()) == 1


def test_a_negative_count_is_refused():
    with pytest.raises(ValueError, match="rows_unreached"):
        ConversionCounts(rows_unreached=-1)


def test_a_standing_bucket_costs_nothing():
    assert BucketRun(uuid.uuid7(), None).counts == NO_COUNTS
    assert BucketRun(uuid.uuid7(), 2).counts == ConversionCounts(
        buckets_minted=1, events_appended=2
    )


def test_the_census_pairs_cover_every_mode_and_outcome():
    covered = {pair.counts_field for pair in CENSUS_PAIRS}
    for verdict in (
        TimingVerdict.TIMED,
        TimingVerdict.DURATION_ONLY,
        TimingVerdict.CORRECTED,
        TimingVerdict.RUNNING,
    ):
        (field,) = (name for name, n in mode_counts(verdict).as_dict().items() if n)
        assert field in covered
    for outcome in AssignmentOutcome:
        (field,) = (
            name for name, n in assignment_counts(outcome).as_dict().items() if n
        )
        assert field in covered
    assert covered <= set(NO_COUNTS.as_dict())


def test_the_display_zone_is_the_users_setting(
    owned_library, owned_user, set_user_setting
):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Asia/Tokyo")
    assert display_zone_name(owned_library) == "Asia/Tokyo"


# --- Assignment, the bucket, the walk ----------------------------------------


def dated_run(run: Playthrough, started: date, completed: date | None) -> Playthrough:
    """State both days on a run the fixture made."""
    run.started = TemporalValue.from_day(started)
    run.start_recorded_at = timezone.now()
    if completed is not None:
        run.completed = TemporalValue.from_day(completed)
        run.completion_recorded_at = timezone.now()
    run.save()
    return run


def second_run(library: UserLibrary, game: Game) -> Playthrough:
    return Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=library,
        player_game=PlayerGame.objects.get(library=library, game=game),
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )


def buckets_of(game: Game) -> list[Playthrough]:
    return list(
        Playthrough.objects.filter(
            player_game__game=game, kind=PlaythroughKind.IMPORTED_HISTORY
        )
    )


def test_a_sole_run_takes_every_row_whatever_the_day(owned_library):
    game = game_at(owned_library)
    run = dated_run(run_of(owned_library, game), date(2024, 2, 1), date(2024, 2, 10))
    early = legacy(game, start=datetime(2020, 1, 1, tzinfo=UTC), timestamp_end=START)
    late = legacy(game, start=datetime(2025, 1, 1, tzinfo=UTC), duration_manual=HOUR)
    counts = convert_library(owned_library)

    assert projection(early).playthrough_id == run.pk
    assert projection(late).playthrough_id == run.pk
    assert counts.sole_run == 2
    assert counts.bucket == 0
    assert buckets_of(game) == []


def test_one_dated_claimer_takes_the_row(owned_library):
    game = game_at(owned_library)
    first = dated_run(run_of(owned_library, game), date(2024, 2, 1), date(2024, 2, 10))
    second = dated_run(second_run(owned_library, game), date(2024, 3, 1), None)
    inside_first = legacy(
        game, start=datetime(2024, 2, 5, tzinfo=UTC), timestamp_end=START
    )
    inside_second = legacy(
        game, start=datetime(2024, 4, 5, tzinfo=UTC), duration_manual=HOUR
    )
    counts = convert_library(owned_library)

    assert projection(inside_first).playthrough_id == first.pk
    assert projection(inside_second).playthrough_id == second.pk
    assert counts.contained == 2
    assert counts.sole_run == 0


def test_a_row_no_dated_run_claims_lands_in_the_bucket(owned_library):
    game = game_at(owned_library)
    dated_run(run_of(owned_library, game), date(2024, 2, 1), date(2024, 2, 10))
    dated_run(second_run(owned_library, game), date(2024, 3, 1), date(2024, 3, 10))
    orphan = legacy(game, start=datetime(2020, 1, 1, tzinfo=UTC), timestamp_end=START)
    counts = convert_library(owned_library)

    (bucket,) = buckets_of(game)
    assert projection(orphan).playthrough_id == bucket.pk
    assert counts.bucket == 1
    assert counts.buckets_minted == 1


def test_two_dated_claimers_land_the_row_in_the_bucket(owned_library):
    game = game_at(owned_library)
    #: Synthetic overlap; production holds none.
    dated_run(run_of(owned_library, game), date(2024, 2, 1), date(2024, 2, 20))
    dated_run(second_run(owned_library, game), date(2024, 2, 10), date(2024, 3, 1))
    contested = legacy(
        game, start=datetime(2024, 2, 15, tzinfo=UTC), timestamp_end=START
    )
    counts = convert_library(owned_library)

    (bucket,) = buckets_of(game)
    assert projection(contested).playthrough_id == bucket.pk
    assert counts.bucket == 1
    event = LibraryEvent.objects.get(event_type="library.playersession.created")
    assert event.source_metadata["legacy"]["claimers"] == 2


def test_an_undated_run_claims_nothing(owned_library):
    game = game_at(owned_library)
    dated_run(run_of(owned_library, game), date(2024, 2, 1), date(2024, 2, 10))
    second_run(owned_library, game)
    outside = legacy(game, start=datetime(2020, 1, 1, tzinfo=UTC), timestamp_end=START)
    counts = convert_library(owned_library)

    (bucket,) = buckets_of(game)
    assert projection(outside).playthrough_id == bucket.pk
    assert counts.bucket == 1


def test_one_bucket_per_game_however_many_rows_reach_it(owned_library):
    game = game_at(owned_library)
    dated_run(run_of(owned_library, game), date(2024, 2, 1), date(2024, 2, 10))
    second_run(owned_library, game)
    for day in (1, 2, 3):
        legacy(game, start=datetime(2020, 1, day, tzinfo=UTC), timestamp_end=START)
    counts = convert_library(owned_library)

    (bucket,) = buckets_of(game)
    assert PlayerSession.objects.filter(playthrough=bucket).count() == 3
    assert counts.bucket == 3
    assert counts.buckets_minted == 1


def test_the_bucket_is_named_and_of_the_imported_kind(owned_library):
    game = game_at(owned_library)
    dated_run(run_of(owned_library, game), date(2024, 2, 1), date(2024, 2, 10))
    second_run(owned_library, game)
    legacy(game, start=datetime(2020, 1, 1, tzinfo=UTC), timestamp_end=START)
    minted_at = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    convert_library(owned_library, minted_at=minted_at)

    (bucket,) = buckets_of(game)
    assert bucket.name == BUCKET_NAME
    assert bucket.kind == "imported_history"
    assert bucket.created_at == minted_at
    assert bucket.library_id == owned_library.pk
    assert bucket.start_recorded_at is None
    events = LibraryEvent.objects.filter(aggregate_id=bucket.pk).order_by("sequence")
    assert [event.event_type for event in events] == [
        "library.playthrough.created",
        "library.playthrough.name_changed",
    ]
    assert len({event.correlation_id for event in events}) == 1


def test_a_game_needing_no_bucket_gets_none(owned_library):
    game = game_at(owned_library)
    dated_run(run_of(owned_library, game), date(2024, 2, 1), date(2024, 2, 10))
    dated_run(second_run(owned_library, game), date(2024, 3, 1), None)
    legacy(game, start=datetime(2024, 2, 5, tzinfo=UTC), timestamp_end=START)
    counts = convert_library(owned_library)

    assert buckets_of(game) == []
    assert counts.buckets_minted == 0


def test_a_second_pass_mints_no_second_bucket(owned_library):
    game = game_at(owned_library)
    dated_run(run_of(owned_library, game), date(2024, 2, 1), date(2024, 2, 10))
    second_run(owned_library, game)
    legacy(game, start=datetime(2020, 1, 1, tzinfo=UTC), timestamp_end=START)
    with transaction.atomic():
        first = convert_library(owned_library)
        repeat = convert_library(owned_library)

    assert first.buckets_minted == 1
    assert repeat.buckets_minted == 0
    assert repeat.events_appended == 0
    assert repeat.bucket == 1
    assert len(buckets_of(game)) == 1


def test_a_bucket_rows_input_names_no_run(owned_library):
    game = game_at(owned_library)
    dated_run(run_of(owned_library, game), date(2024, 2, 1), date(2024, 2, 10))
    second_run(owned_library, game)
    row = legacy(game, start=datetime(2020, 1, 1, tzinfo=UTC), timestamp_end=START)
    convert_library(owned_library)
    key = f"{KEY_PREFIX}:playersession:created:{row.pk}"
    before = LibraryIdempotencyRecord.objects.get(idempotency_key=key)
    convert_library(owned_library)
    after = LibraryIdempotencyRecord.objects.get(idempotency_key=key)

    assert before.request_fingerprint == after.request_fingerprint
    assert before.first_sequence == after.first_sequence


@pytest.mark.untracked_games
def test_a_row_on_an_untracked_game_refuses(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START + HOUR)
    with pytest.raises(ConversionRefused, match=f"Session {row.pk} .* does not track"):
        convert_library(owned_library)


def test_a_row_on_a_removed_tracking_row_refuses(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START + HOUR)
    #: The projector's mark; no helper states it.
    PlayerGame.objects.filter(library=owned_library, game=game).update(
        removed_at=timezone.now()
    )
    with pytest.raises(ConversionRefused, match=f"Session {row.pk} .* tracking row"):
        convert_library(owned_library)


def test_a_row_on_a_removed_catalog_game_refuses(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end=START + HOUR)
    remove(game)
    with pytest.raises(ConversionRefused, match=f"Session {row.pk} .* marks removed"):
        convert_library(owned_library)


@pytest.mark.untracked_games
def test_a_row_on_a_shared_game_refuses(owned_library):
    shared = Game.objects.create(library=None, name="Shared")
    row = legacy(shared, timestamp_end=START + HOUR)
    with pytest.raises(ConversionRefused, match=f"Session {row.pk} .* no library"):
        convert_library(owned_library)
    with pytest.raises(ConversionRefused):
        refuse_shared_game_rows()


def test_a_game_with_no_rows_is_walked_past(owned_library):
    game_at(owned_library, name="Untouched")
    counts = convert_library(owned_library)

    assert counts.tracked == 0
    assert counts.rows_total == 0
    assert counts.events_appended == 0


def test_a_second_pass_over_a_library_appends_nothing(owned_library):
    game = game_at(owned_library)
    legacy(game, timestamp_end=START + HOUR)
    remove(legacy(game, start=START + HOUR))
    first = convert_library(owned_library)
    repeat = convert_library(owned_library)

    assert first.events_appended == 3
    assert repeat.events_appended == 0
    assert repeat.as_dict() | {"events_appended": 3} == first.as_dict()


def test_rows_unreached_counts_what_the_walk_left(owned_library, monkeypatch):
    game = game_at(owned_library)
    legacy(game, timestamp_end=START + HOUR)
    legacy(game, timestamp_end=START + HOUR)

    original = conversion.convert_game
    monkeypatch.setattr(
        conversion,
        "convert_game",
        lambda rows, **kwargs: original(rows[:-1], **kwargs),
    )
    counts = convert_library(owned_library)

    assert counts.rows_total == 2
    assert counts.rows_unreached == 1


def test_unreachable_kinds_stay_a_commands_claim(owned_library):
    """Only this walk states the bucket kind."""
    game = game_at(owned_library)
    dated_run(run_of(owned_library, game), date(2024, 2, 1), date(2024, 2, 10))
    second_run(owned_library, game)
    legacy(game, start=datetime(2020, 1, 1, tzinfo=UTC), timestamp_end=START)
    convert_library(owned_library)

    stated = set(
        Playthrough.objects.filter(library=owned_library).values_list("kind", flat=True)
    )
    assert stated == set(PlaythroughKind)
    assert set(PlaythroughKind) - UNREACHABLE_KINDS == {PlaythroughKind.ORDINARY}


# --- The gate ---------------------------------------------------------------


def stated(library: UserLibrary, command: Command, key: str) -> None:
    """Through dispatch, so a replay reproduces it."""
    result = dispatch(command, actor=library.user, library=library, idempotency_key=key)
    assert result.outcome is CommandOutcome.APPENDED, key


def tracked_game(library: UserLibrary, name: str) -> Game:
    game = Game.objects.create(library=library, name=name)
    stated(library, TrackGame(game_id=game.pk), f"track:{name}")
    return game


def stated_run(
    library: UserLibrary, run: Playthrough, started: date, completed: date | None
) -> Playthrough:
    stated(
        library,
        StartPlaythrough(
            playthrough_id=run.pk, when=TemporalValue.from_day(started), note=""
        ),
        f"start:{run.pk}",
    )
    if completed is not None:
        stated(
            library,
            CompletePlaythrough(
                playthrough_id=run.pk, when=TemporalValue.from_day(completed), note=""
            ),
            f"complete:{run.pk}",
        )
    return Playthrough.objects.get(pk=run.pk)


def stated_second_run(library: UserLibrary, game: Game) -> Playthrough:
    before = set(
        Playthrough.objects.filter(player_game__game=game).values_list("pk", flat=True)
    )
    stated(
        library, CreatePlaythrough(game_id=game.pk), f"create:{game.pk}:{len(before)}"
    )
    return (
        Playthrough.objects.filter(player_game__game=game).exclude(pk__in=before).get()
    )


def seeded(library: UserLibrary) -> tuple[Game, ConversionCounts]:
    """Every verdict and outcome, all from events."""
    game = tracked_game(library, "Chrono Trigger")
    stated_run(library, run_of(library, game), date(2024, 2, 1), date(2024, 2, 10))
    stated_run(library, stated_second_run(library, game), date(2024, 3, 1), None)
    legacy(game, start=datetime(2024, 2, 5, tzinfo=UTC), timestamp_end=START, note="x")
    legacy(game, start=datetime(2024, 3, 5, tzinfo=UTC), duration_manual=HOUR)
    legacy(game, start=datetime(2020, 1, 1, tzinfo=UTC), timestamp_end=START)
    remove(legacy(game, start=datetime(2024, 3, 6, tzinfo=UTC)))
    other = tracked_game(library, "Sole")
    legacy(other, timestamp_end=START + HOUR, duration_manual=HOUR)
    tracked_game(library, "Untouched")
    return game, convert_library(library)


def codes(mismatches) -> set[str]:
    return {mismatch.code for mismatch in mismatches}


@pytest.mark.untracked_games
def test_a_converted_library_reconciles_clean(owned_library):
    _game, counts = seeded(owned_library)

    assert reconcile(owned_library, counts) == []
    assert ordering_violations() == []


@pytest.mark.untracked_games
def test_a_row_disagreement_is_reported(owned_library):
    _game, counts = seeded(owned_library)
    PlayerSession.objects.filter(removed_at__isnull=True, note="x").update(note="y")

    found = [
        m for m in reconcile(owned_library, counts) if m.code == "row_disagreement"
    ]
    assert len(found) == 1
    assert "note: row says 'x', projection says 'y'" in found[0].detail


@pytest.mark.untracked_games
def test_a_removed_row_without_a_mark_is_reported(owned_library):
    _game, counts = seeded(owned_library)
    PlayerSession.objects.filter(removed_at__isnull=False).update(removed_at=None)

    assert "removed_row_disagreement" in codes(reconcile(owned_library, counts))


@pytest.mark.untracked_games
def test_a_row_naming_the_wrong_run_is_reported(owned_library):
    game, counts = seeded(owned_library)
    (bucket,) = buckets_of(game)
    PlayerSession.objects.filter(note="x").update(playthrough=bucket)

    mismatches = reconcile(owned_library, counts)
    assert "row_disagreement" in codes(mismatches)
    assert "bucket_membership" in codes(mismatches)


@pytest.mark.untracked_games
def test_a_census_disagreement_is_reported(owned_library):
    _game, counts = seeded(owned_library)

    drifted = counts + ConversionCounts(timed=1)
    assert "census_drift" in codes(reconcile(owned_library, drifted))


@pytest.mark.untracked_games
def test_a_row_the_walk_never_saw_is_reported(owned_library):
    _game, counts = seeded(owned_library)

    short = counts + ConversionCounts(rows_unreached=1)
    assert "rows_unreached" in codes(reconcile(owned_library, short))


@pytest.mark.untracked_games
def test_a_second_bucket_is_reported(owned_library):
    game, counts = seeded(owned_library)
    Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=PlayerGame.objects.get(library=owned_library, game=game),
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )

    assert "bucket_surplus" in codes(reconcile(owned_library, counts))


@pytest.mark.untracked_games
def test_a_bucket_where_none_is_needed_is_reported(owned_library):
    _game, counts = seeded(owned_library)
    other = Game.objects.get(name="Sole")
    Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=PlayerGame.objects.get(library=owned_library, game=other),
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )

    found = [m for m in reconcile(owned_library, counts) if m.code == "bucket_unneeded"]
    assert [m.subject for m in found] == [str(other.pk)]


@pytest.mark.untracked_games
def test_a_bucket_holding_a_contained_row_is_reported(owned_library):
    game, counts = seeded(owned_library)
    (bucket,) = buckets_of(game)
    PlayerSession.objects.filter(timing_mode="duration_only").update(playthrough=bucket)

    assert "bucket_membership" in codes(reconcile(owned_library, counts))


@pytest.mark.untracked_games
def test_a_playtime_difference_is_reported(owned_library):
    _game, counts = seeded(owned_library)
    #: Legacy moves; projection agrees with itself.
    Session.objects.filter(note="x").update(timestamp_end=START + 2 * HOUR)

    mismatches = reconcile(owned_library, counts)
    assert "playtime_differs" in codes(mismatches)
    #: Row check sees it; figure names scope.
    assert "row_disagreement" in codes(mismatches)


@pytest.mark.untracked_games
def test_a_count_difference_is_reported(owned_library):
    _game, counts = seeded(owned_library)
    other = Game.objects.get(name="Sole")
    #: A legacy row nothing converted.
    legacy(other, timestamp_end=START + HOUR)

    mismatches = reconcile(owned_library, counts)
    assert "count_drift" in codes(mismatches)
    assert "row_disagreement" in codes(mismatches)


@pytest.mark.untracked_games
def test_an_identity_out_of_order_is_reported(owned_library):
    game, _counts = seeded(owned_library)
    #: A key minted now, dated a decade back.
    Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=PlayerGame.objects.get(library=owned_library, game=game),
        kind=PlaythroughKind.ORDINARY,
        created_at=datetime(2013, 1, 1, tzinfo=UTC),
    )

    found = [m for m in ordering_violations() if m.code == "identity_ordering"]
    assert [m.subject for m in found] == ["games_playthrough"]


@pytest.mark.untracked_games
def test_a_session_identity_out_of_order_is_reported(owned_library):
    seeded(owned_library)
    #: Later key, earlier date.
    PlayerSession.objects.filter(timing_mode="duration_only").update(
        created_at=datetime(2013, 1, 1, tzinfo=UTC)
    )

    found = [m for m in ordering_violations() if m.code == "identity_ordering"]
    assert [m.subject for m in found] == ["games_playersession"]


@pytest.mark.untracked_games
def test_a_blind_identity_audit_is_reported(owned_library, monkeypatch):
    monkeypatch.setattr(
        "games.backfill.playersession.identity_models",
        lambda: [
            entry for entry in identity_models() if entry.table != "games_playersession"
        ],
    )

    found = [m for m in ordering_violations() if m.code == "identity_audit_blind"]
    assert [m.subject for m in found] == ["games_playersession"]


@pytest.mark.untracked_games
def test_a_replay_difference_is_reported(owned_library):
    _game, counts = seeded(owned_library)
    #: Both sides move; only replay sees it.
    PlayerSession.objects.filter(note="x").update(emulated=True)
    Session.objects.filter(note="x").update(emulated=True)

    mismatches = reconcile(owned_library, counts)
    assert "row_disagreement" not in codes(mismatches)
    found = [m for m in mismatches if m.code == "replay_differs"]
    assert [m.subject for m in found] == ["games_playersession"]


@pytest.mark.untracked_games
def test_the_display_zone_the_census_reads_is_the_one_the_conversion_seeds(
    owned_library, owned_user, set_user_setting
):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Asia/Tokyo")

    assert report_zones(owned_library).secondary == ZoneInfo(
        display_zone_name(owned_library)
    )
    assert display_zone(owned_library) == ZoneInfo("Asia/Tokyo")


@pytest.mark.untracked_games
def test_a_conversion_in_another_zone_reconciles_clean(
    owned_library, owned_user, set_user_setting
):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Asia/Tokyo")
    _game, counts = seeded(owned_library)

    assert PlayerSession.objects.filter(day_zone="Asia/Tokyo").exists()
    assert reconcile(owned_library, counts) == []


# --- The migration and the sample loader --------------------------------------

#: A digit-first module name needs importlib.
_migration = importlib.import_module("games.migrations.0004_playersession_conversion")
MACHINE_PREFIX = _migration.MACHINE_PREFIX
convert_legacy_sessions = _migration.convert_legacy_sessions


def _machine_payload(capsys):
    """The migration's one machine-readable line, off stderr."""
    line = next(
        text
        for text in capsys.readouterr().err.splitlines()
        if text.startswith(MACHINE_PREFIX)
    )
    return json.loads(line[len(MACHINE_PREFIX) :])


@pytest.mark.untracked_games
def test_the_migration_converts_and_reports(owned_library, capsys):
    game = tracked_game(owned_library, "Chrono Trigger")
    legacy(game, timestamp_end=START + HOUR)
    remove(legacy(game, start=START + HOUR))
    convert_legacy_sessions(None, None)

    payload = _machine_payload(capsys)
    assert payload["mismatches"] == []
    assert payload["summary"]["libraries"] == 1
    assert payload["summary"]["timed"] == 1
    assert payload["summary"]["running_removed"] == 1
    assert payload["summary"]["rows_unreached"] == 0
    assert payload["summary"]["mismatches"] == 0
    assert PlayerSession.objects.count() == 2


def _one_mismatch(library):
    return [
        Mismatch(
            code=MismatchCode.ROW_DISAGREEMENT, subject=str(library.pk), detail="stated"
        )
    ]


@pytest.mark.untracked_games
def test_the_migration_raises_on_a_mismatch(owned_library, monkeypatch):
    game = tracked_game(owned_library, "Chrono Trigger")
    legacy(game, timestamp_end=START + HOUR)
    #: The migration reads it at call time.
    monkeypatch.setattr(
        conversion, "reconcile", lambda library, counts: _one_mismatch(library)
    )
    with pytest.raises(RuntimeError, match="1 mismatch"):
        convert_legacy_sessions(None, None)


@pytest.mark.untracked_games
def test_the_migration_names_the_mismatch_it_raises_on(owned_library, monkeypatch):
    game = tracked_game(owned_library, "Chrono Trigger")
    legacy(game, timestamp_end=START + HOUR)
    monkeypatch.setattr(
        conversion, "reconcile", lambda library, counts: _one_mismatch(library)
    )
    #: The count alone says nothing.
    with pytest.raises(
        RuntimeError, match=f"row_disagreement {owned_library.pk}: stated"
    ):
        convert_legacy_sessions(None, None)


@pytest.mark.untracked_games
def test_a_mismatch_leaves_the_conversion_rolled_back(owned_library, monkeypatch):
    game = tracked_game(owned_library, "Chrono Trigger")
    legacy(game, timestamp_end=START + HOUR)
    monkeypatch.setattr(
        conversion, "reconcile", lambda library, counts: _one_mismatch(library)
    )
    before = (LibraryEvent.objects.count(), PlayerSession.objects.count())

    #: What the migration framework wraps this in.
    with pytest.raises(RuntimeError), transaction.atomic():
        convert_legacy_sessions(None, None)

    assert (LibraryEvent.objects.count(), PlayerSession.objects.count()) == before


@pytest.mark.untracked_games
def test_the_migration_reports_a_second_pass_that_appends(owned_library, monkeypatch):
    game = tracked_game(owned_library, "Chrono Trigger")
    legacy(game, timestamp_end=START + HOUR)
    passes = []

    def drifting(library, *, minted_at=None):
        counts = convert_library(library, minted_at=minted_at)
        passes.append(library)
        #: The second call over one library.
        if len(passes) % 2 == 0:
            return counts + ConversionCounts(buckets_minted=1)
        return counts

    monkeypatch.setattr(conversion, "convert_library", drifting)
    with pytest.raises(RuntimeError, match="count_drift"):
        convert_legacy_sessions(None, None)


@pytest.mark.untracked_games
def test_a_refused_row_aborts_and_still_emits(owned_library, capsys):
    game = tracked_game(owned_library, "Chrono Trigger")
    legacy(game, timestamp_end=START + HOUR)
    running = legacy(game, start=START + HOUR)
    with pytest.raises(ConversionRefused, match=f"Session {running.pk}"):
        convert_legacy_sessions(None, None)

    payload = _machine_payload(capsys)
    assert payload["summary"]["aborted"] == 1
    assert payload["summary"]["events_appended"] == 0


@pytest.mark.untracked_games
def test_the_migration_is_elidable_and_reversible_by_noop():
    (operation,) = _migration.Migration.operations
    assert operation.elidable is True
    assert operation.reverse_code is migrations.RunPython.noop
    assert _migration.Migration.dependencies == [("games", "0003_remove_game_playtime")]


@pytest.mark.untracked_games
def test_load_sample_data_converts_the_fixture(owned_user):
    call_command("load_sample_data", "--user", owned_user.username, verbosity=0)
    library = UserLibrary.objects.get(user=owned_user)

    assert Session.objects.filter(game__library=library).count() > 0
    assert PlayerSession.objects.filter(library=library).count() == (
        Session.objects.filter(game__library=library).count()
    )
    counts = convert_library(library)
    assert counts.events_appended == 0
    assert reconcile(library, counts) == []
    assert ordering_violations() == []


@pytest.mark.untracked_games
def test_reconcile_refreshes_the_planner_statistics_first(owned_library):
    """Uncommitted rows blind the planner."""
    _game, counts = seeded(owned_library)
    with CaptureQueriesContext(connection) as captured:
        reconcile(owned_library, counts)

    statements = [query["sql"] for query in captured.captured_queries]
    assert statements[0].startswith('ANALYZE "games_playersession"')
    assert '"games_libraryevent"' in statements[0]


# --- What the review added ----------------------------------------------------


def test_a_corrected_row_with_a_sub_second_total_refuses(owned_library):
    game = game_at(owned_library)
    row = legacy(
        game,
        timestamp_end=START + timedelta(microseconds=400_000),
        duration_manual=HOUR,
    )
    with pytest.raises(ConversionRefused, match="finer than a second"):
        convert(owned_library, row, run_of(owned_library, game))


def test_an_unknown_stated_zone_refuses(owned_library):
    game = game_at(owned_library)
    row = legacy(
        game, timestamp_end=START + HOUR, timestamp_start_timezone="Mars/Olympus"
    )
    with pytest.raises(ConversionRefused, match="Mars/Olympus"):
        convert(owned_library, row, run_of(owned_library, game))


def test_a_removed_running_row_drops_its_end_zone_into_the_evidence(owned_library):
    game = game_at(owned_library)
    row = legacy(game, timestamp_end_timezone="Europe/Prague")
    remove(row)
    convert(owned_library, row, run_of(owned_library, game))

    assert projection(row).ended_at_zone is None
    event = LibraryEvent.objects.get(event_type="library.playersession.created")
    assert event.source_metadata["legacy"]["timestamp_end_timezone"] == "Europe/Prague"


@pytest.mark.untracked_games
def test_a_wrongly_seeded_day_zone_is_reported(owned_library):
    _game, counts = seeded(owned_library)
    PlayerSession.objects.filter(note="x").update(day_zone="Asia/Tokyo")

    found = [
        m for m in reconcile(owned_library, counts) if m.code == "row_disagreement"
    ]
    assert len(found) == 1
    seeded_zone = display_zone_name(owned_library)
    assert f"day_zone: row says '{seeded_zone}', projection says 'Asia/Tokyo'" in (
        found[0].detail
    )


@pytest.mark.untracked_games
def test_a_second_pass_after_the_bucket_is_removed_refuses(owned_library):
    game, _counts = seeded(owned_library)
    (bucket,) = buckets_of(game)
    Playthrough.objects.filter(pk=bucket.pk).update(removed_at=timezone.now())
    legacy(game, start=datetime(2019, 1, 1, tzinfo=UTC), timestamp_end=START)

    with pytest.raises(ConversionRefused, match="an earlier pass minted one"):
        convert_library(owned_library)


def test_the_walk_defers_no_column(owned_library):
    """A column read but not named would load once per row."""
    game = game_at(owned_library)
    device = Device.objects.create(library=owned_library, name="Deck", type="PC")
    for day in (1, 2, 3):
        start = datetime(2024, 3, day, tzinfo=UTC)
        legacy(game, start=start, timestamp_end=start + HOUR, device=device, note="n")
    with CaptureQueriesContext(connection) as captured:
        convert_library(owned_library)

    unnamed = (
        '"games_session"."modified_at"',
        '"games_game"."name"',
        '"games_playergame"."status"',
        '"games_playthrough"."name"',
        '"games_device"."created_at"',
    )
    for query in captured.captured_queries:
        for column in unnamed:
            assert column not in query["sql"], query["sql"][:200]


def test_the_skipped_note_prefix_is_the_audits(owned_library):
    (entry,) = (model for model in identity_models_for("games_playersession"))
    blind = IdentityModel(
        model=entry.model,
        table=entry.table,
        identity_field=entry.identity_field,
        identity_column=entry.identity_column,
        order_source=None,
    )
    report = check_ordering([blind])
    assert report.notes[0].detail.startswith(SKIPPED_NOTE_PREFIX)


def identity_models_for(table):
    return [entry for entry in identity_models() if entry.table == table]


@pytest.mark.untracked_games
def test_a_moved_head_is_reported_as_a_replay_difference(owned_library, monkeypatch):
    _game, counts = seeded(owned_library)
    clean = TableDiff(
        table="games_playersession",
        live_rows=1,
        rebuilt_rows=1,
        only_live=0,
        only_rebuilt=0,
        differing=0,
        sample=(),
    )
    monkeypatch.setattr(
        conversion,
        "rebuild_projections",
        lambda library, *, mode: RebuildReport(
            library_id=library.pk,
            stream_id=None,
            mode=mode,
            swapped=False,
            replayed_through=10,
            head_at_diff=11,
            tables=(clean,),
            attempts=(),
            elapsed_seconds=0.0,
        ),
    )

    found = [m for m in reconcile(owned_library, counts) if m.code == "replay_differs"]
    assert [m.detail for m in found] == ["replayed through 10, the head stood at 11"]


def test_the_failure_sentence_counts_what_it_does_not_name():
    entries = [
        Mismatch(code=MismatchCode.COUNT_DRIFT, subject=str(n), detail="d").as_dict()
        for n in range(5)
    ]
    sentence = failure_sentence(entries, subject="Test")
    assert sentence.startswith("Test failed with 5 mismatch(es): count_drift 0: d;")
    assert sentence.endswith("; and 2 more")
    assert failure_sentence([], subject="Test") is None


def test_the_summary_keys_are_the_counts_fields():
    assert _migration.SUMMARY_KEYS == (*NO_COUNTS.as_dict(), "mismatches")


@pytest.mark.untracked_games
def test_the_migration_reports_every_library(owned_library, django_user_model, capsys):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    for library, name in ((owned_library, "Mine"), (stranger.library, "Theirs")):
        legacy(tracked_game(library, name), timestamp_end=START + HOUR)
    convert_legacy_sessions(None, None)

    payload = _machine_payload(capsys)
    assert payload["summary"]["libraries"] == 2
    assert payload["summary"]["timed"] == 2
    assert payload["mismatches"] == []


@pytest.mark.untracked_games
def test_the_migration_names_a_second_librarys_mismatch(
    owned_library, django_user_model, monkeypatch
):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    for library, name in ((owned_library, "Mine"), (stranger.library, "Theirs")):
        legacy(tracked_game(library, name), timestamp_end=START + HOUR)
    original = conversion.reconcile
    monkeypatch.setattr(
        conversion,
        "reconcile",
        lambda library, counts: (
            original(library, counts)
            + (_one_mismatch(library) if library.pk == stranger.library.pk else [])
        ),
    )
    with pytest.raises(RuntimeError, match=f"row_disagreement {stranger.library.pk}"):
        convert_legacy_sessions(None, None)


@pytest.mark.untracked_games
def test_the_migration_runs_from_the_schema_before_it(owned_library):
    """The tripwire for a later column: run 0004 at 0003."""
    from django.db.migrations.executor import MigrationExecutor

    game = tracked_game(owned_library, "Chrono Trigger")
    legacy(game, timestamp_end=START + HOUR)
    executor = MigrationExecutor(connection)
    executor.migrate([("games", "0003_remove_game_playtime")])
    executor = MigrationExecutor(connection)
    executor.migrate([("games", "0004_playersession_conversion")])

    assert PlayerSession.objects.filter(library=owned_library).count() == 1


@pytest.mark.untracked_games
def test_load_sample_data_refuses_a_mismatch_and_loads_nothing(owned_user, monkeypatch):
    monkeypatch.setattr(
        "games.management.commands.load_sample_data.reconcile",
        lambda library, counts: _one_mismatch(library),
    )
    with pytest.raises(CommandError, match="Sample session conversion failed with 1"):
        call_command("load_sample_data", "--user", owned_user.username, verbosity=0)

    assert Session.objects.count() == 0
    assert PlayerSession.objects.count() == 0


@pytest.mark.untracked_games
def test_load_sample_data_refuses_a_refused_row(owned_user, monkeypatch):
    def refusing(library, **kwargs):
        raise ConversionRefused("Session x is still running.")

    monkeypatch.setattr(
        "games.management.commands.load_sample_data.convert_library", refusing
    )
    with pytest.raises(CommandError, match="could not be converted: Session x"):
        call_command("load_sample_data", "--user", owned_user.username, verbosity=0)
