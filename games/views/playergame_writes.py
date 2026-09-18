"""The request-shaped half of the write path.

games/writes/playergame.py raises. A view that stays on its page toasts
and answers the refusal; one that stands behind a confirmation re-raises,
so the confirmation states the sentence itself.
"""

import logging
import uuid
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest

from games.models import Game, PlayerGameStatus
from games.removal import remove, restore
from games.writes.answers import CONFLICT_STATUS, CommandFailed, WriteAnswer
from games.writes.playergame import (
    new_correlation_id,
    record_facts,
    retrack_game,
    track_game,
    untrack_game,
)

logger = logging.getLogger("games")


def track_game_for_request(
    request: HttpRequest, game: Game, *, correlation_id: uuid.UUID
) -> WriteAnswer:
    """Track the game; the refusal on failure."""
    try:
        track_game(cast("User", request.user), game, correlation_id=correlation_id)
    except CommandFailed as failure:
        messages.error(request, failure.message)
        return WriteAnswer(failure)
    return WriteAnswer(None)


def record_facts_for_request(
    request: HttpRequest,
    game: Game,
    *,
    status: PlayerGameStatus | None = None,
    mastered: bool | None = None,
    correlation_id: uuid.UUID,
) -> WriteAnswer:
    """State the facts; the refusal on failure."""
    try:
        record_facts(
            cast("User", request.user),
            game,
            status=status,
            mastered=mastered,
            correlation_id=correlation_id,
        )
    except CommandFailed as failure:
        messages.error(request, failure.message)
        return WriteAnswer(failure)
    return WriteAnswer(None)


def remove_game_for_request(request: HttpRequest, game: Game) -> None:
    """Untrack it, then take the row out.

    This order, and no transaction around it: dispatch opens its own
    and refuses to nest. A failure between the two leaves a game no
    list shows, and running the act again completes it.

    A refused command rises as the `CommandFailed` it already is,
    which `confirm_and_apply` reads: the confirmation comes back
    with the sentence and the status the refusal states.
    """
    untrack_game(cast("User", request.user), game, correlation_id=new_correlation_id())
    remove(game)


def restore_game_for_request(request: HttpRequest, game: Game) -> None:
    """Stamp first: a halfway is the removal's own halfway."""
    restore(game)
    try:
        retrack_game(
            cast("User", request.user), game, correlation_id=new_correlation_id()
        )
    except CommandFailed as failure:
        #: The stamp is cleared; the sentence must not say nothing was.
        logger.error(
            "[restore]: game %s of library %s is back in the catalog but not "
            "tracked: %s",
            game.pk,
            game.library_id,
            failure.message,
            exc_info=failure,
        )
        #: A defect states no second press that can work.
        tail = (
            "Try again."
            if failure.status_code == CONFLICT_STATUS
            else "The problem has been reported."
        )
        raise CommandFailed(
            f"{game.name} is back in the catalog but not tracked yet. {tail}",
            failure.status_code,
        ) from failure
