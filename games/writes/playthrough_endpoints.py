"""State one endpoint, then the status it implies."""

import uuid
from typing import NamedTuple

from django.contrib.auth.models import User

from games.events.append import SourceMetadata
from games.events.dispatch import CommandOutcome, CommandResult
from games.events.idempotency import IdempotencyKey
from games.models import Playthrough
from games.writes.implied_status import (
    IMPLIED_BY_COMPLETION,
    StatusAnswer,
    implied_by_start,
    state_implied_status,
)
from games.writes.playthrough import complete_run, start_run
from timetracker.temporal import TemporalValue


class StatedAct(NamedTuple):
    """What the endpoint did, and the status after.

    Carried rather than raised: the endpoint is stated by then, and a
    caller that turned the row down for the fact it implies would report
    a stated endpoint as refused.
    """

    result: CommandResult
    status: StatusAnswer


def state_start(
    actor: User,
    run: Playthrough,
    when: TemporalValue | None,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> StatedAct:
    """State the start, and Played where Unplayed."""
    result = start_run(
        actor,
        run,
        when,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        source_metadata=source_metadata,
    )
    game = run.player_game.game
    status = implied_by_start(actor.library, game)
    if not _stated_now(result) or status is None:
        return StatedAct(result, None)
    return StatedAct(
        result,
        state_implied_status(
            actor,
            game,
            status,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        ),
    )


def state_completion(
    actor: User,
    run: Playthrough,
    when: TemporalValue | None,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> StatedAct:
    """State the completion, and Completed on the game."""
    result = complete_run(
        actor,
        run,
        when,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        source_metadata=source_metadata,
    )
    if not _stated_now(result):
        return StatedAct(result, None)
    return StatedAct(
        result,
        state_implied_status(
            actor,
            run.player_game.game,
            IMPLIED_BY_COMPLETION,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        ),
    )


def _stated_now(result: CommandResult) -> bool:
    """Whether this act recorded the endpoint.

    A replay counts: the post that appended the endpoint may never have
    reached the status, and the command states nothing twice. An
    unchanged outcome does not: the run held the endpoint before the act.
    """
    return result.outcome in (CommandOutcome.APPENDED, CommandOutcome.REPLAYED)
