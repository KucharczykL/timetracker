"""Events on one copy of a Release."""

import uuid
from typing import Literal, TypedDict

from pydantic import with_config

from games.events.endpoint import (
    EndpointPayload,
    endpoint_events,
    opening_endpoint_events,
)
from games.events.playersession import NoteText
from games.events.references import (
    STRICT_SCHEMA,
    Reference,
    ReferenceId,
    capture_reference,
)
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec, NewEvent
from games.models import Release
from timetracker.temporal import TemporalValue

#: Recorded spelling: the words `LibraryEntry.access` stores.
type EntryAccessValue = Literal[
    "owned", "borrowed", "rented", "subscription", "trial", "demo", "pirated"
]
#: Recorded spelling: the words `LibraryEntry.format` stores.
type EntryFormatValue = Literal["physical", "digital", "unknown"]
#: Recorded spelling: `ENTRY_WAYS`.
type EntryWayValue = Literal[
    "returned",
    "expired",
    "revoked",
    "refunded",
    "sold",
    "lost",
    "given_away",
    "broken",
    "stolen",
]


@with_config(STRICT_SCHEMA)
class LibraryEntryCreatedPayload(TypedDict):
    """First statement; the day is effective_time."""

    #: Bare: the row may not exist yet.
    player_game: ReferenceId
    release: Reference
    access: EntryAccessValue
    format: EntryFormatValue
    note: NoteText
    acquisition_note: NoteText


@with_config(STRICT_SCHEMA)
class LibraryEntryAccessChangedPayload(TypedDict):
    access: EntryAccessValue


@with_config(STRICT_SCHEMA)
class LibraryEntryFormatChangedPayload(TypedDict):
    format: EntryFormatValue


@with_config(STRICT_SCHEMA)
class LibraryEntryNoteChangedPayload(TypedDict):
    note: NoteText


@with_config(STRICT_SCHEMA)
class LibraryEntryReleaseChangedPayload(TypedDict):
    release: Reference


@with_config(STRICT_SCHEMA)
class LibraryEntryAccessEndPayload(TypedDict):
    """How access ended; day is effective_time."""

    way: EntryWayValue
    note: NoteText


@with_config(STRICT_SCHEMA)
class LibraryEntryAccessEndVoidedPayload(TypedDict):
    """The library takes back the record of an end."""


@with_config(STRICT_SCHEMA)
class LibraryEntryMarkPayload(TypedDict):
    """Removed and restored state nothing more."""


LIBRARYENTRY_CREATED = EventSpec(
    "library.libraryentry.created",
    aggregate_type="libraryentry",
    payload=LibraryEntryCreatedPayload,
)
LIBRARYENTRY_ACCESS_CHANGED = EventSpec(
    "library.libraryentry.access_changed",
    aggregate_type="libraryentry",
    payload=LibraryEntryAccessChangedPayload,
)
LIBRARYENTRY_FORMAT_CHANGED = EventSpec(
    "library.libraryentry.format_changed",
    aggregate_type="libraryentry",
    payload=LibraryEntryFormatChangedPayload,
)
LIBRARYENTRY_NOTE_CHANGED = EventSpec(
    "library.libraryentry.note_changed",
    aggregate_type="libraryentry",
    payload=LibraryEntryNoteChangedPayload,
)
LIBRARYENTRY_RELEASE_CHANGED = EventSpec(
    "library.libraryentry.release_changed",
    aggregate_type="libraryentry",
    payload=LibraryEntryReleaseChangedPayload,
)
LIBRARYENTRY_REMOVED = EventSpec(
    "library.libraryentry.removed",
    aggregate_type="libraryentry",
    payload=LibraryEntryMarkPayload,
)
LIBRARYENTRY_RESTORED = EventSpec(
    "library.libraryentry.restored",
    aggregate_type="libraryentry",
    payload=LibraryEntryMarkPayload,
)
for _spec in (
    LIBRARYENTRY_CREATED,
    LIBRARYENTRY_ACCESS_CHANGED,
    LIBRARYENTRY_FORMAT_CHANGED,
    LIBRARYENTRY_NOTE_CHANGED,
    LIBRARYENTRY_RELEASE_CHANGED,
    LIBRARYENTRY_REMOVED,
    LIBRARYENTRY_RESTORED,
):
    DEFAULT_EVENT_TYPES.register(_spec)

