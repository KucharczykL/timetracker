"""What the legacy PlayEvent rows hold, read and never written.

Issue #686. #684 converts these rows into Playthroughs; this says what that
conversion will meet. Nothing here appends an event or writes a row, and #684
imports the classifiers so the two agree by construction.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date
from enum import StrEnum
from itertools import batched
from typing import NamedTuple

from django.db.models import Count

from common.keyset import keyset_pages
from games.backfill.playergame import PGAME_ISSUE
from games.events.playergame import PLAYERGAME_STATUS_CHANGED
from games.models import (
    Game,
    LibraryEvent,
    PlayerGame,
    PlayerGameStatus,
    PlayEvent,
    UserLibrary,
)

#: Sorts before every real date, and only reached when the flag beside it
#: already sorted the unknown value last.
_ABSENT_DAY = date.min


class RowVerdict(StrEnum):
    """What one legacy row states, and whether #684 can state it back."""

    CLEAN_BOTH = "clean_both"
    CLEAN_START_ONLY = "clean_start_only"
    CLEAN_END_ONLY = "clean_end_only"
    NO_KNOWN_ENDPOINT = "no_known_endpoint"
    #: #681 refuses a completion earlier than its start, so #684 decides.
    REVERSED_ENDPOINTS = "reversed_endpoints"


def classify_row(row: PlayEvent) -> RowVerdict:
    """One verdict per row. The five partition the live rows."""
    if row.started is None and row.ended is None:
        return RowVerdict.NO_KNOWN_ENDPOINT
    if row.started is None:
        return RowVerdict.CLEAN_END_ONLY
    if row.ended is None:
        return RowVerdict.CLEAN_START_ONLY
    if row.ended < row.started:
        return RowVerdict.REVERSED_ENDPOINTS
    return RowVerdict.CLEAN_BOTH


class LegacyOrderKey(NamedTuple):
    """The wave's numbering rule, over the legacy columns.

    Known start first, then known completion, then insertion. The booleans
    carry NULLS LAST: False sorts before True.
    """

    start_unknown: bool
    start: date
    completion_unknown: bool
    completion: date
    inserted: uuid.UUID


def legacy_order_key(row: PlayEvent) -> LegacyOrderKey:
    """Order by known start, then known completion, then primary key.

    The primary key, never created_at: created_at is auto_now_add, so loaddata
    rewrites it, while the UUIDv7 key survives a dump.
    """
    return LegacyOrderKey(
        start_unknown=row.started is None,
        start=row.started or _ABSENT_DAY,
        completion_unknown=row.ended is None,
        completion=row.ended or _ABSENT_DAY,
        inserted=row.id,
    )


