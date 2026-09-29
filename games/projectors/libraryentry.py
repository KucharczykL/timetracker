"""Current-state rows for library entries."""

import uuid
from typing import ClassVar

from games.events.envelope import RecordedEvent
from games.events.libraryentry import (
    LIBRARYENTRY_ACCESS_CHANGED,
    LIBRARYENTRY_ACQUISITION_CORRECTED,
    LIBRARYENTRY_CREATED,
    LIBRARYENTRY_FORMAT_CHANGED,
    LIBRARYENTRY_NOTE_CHANGED,
    LIBRARYENTRY_RELEASE_CHANGED,
    LIBRARYENTRY_REMOVED,
    LIBRARYENTRY_RESTORED,
)
from games.events.projection import HandlerMap, Projector, ProjectorFamily
from games.models import ENTRY_ACQUISITION_COLUMNS, LibraryEntry


class Entries(Projector):
    """One row per entry."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _created(self, event: RecordedEvent) -> None:
        #: Never names the mark; removal survives replay.
        payload = event.payload
        self.project(
            LibraryEntry,
            event,
            player_game_id=uuid.UUID(payload["player_game"]),
            release_id=uuid.UUID(payload["release"]["id"]),
            access=payload["access"],
            format=payload["format"],
            note=payload["note"],
            #: The event's instant, so a replay agrees.
            created_at=event.recorded_at,
            **self.opening_columns(
                ENTRY_ACQUISITION_COLUMNS, event, note=payload["acquisition_note"]
            ),
        )

    def _access_changed(self, event: RecordedEvent) -> None:
        self.amend(LibraryEntry, event, access=event.payload["access"])

    def _format_changed(self, event: RecordedEvent) -> None:
        self.amend(LibraryEntry, event, format=event.payload["format"])

    def _note_changed(self, event: RecordedEvent) -> None:
        self.amend(LibraryEntry, event, note=event.payload["note"])

    def _release_changed(self, event: RecordedEvent) -> None:
        self.amend(
            LibraryEntry, event, release_id=uuid.UUID(event.payload["release"]["id"])
        )

    def _acquisition_corrected(self, event: RecordedEvent) -> None:
        self.project_corrected(ENTRY_ACQUISITION_COLUMNS, event)

    def _removed(self, event: RecordedEvent) -> None:
        self.amend(LibraryEntry, event, removed_at=event.recorded_at)

    def _restored(self, event: RecordedEvent) -> None:
        self.amend(LibraryEntry, event, removed_at=None)

    handles: ClassVar[HandlerMap] = {
        LIBRARYENTRY_CREATED: _created,
        LIBRARYENTRY_ACCESS_CHANGED: _access_changed,
        LIBRARYENTRY_FORMAT_CHANGED: _format_changed,
        LIBRARYENTRY_NOTE_CHANGED: _note_changed,
        LIBRARYENTRY_RELEASE_CHANGED: _release_changed,
        LIBRARYENTRY_ACQUISITION_CORRECTED: _acquisition_corrected,
        LIBRARYENTRY_REMOVED: _removed,
        LIBRARYENTRY_RESTORED: _restored,
    }
