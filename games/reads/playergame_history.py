"""The status transitions a library recorded for one game.

Issue #678 D1. The events are the record; GameStatusChange is not read.
"""

from datetime import datetime
from typing import NamedTuple

from games.events.playergame import PLAYERGAME_STATUS_CHANGED
from games.models import Game, LibraryEvent, PlayerGame, PlayerGameStatus, UserLibrary


class StatusEntry(NamedTuple):
    """One transition, ready to render."""

    #: None where nobody knows when it happened.
    recorded_at: datetime | None
    previous: PlayerGameStatus
    current: PlayerGameStatus


def status_history(library: UserLibrary, game: Game) -> list[StatusEntry]:
    """The library's transitions for this game, newest first."""
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
        #: By sequence, never recorded_at: the backfill dates an event
        #: from the legacy row, so a stream is only a chain in the
        #: order it was appended.
    ).order_by("sequence")

    entries: list[StatusEntry] = []
    #: PLAYERGAME_CREATED states no status and the column defaults
    #: to unplayed, so the first transition leaves that.
    previous = PlayerGameStatus.UNPLAYED
    for event in events:
        current = PlayerGameStatus(event.payload["status"])
        entries.append(
            StatusEntry(
                #: An unknown effective time is the one signal that
                #: recorded_at is an append time and not a transition
                #: time. The live command states one, so only a
                #: backfilled event without a date lands here.
                recorded_at=None if event.effective_time is None else event.recorded_at,
                previous=previous,
                current=current,
            )
        )
        previous = current
    entries.reverse()
    return entries
