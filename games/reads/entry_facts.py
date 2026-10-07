"""A copy's facts before a batch."""

import uuid
from dataclasses import dataclass

from games.events.dispatch import RowUnreadable
from games.events.libraryentry import (
    LIBRARYENTRY_ACCESS_CHANGED,
    LIBRARYENTRY_CREATED,
    LIBRARYENTRY_FORMAT_CHANGED,
    LIBRARYENTRY_NOTE_CHANGED,
    LIBRARYENTRY_RELEASE_CHANGED,
)
from games.ids import ReleaseId
from games.models import EntryAccess, EntryFormat, LibraryEvent, UserLibrary
from games.reads.fact_change import Fact, FactChange, fact_change, payload_fact


def _access(value: object) -> EntryAccess | None:
    return EntryAccess(value) if value in EntryAccess.values else None


def _format(value: object) -> EntryFormat | None:
    return EntryFormat(value) if value in EntryFormat.values else None


def _note(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _release(event: LibraryEvent) -> ReleaseId:
    """The recorded Reference's key, or a defect."""
    reference = event.payload.get("release")
    if isinstance(reference, dict) and isinstance(reference.get("id"), str):
        try:
            return uuid.UUID(reference["id"])
        except ValueError:
            pass
    raise RowUnreadable(
        f"event {event.pk} ({event.event_type}) of library {event.library_id} "
        f"states release {reference!r}"
    )


_ACCESS = Fact(
    LIBRARYENTRY_CREATED, LIBRARYENTRY_ACCESS_CHANGED, payload_fact("access", _access)
)
_FORMAT = Fact(
    LIBRARYENTRY_CREATED, LIBRARYENTRY_FORMAT_CHANGED, payload_fact("format", _format)
)
_NOTE = Fact(
    LIBRARYENTRY_CREATED, LIBRARYENTRY_NOTE_CHANGED, payload_fact("note", _note)
)
_RELEASE = Fact(LIBRARYENTRY_CREATED, LIBRARYENTRY_RELEASE_CHANGED, _release)


@dataclass(frozen=True, slots=True)
class EntryFactChanges:
    """Each fact a batch changed, else None."""

    access: FactChange[EntryAccess] | None
    format: FactChange[EntryFormat] | None
    note: FactChange[str] | None
    release: FactChange[ReleaseId] | None

    @property
    def changed_any(self) -> bool:
        return any(
            change is not None
            for change in (self.access, self.format, self.note, self.release)
        )


def entry_fact_changes(
    library: UserLibrary, entry_id: uuid.UUID, batch_id: uuid.UUID
) -> EntryFactChanges:
    return EntryFactChanges(
        access=fact_change(_ACCESS, library, entry_id, batch_id),
        format=fact_change(_FORMAT, library, entry_id, batch_id),
        note=fact_change(_NOTE, library, entry_id, batch_id),
        release=fact_change(_RELEASE, library, entry_id, batch_id),
    )
