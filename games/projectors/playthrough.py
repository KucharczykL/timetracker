"""Current-state rows for runs at tracked games."""

import uuid
from typing import ClassVar

from games.events.envelope import RecordedEvent
from games.events.playthrough import PLAYTHROUGH_CREATED
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

    #: Only these four columns, so amendments survive.
    #:
    #: A rebuild inserts the model defaults for the rest and the amendment
    #: events that follow set the real values, so naming a column in the
    #: handler above would let a re-applied creation event overwrite one.
    #: #681's endpoint handlers use amend, never project, and are never
    #: added: `started` and `completed` carry a default, so
    #: `_required_columns` exempts them and would not catch the mistake.
    handles: ClassVar[HandlerMap] = {PLAYTHROUGH_CREATED: _created}
