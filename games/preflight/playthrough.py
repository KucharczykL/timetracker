"""What the legacy PlayEvent rows hold.

#684 imports the classifiers, so the two agree.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date
from enum import StrEnum
from itertools import batched
from typing import NamedTuple, assert_never

from django.db.models import Count, Q, QuerySet

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

#: Sorts before every real date.
_ABSENT_DAY = date.min


class RowVerdict(StrEnum):
    """What one legacy row states."""

    CLEAN_BOTH = "clean_both"
    CLEAN_START_ONLY = "clean_start_only"
    CLEAN_END_ONLY = "clean_end_only"
    NO_KNOWN_ENDPOINT = "no_known_endpoint"
    #: #681 refuses it, so #684 decides.
    REVERSED_ENDPOINTS = "reversed_endpoints"


def classify_row(row: PlayEvent) -> RowVerdict:
    """One of five verdicts per row."""
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
    """The wave's numbering rule over legacy columns."""

    start_unknown: bool
    start: date
    completion_unknown: bool
    completion: date
    inserted: uuid.UUID


def legacy_order_key(row: PlayEvent) -> LegacyOrderKey:
    """Order by start, then completion, then pk.

    created_at is auto_now_add, so loaddata rewrites it.
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
    """What one library holds, summable into totals."""

    tracked: int = 0
    tracked_without_rows: int = 0
    tracked_on_removed_game: int = 0
    rows_total: int = 0
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
    rows_unaccounted: int = 0
    status_events_676: int = 0
    status_events_undated: int = 0
    pairs_unambiguous: int = 0
    pairs_retired_or_abandoned: int = 0
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


def _verdict_field(verdict: RowVerdict) -> str:
    """The counts field one row verdict adds to."""
    match verdict:
        case RowVerdict.CLEAN_BOTH:
            return "clean_both"
        case RowVerdict.CLEAN_START_ONLY:
            return "clean_start_only"
        case RowVerdict.CLEAN_END_ONLY:
            return "clean_end_only"
        case RowVerdict.NO_KNOWN_ENDPOINT:
            return "no_known_endpoint"
        case RowVerdict.REVERSED_ENDPOINTS:
            return "reversed_endpoints"
    assert_never(verdict)


class OrderingVerdict(NamedTuple):
    """ordered_by_date is not tie_broken; differs is independent."""

    ordered_by_date: bool
    tie_broken: bool
    date_order_differs: bool


def ordering_counts(rows: Sequence[PlayEvent]) -> OrderingVerdict:
    """Read one game's rows against the rule."""
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
    """Which of a row's dates pairs."""

    START = "start"
    COMPLETION = "completion"


class Endpoint(NamedTuple):
    """One known date on one row."""

    row_id: uuid.UUID
    kind: EndpointKind
    day: date
    aggregate_id: uuid.UUID


class CandidateKey(NamedTuple):
    """What a #676 event must match."""

    aggregate_id: uuid.UUID
    kind: EndpointKind
    day: date


class CandidateEvent(NamedTuple):
    """One #676 event, its status and correlation id."""

    key: CandidateKey
    correlation_id: uuid.UUID
    status: PlayerGameStatus = PlayerGameStatus.COMPLETED


class PairingVerdict(StrEnum):
    UNAMBIGUOUS = "unambiguous"
    AMBIGUOUS = "ambiguous"
    ABSENT = "absent"


def _pairing_field(verdict: PairingVerdict) -> str:
    """The counts field one pairing verdict adds to."""
    match verdict:
        case PairingVerdict.UNAMBIGUOUS:
            return "pairs_unambiguous"
        case PairingVerdict.AMBIGUOUS:
            return "pairs_ambiguous"
        case PairingVerdict.ABSENT:
            return "pairs_absent"
    assert_never(verdict)


class Pairing(NamedTuple):
    """A verdict, and the event when uncontested."""

    verdict: PairingVerdict
    event: CandidateEvent | None

    @property
    def correlation_id(self) -> uuid.UUID | None:
        return None if self.event is None else self.event.correlation_id


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
    """Pair each endpoint with its #676 event.

    One endpoint and one event pair; a larger group pairs nothing. A greedy
    walk would answer differently by order, so the verdict is a property of
    the group.
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
            verdict, event = PairingVerdict.ABSENT, None
        elif len(group) == 1 and len(events) == 1:
            verdict, event = PairingVerdict.UNAMBIGUOUS, events[0]
        else:
            verdict, event = PairingVerdict.AMBIGUOUS, None
        for endpoint in group:
            pairings[endpoint] = Pairing(verdict, event)

    unclaimed = sum(
        len(events)
        for key, events in events_by_key.items()
        if key not in endpoints_by_key
    )
    return PairingResult(pairings=pairings, unclaimed_events=unclaimed)


#: Aggregates per query.
WALK_PAGE_SIZE = 200

#: Identifiers per sampled list.
DEFAULT_SAMPLE_SIZE = 20

#: Which endpoint a #676 status can date.
_KIND_FOR_STATUS: dict[PlayerGameStatus, EndpointKind] = {
    PlayerGameStatus.PLAYED: EndpointKind.START,
    PlayerGameStatus.COMPLETED: EndpointKind.COMPLETION,
    #: A dropped game ends on a day.
    PlayerGameStatus.RETIRED: EndpointKind.COMPLETION,
    PlayerGameStatus.ABANDONED: EndpointKind.COMPLETION,
}

#: A completion #684 must not read as completed.
_ENDING_STATUSES = frozenset({PlayerGameStatus.RETIRED, PlayerGameStatus.ABANDONED})


@dataclass(frozen=True, slots=True)
class Samples:
    """The first few identifiers, never random.

    Two runs over unchanged data print the same bytes.
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


