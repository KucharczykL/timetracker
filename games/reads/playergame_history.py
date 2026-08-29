"""A library's status transitions for one game."""

from datetime import datetime
from typing import NamedTuple

from games.events.playergame import PLAYERGAME_STATUS_CHANGED
from games.models import Game, LibraryEvent, PlayerGame, PlayerGameStatus, UserLibrary


class StatusEntry(NamedTuple):
    """One transition, ready to render."""

    #: None where nobody knows when.
    recorded_at: datetime | None
    previous: PlayerGameStatus
    current: PlayerGameStatus


def status_history(library: UserLibrary, game: Game) -> list[StatusEntry]:
    """This game's transitions, newest first."""
    tracked_id = (
        PlayerGame.objects.filter(library=library, game=game)
        .values_list("pk", flat=True)
        .first()
    )
    if tracked_id is None:
        return []
    events = LibraryEvent.objects.filter(
        library=library,
        aggregate_id=tracked_id,
        event_type=PLAYERGAME_STATUS_CHANGED.event_type,
        #: A backfilled event keeps its legacy
        #: date, so sequence gives the order.
    ).order_by("sequence")

    entries: list[StatusEntry] = []
    #: The creation event states no status.
    previous = PlayerGameStatus.UNPLAYED
    for event in events:
        current = PlayerGameStatus(event.payload["status"])
        entries.append(
            StatusEntry(
                #: Unknown effective time: an append time.
                recorded_at=None if event.effective_time is None else event.recorded_at,
                previous=previous,
                current=current,
            )
        )
        previous = current
    entries.reverse()
    return entries