ENTRY_ACQUISITION_EVENTS = opening_endpoint_events(
    "libraryentry",
    corrected="library.libraryentry.acquisition_corrected",
    payload=EndpointPayload,
)
LIBRARYENTRY_ACQUISITION_CORRECTED = ENTRY_ACQUISITION_EVENTS.corrected

ENTRY_ACCESS_END_EVENTS = endpoint_events(
    "libraryentry",
    stated="library.libraryentry.access_ended",
    corrected="library.libraryentry.access_end_corrected",
    voided="library.libraryentry.access_end_voided",
    resumed="library.libraryentry.access_resumed",
    payload=LibraryEntryAccessEndPayload,
    voided_payload=LibraryEntryAccessEndVoidedPayload,
)
LIBRARYENTRY_ACCESS_ENDED = ENTRY_ACCESS_END_EVENTS.stated
LIBRARYENTRY_ACCESS_END_CORRECTED = ENTRY_ACCESS_END_EVENTS.corrected
LIBRARYENTRY_ACCESS_END_VOIDED = ENTRY_ACCESS_END_EVENTS.voided
LIBRARYENTRY_ACCESS_RESUMED = ENTRY_ACCESS_END_EVENTS.resumed_spec()


def libraryentry_created(
    player_game_id: uuid.UUID,
    release: Release,
    *,
    access: EntryAccessValue,
    format: EntryFormatValue,
    note: str,
    acquired: TemporalValue | None,
    acquisition_note: str,
    entry_id: uuid.UUID | None = None,
) -> NewEvent:
    """A new entry; key minted unless given."""
    return LIBRARYENTRY_CREATED.new(
        aggregate_id=uuid.uuid7() if entry_id is None else entry_id,
        effective_time=acquired,
        payload={
            "player_game": str(player_game_id),
            "release": capture_reference(release),
            "access": access,
            "format": format,
            "note": note,
            "acquisition_note": acquisition_note,
        },
    )


def libraryentry_access_changed(
    entry_id: uuid.UUID, access: EntryAccessValue
) -> NewEvent:
    return LIBRARYENTRY_ACCESS_CHANGED.new(
        aggregate_id=entry_id, payload={"access": access}
    )


def libraryentry_format_changed(
    entry_id: uuid.UUID, format: EntryFormatValue
) -> NewEvent:
    return LIBRARYENTRY_FORMAT_CHANGED.new(
        aggregate_id=entry_id, payload={"format": format}
    )


def libraryentry_note_changed(entry_id: uuid.UUID, note: str) -> NewEvent:
    return LIBRARYENTRY_NOTE_CHANGED.new(aggregate_id=entry_id, payload={"note": note})


def libraryentry_release_changed(entry_id: uuid.UUID, release: Release) -> NewEvent:
    return LIBRARYENTRY_RELEASE_CHANGED.new(
        aggregate_id=entry_id, payload={"release": capture_reference(release)}
    )


def libraryentry_acquisition_corrected(
    entry_id: uuid.UUID, *, when: TemporalValue | None, note: str
) -> NewEvent:
    return LIBRARYENTRY_ACQUISITION_CORRECTED.new(
        aggregate_id=entry_id, effective_time=when, payload={"note": note}
    )


def libraryentry_removed(entry_id: uuid.UUID) -> NewEvent:
    return LIBRARYENTRY_REMOVED.new(aggregate_id=entry_id, payload={})


def libraryentry_restored(entry_id: uuid.UUID) -> NewEvent:
    return LIBRARYENTRY_RESTORED.new(aggregate_id=entry_id, payload={})
