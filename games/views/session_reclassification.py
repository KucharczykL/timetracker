"""Record a session as historical playtime, and take it back."""

import json
import logging
import uuid
from collections.abc import Sequence
from datetime import timedelta
from functools import partial
from typing import NamedTuple, cast
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
from common.components.primitives import Column, Input, StyledTable, make_row
from common.criteria import ChoiceCriterion, IntCriterion, Modifier
from common.date_time_presentation import date_time_presentation_for_request
from common.duration_presentation import (
    DurationPresentation,
    duration_presentation_for_request,
)
from common.layout import render_page
from common.notices import Undo, notify
from common.returns import OriginUrl, action_url
from games.commands.session_reclassification import statement_from_session
from games.forms import HistoricalPlaytimeForm
from games.models import (
    PlayerSession,
    PlayerSessionQuerySet,
    PlayerSessionTimingMode,
)
from games.ownership import owned_or_404
from games.reads.player_sessions import library_sessions
from games.views.historical_playtime_entry import FORM_SCRIPTS
from games.views.removal import confirm_and_apply, restore_and_return
from games.views.returns import return_url
from games.writes.answers import CONFLICT_STATUS, CommandFailed
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


#: Longer than a sitting a person recalls.
REVIEW_THRESHOLD_HOURS = 8


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
    """The session list, narrowed to the rows worth reviewing."""
    return f"{reverse('games:list_sessions')}?filter={quote(review_filter())}"


NOT_WRITTEN = (
    "Only a session whose time was written down can be recorded as historical playtime."
)
NOT_AVAILABLE = "One of the sessions is no longer available, so it was left as it is."
UNDER_THRESHOLD = (
    f"A session shorter than {REVIEW_THRESHOLD_HOURS} hours is not one the "
    "review offers, so it was left as it is."
)

#: A session key as the page posts it.
type PostedKey = str


def reviewable_sessions(library) -> PlayerSessionQuerySet:
    """Live written-down rows of the threshold or longer."""
    return library_sessions(library).filter(
        timing_mode=PlayerSessionTimingMode.DURATION_ONLY,
        effective_duration__gte=timedelta(hours=REVIEW_THRESHOLD_HOURS),
    )


def _reviewable(library, keys=None) -> list[PlayerSession]:
    """Live written-down rows; `keys` narrows to a post."""
    rows = reviewable_sessions(library)
    if keys is not None:
        rows = rows.filter(pk__in=keys)
    return list(
        rows.select_related("playthrough__player_game__game").order_by(
            "-effective_duration", "id"
        )
    )


class Classified(NamedTuple):
    """What the review offers, and why the rest are left."""

    convertible: list[PlayerSession]
    refused: list[tuple[PostedKey, str]]


def _classified(library, posted: Sequence[PostedKey]) -> Classified:
    """The review's rows; a sentence true of each other key."""
    keys: dict[PostedKey, UUID] = {}
    refused: list[tuple[PostedKey, str]] = []
    for value in posted:
        try:
            keys[value] = UUID(value)
        except ValueError:
            refused.append((value, NOT_AVAILABLE))
    convertible = _reviewable(library, list(keys.values()))
    offered = {row.pk for row in convertible}
    rest = {value: key for value, key in keys.items() if key not in offered}
    live = library_sessions(library).in_bulk(list(rest.values()))
    for value, key in rest.items():
        row = live.get(key)
        if row is None:
            refused.append((value, NOT_AVAILABLE))
        elif row.timing_mode != PlayerSessionTimingMode.DURATION_ONLY:
            refused.append((value, NOT_WRITTEN))
        else:
            refused.append((value, UNDER_THRESHOLD))
    return Classified(convertible, refused)


def _convert_each(
    request: HttpRequest,
    user: User,
    classified: Classified,
    posted: int,
    token: str,
) -> None:
    """Convert each row; a refusal is a sentence, a defect stops."""
    correlation_id = new_correlation_id()
    recorded = 0
    sentences: list[str] = []

    def left(key: object, sentence: str) -> None:
        if sentence not in sentences:
            sentences.append(sentence)
        #: The page prints sentences, not keys; the log holds both.
        logger.info(
            "Session %s of library %s was not recorded under %s: %s",
            key,
            user.library.pk,
            correlation_id,
            sentence,
        )

    for key, sentence in classified.refused:
        left(key, sentence)
    for row in classified.convertible:
        try:
            state_reclassification(
                user,
                row,
                statement_from_session(row),
                idempotency_key=f"reclassify-{token}-{row.pk}",
                correlation_id=correlation_id,
            )
        except CommandFailed as failure:
            #: One type, two meanings; the status tells them apart.
            if failure.status_code != CONFLICT_STATUS:
                raise CommandFailed(
                    f"{recorded} of {posted} sessions were recorded before a "
                    "problem on our side stopped the request. The problem has "
                    "been reported, and the review still lists the rest.",
                    failure.status_code,
                ) from failure
            left(row.pk, failure.message)
            continue
        recorded += 1
    notify(
        request,
        f"{recorded} of {posted} sessions recorded as historical playtime.",
        level=messages.SUCCESS if recorded else messages.ERROR,
    )
    for sentence in sentences:
        notify(request, sentence, level=messages.ERROR)


@login_required
def reclassify_reviewed_sessions(request: HttpRequest) -> HttpResponse:
    user = cast(User, request.user)
    posted = request.POST.getlist("session")
    #: GET the filter; POST the page's keys.
    if request.method == "POST":
        classified = _classified(user.library, posted)
    else:
        classified = Classified(_reviewable(user.library), [])
    rows = classified.convertible
    token = request.POST.get("submission") or str(uuid.uuid7())
    return confirm_and_apply(
        request,
        action=partial(_convert_each, request, user, classified, len(posted), token),
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


#: Marks the panel while it has no permanent home.
TEMPORARY_NOTE = (
    "This section is temporary. It moves into the Playtime page once that "
    "page can hold it."
)


def PlaytimeReviewPanel(library, *, origin: OriginUrl) -> Node:
    """What the review offers, in a person's own words."""
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
        P(class_="text-type-body text-body mb-4")[
            "Nothing is thrown away. Moving one session offers an Undo; moving "
            "all of them at once does not yet."
        ],
        Div(class_="flex flex-wrap items-center gap-2")[
            ControlButton(href=review_url(), color="gray")["See these sessions"],
            ControlButton(
                href=action_url("games:reclassify_reviewed_sessions", origin=origin),
                color="blue",
            )[f"Move all {waiting} to historical playtime"],
        ],
    )
