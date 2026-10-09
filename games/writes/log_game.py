"""Log a game: what one press states, and the writes that state it.

The form builds a `LogStatement`; `log_game` writes it, one dispatch
per step, each answered by its own section.
"""

import datetime
import uuid
from dataclasses import dataclass
from typing import Final, Literal, NamedTuple

from games.commands.endpoint import ActStatement
from games.commands.libraryentry import EntryStatement
from games.ids import PlaythroughId
from games.models import Game, PlayerGameStatus
from games.writes.purchase import PurchaseDraft

type LogSection = Literal["copy", "dates", "playtime", "more"]

#: The order the page lists its sections in.
SECTIONS: Final[tuple[LogSection, ...]] = ("copy", "dates", "playtime", "more")


class SessionTiming(NamedTuple):
    """One sitting on a day, the duration it lasted."""

    day: datetime.date
    duration: datetime.timedelta
    device_id: uuid.UUID | None


class HistoricalHours(NamedTuple):
    """Playtime a library states without a sitting."""

    duration: datetime.timedelta
    device_id: uuid.UUID | None


type LogPlaytime = SessionTiming | HistoricalHours


@dataclass(frozen=True, slots=True)
class LogStatement:
    """What one press of Log a game states.

    None states nothing for that part. A section that is not ticked
    arrives as None, so `log_game` never reads it.
    """

    game: Game
    sections: frozenset[LogSection]
    copy: EntryStatement | None
    #: The copy's price, where one is stated; the copy is then bought.
    purchase: PurchaseDraft | None
    #: The run the person picked, if any.
    run_id: PlaythroughId | None
    started: ActStatement | None
    completed: ActStatement | None
    #: The run's note, where More is ticked.
    note: str | None
    playtime: LogPlaytime | None
    mastered: bool | None
    status: PlayerGameStatus | None
