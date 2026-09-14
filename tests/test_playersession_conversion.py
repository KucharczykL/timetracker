"""What the legacy Session rows become. Issue #700."""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction
from django.utils import timezone

from games.backfill import playersession as conversion
from games.backfill.playersession import (
    ASSIGNMENT_FIELD,
    BUCKET_NAME,
    KEY_PREFIX,
    MODE_FIELD,
    MODE_VERDICTS,
    NO_COUNTS,
    ConversionCounts,
    ConversionRefused,
    convert_library,
    convert_row,
    display_zone_name,
    refuse_shared_game_rows,
)
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
from games.preflight.session import Assignment, AssignmentOutcome
from games.removal import remove
from tests.session_rows import tracked_run
from tests.test_playergame_playthrough_gate import UNREACHABLE_KINDS
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)

PRAGUE = ZoneInfo("Europe/Prague")
START = datetime(2024, 3, 1, 10, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


def game_at(library: UserLibrary, name: str = "Chrono Trigger") -> Game:
    return Game.objects.create(library=library, name=name)


def legacy(game: Game, start: datetime = START, **columns: object) -> Session:
    """One row, read back so the generated columns are filled."""
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
    #: The model fills a null on save; the column still admits one.
    Session.objects.filter(pk=row.pk).update(duration_manual=None)
    with pytest.raises(ConversionRefused, match="no manual duration"):
        convert(owned_library, row, run_of(owned_library, game))


def test_an_unknown_display_zone_refuses(owned_library, monkeypatch):
    #: The resolver refuses a spelling Python lacks before it
    #: is stored, so the check guards the database's tzdata.
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
    #: save() refuses it; the drift the ownership audit reports.
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
    #: PostgreSQL text holds no NUL, so the row is amended in memory.
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
    #: The event's own key sorts with the instant it records.
    assert event.pk < uuid.uuid7()


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


def test_every_mode_verdict_names_a_counts_field():
    #: convert_row indexes both maps, so a new verdict or
    #: outcome would raise KeyError on the row that first held it.
    assert set(MODE_FIELD) == set(MODE_VERDICTS)
    assert set(MODE_FIELD.values()) <= set(NO_COUNTS.as_dict())
    assert set(ASSIGNMENT_FIELD) == set(AssignmentOutcome)
    assert set(ASSIGNMENT_FIELD.values()) <= set(NO_COUNTS.as_dict())


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
    #: Synthetic overlap: production never holds two runs on one day.
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
    #: The projector's mark, so no removal helper states it.
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
    """The bucket is an importer's kind: only this walk states it."""
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
