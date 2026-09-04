"""What the legacy PlayEvent rows hold, read and never written.

Issue #686. #684 converts these rows into Playthroughs; this says what that
conversion will meet. Nothing here appends an event or writes a row, and #684
imports the classifiers so the two agree by construction.
"""

import uuid
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
