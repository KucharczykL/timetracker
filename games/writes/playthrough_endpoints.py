"""State one endpoint of a run, and the status it implies.

An actor goes in here, not a request. The status is the act's own rule,
not the caller's: whichever surface states the endpoint states the same
second fact about the game.
"""

import uuid
from typing import NamedTuple

from django.contrib.auth.models import User

from games.events.append import SourceMetadata
from games.events.dispatch import CommandOutcome, CommandResult
from games.events.idempotency import IdempotencyKey
from games.models import PlayerGameStatus, Playthrough
from games.reads.companion_status import played_is_offered
from games.writes.answers import CONFLICT_STATUS, CommandFailed
from games.writes.playergame import record_facts
from games.writes.playthrough import complete_run, start_run
from timetracker.temporal import TemporalValue

#: What the status statement is keyed on, beside the endpoint's own key.
_STATUS_KEY_SUFFIX = "-status"


class StatedAct(NamedTuple):
    """What the endpoint did, and what the status refused.

    The refusal is carried rather than raised: the endpoint is stated by
    then, and a caller that turned this row down for the fact it implies
    would report a stated endpoint as refused.
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
    """State that the run began, and that the game was played.

    Played only where nothing stronger stands: a game a library
    completed is not turned back by a run beginning.
    """
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
    """State that the run finished, and that the game is completed."""
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
    reached the status, and the command states nothing twice.

    An unchanged outcome does not: the run held that endpoint before the
    act, so the act implies nothing about the game.
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
    """State the word the act implies; answer a conflict.

    The key is derived from the endpoint's, so two posts of one act
    state the status once. A defect rises: nothing was recorded, and a
    caller that swallowed it would report the row done.
    """
    try:
        record_facts(
            actor,
            run.player_game.game,
            status=status,
            correlation_id=correlation_id,
            idempotency_key=(
                None
                if idempotency_key is None
                else f"{idempotency_key}{_STATUS_KEY_SUFFIX}"
            ),
            source_metadata=source_metadata,
        )
    except CommandFailed as refusal:
        if refusal.status_code != CONFLICT_STATUS:
            raise
        return refusal
    return None
