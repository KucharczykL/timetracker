"""The current-state family for tracked games."""

import uuid
from typing import ClassVar

from games.events.envelope import RecordedEvent
from games.events.playergame import PLAYERGAME_CREATED
from games.events.projection import HandlerMap, Projector, ProjectorFamily
from games.models import PlayerGame


class PlayerGames(Projector):
    """One row per tracked game."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _created(self, event: RecordedEvent) -> None:
        #: Never the imported model: a rebuild redirects.
        projected = self.target.model(PlayerGame)
        projected.objects.update_or_create(
            id=event.aggregate_id,
            defaults={
                #: From the event, never a command's context.
                "library_id": event.library_id,
                "game_id": uuid.UUID(event.payload["game"]["id"]),
                "tracked_at": event.recorded_at,
            },
        )

    handles: ClassVar[HandlerMap] = {PLAYERGAME_CREATED: _created}
