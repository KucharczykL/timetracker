"""The status a game held before a batch."""

import uuid

from games.events.dispatch import RowUnreadable
from games.events.playergame import PLAYERGAME_CREATED, PLAYERGAME_STATUS_CHANGED
from games.models import PlayerGameStatus, UserLibrary
from games.reads.events import aggregate_events

#: Events stating a word; creation implies Unplayed.
_STATUS_FAMILY = (PLAYERGAME_CREATED.event_type, PLAYERGAME_STATUS_CHANGED.event_type)


def status_before(
    library: UserLibrary, player_game_id: uuid.UUID, batch_id: uuid.UUID
) -> PlayerGameStatus | None:
    """The word before the batch's; None if unchanged."""
    events = list(
        aggregate_events(library, player_game_id).filter(event_type__in=_STATUS_FAMILY)
    )
    ours = next(
        (
            event
            for event in events
            if event.correlation_id == batch_id
            and event.event_type == PLAYERGAME_STATUS_CHANGED.event_type
        ),
        None,
    )
    if ours is None:
        return None
    earlier = [event for event in events if event.sequence < ours.sequence]
    if not earlier:
        raise RowUnreadable(
            f"PlayerGame {player_game_id} of library {library.pk} states a "
            f"status at sequence {ours.sequence} and no creation before it"
        )
    latest = earlier[-1]
    if latest.event_type == PLAYERGAME_CREATED.event_type:
        return PlayerGameStatus.UNPLAYED
    return PlayerGameStatus(latest.payload["status"])
