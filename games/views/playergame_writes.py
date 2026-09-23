"""The request-shaped half of the write path.

games/writes/playergame.py raises. A view that stays on its page toasts
and answers the refusal; one that stands behind a confirmation re-raises,
so the confirmation states the sentence itself.
"""

import uuid
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest

from games.models import Game, PlayerGameStatus
from games.writes.answers import CommandFailed, WriteAnswer
from games.writes.playergame import (
    new_correlation_id,
    record_facts,
    remove_from_library,
    restore_to_library,
    track_game,
)


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
    """Take the game out of the library, as `remove_from_library` does.

    A game the library does not track is stamped all the same: the
    per-row route is how a halfway removal is completed.

    A refused command rises as the `CommandFailed` it already is,
    which `confirm_and_apply` reads: the confirmation comes back
    with the sentence and the status the refusal states.
    """
    remove_from_library(
        cast("User", request.user),
        game,
        correlation_id=new_correlation_id(),
        stamp_untracked=True,
    )


def restore_game_for_request(request: HttpRequest, game: Game) -> None:
    """Put it back, as `restore_to_library` does."""
    restore_to_library(
        cast("User", request.user), game, correlation_id=new_correlation_id()
    )
