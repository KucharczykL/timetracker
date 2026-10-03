"""The status a run's endpoints imply."""

import uuid
from typing import NamedTuple

from django.contrib.auth.models import User

from games.events.append import SourceMetadata
from games.events.dispatch import CommandOutcome
from games.events.idempotency import IdempotencyKey
from games.models import Game, PlayerGameStatus, Playthrough
from games.reads.companion_status import played_is_offered
from games.reads.playthrough_endpoints import stated_completion, stated_start
from games.writes.answers import CONFLICT_STATUS, CommandFailed
from games.writes.playergame import record_facts

#: What the status is keyed on, beside the act.
_STATUS_KEY_SUFFIX = "-status"


class StatusAnswer(NamedTuple):
    """Whether the word changed, or its refusal."""

    changed: bool
    refusal: CommandFailed | None


def implied_status(run: Playthrough) -> PlayerGameStatus | None:
    """Completed, else Played over Unplayed, else none."""
    if stated_completion(run) is not None:
        return PlayerGameStatus.COMPLETED
    if stated_start(run) is not None and played_is_offered(
        run.library, run.player_game.game
    ):
        return PlayerGameStatus.PLAYED
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
    """Whether the status changed; a conflict answered.

    The key comes from the act's, so two posts state it once. A
    defect rises: nothing was recorded, and a caller that swallowed it
    would report the row done.
    """
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
        if refusal.status_code != CONFLICT_STATUS:
            raise
        return StatusAnswer(changed=False, refusal=refusal)
    return StatusAnswer(
        changed=result.outcome is not CommandOutcome.UNCHANGED, refusal=None
    )
