"""Playthrough facts for the legacy rows. #684.

Every row in scope becomes one ordinary run stating both
acts. A row carrying no date is still the library's record
that a run happened, which is #681's "played before": a
marker set beside a null day.
"""

import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from datetime import date, datetime
from itertools import batched
from operator import attrgetter
from typing import Any, NamedTuple

from django.contrib.auth.models import User
from django.db import transaction

from common.keyset import keyset_pages
from games.events.append import LockedStream, SourceMetadata, identity_at
from games.events.idempotency import ReplayedAppend, idempotent_append
from games.events.playthrough import (
    playthrough_completed,
    playthrough_created,
    playthrough_note_changed,
    playthrough_removed,
    playthrough_started,
)
from games.events.vocabulary import NewEvent
from games.identity_audit import check_ordering, identity_models
from games.models import Game, PlayerGame, PlayEvent, Playthrough, UserLibrary
from games.preflight.playthrough import (
    CandidateEvent,
    Endpoint,
    EndpointKind,
    Pairing,
    RowVerdict,
    candidate_events,
    classify_row,
    legacy_order_key,
    pair_endpoints,
)
from games.reads.playthrough_numbering import with_display_number
from timetracker.temporal import TemporalValue

#: Named in every key and metadata value.
PTHROUGH_ISSUE = 684
KEY_PREFIX = "backfill:684:playthrough"

#: Aggregates per query.
CONVERSION_PAGE_SIZE = 200

#: Every PlayEvent field this module reads.
#:
#: 0045 replays this code against the concrete model, so a bare query
#: selects the columns PlayEvent declares today. A field read here and
#: missing from this tuple is deferred, and reading it raises
#: UndefinedColumn one page later.
PLAYEVENT_FIELDS = (
    "created_at",
    "ended",
    "game_id",
    "note",
    "removed_at",
    "started",
)


@dataclass(frozen=True, slots=True)
class ConversionCounts:
    """What one pass did, summable everywhere."""

    libraries: int = 0
    tracked: int = 0
    tracked_on_removed_game: int = 0
    live_rows: int = 0
    rows_removed_converted: int = 0
    clean_both: int = 0
    clean_start_only: int = 0
    clean_end_only: int = 0
    no_known_endpoint: int = 0
    reversed_endpoints: int = 0
    runs_converted: int = 0
    runs_default: int = 0
    notes: int = 0
    endpoints_paired: int = 0
    endpoints_fresh: int = 0
    endpoints_dayless: int = 0
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

#: The counts field one verdict adds to.
VERDICT_FIELD: Mapping[RowVerdict, str] = {
    RowVerdict.CLEAN_BOTH: "clean_both",
    RowVerdict.CLEAN_START_ONLY: "clean_start_only",
    RowVerdict.CLEAN_END_ONLY: "clean_end_only",
    RowVerdict.NO_KNOWN_ENDPOINT: "no_known_endpoint",
    RowVerdict.REVERSED_ENDPOINTS: "reversed_endpoints",
}


def _append(
    library: UserLibrary,
    event: NewEvent,
    *,
    actor: User,
    idempotency_key: str,
    command_input: dict[str, Any],
    recorded_at: datetime,
    correlation_id: uuid.UUID,
    source_metadata: SourceMetadata,
) -> bool:
    """Append one event. True when it appended.

    One event per call, never one call per row:
    LockedStream.append() stamps one recorded_at across every row
    of a call, and a removed legacy row carries two instants.

    No command_input names an aggregate id. Every identity is
    minted fresh per pass, so a fingerprint holding one answers a
    second pass with IdempotencyKeyMismatch, in place of the drift
    the gate reads.

    dispatch() is not used: its refusals guard what a person
    states next, and this states what the library recorded.
    """

    def build(stream: LockedStream) -> Sequence[NewEvent]:
        #: The contract passes it; nothing reads it.
        del stream
        return [event]

    outcome = idempotent_append(
        library,
        idempotency_key=idempotency_key,
        command_input=command_input,
        build=build,
        actor=actor,
        correlation_id=correlation_id,
        source_metadata=source_metadata,
        recorded_at=recorded_at,
    )
    return not isinstance(outcome, ReplayedAppend)


