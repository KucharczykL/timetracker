"""One press states one endpoint, dated today."""

import uuid
from typing import cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from games.commands.playthrough import ActStatement
from games.models import Game, PlayerGameStatus, Playthrough
from games.ownership import owned_or_404
from games.reads.companion_status import played_is_offered
from games.views.playergame_writes import record_facts_for_request
from games.views.playthrough import editable_runs, record_completed
from games.views.playthrough_writes import restate_run_for_request
from games.views.returns import return_url
from games.writes.playergame import new_correlation_id
from games.writes.playthrough import RunDraft
from timetracker.temporal import TemporalValue


def _today() -> ActStatement:
    """The act happened when it was pressed."""
    return ActStatement(TemporalValue.from_day(timezone.localdate()))


def _run_of(request: HttpRequest, playthrough_id: UUID) -> Playthrough:
    library = cast("User", request.user).library
    return owned_or_404(editable_runs(library), library, id=playthrough_id)


def _back_to(request: HttpRequest, game: Game) -> HttpResponse:
    return redirect(
        return_url(
            request,
            fallback="games:view_game",
            fallback_args=[game.id, game.url_slug],
        )
    )


def _state_endpoint(
    run: Playthrough,
    request: HttpRequest,
    correlation_id: uuid.UUID,
    *,
    started: ActStatement | None = None,
    completed: ActStatement | None = None,
) -> bool:
    """State one endpoint, and nothing else.

    The run's own note rides along, so the restatement
    describes nothing and the endpoint the caller did not
    name is left alone.

    A run that states this endpoint already is refused by
    the command in its own words. No gate here: a second
    one could disagree with it.
    """
    return restate_run_for_request(
        request,
        run,
        RunDraft(started=started, completed=completed, note=run.note),
        correlation_id=correlation_id,
    )


@login_required
@require_POST
def start_playthrough(request: HttpRequest, playthrough_id: UUID) -> HttpResponse:
    """Record that this run started today."""
    run = _run_of(request, playthrough_id)
    game = run.player_game.game
    library = cast("User", request.user).library
    correlation_id = new_correlation_id()
    if _state_endpoint(run, request, correlation_id, started=_today()) and (
        played_is_offered(library, game)
    ):
        #: Discarded on purpose: a refused status toasts,
        #: and the act it belongs to stands.
        record_facts_for_request(
            request,
            game,
            status=PlayerGameStatus.PLAYED,
            correlation_id=correlation_id,
        )
    return _back_to(request, game)


@login_required
@require_POST
def complete_playthrough(request: HttpRequest, playthrough_id: UUID) -> HttpResponse:
    """Record that this run was completed today."""
    run = _run_of(request, playthrough_id)
    game = run.player_game.game
    correlation_id = new_correlation_id()
    if _state_endpoint(run, request, correlation_id, completed=_today()):
        record_completed(request, game, correlation_id)
    return _back_to(request, game)
