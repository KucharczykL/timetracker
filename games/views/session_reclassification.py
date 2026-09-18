"""Record a session as historical playtime, and take it back."""

from functools import partial
from typing import cast
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.components import AddForm, FormFields, Fragment, ModuleScript
from common.date_time_presentation import date_time_presentation_for_request
from common.layout import render_page
from common.notices import Undo, notify
from games.forms import HistoricalPlaytimeForm
from games.models import PlayerSession
from games.ownership import owned_or_404
from games.views.historical_playtime_entry import FORM_SCRIPTS
from games.views.removal import restore_and_return
from games.views.returns import return_url
from games.writes.answers import CommandFailed
from games.writes.playergame import new_correlation_id
from games.writes.playersession import reclassify_session as state_reclassification
from games.writes.playersession import undo_reclassification


def _library_session(request: HttpRequest, session_id: UUID) -> PlayerSession:
    """This library's session, removed or not."""
    library = cast(User, request.user).library
    return owned_or_404(
        PlayerSession.objects.filter(library=library).select_related(
            "playthrough__player_game__game"
        ),
        library,
        id=session_id,
    )


@login_required
def reclassify_session(request: HttpRequest, session_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    session = _library_session(request, session_id)
    game = session.playthrough.player_game.game
    form = HistoricalPlaytimeForm(
        request.POST or None,
        library=user.library,
        game=game,
        presentation=date_time_presentation_for_request(request),
        session=session,
    )
    title = f"Record as historical playtime - {game.name}"
    if form.is_valid():
        try:
            state_reclassification(
                user,
                session,
                form.statement(),
                idempotency_key=form.submission_key(),
                correlation_id=new_correlation_id(),
            )
        except CommandFailed as failure:
            messages.error(request, failure.message)
            return _render_form(request, form, title, status=failure.status_code)
        notify(
            request,
            "Session recorded as historical playtime.",
            level=messages.SUCCESS,
            action=Undo(reverse("games:undo_reclassify_session", args=[session.pk])),
        )
        return redirect(_back_to(request))
    return _render_form(request, form, title)


@login_required
@require_POST
def undo_reclassify_session(request: HttpRequest, session_id: UUID) -> HttpResponse:
    session = _library_session(request, session_id)
    return restore_and_return(
        request,
        action=partial(
            undo_reclassification,
            cast(User, request.user),
            session,
            correlation_id=new_correlation_id(),
        ),
        restored="Session restored.",
        fallback="games:list_sessions",
    )


def _render_form(
    request: HttpRequest, form: HistoricalPlaytimeForm, title: str, status: int = 200
) -> HttpResponse:
    return render_page(
        request,
        AddForm(form, request=request, submit_class="", fields=FormFields(form)),
        title=title,
        scripts=Fragment(*(ModuleScript(path) for path in FORM_SCRIPTS)),
        status=status,
    )


def _back_to(request: HttpRequest) -> str:
    """The origin, else the session list."""
    return return_url(request, fallback="games:list_sessions")