def convert_row(
    row: PlayEvent,
    *,
    library: UserLibrary,
    actor: User,
    tracked_id: uuid.UUID,
    pairings: Mapping[Endpoint, Pairing],
) -> ConversionCounts:
    """State one legacy row as one run.

    The block is this function's own: lock_stream refuses the head
    lock outside a transaction. Inside a caller's transaction it
    is a savepoint, so the migration still rolls everything back.
    """
    metadata: SourceMetadata = {
        "origin": "backfill",
        "issue": PTHROUGH_ISSUE,
        #: Provenance, not a lookup. A string, because
        #: canonical_json refuses a UUID.
        "play_event_id": str(row.pk),
    }
    verdict = classify_row(row)
    counts = ConversionCounts(
        runs_converted=1,
        live_rows=int(row.removed_at is None),
        rows_removed_converted=int(row.removed_at is not None),
        **{VERDICT_FIELD[verdict]: 1},
    )
    #: The row's own instant, so created_at is the day
    #: the row was written and the identity sorts with it.
    recorded_at = row.created_at
    run_id = identity_at(recorded_at)

    with transaction.atomic():
        #: Always first: amend() raises without it.
        if _append(
            library,
            playthrough_created(tracked_id, playthrough_id=run_id),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:created:{row.pk}",
            command_input={"fact": "created", "play_event_id": str(row.pk)},
            recorded_at=recorded_at,
            correlation_id=uuid.uuid7(),
            source_metadata=metadata,
        ):
            counts = replace(counts, events_appended=counts.events_appended + 1)

        if row.note and _append(
            library,
            playthrough_note_changed(run_id, note=row.note),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:note:{row.pk}",
            command_input={
                "fact": "note",
                "play_event_id": str(row.pk),
                #: Named, so a changed note is loud.
                "note": row.note,
            },
            recorded_at=recorded_at,
            correlation_id=uuid.uuid7(),
            source_metadata=metadata,
        ):
            counts = replace(
                counts, notes=1, events_appended=counts.events_appended + 1
            )

        for kind, day, build_event, word in (
            (EndpointKind.START, row.started, playthrough_started, "started"),
            (EndpointKind.COMPLETION, row.ended, playthrough_completed, "completed"),
        ):
            correlation_id = uuid.uuid7()
            if day is None:
                counts = replace(counts, endpoints_dayless=counts.endpoints_dayless + 1)
            else:
                paired = pairings.get(
                    Endpoint(
                        row_id=row.pk,
                        kind=kind,
                        day=day,
                        aggregate_id=tracked_id,
                    )
                )
                adopted = None if paired is None else paired.correlation_id
                if adopted is None:
                    counts = replace(counts, endpoints_fresh=counts.endpoints_fresh + 1)
                else:
                    correlation_id = adopted
                    counts = replace(
                        counts, endpoints_paired=counts.endpoints_paired + 1
                    )
            if _append(
                library,
                build_event(
                    run_id,
                    #: None, not unknown(): the column holds
                    #: None either way.
                    when=None if day is None else TemporalValue.from_day(day),
                    note="",
                ),
                actor=actor,
                idempotency_key=f"{KEY_PREFIX}:{word}:{row.pk}",
                command_input={
                    "fact": word,
                    "play_event_id": str(row.pk),
                    #: Named, so a changed day is loud.
                    "day": day,
                },
                recorded_at=recorded_at,
                correlation_id=correlation_id,
                source_metadata=metadata,
            ):
                counts = replace(counts, events_appended=counts.events_appended + 1)

        if row.removed_at is not None and _append(
            library,
            playthrough_removed(run_id),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:removed:{row.pk}",
            command_input={"fact": "removed", "play_event_id": str(row.pk)},
            #: The row's own mark, hence a second append.
            recorded_at=row.removed_at,
            correlation_id=uuid.uuid7(),
            source_metadata=metadata,
        ):
            counts = replace(counts, events_appended=counts.events_appended + 1)

    return counts


