"""The request-shaped half of the write path.

games/writes/playergame.py raises; this toasts and answers False.
"""

import uuid
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest

from games.models import Game
from games.playergame_status import LegacyStatus
from games.writes.playergame import (
    PlayerGameWriteFailed,
    record_facts,
    track_game,
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
    status: LegacyStatus | None = None,
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
