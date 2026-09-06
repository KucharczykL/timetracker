"""Playthrough facts for the legacy PlayEvent rows.

Issue #684. The legacy table is the only record of which games a library
played through and when. Every row in scope becomes one ordinary run
stating both acts, because a row carrying no date is still the library's
record that a run happened -- #681's "played before", which is a marker
set beside a null day.
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

#: Named in every key and every source_metadata value.
PTHROUGH_ISSUE = 684
KEY_PREFIX = "backfill:684:playthrough"

#: Aggregates per query.
CONVERSION_PAGE_SIZE = 200

#: Every PlayEvent field this module reads.
#:
#: 0045 replays this code against the concrete model, so a bare query
#: selects the columns PlayEvent declares today while the schema stands
#: at 0045. A field read here and missing from this tuple is deferred,
#: and reading it raises UndefinedColumn one page later. #771 takes this
#: table, so the tuple is what keeps the run readable until then.
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
    """What one pass did, summable across rows, games and libraries."""

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

#: The counts field one row verdict adds to. A mapping rather than a
#: match, because every arm is the enum's own value.
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
    """Append one event, or replay its key. True when it appended.

    One append per event, never one append per row: LockedStream.append()
    stamps one recorded_at across every row of a call, and a removed
    legacy row carries two different instants.

    No command_input names an aggregate id. Every identity here is minted
    fresh per pass, so a fingerprint holding one would answer a second
    pass with IdempotencyKeyMismatch rather than with the drift the gate
    reads.

    dispatch() is not used. A command validates against current state,
    and every refusal #681 and #1011 wrote guards what a person states
    next. This run states what the library already recorded.
    """

    def build(stream: LockedStream) -> Sequence[NewEvent]:
        #: The append contract passes it; nothing here consults it.
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

    The atomic block is this function's own: lock_stream refuses the head
    lock outside a transaction, and one row's facts are recorded whole or
    not at all. Inside a caller's transaction it is a savepoint, so the
    migration still rolls the whole run back.
    """
    metadata: SourceMetadata = {
        "origin": "backfill",
        "issue": PTHROUGH_ISSUE,
        #: Provenance, not a lookup: nothing reads it back. A string,
        #: because canonical_json refuses a UUID.
        "play_event_id": str(row.pk),
    }
    verdict = classify_row(row)
    counts = ConversionCounts(
        runs_converted=1,
        live_rows=int(row.removed_at is None),
        rows_removed_converted=int(row.removed_at is not None),
        **{VERDICT_FIELD[verdict]: 1},
    )
    #: The row's own instant, so the projector's created_at is the day
    #: the row was written and the identity sorts with it.
    recorded_at = row.created_at
    run_id = identity_at(recorded_at)

    with transaction.atomic():
        #: Always first. amend() raises against a row no creation event
        #: made.
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
                #: Named, so a changed note is a loud mismatch.
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
                    #: None rather than TemporalValue.unknown(): an event
                    #: that says nothing about a day is plainer than one
                    #: spelling out an unknown, and the column holds
                    #: None either way.
                    when=None if day is None else TemporalValue.from_day(day),
                    note="",
                ),
                actor=actor,
                idempotency_key=f"{KEY_PREFIX}:{word}:{row.pk}",
                command_input={
                    "fact": word,
                    "play_event_id": str(row.pk),
                    #: Named, so a changed source day is a loud mismatch.
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
            #: The row's own mark, which is why this is a second append.
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
    """State one tracked game's rows, and its default run where it needs one.

    Pairing runs here rather than over the whole library because a group
    is keyed on the PlayerGame, so no group spans two games. The
    candidates are this game's alone, which is why unclaimed_events is
    not read: every other game's events would count as unclaimed.
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
    #: legacy_order_key, so the run a person entered first is numbered
    #: first: the identities ascend with the rows.
    for row in sorted(rows, key=legacy_order_key):
        counts = counts + convert_row(
            row,
            library=library,
            actor=actor,
            tracked_id=tracked_id,
            pairings=pairings,
        )

    #: "No live run", not "no legacy row": a game whose only row was
    #: removed keeps a removed run and still needs the live one every
    #: tracked game holds. One live row is one live run, so the rows
    #: answer this without a query.
    if any(row.removed_at is None for row in rows):
        return counts

    counts = counts + ConversionCounts(runs_default=1)
    #: Its own block, as convert_row's is: lock_stream refuses the head
    #: lock outside a transaction.
    with transaction.atomic():
        if _append(
            library,
            playthrough_created(tracked_id, playthrough_id=identity_at(tracked_at)),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:default:{tracked_id}",
            command_input={"fact": "default", "player_game_id": str(tracked_id)},
            #: The tracked game's own instant: the run has been open
            #: since the library started tracking it.
            recorded_at=tracked_at,
            correlation_id=uuid.uuid7(),
            source_metadata={"origin": "backfill", "issue": PTHROUGH_ISSUE},
        ):
            counts = counts + ConversionCounts(events_appended=1)
    return counts


def _rows_for_games(batch: Sequence[PlayerGame]) -> dict[uuid.UUID, list[PlayEvent]]:
    """One batch's live catalog games, each with its legacy rows.

    A game the catalog marks removed is absent from the answer, which is
    what the caller counts as tracked_on_removed_game.
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
    """State every legacy row this library tracks, live and removed alike.

    The preflight's walk, with one difference: it takes live rows only,
    and this takes both. Nothing the library removed is destroyed, and
    #771 destroys the legacy table, so a skipped removed row would be a
    record that survives this run and not the next one.
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
    """One reason the conversion must not commit."""

    code: str
    game_id: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail, "game_id": self.game_id}


class RunShape(NamedTuple):
    """What a row and the run it became must both say."""

    started: date | None
    completed: date | None
    note: str


def _row_shape(row: PlayEvent) -> RunShape:
    return RunShape(started=row.started, completed=row.ended, note=row.note)


def _run_shape(run: Playthrough) -> RunShape:
    #: The generated bounds, which the database computed from the value
    #: the endpoint event carried.
    return RunShape(
        started=run.started_lower, completed=run.completed_lower, note=run.note
    )


def _states_an_act(run: Playthrough) -> bool:
    """A run one legacy row became. The default run states neither act."""
    return run.start_recorded_at is not None or run.completion_recorded_at is not None


def _reconcile_game(
    game_id: str, rows: Sequence[PlayEvent], tracked_id: uuid.UUID
) -> list[Mismatch]:
    """The four row-to-row checks over one tracked game."""
    mismatches: list[Mismatch] = []
    runs = list(Playthrough.objects.filter(player_game_id=tracked_id))
    live_runs = [run for run in runs if run.removed_at is None]
    live_rows = [row for row in rows if row.removed_at is None]
    removed_rows = [row for row in rows if row.removed_at is not None]
    removed_runs = [run for run in runs if run.removed_at is not None]

    #: Check 1. A multiset, because nothing distinguishes two rows that
    #: say the same thing, and neither side is ordered here.
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

    #: Check 4. Rows that are peers on all three come back in either
    #: order, and the triples they compare as are equal, so a peer swap
    #: cannot be seen here -- which is the point.
    #: attrgetter, because the number is annotated onto the queryset and
    #: the model declares no such field.
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
    """Compare every row the walk reached against the run it became.

    Scoped to those rows, never to PlayEvent.objects whole. A row on an
    untracked game, on a removed catalog game, or on a game with no
    projection row is outside this run by design, and a gate demanding a
    run for it would fail a migration that did nothing wrong.

    No column links a run back to the row it came from, and none is
    added: the projection carries what the library states, not where a
    one-time conversion read it. So the comparison is per game, over
    what both sides say.
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
                #: The catalog marks the game removed. The walk skipped
                #: it, so nothing is owed.
                continue
            mismatches.extend(
                _reconcile_game(str(tracked_row.game_id), rows, tracked_row.pk)
            )
    return mismatches


def ordering_violations() -> list[Mismatch]:
    """Check 6: every Playthrough key still sorts by its created_at.

    The one invariant no constraint enforces, and the one this run is
    most able to break: it records instants from years ago, where a
    uuid7() minted now would stamp today and pass every other check.
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
