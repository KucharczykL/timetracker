"""Which act a restatement of one endpoint is."""

from dataclasses import dataclass

from games.reads.endpoints import StatedEndpoint


@dataclass(frozen=True, slots=True)
class Act[StatementT]:
    """State the act the row lacks."""

    statement: StatementT


def endpoint_move(stated: StatedEndpoint | None, wanted: object | None) -> EndpointMove:
    """The act, chosen by presence alone.

    Read before dispatch's lock: comparing values here would
    drop this statement over a racer's correction.
    """
    if wanted is None:
        return Nothing() if stated is None else Void()
    return Act(wanted) if stated is None else Correct(wanted)
