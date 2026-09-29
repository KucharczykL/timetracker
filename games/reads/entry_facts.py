"""A copy's facts before a batch changed them."""

import uuid
from dataclasses import dataclass

from games.events.libraryentry import (
    LIBRARYENTRY_ACCESS_CHANGED,
    LIBRARYENTRY_CREATED,
    LIBRARYENTRY_FORMAT_CHANGED,
    LIBRARYENTRY_NOTE_CHANGED,
)
from games.models import EntryAccess, EntryFormat, UserLibrary
from games.reads.fact_change import Fact, FactChange, fact_change


def _access(value: object) -> EntryAccess | None:
    return EntryAccess(value) if value in EntryAccess.values else None


def _format(value: object) -> EntryFormat | None:
    return EntryFormat(value) if value in EntryFormat.values else None


def _note(value: object) -> str | None:
    return value if isinstance(value, str) else None


_ACCESS = Fact(LIBRARYENTRY_CREATED, LIBRARYENTRY_ACCESS_CHANGED, "access", _access)
_FORMAT = Fact(LIBRARYENTRY_CREATED, LIBRARYENTRY_FORMAT_CHANGED, "format", _format)
_NOTE = Fact(LIBRARYENTRY_CREATED, LIBRARYENTRY_NOTE_CHANGED, "note", _note)


@dataclass(frozen=True, slots=True)
class EntryFactChanges:
    """Each fact a batch changed, else None."""

    access: FactChange[EntryAccess] | None
    format: FactChange[EntryFormat] | None
    note: FactChange[str] | None

    @property
    def changed_any(self) -> bool:
        return not (self.access is None and self.format is None and self.note is None)


def entry_fact_changes(
    library: UserLibrary, entry_id: uuid.UUID, batch_id: uuid.UUID
) -> EntryFactChanges:
    return EntryFactChanges(
        access=fact_change(_ACCESS, library, entry_id, batch_id),
        format=fact_change(_FORMAT, library, entry_id, batch_id),
        note=fact_change(_NOTE, library, entry_id, batch_id),
    )
