"""State times played; answer a refusal."""

import logging
from typing import NamedTuple

from django.contrib.auth.models import User

from games.commands.playthrough_count import (
    StatePlaythroughCount,
    TimesPlayedCount,
    UndoPlaythroughCount,
    count_statement_key,
)
from games.events.dispatch import CommandOutcome, dispatch
from games.events.playergame import PLAYERGAME_STATUS_CHANGED
from games.ids import CorrelationId
from games.models import Game, PlayerGame
from games.reads.events import dispatched_events
from games.reads.playergame_facts import status_change
from games.writes.answers import answered

logger = logging.getLogger("games")


class TimesPlayed(NamedTuple):
    """What one press of Save did."""

    stated: TimesPlayedCount
    outcome: CommandOutcome
    #: Set only where this press appended.
    undoable: CorrelationId | None


def state_times_played(
    actor: User,
    game: Game,
    count: TimesPlayedCount,
    *,
    submission: CorrelationId,
) -> TimesPlayed:
    """State the count; the submission keys it."""
    with answered("playthrough"):
        result = dispatch(
            StatePlaythroughCount(game_id=game.pk, count=count),
            actor=actor,
            library=actor.library,
            idempotency_key=count_statement_key(submission),
            correlation_id=submission,
        )
    appended = result.outcome is CommandOutcome.APPENDED
    return TimesPlayed(count, result.outcome, submission if appended else None)


class UndoneCount(NamedTuple):
    """An Undo, and whether a later status stood."""

    outcome: CommandOutcome
    status_kept: bool


def undo_times_played(
    actor: User,
    game: Game,
    statement_id: CorrelationId,
    stated: TimesPlayedCount,
) -> UndoneCount:
    """Take one statement back; repeats replay."""
    with answered("playthrough"):
        result = dispatch(
            UndoPlaythroughCount(
                game_id=game.pk, statement_id=statement_id, stated=stated
            ),
            actor=actor,
            library=actor.library,
            idempotency_key=f"times-played-undo-{statement_id}-{stated}",
        )
    tracked = PlayerGame.objects.get(library=actor.library, game=game)
    status_kept = (
        status_change(actor.library, tracked.pk, statement_id) is not None
        and not dispatched_events(result)
        .filter(event_type=PLAYERGAME_STATUS_CHANGED.event_type)
        .exists()
    )
    if status_kept:
        logger.info(
            "[times played]: undo of %s left game %s of library %s at %s, stated since",
            statement_id,
            game.pk,
            actor.library.pk,
            tracked.status,
        )
    return UndoneCount(result.outcome, status_kept)
