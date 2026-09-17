"""Events about playtime stated without sittings."""

import uuid
from collections.abc import Iterable
from datetime import timedelta
from typing import Annotated, Literal, TypedDict

from pydantic import AfterValidator, Field, with_config

from games.events.playersession import NoteText
from games.events.references import STRICT_SCHEMA, Reference, ReferenceId
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec, NewEvent
from timetracker.temporal import TemporalValue

#: Recorded spelling; not the TextChoices.
type ProvenanceValue = Literal["estimated", "manually_entered", "externally_measured"]


@with_config(STRICT_SCHEMA)
class HistoricalPlaytimeRunPayload(TypedDict):
    """One named run and its join id.

    Both bare ids: a ReferenceKind on a projection row would make
    replay's reference check read the live table before the first row.
    """

    id: ReferenceId
    playthrough: ReferenceId


def sorted_runs(
    members: Iterable[HistoricalPlaytimeRunPayload],
) -> list[HistoricalPlaytimeRunPayload]:
    """The one recorded order: by playthrough text."""
    return sorted(members, key=lambda member: member["playthrough"])


def _canonical_runs(
    members: list[HistoricalPlaytimeRunPayload],
) -> list[HistoricalPlaytimeRunPayload]:
    """Refuse empty, repeated or unsorted runs."""
    if not members:
        raise ValueError("A record names at least one playthrough.")
    runs = [member["playthrough"] for member in members]
    if len(set(runs)) != len(runs):
        raise ValueError("A record names each playthrough once.")
    if members != sorted_runs(members):
        raise ValueError("A record's playthroughs are sorted by id.")
    return members


type RunMembers = Annotated[
    list[HistoricalPlaytimeRunPayload], AfterValidator(_canonical_runs)
]


@with_config(STRICT_SCHEMA)
class HistoricalPlaytimeStatementPayload(TypedDict):
    """Whole record; created and restated share it."""

    player_game: ReferenceId
    playthroughs: RunMembers
    duration_seconds: Annotated[int, Field(gt=0)]
    provenance: ProvenanceValue
    device: Reference | None
    emulated: bool
    note: NoteText
    release: None
    source: None


@with_config(STRICT_SCHEMA)
class HistoricalPlaytimeMarkPayload(TypedDict):
    """Removed and restored state nothing more."""


HISTORICALPLAYTIME_CREATED = EventSpec(
    "library.historicalplaytime.created",
    aggregate_type="historicalplaytime",
    payload=HistoricalPlaytimeStatementPayload,
)
HISTORICALPLAYTIME_RESTATED = EventSpec(
    "library.historicalplaytime.restated",
    aggregate_type="historicalplaytime",
    payload=HistoricalPlaytimeStatementPayload,
)
HISTORICALPLAYTIME_REMOVED = EventSpec(
    "library.historicalplaytime.removed",
    aggregate_type="historicalplaytime",
    payload=HistoricalPlaytimeMarkPayload,
)
HISTORICALPLAYTIME_RESTORED = EventSpec(
    "library.historicalplaytime.restored",
    aggregate_type="historicalplaytime",
    payload=HistoricalPlaytimeMarkPayload,
)
for _spec in (
    HISTORICALPLAYTIME_CREATED,
    HISTORICALPLAYTIME_RESTATED,
    HISTORICALPLAYTIME_REMOVED,
    HISTORICALPLAYTIME_RESTORED,
):
    DEFAULT_EVENT_TYPES.register(_spec)


def _statement(
    *,
    player_game_id: uuid.UUID,
    runs: Iterable[HistoricalPlaytimeRunPayload],
    duration: timedelta,
    provenance: ProvenanceValue,
    device: Reference | None,
    emulated: bool,
    note: str,
) -> HistoricalPlaytimeStatementPayload:
    return {
        "player_game": str(player_game_id),
        "playthroughs": sorted_runs(runs),
        #: Whole seconds; the command truncates.
        "duration_seconds": duration // timedelta(seconds=1),
        "provenance": provenance,
        "device": device,
        "emulated": emulated,
        "note": note,
        "release": None,
        "source": None,
    }


def _effective(when: TemporalValue) -> TemporalValue | None:
    """Unknown when is a null effective_time."""
    return None if when.is_unknown else when


def historicalplaytime_created(
    *,
    player_game_id: uuid.UUID,
    runs: Iterable[HistoricalPlaytimeRunPayload],
    duration: timedelta,
    when: TemporalValue,
    provenance: ProvenanceValue,
    device: Reference | None,
    emulated: bool,
    note: str,
    record_id: uuid.UUID | None = None,
) -> NewEvent:
    """The library stated untracked playtime."""
    return HISTORICALPLAYTIME_CREATED.new(
        aggregate_id=uuid.uuid7() if record_id is None else record_id,
        effective_time=_effective(when),
        payload=_statement(
            player_game_id=player_game_id,
            runs=runs,
            duration=duration,
            provenance=provenance,
            device=device,
            emulated=emulated,
            note=note,
        ),
    )


def historicalplaytime_restated(
    record_id: uuid.UUID,
    *,
    player_game_id: uuid.UUID,
    runs: Iterable[HistoricalPlaytimeRunPayload],
    duration: timedelta,
    when: TemporalValue,
    provenance: ProvenanceValue,
    device: Reference | None,
    emulated: bool,
    note: str,
) -> NewEvent:
    """The library restated the whole record."""
    return HISTORICALPLAYTIME_RESTATED.new(
        aggregate_id=record_id,
        effective_time=_effective(when),
        payload=_statement(
            player_game_id=player_game_id,
            runs=runs,
            duration=duration,
            provenance=provenance,
            device=device,
            emulated=emulated,
            note=note,
        ),
    )


def historicalplaytime_removed(record_id: uuid.UUID) -> NewEvent:
    """Took the record out of totals."""
    return HISTORICALPLAYTIME_REMOVED.new(aggregate_id=record_id, payload={})


def historicalplaytime_restored(record_id: uuid.UUID) -> NewEvent:
    """Put a removed record back."""
    return HISTORICALPLAYTIME_RESTORED.new(aggregate_id=record_id, payload={})
