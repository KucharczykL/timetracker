"""State one endpoint, and the status it implies.

An actor goes in here, not a request. The status is the act's rule, so
every surface that states an endpoint states the same second fact.
"""

import uuid
from typing import NamedTuple

from django.contrib.auth.models import User

from games.events.append import SourceMetadata
from games.events.dispatch import CommandOutcome, CommandResult
from games.events.idempotency import IdempotencyKey
from games.models import PlayerGameStatus, Playthrough
from games.reads.companion_status import played_is_offered
from games.writes.answers import CommandFailed
from games.writes.implied_status import state_implied_status
from games.writes.playthrough import complete_run, start_run
from timetracker.temporal import TemporalValue


class StatedAct(NamedTuple):
    """What the endpoint did, and what the status refused.

    Carried rather than raised: the endpoint is stated by then, and a
    caller that turned the row down for the fact it implies would report
    a stated endpoint as refused.
    """

    result: CommandResult
    status_refusal: CommandFailed | None


def state_start(
    actor: User,
    run: Playthrough,
    when: TemporalValue | None,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> StatedAct:
    """State the start, and Played where nothing stronger stands."""
    result = start_run(
        actor,
        run,
        when,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        source_metadata=source_metadata,
    )
    game = run.player_game.game
    if not _stated_now(result) or not played_is_offered(actor.library, game):
        return StatedAct(result, None)
    return StatedAct(
        result,
        _state_the_status(
            actor,
            run,
            PlayerGameStatus.PLAYED,
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
        _state_the_status(
            actor,
            run,
            PlayerGameStatus.COMPLETED,
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


def _state_the_status(
    actor: User,
    run: Playthrough,
    status: PlayerGameStatus,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None,
    source_metadata: SourceMetadata | None,
) -> CommandFailed | None:
    """State the word the act implies; answer a conflict."""
    return state_implied_status(
        actor,
        run.player_game.game,
        status,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        source_metadata=source_metadata,
    ).refusal
