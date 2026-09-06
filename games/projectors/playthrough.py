"""Current-state rows for runs at tracked games."""

import uuid
from typing import ClassVar

from games.events.envelope import RecordedEvent
from games.events.playthrough import (
    PLAYTHROUGH_COMPLETED,
    PLAYTHROUGH_COMPLETION_CORRECTED,
    PLAYTHROUGH_CREATED,
    PLAYTHROUGH_NAME_CHANGED,
    PLAYTHROUGH_NOTE_CHANGED,
    PLAYTHROUGH_REMOVED,
    PLAYTHROUGH_RESTORED,
    PLAYTHROUGH_START_CORRECTED,
    PLAYTHROUGH_STARTED,
)
from games.events.projection import HandlerMap, Projector, ProjectorFamily
from games.models import Playthrough


class Playthroughs(Projector):
    """One row per run at a game."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _created(self, event: RecordedEvent) -> None:
        self.project(
            Playthrough,
            event.aggregate_id,
            #: From the event, never a command's context.
            library_id=event.library_id,
            player_game_id=uuid.UUID(event.payload["player_game"]),
            kind=event.payload["kind"],
            created_at=event.recorded_at,
        )

    def _started(self, event: RecordedEvent) -> None:
        #: Every value off the event, so a replay agrees.
        self.amend(
            Playthrough,
            event.aggregate_id,
            started=event.effective_time,
            start_recorded_at=event.recorded_at,
            start_note=event.payload["note"],
        )

    def _completed(self, event: RecordedEvent) -> None:
        self.amend(
            Playthrough,
            event.aggregate_id,
            completed=event.effective_time,
            completion_recorded_at=event.recorded_at,
            completion_note=event.payload["note"],
        )

    def _name_changed(self, event: RecordedEvent) -> None:
        self.amend(Playthrough, event.aggregate_id, name=event.payload["name"])

    def _note_changed(self, event: RecordedEvent) -> None:
        self.amend(Playthrough, event.aggregate_id, note=event.payload["note"])

    def _start_corrected(self, event: RecordedEvent) -> None:
        #: The marker holds the first statement's instant, not this one.
        self.amend(
            Playthrough,
            event.aggregate_id,
            started=event.effective_time,
            start_note=event.payload["note"],
        )

    def _completion_corrected(self, event: RecordedEvent) -> None:
        self.amend(
            Playthrough,
            event.aggregate_id,
            completed=event.effective_time,
            completion_note=event.payload["note"],
        )

    def _removed(self, event: RecordedEvent) -> None:
        #: The event's instant, so a replay agrees.
        self.amend(Playthrough, event.aggregate_id, removed_at=event.recorded_at)

    def _restored(self, event: RecordedEvent) -> None:
        self.amend(Playthrough, event.aggregate_id, removed_at=None)

    #: The creation handler names four columns, so amendments survive.
    #:
    #: A rebuild inserts the model defaults for the rest, and the events
    #: that follow set the real values. Naming one there would let a
    #: re-applied creation event take an amendment back out, and every
    #: amended column carries a default, so `_required_columns` exempts
    #: them and would not report it.
    handles: ClassVar[HandlerMap] = {
        PLAYTHROUGH_CREATED: _created,
        PLAYTHROUGH_STARTED: _started,
        PLAYTHROUGH_COMPLETED: _completed,
        PLAYTHROUGH_NAME_CHANGED: _name_changed,
        PLAYTHROUGH_NOTE_CHANGED: _note_changed,
        PLAYTHROUGH_START_CORRECTED: _start_corrected,
        PLAYTHROUGH_COMPLETION_CORRECTED: _completion_corrected,
        PLAYTHROUGH_REMOVED: _removed,
        PLAYTHROUGH_RESTORED: _restored,
    }
