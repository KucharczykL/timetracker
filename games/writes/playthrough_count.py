"""State times played; answer a refusal."""

import uuid
from typing import NamedTuple

from django.contrib.auth.models import User

from games.commands.playthrough_count import (
    StatePlaythroughCount,
    UndoPlaythroughCount,
)
from games.events.dispatch import CommandOutcome, CommandResult, dispatch
from games.models import Game
from games.writes.answers import answered


class TimesPlayed(NamedTuple):
    """What one statement left."""

    stated: int
    #: Its correlation id, which the Undo names.
    statement: uuid.UUID
    changed: bool


def state_times_played(
    actor: User, game: Game, count: int, *, submission: uuid.UUID
) -> TimesPlayed:
    """State the count; the submission keys it."""
    with answered("playthrough"):
        result = dispatch(
            StatePlaythroughCount(game_id=game.pk, count=count),
            actor=actor,
            library=actor.library,
            idempotency_key=f"times-played-{submission}",
            correlation_id=submission,
        )
    return TimesPlayed(
        stated=count,
        statement=submission,
        changed=result.outcome is not CommandOutcome.UNCHANGED,
    )


def undo_times_played(
    actor: User, game: Game, statement: uuid.UUID, stated: int
) -> CommandResult:
    """Take one statement back; repeats replay."""
    with answered("playthrough"):
        return dispatch(
            UndoPlaythroughCount(game_id=game.pk, statement=statement, stated=stated),
            actor=actor,
            library=actor.library,
            idempotency_key=f"times-played-undo-{statement}",
        )
