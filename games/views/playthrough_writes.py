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
    RunDraft,
    complete_run,
    record_run,
    remove_run,
    restate_run,
    start_run,
)
from timetracker.temporal import TemporalValue


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
        restate_run(
            cast("User", request.user), run, draft, correlation_id=correlation_id
        )
    except CommandFailed as failure:
        messages.error(request, failure.message)
        return WriteAnswer(failure)
    return WriteAnswer(None)


def start_run_for_request(
    request: HttpRequest,
    run: Playthrough,
    when: TemporalValue | None,
    *,
    correlation_id: uuid.UUID,
) -> WriteAnswer:
    """State the run's start; refusal on failure."""
    try:
        start_run(cast("User", request.user), run, when, correlation_id=correlation_id)
    except CommandFailed as failure:
        messages.error(request, failure.message)
        return WriteAnswer(failure)
    return WriteAnswer(None)


def complete_run_for_request(
    request: HttpRequest,
    run: Playthrough,
    when: TemporalValue | None,
    *,
    correlation_id: uuid.UUID,
) -> WriteAnswer:
    """State the run's completion; refusal on failure."""
    try:
        complete_run(
            cast("User", request.user), run, when, correlation_id=correlation_id
        )
    except CommandFailed as failure:
        messages.error(request, failure.message)
        return WriteAnswer(failure)
    return WriteAnswer(None)


def remove_run_for_request(
    request: HttpRequest, run: Playthrough, *, correlation_id: uuid.UUID
) -> None:
    """Take the run out; a refusal rises.

    confirm_and_apply reads the CommandFailed and renders
    its sentence with its status.
    """
    remove_run(cast("User", request.user), run, correlation_id=correlation_id)
