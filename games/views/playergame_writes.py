"""The request-shaped half of the write path.

games/writes/playergame.py raises. A view that stays on its page toasts
and answers False; one that stands behind a confirmation re-raises, so
the confirmation states the sentence itself.
"""

import uuid
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.http import HttpRequest

from games.models import Game, PlayerGameStatus
from games.removal import remove
from games.writes.answers import CommandFailed
from games.writes.playergame import (
    new_correlation_id,
    record_facts,
    track_game,
    untrack_game,
)


def track_game_for_request(
    request: HttpRequest, game: Game, *, correlation_id: uuid.UUID
) -> bool:
    """Track the game; False on failure."""
    try:
        track_game(cast("User", request.user), game, correlation_id=correlation_id)
    except CommandFailed as failure:
        messages.error(request, failure.message)
        return False
    return True


def record_facts_for_request(
    request: HttpRequest,
    game: Game,
    *,
    status: PlayerGameStatus | None = None,
    mastered: bool | None = None,
    correlation_id: uuid.UUID,
) -> bool:
    """State the facts; False on failure."""
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
        return False
    return True


def remove_game_for_request(request: HttpRequest, game: Game) -> None:
    """Untrack it, then take the row out.

    This order, and no transaction around it: dispatch opens its own
    and refuses to nest. A failure between the two leaves a game no
    list shows, and running the act again completes it.

    A refused command rises as a `ValidationError`, which is what
    `confirm_and_apply` reads: the confirmation comes back with the
    sentence on it and a 409. A toast here would have said no while
    the redirect said yes.
    """
    try:
        untrack_game(
            cast("User", request.user), game, correlation_id=new_correlation_id()
        )
    except CommandFailed as failure:
        raise ValidationError(failure.message) from failure
    remove(game)
