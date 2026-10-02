"""Which act a restatement of one endpoint is."""

from dataclasses import dataclass
from enum import Enum
from typing import Final

from games.reads.endpoints import StatedEndpoint


class Keep(Enum):
    """No statement; None is a void."""

    KEEP = "keep"


KEEP: Final = Keep.KEEP

#: KEEP keeps, None voids, else states.
type Restated[StatementT] = StatementT | None | Keep


@dataclass(frozen=True, slots=True)
class Act[StatementT]:
    """State the act the row lacks."""

    statement: StatementT


@dataclass(frozen=True, slots=True)
class Correct[StatementT]:
    """Restate the act the row holds."""

    statement: StatementT


@dataclass(frozen=True, slots=True)
class Void:
    """Take back the act the row holds."""


@dataclass(frozen=True, slots=True)
class Nothing:
    """Neither side states an act."""


type EndpointMove[StatementT] = Act[StatementT] | Correct[StatementT] | Void | Nothing


def endpoint_move[StatementT](
    stated: StatedEndpoint | None, wanted: StatementT | None
) -> EndpointMove[StatementT]:
    """The act, chosen by presence alone.

    Read before dispatch's lock: comparing values here would
    drop this statement over a racer's correction.
    """
    if wanted is None:
        return Nothing() if stated is None else Void()
    return Act(wanted) if stated is None else Correct(wanted)
