"""Session facts for the legacy rows.

Every row in scope becomes one PlayerSession naming a run.
The census classifies the row and picks the run; the command
module's payload functions state it, so a value the command
refuses, this pass refuses too. A game whose runs cannot claim
a row gets one imported-history bucket, minted here.
"""

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta
from enum import StrEnum
from itertools import batched
from typing import NamedTuple, NoReturn, assert_never
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.db import connection, transaction
from django.db.models import QuerySet
from django.utils import timezone

from common.keyset import keyset_pages
from games.backfill.appending import append_one
from games.backfill.mismatch import Mismatch
from games.commands.playersession import (
    CorrectedTiming,
    DurationOnlyTiming,
    TimedTiming,
    TimingStatement,
    check_note,
    known_zone,
    normalized_timing,
    timing_payload,
)
from games.events.append import SourceMetadata, identity_at
from games.events.dispatch import CommandRejected
from games.events.playersession import (
    ZoneName,
    instant_text,
    playersession_created,
    playersession_removed,
)
from games.events.playthrough import playthrough_created, playthrough_name_changed
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.references import Reference, capture_reference
from games.identity_audit import check_ordering, identity_models
from games.models import (
    Device,
    Game,
    LibraryEvent,
    LibraryIdempotencyRecord,
    PlayerGame,
    PlayerSession,
    PlayerSessionTimingMode,
    Playthrough,
    PlaythroughKind,
    Session,
    UserLibrary,
)
from games.preflight.session import (
    MODE_VERDICTS,
    Assignment,
    AssignmentOutcome,
    RunInterval,
    TimingVerdict,
    assign_run,
    classify_timing,
    preflight_library,
)
from games.reads.playtime_parity import differing, display_zone, playtime_figures
from timetracker.settings_resolver import resolve_str_for_user

#: Named in every key and metadata value.
PLAYERSESSION_ISSUE = 700
KEY_PREFIX = f"backfill:{PLAYERSESSION_ISSUE}"
BUCKET_NAME = "Imported history — needs sorting"

#: Games per query.
CONVERSION_PAGE_SIZE = 200

#: Every column this module reads, per table.
#:
#: The migration runs this code against the concrete models while
#: the schema stands at 0004, so a bare query would select a column
#: a later migration adds and fail on the deployment. A column read
#: here and missing from its tuple is deferred, one query per row.
SESSION_FIELDS = (
    "id",
    "game_id",
    "timestamp_start",
    "timestamp_end",
    "timestamp_start_timezone",
    "timestamp_end_timezone",
    "duration_manual",
    "duration_calculated",
    "duration_total",
    "device_id",
    "note",
    "emulated",
    "created_at",
    "removed_at",
)
PLAYERGAME_FIELDS = ("id", "game_id", "library_id", "removed_at")
PLAYTHROUGH_FIELDS = (
    "id",
    "player_game_id",
    "kind",
    "removed_at",
    "created_at",
    "started_lower",
    "completed_upper",
)
GAME_FIELDS = ("id", "removed_at")
DEVICE_FIELDS = ("id", "library_id", "name", "type")
PLAYERSESSION_FIELDS = (
    "id",
    "playthrough_id",
    "device_id",
    "timing_mode",
    "started_at",
    "started_at_zone",
    "ended_at",
    "ended_at_zone",
    "stated_day",
    "effective_duration",
    "note",
    "emulated",
    "removed_at",
)

#: One microsecond, the unit the evidence counts in.
MICROSECOND = timedelta(microseconds=1)


class ConversionRefused(Exception):
    """A row this pass will not state. The message names it."""


