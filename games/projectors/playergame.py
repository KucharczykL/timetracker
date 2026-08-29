"""The current-state family for tracked games."""

import uuid
from typing import ClassVar

from games.events.envelope import RecordedEvent
from games.events.playergame import (
    PLAYERGAME_CREATED,
    PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_REMOVED,
    PLAYERGAME_RESTORED,
    PLAYERGAME_STATUS_CHANGED,
)
from games.events.projection import HandlerMap, Projector, ProjectorFamily
from games.models import PlayerGame


class PlayerGames(Projector):
    """One row per tracked game."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _created(self, event: RecordedEvent) -> None:
        self.project(
            PlayerGame,
            event.aggregate_id,
            #: From the event, never a command's context.
            library_id=event.library_id,
            game_id=uuid.UUID(event.payload["game"]["id"]),
            tracked_at=event.recorded_at,
        )

    def _status_changed(self, event: RecordedEvent) -> None:
        #: From the payload, so replays agree.
        self.amend(PlayerGame, event.aggregate_id, status=event.payload["status"])

    def _mastered_changed(self, event: RecordedEvent) -> None:
        #: From the payload, so replays agree.
        self.amend(PlayerGame, event.aggregate_id, mastered=event.payload["mastered"])

    def _excluded_from_unfinished_changed(self, event: RecordedEvent) -> None:
        #: From the payload, so replays agree.
        self.amend(
            PlayerGame,
            event.aggregate_id,
            excluded_from_unfinished=event.payload["excluded_from_unfinished"],
        )

    def _removed(self, event: RecordedEvent) -> None:
        #: The event's own time, so replays agree.
        self.amend(PlayerGame, event.aggregate_id, removed_at=event.recorded_at)

    def _restored(self, event: RecordedEvent) -> None:
        self.amend(PlayerGame, event.aggregate_id, removed_at=None)

    handles: ClassVar[HandlerMap] = {
        PLAYERGAME_CREATED: _created,
        PLAYERGAME_STATUS_CHANGED: _status_changed,
        PLAYERGAME_MASTERED_CHANGED: _mastered_changed,
        PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED: _excluded_from_unfinished_changed,
        PLAYERGAME_REMOVED: _removed,
        PLAYERGAME_RESTORED: _restored,
    }
