"""Record a session as historical playtime."""

import json
import logging
from functools import partial
from typing import cast
from urllib.parse import quote
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.components import (
    AddForm,
    ControlButton,
    Div,
    FormFields,
    Fragment,
    ModuleScript,
    P,
)
from common.components.core import Node
from common.components.library_kit import EmptyState
from common.criteria import ChoiceCriterion, IntCriterion, Modifier
from common.date_time_presentation import date_time_presentation_for_request
from common.layout import render_page
from common.notices import Undo, notify
from games.bulk_reclassification import (
    REVIEW_THRESHOLD_HOURS,
    reviewable_sessions,
)
from games.forms import HistoricalPlaytimeForm
from games.models import PlayerSession, PlayerSessionTimingMode, UserLibrary
from games.ownership import owned_or_404
from games.views.historical_playtime_entry import FORM_SCRIPTS
from games.views.removal import restore_and_return
from games.views.returns import return_url
from games.writes.answers import CommandFailed
from games.writes.playergame import new_correlation_id
from games.writes.playersession import reclassify_session as state_reclassification
from games.writes.playersession import undo_reclassification

logger = logging.getLogger("games")


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
                idempotency_key=form.submission_key(act="reclassify"),
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
        unchanged="That session was already back.",
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


def review_filter() -> str:
    """The rows worth reviewing, as `?filter=` JSON."""
    from games.filters import PlayerSessionFilter

    return json.dumps(
        PlayerSessionFilter(
            timing_mode=ChoiceCriterion(
                value=[PlayerSessionTimingMode.DURATION_ONLY.value],
                modifier=Modifier.INCLUDES,
            ),
            duration_hours=IntCriterion(
                value=REVIEW_THRESHOLD_HOURS,
                modifier=Modifier.GREATER_THAN_OR_EQUAL,
            ),
        ).to_json()
    )


def review_url() -> str:
    """The session list, narrowed to the review."""
    return f"{reverse('games:list_sessions')}?filter={quote(review_filter())}"


#: The panel has no permanent home yet.
TEMPORARY_NOTE = (
    "This section is temporary. It moves into the Playtime page once that "
    "page can hold it."
)


def PlaytimeReviewPanel(library: UserLibrary) -> Node:
    """The review, in a person's words."""
    waiting = reviewable_sessions(library).count()
    if not waiting:
        return EmptyState(
            title="Nothing to review",
            description=(
                "None of your play sessions look like a total rather than a "
                "single sitting. If you type a long time into a session later, "
                "it shows up here."
            ),
        )
    return Fragment(
        P(class_="text-type-body text-body mb-3")[
            f"{waiting} of your play sessions are {REVIEW_THRESHOLD_HOURS} hours "
            "or longer and have a length you typed in yourself, rather than one "
            "the app measured while you played. A number that big is usually not "
            "one sitting. It is the total you remembered, or the figure a "
            "launcher showed you."
        ],
        P(class_="text-type-body text-body mb-3")[
            "You can move those hours to historical playtime, which is where "
            "this app keeps time you played without it watching the clock. "
            "Your total playtime does not change. What changes is that the "
            "hours stop pretending to be one enormous session, so figures like "
            "your longest session and your busiest day tell the truth again."
        ],
        Div(class_="flex flex-wrap items-center gap-2")[
            ControlButton(href=review_url(), color="gray")["See these sessions"],
        ],
    )