@dataclass(frozen=True, slots=True)
class ConversionCounts:
    """What one pass did, summable everywhere."""

    libraries: int = 0
    #: Tracked games holding at least one row.
    tracked: int = 0
    #: Every row in scope, counted apart from the walk.
    rows_total: int = 0
    #: rows_total less the rows the walk converted.
    rows_unreached: int = 0
    live_rows: int = 0
    rows_removed_converted: int = 0
    timed: int = 0
    duration_only: int = 0
    corrected: int = 0
    #: A running row converts only once removed.
    running_removed: int = 0
    notes: int = 0
    devices: int = 0
    sole_run: int = 0
    contained: int = 0
    bucket: int = 0
    buckets_minted: int = 0
    events_appended: int = 0

    def __add__(self, other: ConversionCounts) -> ConversionCounts:
        return ConversionCounts(
            **{
                field.name: getattr(self, field.name) + getattr(other, field.name)
                for field in fields(self)
            }
        )

    def as_dict(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


#: The value an accumulation starts from.
NO_COUNTS = ConversionCounts()

#: The counts field one mode verdict adds to.
MODE_FIELD: Mapping[TimingVerdict, str] = {
    TimingVerdict.TIMED: "timed",
    TimingVerdict.DURATION_ONLY: "duration_only",
    TimingVerdict.CORRECTED: "corrected",
}

#: The counts field one assignment outcome adds to.
ASSIGNMENT_FIELD: Mapping[AssignmentOutcome, str] = {
    AssignmentOutcome.SOLE_RUN: "sole_run",
    AssignmentOutcome.CONTAINED: "contained",
    AssignmentOutcome.BUCKET: "bucket",
}


def display_zone_name(library: UserLibrary) -> ZoneName:
    """The zone the library counts days in, or a refusal."""
    name = resolve_str_for_user(library.user, "DISPLAY_TIME_ZONE")
    if not known_zone(name):
        raise ConversionRefused(
            f"Library {library.pk} displays days in {name!r}, a zone the "
            "database or Python does not know, so no day can be seeded in it."
        )
    return name


def _stated_zone(value: str | None) -> ZoneName | None:
    """NULL and blank both read as a zone nobody stated."""
    return value if value else None


def _refuse(row: Session, reason: str) -> ConversionRefused:
    return ConversionRefused(f"Session {row.pk} {reason}")


def statement_for(row: Session, *, day_zone: ZoneName) -> TimingStatement:
    """The statement one legacy row makes, or a refusal.

    A null manual duration is refused ahead of the verdict:
    classify_timing reads it as zero, and the census counts it
    beside the verdict, so the two agree on every row converted.
    """
    if row.duration_manual is None:
        raise _refuse(row, "states no manual duration, not even zero.")
    verdict = classify_timing(row)
    started_zone = _stated_zone(row.timestamp_start_timezone)
    ended_zone = _stated_zone(row.timestamp_end_timezone)
    statement: TimingStatement
    match verdict:
        case TimingVerdict.NEGATIVE_ELAPSED:
            raise _refuse(row, "ends before it starts.")
        case TimingVerdict.NEGATIVE_MANUAL:
            raise _refuse(row, "states a negative manual duration.")
        case TimingVerdict.RUNNING:
            if row.removed_at is None:
                raise _refuse(
                    row,
                    "is still running. Finish or correct it before converting.",
                )
            statement = TimedTiming(row.timestamp_start, day_zone, started_zone)
        case TimingVerdict.TIMED:
            statement = TimedTiming(
                row.timestamp_start,
                day_zone,
                started_zone,
                row.timestamp_end,
                ended_zone,
            )
        case TimingVerdict.DURATION_ONLY:
            statement = DurationOnlyTiming(
                row.timestamp_start.astimezone(ZoneInfo(day_zone)).date(),
                row.duration_manual,
            )
        case TimingVerdict.CORRECTED:
            #: `timestamp_end` is set: the verdict says so.
            assert row.timestamp_end is not None
            #: The total, not the manual part: legacy added the
            #: manual part to the elapsed time, the mode replaces it.
            statement = CorrectedTiming(
                row.timestamp_start,
                row.timestamp_end,
                row.duration_total,
                day_zone,
                started_zone,
                ended_zone,
            )
        case _:
            assert_never(verdict)
    return normalized_timing(statement)


def _microseconds(duration: timedelta | None) -> int | None:
    return None if duration is None else duration // MICROSECOND


def _instant_or_none(instant: datetime | None) -> str | None:
    return None if instant is None else instant_text(instant)


def legacy_evidence(
    row: Session, *, verdict: TimingVerdict, assignment: Assignment
) -> SourceMetadata:
    """Every legacy column the projection cannot carry.

    Microseconds, because an elapsed interval below a second is
    evidence too, and a payload states whole seconds. Nothing
    reads it; it is what survives the legacy table.
    """
    return {
        "origin": "backfill",
        "issue": PLAYERSESSION_ISSUE,
        "legacy": {
            "timestamp_start": instant_text(row.timestamp_start),
            "timestamp_end": _instant_or_none(row.timestamp_end),
            "timestamp_start_timezone": row.timestamp_start_timezone,
            "timestamp_end_timezone": row.timestamp_end_timezone,
            "duration_manual_microseconds": _microseconds(row.duration_manual),
            "duration_calculated_microseconds": _microseconds(row.duration_calculated),
            "duration_total_microseconds": _microseconds(row.duration_total),
            "created_at": instant_text(row.created_at),
            "verdict": verdict.value,
            "assignment": assignment.outcome.value,
            "claimers": assignment.claimers,
        },
    }


def _device_reference(row: Session, *, library: UserLibrary) -> Reference | None:
    """The device as named, removed or not; another library's refused."""
    if row.device_id is None:
        return None
    device = Device.objects.filter(pk=row.device_id).only(*DEVICE_FIELDS).first()
    if device is None:
        raise _refuse(row, f"names device {row.device_id}, which does not exist.")
    if device.library_id != library.pk:
        raise _refuse(
            row,
            f"names device {row.device_id} of library {device.library_id}, "
            f"not of library {library.pk}.",
        )
    return capture_reference(device)


def _stream_evidence() -> SourceMetadata:
    return {"origin": "backfill", "issue": PLAYERSESSION_ISSUE}


def convert_row(
    row: Session,
    *,
    library: UserLibrary,
    actor: User,
    run_id: uuid.UUID,
    assignment: Assignment,
    day_zone: ZoneName,
) -> ConversionCounts:
    """State one legacy row as its events.

    The block is this function's own: lock_stream refuses the head
    lock outside a transaction. Inside a caller's transaction it
    is a savepoint, so the migration still rolls everything back.
    """
    verdict = classify_timing(row)
    try:
        payload = timing_payload(statement_for(row, day_zone=day_zone))
        note = row.note.strip()
        check_note(note)
    except CommandRejected as refusal:
        raise _refuse(row, f"was refused: {refusal}") from refusal
    device = _device_reference(row, library=library)

    #: A bucket row names no run: the run it landed on is the
    #: identity this pass mints, fresh per pass, and naming it
    #: would answer a second pass with a key mismatch.
    command_input: dict[str, object] = {
        "session": str(row.pk),
        "assignment": assignment.outcome.value,
    }
    if assignment.outcome is not AssignmentOutcome.BUCKET:
        command_input["playthrough"] = str(run_id)

    mode_field = (
        "running_removed" if verdict is TimingVerdict.RUNNING else MODE_FIELD[verdict]
    )
    counts = ConversionCounts(
        live_rows=int(row.removed_at is None),
        rows_removed_converted=int(row.removed_at is not None),
        notes=int(bool(note)),
        devices=int(device is not None),
        **{mode_field: 1, ASSIGNMENT_FIELD[assignment.outcome]: 1},
    )
    evidence = legacy_evidence(row, verdict=verdict, assignment=assignment)
    #: One correlation for the row's acts, created and removed alike.
    correlation_id = uuid.uuid7()

    with transaction.atomic():
        if append_one(
            library,
            playersession_created(
                run_id,
                timing=payload,
                device=device,
                release=None,
                note=note,
                emulated=row.emulated,
                #: The legacy key, so every link to it keeps working.
                session_id=row.pk,
            ),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:playersession:created:{row.pk}",
            command_input=command_input,
            recorded_at=row.created_at,
            correlation_id=correlation_id,
            source_metadata=evidence,
        ):
            counts = counts + ConversionCounts(events_appended=1)

        if row.removed_at is not None and append_one(
            library,
            playersession_removed(row.pk),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:playersession:removed:{row.pk}",
            command_input={"session": str(row.pk), "fact": "removed"},
            #: The row's own mark, hence a second append.
            recorded_at=row.removed_at,
            correlation_id=correlation_id,
            source_metadata=evidence,
        ):
            counts = counts + ConversionCounts(events_appended=1)
    return counts


def runs_for(tracked_id: uuid.UUID, *, library: UserLibrary) -> list[RunInterval]:
    """The live ordinary runs at one tracked game, as intervals."""
    return [
        RunInterval(run_id, started, completed)
        for run_id, started, completed in Playthrough.objects.filter(
            library=library,
            player_game_id=tracked_id,
            player_game__library=library,
            removed_at__isnull=True,
            kind=PlaythroughKind.ORDINARY,
        )
        .order_by("created_at", "id")
        .values_list("id", "started_lower", "completed_upper")
    ]


def live_bucket(tracked_id: uuid.UUID, *, library: UserLibrary) -> uuid.UUID | None:
    """The game's live imported-history run, if one stands."""
    bucket = (
        Playthrough.objects.filter(
            library=library,
            player_game_id=tracked_id,
            player_game__library=library,
            removed_at__isnull=True,
            kind=PlaythroughKind.IMPORTED_HISTORY,
        )
        .only(*PLAYTHROUGH_FIELDS)
        .order_by("created_at", "id")
        .first()
    )
    return None if bucket is None else bucket.pk


class BucketRun(NamedTuple):
    """The bucket's identity, and what finding it cost."""

    run_id: uuid.UUID
    counts: ConversionCounts


def bucket_for(
    tracked: PlayerGame, *, library: UserLibrary, actor: User, minted_at: datetime
) -> BucketRun:
    """The game's bucket, minted only where none stands.

    Resolved by query first: a second pass finds the run the first
    minted, and never mints a second under the same key.
    """
    standing = live_bucket(tracked.pk, library=library)
    if standing is not None:
        return BucketRun(standing, NO_COUNTS)

    #: The importer's act, at the importer's instant.
    run_id = identity_at(minted_at)
    correlation_id = uuid.uuid7()
    counts = ConversionCounts(buckets_minted=1)
    with transaction.atomic():
        for event, key in (
            (
                playthrough_created(
                    tracked.pk, kind="imported_history", playthrough_id=run_id
                ),
                "bucket",
            ),
            (playthrough_name_changed(run_id, name=BUCKET_NAME), "bucket_name"),
        ):
            if append_one(
                library,
                event,
                actor=actor,
                idempotency_key=f"{KEY_PREFIX}:playthrough:{key}:{tracked.pk}",
                command_input={"player_game": str(tracked.pk)},
                recorded_at=minted_at,
                correlation_id=correlation_id,
                source_metadata=_stream_evidence(),
            ):
                counts = counts + ConversionCounts(events_appended=1)
    return BucketRun(run_id, counts)


def day_of(row: Session, zone: ZoneInfo) -> date:
    """The day the census assigns by."""
    return row.timestamp_start.astimezone(zone).date()


def convert_game(
    rows: Sequence[Session],
    *,
    library: UserLibrary,
    actor: User,
    tracked: PlayerGame,
    day_zone: ZoneName,
    minted_at: datetime,
) -> ConversionCounts:
    """State one game's rows, each at the run the census names.

    The bucket is minted on the first row that needs it, so a
    game whose runs claim every row gets none.
    """
    runs = runs_for(tracked.pk, library=library)
    zone = ZoneInfo(day_zone)
    counts = NO_COUNTS
    bucket_id: uuid.UUID | None = None
    for row in rows:
        assignment = assign_run(runs, day_of(row, zone))
        if assignment.outcome is AssignmentOutcome.BUCKET:
            if bucket_id is None:
                bucket = bucket_for(
                    tracked, library=library, actor=actor, minted_at=minted_at
                )
                bucket_id = bucket.run_id
                counts = counts + bucket.counts
            run_id = bucket_id
        else:
            #: The census names one for both other outcomes.
            assert assignment.run_id is not None
            run_id = assignment.run_id
        counts = counts + convert_row(
            row,
            library=library,
            actor=actor,
            run_id=run_id,
            assignment=assignment,
            day_zone=day_zone,
        )
    return counts


def rows_the_walk_reaches(library: UserLibrary) -> QuerySet[Session]:
    """Every row in the census's scope: on a game the library owns."""
    return Session.objects.filter(game__library=library)


def refuse_shared_game_rows() -> None:
    """A row at a game no library owns is outside every walk."""
    shared = Session.objects.filter(game__library__isnull=True).order_by("id")
    first = shared.only("id", "game_id").first()
    if first is not None:
        raise ConversionRefused(
            f"Session {first.pk} is at game {first.game_id}, which no library "
            f"owns, so no library's walk reaches it ({shared.count()} such rows)."
        )


class GameRows(NamedTuple):
    """One page's rows and tracking, keyed on the game."""

    sessions: Mapping[uuid.UUID, list[Session]]
    live_tracking: Mapping[uuid.UUID, PlayerGame]
    removed_tracking: frozenset[uuid.UUID]


def _page_rows(game_ids: Sequence[uuid.UUID], *, library: UserLibrary) -> GameRows:
    sessions: dict[uuid.UUID, list[Session]] = defaultdict(list)
    for row in (
        Session.objects.filter(game_id__in=game_ids)
        .only(*SESSION_FIELDS)
        .order_by("id")
    ):
        sessions[row.game_id].append(row)
    live_tracking: dict[uuid.UUID, PlayerGame] = {}
    removed_tracking: set[uuid.UUID] = set()
    for tracking_row in PlayerGame.objects.filter(
        library=library, game_id__in=game_ids
    ).only(*PLAYERGAME_FIELDS):
        if tracking_row.removed_at is None:
            live_tracking[tracking_row.game_id] = tracking_row
        else:
            removed_tracking.add(tracking_row.game_id)
    return GameRows(sessions, live_tracking, frozenset(removed_tracking))


def _refuse_game(game: Game, rows: Sequence[Session], category: str) -> NoReturn:
    raise ConversionRefused(
        f"Session {rows[0].pk} is at game {game.pk}, {category}, so it has no "
        f"run to name ({len(rows)} such rows at this game)."
    )


def convert_library(
    library: UserLibrary, *, minted_at: datetime | None = None
) -> ConversionCounts:
    """State every row at a game this library owns, removed included.

    Walks games, as the census does, so a row on an untracked,
    removed-tracking or removed game is visited and refused by
    name rather than left as an anonymous residual.
    """
    refuse_shared_game_rows()
    minted_at = timezone.now() if minted_at is None else minted_at
    actor = library.user
    day_zone = display_zone_name(library)
    counts = ConversionCounts(libraries=1)

    owned = Game.objects.filter(library=library).only(*GAME_FIELDS)
    for batch in batched(
        keyset_pages(owned, key=("id",), page_size=CONVERSION_PAGE_SIZE),
        CONVERSION_PAGE_SIZE,
    ):
        page = _page_rows([game.pk for game in batch], library=library)
        for game in batch:
            rows = page.sessions.get(game.pk, [])
            if not rows:
                continue
            if game.removed_at is not None:
                _refuse_game(game, rows, "which the catalog marks removed")
            tracked = page.live_tracking.get(game.pk)
            if tracked is None:
                _refuse_game(
                    game,
                    rows,
                    "whose tracking row is removed"
                    if game.pk in page.removed_tracking
                    else "which the library does not track",
                )
            counts = counts + ConversionCounts(tracked=1)
            counts = counts + convert_game(
                rows,
                library=library,
                actor=actor,
                tracked=tracked,
                day_zone=day_zone,
                minted_at=minted_at,
            )

    #: Counted apart from the walk, and by a different query, so
    #: a row the walk never reached is a number and not a silence.
    total = rows_the_walk_reaches(library).count()
    converted = counts.live_rows + counts.rows_removed_converted
    return counts + ConversionCounts(rows_total=total, rows_unreached=total - converted)


class MismatchCode(StrEnum):
    """Every reason this run refuses to commit."""

    ROW_DISAGREEMENT = "row_disagreement"
    REMOVED_ROW_DISAGREEMENT = "removed_row_disagreement"
    CENSUS_DRIFT = "census_drift"
    ROWS_UNREACHED = "rows_unreached"
    BUCKET_SURPLUS = "bucket_surplus"
    BUCKET_MEMBERSHIP = "bucket_membership"
    PLAYTIME_DIFFERS = "playtime_differs"
    COUNT_DRIFT = "count_drift"
    IDENTITY_ORDERING = "identity_ordering"
    IDENTITY_AUDIT_BLIND = "identity_audit_blind"
    REPLAY_DIFFERS = "replay_differs"


class RowShape(NamedTuple):
    """What a legacy row and its projection row must both say."""

    mode: str
    playthrough_id: uuid.UUID | None
    started_at: datetime | None
    started_at_zone: str | None
    ended_at: datetime | None
    ended_at_zone: str | None
    stated_day: date | None
    effective_duration: timedelta | None
    device_id: uuid.UUID | None
    note: str
    emulated: bool
    removed_at: datetime | None


def _legacy_shape(
    row: Session, *, run_id: uuid.UUID | None, zone: ZoneInfo
) -> RowShape:
    """The row's statement, read the way the walk read it."""
    verdict = classify_timing(row)
    mode = (
        PlayerSessionTimingMode.TIMED
        if verdict is TimingVerdict.RUNNING
        else PlayerSessionTimingMode(verdict.value)
    )
    instants = verdict is not TimingVerdict.DURATION_ONLY
    return RowShape(
        mode=mode.value,
        playthrough_id=run_id,
        started_at=row.timestamp_start if instants else None,
        started_at_zone=_stated_zone(row.timestamp_start_timezone)
        if instants
        else None,
        ended_at=row.timestamp_end if instants else None,
        ended_at_zone=_stated_zone(row.timestamp_end_timezone)
        if instants and row.timestamp_end is not None
        else None,
        stated_day=None if instants else day_of(row, zone),
        effective_duration=row.duration_total,
        device_id=row.device_id,
        note=row.note.strip(),
        emulated=row.emulated,
        removed_at=row.removed_at,
    )


def _projection_shape(row: PlayerSession) -> RowShape:
    return RowShape(
        mode=row.timing_mode,
        playthrough_id=row.playthrough_id,
        started_at=row.started_at,
        started_at_zone=row.started_at_zone,
        ended_at=row.ended_at,
        ended_at_zone=row.ended_at_zone,
        stated_day=row.stated_day,
        effective_duration=row.effective_duration,
        device_id=row.device_id,
        note=row.note,
        emulated=row.emulated,
        removed_at=row.removed_at,
    )


def _differences(expected: RowShape, found: RowShape) -> str:
    return ", ".join(
        f"{name}: row says {left!r}, projection says {right!r}"
        for name, left, right in zip(RowShape._fields, expected, found, strict=True)
        if left != right
    )


class ExpectedRuns(NamedTuple):
    """Where each row of one game lands, read again from legacy."""

    run_by_row: Mapping[uuid.UUID, uuid.UUID | None]
    bucketed: frozenset[uuid.UUID]


def _expected_runs(
    rows: Sequence[Session],
    *,
    tracked: PlayerGame,
    library: UserLibrary,
    zone: ZoneInfo,
) -> ExpectedRuns:
    """The census's answer per row, with the bucket resolved by query."""
    runs = runs_for(tracked.pk, library=library)
    bucket_id = live_bucket(tracked.pk, library=library)
    run_by_row: dict[uuid.UUID, uuid.UUID | None] = {}
    bucketed: set[uuid.UUID] = set()
    for row in rows:
        assignment = assign_run(runs, day_of(row, zone))
        if assignment.outcome is AssignmentOutcome.BUCKET:
            run_by_row[row.pk] = bucket_id
            bucketed.add(row.pk)
        else:
            run_by_row[row.pk] = assignment.run_id
    return ExpectedRuns(run_by_row, frozenset(bucketed))


def _reconcile_game(
    game_id: uuid.UUID,
    rows: Sequence[Session],
    *,
    tracked: PlayerGame,
    library: UserLibrary,
    zone: ZoneInfo,
) -> list[Mismatch[MismatchCode]]:
    """Checks 1 and 3, one game."""
    mismatches: list[Mismatch[MismatchCode]] = []
    expected = _expected_runs(rows, tracked=tracked, library=library, zone=zone)
    projected = {
        projection.pk: projection
        for projection in PlayerSession.objects.filter(
            library=library, pk__in=[row.pk for row in rows]
        ).only(*PLAYERSESSION_FIELDS)
    }

    #: Check 1, both populations apart: a removed row's
    #: columns are as unrecoverable as a live one's.
    for row in rows:
        code = (
            MismatchCode.ROW_DISAGREEMENT
            if row.removed_at is None
            else MismatchCode.REMOVED_ROW_DISAGREEMENT
        )
        projection = projected.get(row.pk)
        if projection is None:
            mismatches.append(
                Mismatch(code=code, subject=str(row.pk), detail="no projection row")
            )
            continue
        legacy = _legacy_shape(row, run_id=expected.run_by_row[row.pk], zone=zone)
        found = _projection_shape(projection)
        if legacy != found:
            mismatches.append(
                Mismatch(
                    code=code, subject=str(row.pk), detail=_differences(legacy, found)
                )
            )

    #: Check 3.
    buckets = list(
        Playthrough.objects.filter(
            library=library,
            player_game=tracked,
            removed_at__isnull=True,
            kind=PlaythroughKind.IMPORTED_HISTORY,
        )
        .only(*PLAYTHROUGH_FIELDS)
        .order_by("created_at", "id")
    )
    if len(buckets) > 1:
        mismatches.append(
            Mismatch(
                code=MismatchCode.BUCKET_SURPLUS,
                subject=str(game_id),
                detail=f"{len(buckets)} live imported-history runs; one is the most",
            )
        )
    if buckets and not expected.bucketed:
        mismatches.append(
            Mismatch(
                code=MismatchCode.BUCKET_SURPLUS,
                subject=str(game_id),
                detail="a bucket stands where no row needs one",
            )
        )
    for bucket in buckets:
        naming = frozenset(
            PlayerSession.objects.filter(
                library=library, playthrough=bucket
            ).values_list("pk", flat=True)
        )
        if naming != expected.bucketed:
            mismatches.append(
                Mismatch(
                    code=MismatchCode.BUCKET_MEMBERSHIP,
                    subject=str(game_id),
                    detail=f"bucket {bucket.pk} holds {sorted(map(str, naming))}, "
                    f"the census buckets {sorted(map(str, expected.bucketed))}",
                )
            )
    return mismatches


def _census_mismatches(
    library: UserLibrary, counts: ConversionCounts
) -> list[Mismatch[MismatchCode]]:
    """Check 2: the pass and the census counted the same rows."""
    census = preflight_library(library, sample_size=0).counts
    #: The secondary column is the display zone, which the
    #: pass seeds day_zone from; a test pins that.
    pairs = (
        ("timed", counts.timed, census.timed),
        ("duration_only", counts.duration_only, census.duration_only),
        ("corrected", counts.corrected, census.corrected),
        ("running", counts.running_removed, census.running),
        ("removed", counts.rows_removed_converted, census.removed),
        ("sole_run", counts.sole_run, census.sole_run),
        ("contained", counts.contained, census.contained_secondary),
        ("bucket", counts.bucket, census.bucket_secondary),
    )
    mismatches = [
        Mismatch(
            code=MismatchCode.CENSUS_DRIFT,
            subject=str(library.pk),
            detail=f"the pass counted {name}={converted}, the census {counted}",
        )
        for name, converted, counted in pairs
        if converted != counted
    ]
    if counts.rows_unreached:
        mismatches.append(
            Mismatch(
                code=MismatchCode.ROWS_UNREACHED,
                subject=str(library.pk),
                detail=f"{counts.rows_unreached} legacy row(s) in scope the walk "
                "did not convert",
            )
        )
    return mismatches


def _count_mismatches(library: UserLibrary) -> list[Mismatch[MismatchCode]]:
    """Check 5: as many projection rows as legacy rows, live and removed."""
    legacy = rows_the_walk_reaches(library)
    projection = PlayerSession.objects.filter(library=library)
    mismatches: list[Mismatch[MismatchCode]] = []
    for population, condition in (("live", True), ("removed", False)):
        expected = legacy.filter(removed_at__isnull=condition).count()
        found = projection.filter(removed_at__isnull=condition).count()
        if expected != found:
            mismatches.append(
                Mismatch(
                    code=MismatchCode.COUNT_DRIFT,
                    subject=str(library.pk),
                    detail=f"{expected} {population} legacy row(s), "
                    f"{found} {population} projection row(s)",
                )
            )
    return mismatches


def _playtime_mismatches(library: UserLibrary) -> list[Mismatch[MismatchCode]]:
    """Check 4: every figure agrees, read in the zone the rows were seeded in."""
    return [
        Mismatch(
            code=MismatchCode.PLAYTIME_DIFFERS,
            subject=str(figure.scope),
            detail=f"legacy {figure.legacy}, projection {figure.projection}",
        )
        for figure in differing(playtime_figures(library, display_zone(library)))
    ]


def _replay_mismatches(library: UserLibrary) -> list[Mismatch[MismatchCode]]:
    """Check 7: a replay from the stream reproduces every row."""
    report = rebuild_projections(library, mode=RebuildMode.CHECK)
    mismatches = [
        Mismatch(
            code=MismatchCode.REPLAY_DIFFERS,
            subject=table.table,
            detail=f"only_live={table.only_live} only_rebuilt={table.only_rebuilt} "
            f"differing={table.differing} sample={list(table.sample)}",
        )
        for table in report.tables
        if table.only_live or table.only_rebuilt or table.differing
    ]
    if report.head_at_diff != report.replayed_through:
        mismatches.append(
            Mismatch(
                code=MismatchCode.REPLAY_DIFFERS,
                subject=str(library.pk),
                detail=f"replayed through {report.replayed_through}, the head "
                f"stood at {report.head_at_diff}",
            )
        )
    return mismatches


#: The tables this pass fills, read again before commit.
FILLED_TABLES = (PlayerSession, LibraryEvent, LibraryIdempotencyRecord, Playthrough)


def refresh_statistics() -> None:
    """ANALYZE what the pass wrote, so the gate's reads plan well.

    The rows are uncommitted, so the planner still holds the
    statistics of the tables as they stood before: empty. The
    parity read then joins thousands of rows as if they were
    none, and takes minutes where it takes seconds. ANALYZE is
    allowed inside a transaction; VACUUM is not, and none is needed.
    """
    tables = ", ".join(
        connection.ops.quote_name(model._meta.db_table) for model in FILLED_TABLES
    )
    with connection.cursor() as cursor:
        cursor.execute(f"ANALYZE {tables}")


def reconcile(
    library: UserLibrary, counts: ConversionCounts
) -> list[Mismatch[MismatchCode]]:
    """Every reading but the identity audit, per library.

    Row to row, the census, the buckets, playtime parity, the
    counts, and a replay. Ordered cheap to dear, and all of them
    run: one mismatch says less than the whole list.
    """
    refresh_statistics()
    zone = ZoneInfo(display_zone_name(library))
    mismatches: list[Mismatch[MismatchCode]] = []
    owned = Game.objects.filter(library=library).only(*GAME_FIELDS)
    for batch in batched(
        keyset_pages(owned, key=("id",), page_size=CONVERSION_PAGE_SIZE),
        CONVERSION_PAGE_SIZE,
    ):
        page = _page_rows([game.pk for game in batch], library=library)
        for game in batch:
            rows = page.sessions.get(game.pk, [])
            tracked = page.live_tracking.get(game.pk)
            if not rows or tracked is None or game.removed_at is not None:
                #: The walk refused it, so nothing stands to compare.
                continue
            mismatches.extend(
                _reconcile_game(
                    game.pk, rows, tracked=tracked, library=library, zone=zone
                )
            )
    mismatches.extend(_census_mismatches(library, counts))
    mismatches.extend(_playtime_mismatches(library))
    mismatches.extend(_count_mismatches(library))
    mismatches.extend(_replay_mismatches(library))
    return mismatches


#: The tables whose keys this pass mints or reuses.
AUDITED_TABLES = (PlayerSession._meta.db_table, Playthrough._meta.db_table)


def ordering_violations() -> list[Mismatch[MismatchCode]]:
    """Check 6: every key sorts by its created_at, on both tables.

    No constraint enforces it, and this run is most able to break
    it: a reused legacy key dated by the row's own instant, and a
    bucket minted now.
    """
    mismatches: list[Mismatch[MismatchCode]] = []
    audited = {entry.table: entry for entry in identity_models()}
    entries = []
    for table in AUDITED_TABLES:
        entry = audited.get(table)
        if entry is None:
            #: An empty list checks clean, so absence has to speak.
            mismatches.append(
                Mismatch(
                    code=MismatchCode.IDENTITY_AUDIT_BLIND,
                    subject=table,
                    detail="the identity audit holds no entry for this table, "
                    "so check 6 examined nothing",
                )
            )
        else:
            entries.append(entry)
    report = check_ordering(entries)
    mismatches.extend(
        Mismatch(
            code=MismatchCode.IDENTITY_ORDERING,
            subject=violation.subject,
            detail=violation.detail,
        )
        for violation in report.violations
    )
    #: A skipped model reports no violation either.
    mismatches.extend(
        Mismatch(
            code=MismatchCode.IDENTITY_AUDIT_BLIND,
            subject=note.subject,
            detail=note.detail,
        )
        for note in report.notes
        if note.detail.startswith("skipped:")
    )
    return mismatches


__all__ = [
    "ASSIGNMENT_FIELD",
    "BUCKET_NAME",
    "KEY_PREFIX",
    "MODE_FIELD",
    "MODE_VERDICTS",
    "NO_COUNTS",
    "PLAYERSESSION_ISSUE",
    "ConversionCounts",
    "ConversionRefused",
    "Mismatch",
    "MismatchCode",
    "RowShape",
    "bucket_for",
    "convert_game",
    "convert_library",
    "convert_row",
    "display_zone_name",
    "legacy_evidence",
    "ordering_violations",
    "reconcile",
    "refuse_shared_game_rows",
    "rows_the_walk_reaches",
    "runs_for",
    "statement_for",
]
