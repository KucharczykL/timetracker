"""What the legacy PlayEvent rows hold, read and never written.

Issue #686. #684 converts these rows into Playthroughs; this says what that
conversion will meet. Nothing here appends an event or writes a row, and #684
imports the classifiers so the two agree by construction.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import date
from enum import StrEnum
from typing import NamedTuple

from games.models import PlayEvent

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

    def __add__(self, other: "PreflightCounts") -> "PreflightCounts":
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
