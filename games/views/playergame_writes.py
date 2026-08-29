"""The request-shaped half of the write path.

games/writes/playergame.py raises; this toasts and answers False.
"""

import uuid
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest

from games.models import Game, PlayerGameStatus
from games.removal import remove
from games.writes.playergame import (
    PlayerGameWriteFailed,
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
    except PlayerGameWriteFailed as failure:
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
    except PlayerGameWriteFailed as failure:
        messages.error(request, failure.message)
        return False
    return True


def remove_game_for_request(request: HttpRequest, game: Game) -> bool:
    """Untrack it, then take the catalog row out.

    This order, and no transaction around it: dispatch opens its own
    and refuses to nest. A failure between the two leaves a game no
    list shows, and running the act again completes it.
    """
    try:
        untrack_game(
            cast("User", request.user), game, correlation_id=new_correlation_id()
        )
    except PlayerGameWriteFailed as failure:
        messages.error(request, failure.message)
        return False
    remove(game)
    return True
