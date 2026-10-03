"""The status a run's endpoints imply."""

import uuid
from typing import NamedTuple

from django.contrib.auth.models import User

from games.events.append import SourceMetadata, StreamSequenceMismatch
from games.events.dispatch import CommandOutcome, CommandRejected
from games.events.idempotency import IdempotencyKey
from games.events.retry import RetryBudgetExhausted
from games.models import Game, PlayerGameStatus, Playthrough, UserLibrary
from games.reads.companion_status import played_is_offered
from games.reads.playthrough_endpoints import stated_completion, stated_start
from games.writes.answers import CommandFailed
from games.writes.playergame import record_facts

#: What the status is keyed on, beside the act.
_STATUS_KEY_SUFFIX = "-status"

#: What a completion implies, whatever stands.
IMPLIED_BY_COMPLETION = PlayerGameStatus.COMPLETED

#: Refusals a person caused; others are defects.
#:
#: A key mismatch is absent: the status key derives
#: from the act's, so a mismatch is the program's.
_EXPECTED_REFUSALS = (CommandRejected, RetryBudgetExhausted, StreamSequenceMismatch)


class StatusStated(NamedTuple):
    """The game now holds this status."""

    status: PlayerGameStatus


class StatusRefused(NamedTuple):
    """The status the act implied, refused."""

    status: PlayerGameStatus
    refusal: CommandFailed


#: None: nothing implied, or the game held it.
type StatusAnswer = StatusStated | StatusRefused | None


def implied_by_start(library: UserLibrary, game: Game) -> PlayerGameStatus | None:
    """Played where the game is Unplayed."""
    return PlayerGameStatus.PLAYED if played_is_offered(library, game) else None


def implied_status(run: Playthrough) -> PlayerGameStatus | None:
    """The status the run's stated endpoints imply."""
    if stated_completion(run) is not None:
        return IMPLIED_BY_COMPLETION
    if stated_start(run) is not None:
        return implied_by_start(run.library, run.player_game.game)
    return None


def state_implied_status(
    actor: User,
    game: Game,
    status: PlayerGameStatus,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None,
    source_metadata: SourceMetadata | None = None,
) -> StatusAnswer:
    """State the status; answer an expected refusal."""
    try:
        result = record_facts(
            actor,
            game,
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
        if not isinstance(refusal.__cause__, _EXPECTED_REFUSALS):
            raise
        return StatusRefused(status, refusal)
    if result.outcome is CommandOutcome.UNCHANGED:
        return None
    return StatusStated(status)