@dataclass(frozen=True, slots=True)
class PreflightCounts:
    """What one library holds, summable into a total.

    Twenty fields, so __add__ reads the field list rather than naming each
    one: a field added here would otherwise sum to itself.
    """

    tracked: int = 0
    tracked_without_rows: int = 0
    live_rows: int = 0
    clean_both: int = 0
    clean_start_only: int = 0
    clean_end_only: int = 0
    no_known_endpoint: int = 0
    reversed_endpoints: int = 0
    ordered_by_date: int = 0
    tie_broken: int = 0
    date_order_differs_from_insertion: int = 0
    rows_removed: int = 0
    rows_on_removed_game: int = 0
    rows_untracked: int = 0
    rows_without_projection: int = 0
    status_events_676: int = 0
    pairs_unambiguous: int = 0
    pairs_ambiguous: int = 0
    pairs_absent: int = 0
    unclaimed_events: int = 0

    def __add__(self, other: PreflightCounts) -> PreflightCounts:
        return PreflightCounts(
            **{
                field.name: getattr(self, field.name) + getattr(other, field.name)
                for field in fields(self)
            }
        )

    def as_dict(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


#: The value an accumulation starts from.
NO_COUNTS = PreflightCounts()

#: One verdict per RowVerdict member, so a new member fails loudly.
_VERDICT_FIELDS: dict[RowVerdict, str] = {
    RowVerdict.CLEAN_BOTH: "clean_both",
    RowVerdict.CLEAN_START_ONLY: "clean_start_only",
    RowVerdict.CLEAN_END_ONLY: "clean_end_only",
    RowVerdict.NO_KNOWN_ENDPOINT: "no_known_endpoint",
    RowVerdict.REVERSED_ENDPOINTS: "reversed_endpoints",
}


class OrderingVerdict(NamedTuple):
    """How one game's rows reached their display numbers.

    Not a partition: a game can be tie-broken and also reordered.
    """

    ordered_by_date: bool
    tie_broken: bool
    date_order_differs: bool


def ordering_counts(rows: Sequence[PlayEvent]) -> OrderingVerdict:
    """Read one tracked game's live rows against the numbering rule."""
    keys = [legacy_order_key(row) for row in rows]
    dated_parts = [key[:4] for key in keys]
    tie_broken = len(set(dated_parts)) != len(dated_parts)
    by_rule = [key.inserted for key in sorted(keys)]
    by_insertion = sorted(key.inserted for key in keys)
    return OrderingVerdict(
        ordered_by_date=not tie_broken,
        tie_broken=tie_broken,
        date_order_differs=by_rule != by_insertion,
    )


class EndpointKind(StrEnum):
    """Which of a row's two dates is being paired."""

    START = "start"
    COMPLETION = "completion"


class Endpoint(NamedTuple):
    """One known date on one live row."""

    row_id: uuid.UUID
    kind: EndpointKind
    day: date
    aggregate_id: uuid.UUID


class CandidateKey(NamedTuple):
    """Everything a #676 status event must match to be a candidate.

    An endpoint reduces to exactly one of these, which is why the components
    of the pairing graph are this key's groups.
    """

    aggregate_id: uuid.UUID
    kind: EndpointKind
    day: date


class CandidateEvent(NamedTuple):
    """One #676 status event, and the id #684 would adopt from it."""

    key: CandidateKey
    correlation_id: uuid.UUID


class PairingVerdict(StrEnum):
    UNAMBIGUOUS = "unambiguous"
    AMBIGUOUS = "ambiguous"
    ABSENT = "absent"


class Pairing(NamedTuple):
    """What one endpoint found. An id only when nothing contests it."""

    verdict: PairingVerdict
    correlation_id: uuid.UUID | None


class PairingResult(NamedTuple):
    pairings: Mapping[Endpoint, Pairing]
    unclaimed_events: int


def _endpoint_key(endpoint: Endpoint) -> CandidateKey:
    return CandidateKey(
        aggregate_id=endpoint.aggregate_id, kind=endpoint.kind, day=endpoint.day
    )


def pair_endpoints(
    endpoints: Iterable[Endpoint], candidates: Iterable[CandidateEvent]
) -> PairingResult:
    """Pair each endpoint with the #676 status event #684 would adopt.

    A component holding one endpoint and one event pairs. Any larger component
    pairs nothing: two rows completing on one day both match the single event,
    and neither may take it. Reading order cannot change an answer, because
    the verdict is a property of the group.
    """
    events_by_key: dict[CandidateKey, list[CandidateEvent]] = defaultdict(list)
    for candidate in candidates:
        events_by_key[candidate.key].append(candidate)

    endpoints_by_key: dict[CandidateKey, list[Endpoint]] = defaultdict(list)
    for endpoint in endpoints:
        endpoints_by_key[_endpoint_key(endpoint)].append(endpoint)

    pairings: dict[Endpoint, Pairing] = {}
    for key, group in endpoints_by_key.items():
        events = events_by_key.get(key, [])
        if not events:
            verdict, correlation_id = PairingVerdict.ABSENT, None
        elif len(group) == 1 and len(events) == 1:
            verdict, correlation_id = (
                PairingVerdict.UNAMBIGUOUS,
                events[0].correlation_id,
            )
        else:
            verdict, correlation_id = PairingVerdict.AMBIGUOUS, None
        for endpoint in group:
            pairings[endpoint] = Pairing(verdict, correlation_id)

    unclaimed = sum(
        len(events)
        for key, events in events_by_key.items()
        if key not in endpoints_by_key
    )
    return PairingResult(pairings=pairings, unclaimed_events=unclaimed)


#: Aggregates per query, matching the backfill's page.
WALK_PAGE_SIZE = 200

#: Identifiers per sampled list.
DEFAULT_SAMPLE_SIZE = 20

#: The status a #676 event states for each endpoint.
_STATUS_FOR_KIND: dict[EndpointKind, PlayerGameStatus] = {
    EndpointKind.START: PlayerGameStatus.PLAYED,
    EndpointKind.COMPLETION: PlayerGameStatus.COMPLETED,
}
_KIND_FOR_STATUS = {status: kind for kind, status in _STATUS_FOR_KIND.items()}


@dataclass(frozen=True, slots=True)
class Samples:
    """The first few identifiers behind a count, never a random draw.

    First in the report's own order, so two runs over unchanged data print the
    same bytes and the JSON line diffs across a rehearsal.
    """

    reversed_endpoints: tuple[uuid.UUID, ...] = ()
    tie_broken: tuple[uuid.UUID, ...] = ()
    date_order_differs: tuple[uuid.UUID, ...] = ()
    ambiguous_endpoints: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, list[str]]:
        return {
            field.name: [str(value) for value in getattr(self, field.name)]
            for field in fields(self)
        }


