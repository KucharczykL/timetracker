"""The request-shaped half of the write path.

A view that stays on its page toasts and answers the refusal.
One behind a confirmation re-raises, so the page states
the sentence itself.
"""

import uuid
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest

from games.models import Game, Playthrough
from games.writes.answers import CommandFailed, WriteAnswer
from games.writes.playthrough import (
    MovedRun,
    MovedThenFailed,
    RunDraft,
    StatusStated,
    record_run,
    remove_run,
    restate_run,
)


def record_run_for_request(
    request: HttpRequest, game: Game, draft: RunDraft, *, correlation_id: uuid.UUID
) -> WriteAnswer:
    """State one run; the refusal on failure.

    Tracking a game is a library-visible act, so a submit
    that had to track one says so rather than doing it
    behind the person's back.
    """
    try:
        recorded = record_run(
            cast("User", request.user), game, draft, correlation_id=correlation_id
        )
    except CommandFailed as failure:
        messages.error(request, failure.message)
        return WriteAnswer(failure)
    if recorded.tracked_the_game:
        messages.info(request, f"{game} is now tracked in your library.")
    return WriteAnswer(None)


def restate_run_for_request(
    request: HttpRequest,
    run: Playthrough,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> WriteAnswer:
    """State the draft; the refusal on failure."""
    try:
        moved = restate_run(
            cast("User", request.user), run, draft, correlation_id=correlation_id
        )
    except CommandFailed as failure:
        if isinstance(failure, MovedThenFailed):
            _toast_the_move(request, failure.moved)
        messages.error(request, failure.message)
        return WriteAnswer(failure)
    if moved is not None:
        _toast_the_move(request, moved)
    return WriteAnswer(None)


def _toast_the_move(request: HttpRequest, moved: MovedRun) -> None:
    messages.info(request, moved_sentence(moved))


def moved_sentence(moved: MovedRun) -> str:
    """One toast: the move, then each swap."""
    if moved.tracked_the_target:
        sentence = f"Moved to {moved.target}, which is now tracked in your library."
    else:
        sentence = f"Moved to {moved.target}."
    if moved.removed_a_placeholder:
        sentence += " Its empty playthrough was removed."
    if isinstance(moved.status, StatusStated):
        sentence += f" {moved.target} is now {moved.status.status.label}."
    if moved.minted_a_placeholder:
        sentence += (
            f" {moved.source} got an empty playthrough, since every tracked "
            "game keeps one."
        )
    if moved.cleared_releases == 1:
        sentence += (
            f" One session or record no longer names a release of {moved.source}."
        )
    elif moved.cleared_releases > 1:
        sentence += (
            f" {moved.cleared_releases} sessions and records no longer name a "
            f"release of {moved.source}."
        )
    return sentence


def remove_run_for_request(
    request: HttpRequest, run: Playthrough, *, correlation_id: uuid.UUID
) -> None:
    """Take the run out; a refusal rises.

    confirm_and_apply reads the CommandFailed and renders
    its sentence with its status.
    """
    remove_run(cast("User", request.user), run, correlation_id=correlation_id)
