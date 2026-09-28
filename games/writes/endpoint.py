"""Which act a restatement of one endpoint is."""

from enum import Enum, auto

from games.reads.endpoints import StatedEndpoint


class EndpointMove(Enum):
    """The one act that turns what a row states into what is wanted."""

    NOTHING = auto()
    ACT = auto()
    CORRECT = auto()
    VOID = auto()


def endpoint_move(stated: StatedEndpoint | None, wanted: object | None) -> EndpointMove:
    """The act a restatement takes, read before dispatch's lock.

    Never compares values. The command compares under the lock and
    answers the same statement as unchanged; a comparison here would
    drop this person's statement over a correction a racer made
    between this read and the dispatch.
    """
    if wanted is None:
        return EndpointMove.NOTHING if stated is None else EndpointMove.VOID
    return EndpointMove.ACT if stated is None else EndpointMove.CORRECT
