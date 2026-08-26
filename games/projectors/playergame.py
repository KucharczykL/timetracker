"""The current-state family for tracked games."""

import uuid
from typing import ClassVar

from games.events.envelope import RecordedEvent
from games.events.playergame import PLAYERGAME_CREATED, PLAYERGAME_STATUS_CHANGED
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

    handles: ClassVar[HandlerMap] = {
        PLAYERGAME_CREATED: _created,
        PLAYERGAME_STATUS_CHANGED: _status_changed,
    }