@dataclass(frozen=True, slots=True)
class LibraryPreflight:
    """One library's whole report."""

    library_id: uuid.UUID
    username: str
    counts: PreflightCounts
    samples: Samples

    def as_dict(self) -> dict[str, object]:
        return {
            "library_id": str(self.library_id),
            "username": self.username,
            "counts": self.counts.as_dict(),
            "samples": self.samples.as_dict(),
        }


def _candidate_events(library: UserLibrary) -> list[CandidateEvent]:
    """Every dated #676 status event this library recorded.

    One query per run, not one per page: LibraryEvent indexes neither
    aggregate_id nor event_type, so the scan is paid once.

    The day is read in Python. effective_time carries no generated bound
    columns, so comparing it in SQL would be a per-row function call over that
    same unindexed scan.

    A day precision is demanded rather than assumed: lower_bound gives the
    first day of a month or a decade too, and that is not a day the legacy row
    could have stated.
    """
    rows = LibraryEvent.objects.filter(
        library=library,
        event_type=PLAYERGAME_STATUS_CHANGED.event_type,
        source_metadata__origin="backfill",
        source_metadata__issue=PGAME_ISSUE,
        payload__status__in=[status.value for status in _STATUS_FOR_KIND.values()],
        effective_time__isnull=False,
    ).values_list("aggregate_id", "payload", "effective_time", "correlation_id")

    candidates = []
    for aggregate_id, payload, effective_time, correlation_id in rows:
        if effective_time is None or not effective_time.has_known_day:
            continue
        day = effective_time.lower_bound
        kind = _KIND_FOR_STATUS[PlayerGameStatus(payload["status"])]
        candidates.append(
            CandidateEvent(
                key=CandidateKey(aggregate_id=aggregate_id, kind=kind, day=day),
                correlation_id=correlation_id,
            )
        )
    return candidates


def _excluded_counts(library: UserLibrary) -> PreflightCounts:
    """The rows the conversion never sees, counted once each.

    The order of the four is the order of the checks: a row on a removed game
    is that, whatever its own mark says.
    """
    owned = PlayEvent.objects.filter(game__library=library)
    on_removed_game = owned.filter(game__removed_at__isnull=False).count()
    live_game_rows = owned.filter(game__removed_at__isnull=True)
    removed_rows = live_game_rows.filter(removed_at__isnull=False).count()
    live = live_game_rows.filter(removed_at__isnull=True)
    untracked = live.filter(
        game__player_games__library=library,
        game__player_games__removed_at__isnull=False,
    ).count()
    without_projection = live.exclude(
        game__player_games__library=library,
    ).count()
    return PreflightCounts(
        rows_on_removed_game=on_removed_game,
        rows_removed=removed_rows,
        rows_untracked=untracked,
        rows_without_projection=without_projection,
    )