class CandidateEvents(NamedTuple):
    """The dated candidates, and the undated ones counted."""

    candidates: list[CandidateEvent]
    undated: int


def _candidate_events(library: UserLibrary) -> CandidateEvents:
    """Every #676 status event, one query.

    LibraryEvent indexes neither the type nor the payload, so the scan is
    paid once and the day is read in Python. A known day is demanded:
    lower_bound answers for a month or a decade too.
    """
    rows = LibraryEvent.objects.filter(
        library=library,
        event_type=PLAYERGAME_STATUS_CHANGED.event_type,
        source_metadata__origin="backfill",
        source_metadata__issue=PGAME_ISSUE,
        payload__status__in=[status.value for status in _KIND_FOR_STATUS],
    ).values_list("aggregate_id", "payload", "effective_time", "correlation_id")

    candidates = []
    undated = 0
    for aggregate_id, payload, effective_time, correlation_id in rows:
        if effective_time is None or not effective_time.has_known_day:
            undated += 1
            continue
        status = PlayerGameStatus(payload["status"])
        candidates.append(
            CandidateEvent(
                key=CandidateKey(
                    aggregate_id=aggregate_id,
                    kind=_KIND_FOR_STATUS[status],
                    day=effective_time.lower_bound,
                ),
                correlation_id=correlation_id,
                status=status,
            )
        )
    return CandidateEvents(candidates=candidates, undated=undated)


def _rows_in_scope(library: UserLibrary) -> QuerySet[PlayEvent]:
    """Every legacy row this library owns or tracks.

    A library can track a catalog game it does not own, so ownership alone
    would miss the shared rows the walk converts.
    """
    return PlayEvent.objects.filter(
        Q(game__library=library) | Q(game__player_games__library=library)
    ).distinct()


def _excluded_counts(library: UserLibrary) -> PreflightCounts:
    """Rows the conversion never sees, counted once.

    The four checks run in this order, so a row is counted in the first that
    claims it. Together with live_rows they exhaust rows_total.
    """
    projected = PlayerGame.objects.filter(library=library)
    tracked_games = projected.filter(removed_at__isnull=True).values("game_id")
    untracked_games = projected.filter(removed_at__isnull=False).values("game_id")

    in_scope = _rows_in_scope(library)
    on_removed_game = in_scope.filter(game__removed_at__isnull=False).count()
    live_game_rows = in_scope.filter(game__removed_at__isnull=True)
    removed_rows = live_game_rows.filter(removed_at__isnull=False).count()
    live = live_game_rows.filter(removed_at__isnull=True).exclude(
        game_id__in=tracked_games
    )
    untracked = live.filter(game_id__in=untracked_games).count()
    without_projection = live.exclude(game_id__in=untracked_games).count()
    return PreflightCounts(
        rows_total=in_scope.count(),
        rows_on_removed_game=on_removed_game,
        rows_removed=removed_rows,
        rows_untracked=untracked,
        rows_without_projection=without_projection,
    )


def preflight_library(
    library: UserLibrary, *, sample_size: int = DEFAULT_SAMPLE_SIZE
) -> LibraryPreflight:
    """One library's legacy rows, read and counted."""
    counts = _excluded_counts(library)
    candidates, undated = _candidate_events(library)
    counts = counts + PreflightCounts(
        status_events_676=len(candidates), status_events_undated=undated
    )

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
            if game_id not in live_games:
                #: Removal never untracks; its rows count elsewhere.
                counts = counts + PreflightCounts(tracked_on_removed_game=1)
                continue
            rows = rows_by_game.get(game_id, [])
            if not rows:
                counts = counts + PreflightCounts(tracked_without_rows=1)
                continue

            counts = counts + PreflightCounts(live_rows=len(rows))
            for row in sorted(rows, key=legacy_order_key):
                verdict = classify_row(row)
                counts = counts + PreflightCounts(**{_verdict_field(verdict): 1})
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
        paired = pairing.pairings[endpoint]
        counts = counts + PreflightCounts(**{_pairing_field(paired.verdict): 1})
        if paired.verdict is PairingVerdict.AMBIGUOUS:
            ambiguous.append(f"{endpoint.row_id}:{endpoint.kind.value}")
        if paired.event is not None and paired.event.status in _ENDING_STATUSES:
            counts = counts + PreflightCounts(pairs_retired_or_abandoned=1)
    counts = counts + PreflightCounts(
        unclaimed_events=pairing.unclaimed_events,
        rows_unaccounted=counts.rows_total
        - counts.live_rows
        - counts.rows_removed
        - counts.rows_on_removed_game
        - counts.rows_untracked
        - counts.rows_without_projection,
    )

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
    """The catalog rows no library owns."""

    shared_games: int = 0
    shared_game_rows: int = 0
    #: A row two libraries both track.
    contested_rows: int = 0

    def as_dict(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


def shared_catalog_counts() -> SharedCatalogCounts:
    """Count shared games, their rows, contested ones."""
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