def convert_game(
    rows: Sequence[PlayEvent],
    *,
    library: UserLibrary,
    actor: User,
    tracked_id: uuid.UUID,
    tracked_at: datetime,
    candidates: Sequence[CandidateEvent],
) -> ConversionCounts:
    """State one game's rows, and its default run.

    Pairing runs here because a group is keyed on the PlayerGame,
    so no group spans two games. The candidates are this game's
    alone, which is why unclaimed_events is not read.
    """
    endpoints = [
        Endpoint(row_id=row.pk, kind=kind, day=day, aggregate_id=tracked_id)
        for row in rows
        for kind, day in (
            (EndpointKind.START, row.started),
            (EndpointKind.COMPLETION, row.ended),
        )
        if day is not None
    ]
    pairings = pair_endpoints(endpoints, candidates).pairings

    counts = NO_COUNTS
    #: legacy_order_key, so identities ascend with the rows.
    for row in sorted(rows, key=legacy_order_key):
        counts = counts + convert_row(
            row,
            library=library,
            actor=actor,
            tracked_id=tracked_id,
            pairings=pairings,
        )

    #: "No live run", not "no legacy row": a game whose only
    #: row was removed still needs the live one. One live row is
    #: one live run, so no query is needed.
    if any(row.removed_at is None for row in rows):
        return counts

    counts = counts + ConversionCounts(runs_default=1)
    #: Its own block, as convert_row's is.
    with transaction.atomic():
        if _append(
            library,
            playthrough_created(tracked_id, playthrough_id=identity_at(tracked_at)),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:default:{tracked_id}",
            command_input={"fact": "default", "player_game_id": str(tracked_id)},
            #: Open since the library tracked the game.
            recorded_at=tracked_at,
            correlation_id=uuid.uuid7(),
            source_metadata={"origin": "backfill", "issue": PTHROUGH_ISSUE},
        ):
            counts = counts + ConversionCounts(events_appended=1)
    return counts


def _rows_for_games(batch: Sequence[PlayerGame]) -> dict[uuid.UUID, list[PlayEvent]]:
    """One batch's live games, each with its rows.

    A game the catalog marks removed is absent, which the caller
    counts as tracked_on_removed_game.
    """
    live_games = set(
        Game.objects.filter(
            pk__in=[row.game_id for row in batch], removed_at__isnull=True
        )
        .only("id")
        .values_list("pk", flat=True)
    )
    rows: dict[uuid.UUID, list[PlayEvent]] = {game_id: [] for game_id in live_games}
    for row in PlayEvent.objects.filter(game_id__in=live_games).only(*PLAYEVENT_FIELDS):
        rows[row.game_id].append(row)
    return rows


def convert_library(library: UserLibrary) -> ConversionCounts:
    """State every row this library tracks, removed included.

    The preflight's walk takes live rows only. #771 takes the
    legacy table away, so a skipped removed row is a record that
    survives this run and not the next one.
    """
    actor = library.user
    counts = ConversionCounts(libraries=1)
    candidates_by_game: dict[uuid.UUID, list[CandidateEvent]] = defaultdict(list)
    for candidate in candidate_events(library).candidates:
        candidates_by_game[candidate.key.aggregate_id].append(candidate)

    tracked = PlayerGame.objects.filter(library=library, removed_at__isnull=True).only(
        "id", "game_id", "tracked_at"
    )
    for batch in batched(
        keyset_pages(tracked, key=("id",), page_size=CONVERSION_PAGE_SIZE),
        CONVERSION_PAGE_SIZE,
    ):
        rows_for_game = _rows_for_games(batch)
        for tracked_row in batch:
            counts = counts + ConversionCounts(tracked=1)
            if tracked_row.game_id not in rows_for_game:
                counts = counts + ConversionCounts(tracked_on_removed_game=1)
                continue
            counts = counts + convert_game(
                rows_for_game[tracked_row.game_id],
                library=library,
                actor=actor,
                tracked_id=tracked_row.pk,
                tracked_at=tracked_row.tracked_at,
                candidates=candidates_by_game.get(tracked_row.pk, []),
            )
    return counts


@dataclass(frozen=True, slots=True)
class Mismatch:
    """One reason the run must not commit."""

    code: str
    game_id: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail, "game_id": self.game_id}


class RunShape(NamedTuple):
    """What a row and its run must both say."""

    started: date | None
    completed: date | None
    note: str


def _row_shape(row: PlayEvent) -> RunShape:
    return RunShape(started=row.started, completed=row.ended, note=row.note)


def _run_shape(run: Playthrough) -> RunShape:
    #: The bounds the database generated.
    return RunShape(
        started=run.started_lower, completed=run.completed_lower, note=run.note
    )


def _states_an_act(run: Playthrough) -> bool:
    """A run a legacy row became, not a default."""
    return run.start_recorded_at is not None or run.completion_recorded_at is not None


