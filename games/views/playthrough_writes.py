"""The request-shaped half of the run write path.

games/writes/playthrough.py raises. A view that stays on its page
toasts and answers False; one that stands behind a confirmation
re-raises, so the confirmation states the sentence itself.
"""

import uuid
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest

from games.models import Game, Playthrough
from games.writes.answers import CommandFailed
from games.writes.playthrough import RunDraft, record_run, remove_run, restate_run


def record_run_for_request(
    request: HttpRequest, game: Game, draft: RunDraft, *, correlation_id: uuid.UUID
) -> bool:
    """State one run; False on a refusal."""
    try:
        record_run(
            cast("User", request.user), game, draft, correlation_id=correlation_id
        )
    except CommandFailed as failure:
        messages.error(request, failure.message)
        return False
    return True


def restate_run_for_request(
    request: HttpRequest,
    run: Playthrough,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> bool:
    """State the draft onto an existing run; False on a refusal."""
    try:
        restate_run(
            cast("User", request.user), run, draft, correlation_id=correlation_id
        )
    except CommandFailed as failure:
        messages.error(request, failure.message)
        return False
    return True


def remove_run_for_request(
    request: HttpRequest, run: Playthrough, *, correlation_id: uuid.UUID
) -> None:
    """Take the run out, and let a refusal rise.

    A refused command rises as the CommandFailed it already is, which
    confirm_and_apply reads: the confirmation comes back with the
    sentence and the status the refusal states.
    """
    remove_run(cast("User", request.user), run, correlation_id=correlation_id)
