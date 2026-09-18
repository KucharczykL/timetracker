"""Record a session as historical playtime, and take it back."""

import json
import uuid
from collections.abc import Sequence
from datetime import timedelta
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
)
from common.components.core import Node
from common.components.primitives import Column, Input, StyledTable, make_row
from common.criteria import ChoiceCriterion, IntCriterion, Modifier
from common.date_time_presentation import date_time_presentation_for_request
from common.duration_presentation import (
    DurationPresentation,
    duration_presentation_for_request,
)
from common.layout import render_page
from common.notices import Undo, notify
from games.commands.session_reclassification import statement_from_session
from games.forms import HistoricalPlaytimeForm
from games.models import PlayerSession, PlayerSessionTimingMode
from games.ownership import owned_or_404
from games.reads.player_sessions import library_sessions
from games.views.historical_playtime_entry import FORM_SCRIPTS
from games.views.removal import confirm_and_apply, restore_and_return
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


#: Long enough that a written number is more likely a total than a sitting.
REVIEW_THRESHOLD_HOURS = 8


def review_filter() -> str:
    """The rows this act was written for, as `?filter=` JSON.

    Built from the criteria rather than written out, so it cannot
    drift from what the parser accepts: `timing_mode` is a set
    criterion, and its modifier is INCLUDES rather than EQUALS.
    """
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
    """The session list, narrowed to the rows worth reviewing."""
    return f"{reverse('games:list_sessions')}?filter={quote(review_filter())}"


def ReviewEstimatesRow() -> Node:
    """The link above the quick bar, and the act beside it."""
    return Div(class_="flex flex-wrap items-center gap-2 mb-2")[
        ControlButton(href=review_url(), color="gray", variant="ghost")[
            f"Review estimates of {REVIEW_THRESHOLD_HOURS} hours or longer"
        ],
    ]


NOT_WRITTEN = (
    "Only a session whose time was written down can be recorded as historical playtime."
)


def _reviewable(library, keys=None) -> list[PlayerSession]:
    """Every live written-down row of eight hours or longer.

    `keys` narrows it to what a POST named, so a re-render after a
    refusal shows what was acted on rather than what the filter
    answers now.
    """
    rows = library_sessions(library).filter(
        timing_mode=PlayerSessionTimingMode.DURATION_ONLY,
        effective_duration__gte=timedelta(hours=REVIEW_THRESHOLD_HOURS),
    )
    if keys is not None:
        rows = rows.filter(pk__in=keys)
    return list(
        rows.select_related("playthrough__player_game__game").order_by(
            "-effective_duration", "id"
        )
    )


def _convert_each(
    request: HttpRequest, user: User, rows: Sequence[PlayerSession], token: str
) -> None:
    """Convert every row, and say what happened to each.

    A refused row does not stop the rest, and nothing is raised: this
    runs inside `confirm_and_apply`, which turns one refusal into a
    re-rendered page, and a review of ninety rows would then report
    only the first. One correlation id for the request; each row's key
    is the submit token and its own key, so a second submit replays.
    """
    correlation_id = new_correlation_id()
    converted = 0
    refusals: list[str] = []
    for row in rows:
        try:
            state_reclassification(
                user,
                row,
                statement_from_session(row),
                idempotency_key=f"reclassify-{token}-{row.pk}",
                correlation_id=correlation_id,
            )
        except CommandFailed as failure:
            if failure.message not in refusals:
                refusals.append(failure.message)
            continue
        converted += 1
    notify(
        request,
        f"{converted} of {len(rows)} sessions recorded as historical playtime.",
        level=messages.SUCCESS if converted else messages.ERROR,
    )
    for sentence in refusals:
        notify(request, sentence, level=messages.ERROR)


@login_required
def reclassify_reviewed_sessions(request: HttpRequest) -> HttpResponse:
    user = cast(User, request.user)
    posted = request.POST.getlist("session")
    #: The GET offers what the filter answers; the POST acts on what
    #: the page it was drawn from named.
    rows = _reviewable(user.library, posted if request.method == "POST" else None)
    if request.method == "POST" and len(posted) != len(rows):
        messages.error(request, NOT_WRITTEN)
    token = request.POST.get("submission") or str(uuid.uuid7())
    return confirm_and_apply(
        request,
        action=partial(_convert_each, request, user, rows, token),
        title="Record these sessions as historical playtime",
        message=(
            f"Record {len(rows)} written-down sessions of "
            f"{REVIEW_THRESHOLD_HOURS} hours or longer as historical playtime?"
        ),
        details=Fragment(
            Input(type="hidden", name="submission", value=token),
            *(Input(type="hidden", name="session", value=str(row.pk)) for row in rows),
            _review_table(rows, duration_presentation_for_request(request)),
        ),
        confirm_label="Record as historical playtime",
        fallback="games:list_sessions",
    )


def _review_table(
    rows: Sequence[PlayerSession], durations: DurationPresentation
) -> Node:
    """What the confirmation lists: every row, not the page's worth."""
    return StyledTable(
        columns=[
            Column("Game", None),
            Column("Day", None),
            Column("Duration", None, align="right"),
        ],
        rows=[
            make_row(
                row.playthrough.player_game.game.name,
                str(row.effective_day),
                durations.format(row.effective_duration),
            )
            for row in rows
        ],
    )