def _reconcile_game(
    game_id: str, rows: Sequence[PlayEvent], tracked_id: uuid.UUID
) -> list[Mismatch]:
    """The four row-to-row checks, one game."""
    mismatches: list[Mismatch] = []
    runs = list(Playthrough.objects.filter(player_game_id=tracked_id))
    live_runs = [run for run in runs if run.removed_at is None]
    live_rows = [row for row in rows if row.removed_at is None]
    removed_rows = [row for row in rows if row.removed_at is not None]
    removed_runs = [run for run in runs if run.removed_at is not None]

    #: Check 1. A multiset: two rows saying the same thing
    #: are not distinguished, and neither side is ordered.
    expected = Counter(_row_shape(row) for row in live_rows)
    converted = Counter(_run_shape(run) for run in live_runs if _states_an_act(run))
    if expected != converted:
        mismatches.append(
            Mismatch(
                code="run_disagreement",
                game_id=game_id,
                detail=f"the rows say {sorted(expected.items())}, "
                f"the runs say {sorted(converted.items())}",
            )
        )
    for run in live_runs:
        markers = (run.start_recorded_at, run.completion_recorded_at)
        if any(marker is None for marker in markers) and not all(
            marker is None for marker in markers
        ):
            mismatches.append(
                Mismatch(
                    code="missing_marker",
                    game_id=game_id,
                    detail=f"run {run.pk} states one act and not the other",
                )
            )

    #: Check 2.
    if len(removed_runs) != len(removed_rows):
        mismatches.append(
            Mismatch(
                code="removed_run_missing",
                game_id=game_id,
                detail=f"{len(removed_rows)} removed row(s), "
                f"{len(removed_runs)} removed run(s)",
            )
        )

    #: Check 3.
    if not live_runs:
        mismatches.append(
            Mismatch(
                code="no_live_run",
                game_id=game_id,
                detail="a tracked game holds no live ordinary run",
            )
        )

    #: Check 4. Peers on all three compare equal, so a peer
    #: swap cannot be seen here, which is the point: below a
    #: microsecond the two orders agree on nothing.
    #:
    #: attrgetter, because the number is annotated.
    numbered = with_display_number(
        Playthrough.objects.filter(player_game_id=tracked_id)
    )
    by_display = [
        (run.started_lower, run.completed_lower, run.created_at)
        for run in sorted(numbered, key=attrgetter("display_number"))
        if _states_an_act(run)
    ]
    by_legacy = [
        (row.started, row.ended, row.created_at)
        for row in sorted(live_rows, key=legacy_order_key)
    ]
    if by_display != by_legacy:
        mismatches.append(
            Mismatch(
                code="display_order_disagreement",
                game_id=game_id,
                detail=f"the rows order as {by_legacy}, the runs as {by_display}",
            )
        )
    return mismatches


def reconcile(library: UserLibrary) -> list[Mismatch]:
    """Compare each row the walk reached with its run.

    Scoped to those rows, never PlayEvent.objects whole. A row on
    an untracked game, on a removed catalog game, or on a game
    with no projection row is outside this run, and a gate that
    demanded a run for it would fail a good migration.

    No column links a run to its row, so the comparison is per
    game, over what both sides say.
    """
    mismatches: list[Mismatch] = []
    tracked = PlayerGame.objects.filter(library=library, removed_at__isnull=True).only(
        "id", "game_id"
    )
    for batch in batched(
        keyset_pages(tracked, key=("id",), page_size=CONVERSION_PAGE_SIZE),
        CONVERSION_PAGE_SIZE,
    ):
        rows_for_game = _rows_for_games(batch)
        for tracked_row in batch:
            rows = rows_for_game.get(tracked_row.game_id)
            if rows is None:
                #: The walk skipped it; nothing is owed.
                continue
            mismatches.extend(
                _reconcile_game(str(tracked_row.game_id), rows, tracked_row.pk)
            )
    return mismatches


def ordering_violations() -> list[Mismatch]:
    """Check 6: every key sorts by its created_at.

    No constraint enforces it, and this run is most able to break
    it: a uuid7() minted now stamps today over an instant from
    years ago, and passes every other check.
    """
    entries = [
        entry for entry in identity_models() if entry.table == "games_playthrough"
    ]
    return [
        Mismatch(
            code="identity_ordering",
            game_id=violation.subject,
            detail=violation.detail,
        )
        for violation in check_ordering(entries).violations
    ]