def preflight_library(
    library: UserLibrary, *, sample_size: int = DEFAULT_SAMPLE_SIZE
) -> LibraryPreflight:
    """Read one library's legacy rows and say what #684 will meet."""
    counts = _excluded_counts(library)
    candidates = _candidate_events(library)
    counts = counts + PreflightCounts(status_events_676=len(candidates))

    reversed_rows: list[uuid.UUID] = []
    tied_games: list[uuid.UUID] = []
    reordered_games: list[uuid.UUID] = []
    ambiguous: list[str] = []
    endpoints: list[Endpoint] = []

    tracked = PlayerGame.objects.filter(library=library, removed_at__isnull=True).only(
        "id", "game_id"
    )
    for batch in batched(
        keyset_pages(tracked, key=("id",), page_size=WALK_PAGE_SIZE), WALK_PAGE_SIZE
    ):
        aggregate_for_game = {row.game_id: row.pk for row in batch}
        live_games = set(
            Game.objects.filter(
                pk__in=aggregate_for_game, removed_at__isnull=True
            ).values_list("pk", flat=True)
        )
        rows_by_game: dict[uuid.UUID, list[PlayEvent]] = defaultdict(list)
        for row in PlayEvent.objects.filter(
            game_id__in=live_games, removed_at__isnull=True
        ).order_by("game_id", "id"):
            rows_by_game[row.game_id].append(row)

        for game_id, aggregate_id in sorted(
            aggregate_for_game.items(), key=lambda pair: pair[1]
        ):
            counts = counts + PreflightCounts(tracked=1)
            rows = rows_by_game.get(game_id, [])
            if not rows:
                counts = counts + PreflightCounts(tracked_without_rows=1)
                continue

            counts = counts + PreflightCounts(live_rows=len(rows))
            for row in sorted(rows, key=legacy_order_key):
                verdict = classify_row(row)
                counts = counts + PreflightCounts(**{_VERDICT_FIELDS[verdict]: 1})
                if verdict is RowVerdict.REVERSED_ENDPOINTS:
                    reversed_rows.append(row.id)
                for kind, day in (
                    (EndpointKind.START, row.started),
                    (EndpointKind.COMPLETION, row.ended),
                ):
                    if day is not None:
                        endpoints.append(
                            Endpoint(
                                row_id=row.id,
                                kind=kind,
                                day=day,
                                aggregate_id=aggregate_id,
                            )
                        )

            ordering = ordering_counts(rows)
            counts = counts + PreflightCounts(
                ordered_by_date=int(ordering.ordered_by_date),
                tie_broken=int(ordering.tie_broken),
                date_order_differs_from_insertion=int(ordering.date_order_differs),
            )
            if ordering.tie_broken:
                tied_games.append(game_id)
            if ordering.date_order_differs:
                reordered_games.append(game_id)

    pairing = pair_endpoints(endpoints, candidates)
    for endpoint in endpoints:
        pair_verdict = pairing.pairings[endpoint].verdict
        counts = counts + PreflightCounts(**{f"pairs_{pair_verdict.value}": 1})
        if pair_verdict is PairingVerdict.AMBIGUOUS:
            ambiguous.append(f"{endpoint.row_id}:{endpoint.kind.value}")
    counts = counts + PreflightCounts(unclaimed_events=pairing.unclaimed_events)

    def capped[SampleT](values: list[SampleT]) -> tuple[SampleT, ...]:
        return tuple(values[:sample_size])

    return LibraryPreflight(
        library_id=library.pk,
        username=library.user.username,
        counts=counts,
        samples=Samples(
            reversed_endpoints=capped(reversed_rows),
            tie_broken=capped(tied_games),
            date_order_differs=capped(reordered_games),
            ambiguous_endpoints=capped(ambiguous),
        ),
    )


@dataclass(frozen=True, slots=True)
class SharedCatalogCounts:
    """The catalog rows no library owns.

    Expected to be zero: GameForm.__init__ always stamps a library, so the
    production catalog holds no shared game. Counted anyway, because
    "expected zero" and "verified zero" are different claims.
    """

    shared_games: int = 0
    shared_game_rows: int = 0
    #: A row on a shared game more than one library tracks. It belongs to no
    #: single Playthrough, and #684 decides what that means.
    contested_rows: int = 0

    def as_dict(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


def shared_catalog_counts() -> SharedCatalogCounts:
    """Count the shared games, their rows, and the contested ones."""
    shared = Game.objects.filter(library__isnull=True, removed_at__isnull=True)
    contested_games = (
        shared.filter(player_games__removed_at__isnull=True)
        .annotate(trackers=Count("player_games__library", distinct=True))
        .filter(trackers__gt=1)
    )
    return SharedCatalogCounts(
        shared_games=shared.count(),
        shared_game_rows=PlayEvent.objects.filter(
            game__in=shared, removed_at__isnull=True
        ).count(),
        contested_rows=PlayEvent.objects.filter(
            game__in=contested_games, removed_at__isnull=True
        ).count(),
    )
