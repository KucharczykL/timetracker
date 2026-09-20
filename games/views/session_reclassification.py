"""Record a session as historical playtime."""

import json
import logging
import uuid
from collections.abc import Sequence
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
from games.bulk_reclassification import (
    ALREADY_RECORDED,
    IN_THE_BUCKET,
    NOT_AVAILABLE,
    NOT_WRITTEN,
    REVIEW_THRESHOLD_HOURS,
    UNDER_THRESHOLD,
    reviewable_sessions,
)
from games.commands.session_reclassification import statement_from_session
from games.forms import HistoricalPlaytimeForm
from games.models import (
    HistoricalPlaytime,
    PlayerSession,
    PlayerSessionTimingMode,
    PlaythroughKind,
    UserLibrary,
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


#: A session key as posted.
type PostedKey = str


def _reviewable(
    library: UserLibrary, keys: Sequence[UUID] | None = None
) -> list[PlayerSession]:
    """The review's rows; `keys` narrows them."""
    rows = reviewable_sessions(library)
    if keys is not None:
        rows = rows.filter(pk__in=keys)
    return list(
        rows.select_related("playthrough__player_game__game").order_by(
            "-effective_duration", "id"
        )
    )


class Refused(NamedTuple):
    """A key left alone, and why."""

    key: PostedKey
    sentence: str


class Classified(NamedTuple):
    """The review's rows, and the rest's sentences."""

    convertible: tuple[PlayerSession, ...]
    refused: tuple[Refused, ...]
    #: Distinct keys sent: the count's denominator.
    posted: int


def _classified(library: UserLibrary, posted: Sequence[PostedKey]) -> Classified:
    """Sort posted keys: convertible or a sentence."""
    keys: dict[UUID, PostedKey] = {}
    refused: list[Refused] = []
    for value in dict.fromkeys(posted):
        try:
            keys.setdefault(UUID(value), value)
        except ValueError:
            refused.append(Refused(value, NOT_AVAILABLE))
    convertible = _reviewable(library, list(keys))
    offered = {row.pk for row in convertible}
    rest = [key for key in keys if key not in offered]
    recorded = set(
        HistoricalPlaytime.objects.filter(
            library=library, reclassified_from__in=rest, removed_at__isnull=True
        ).values_list("reclassified_from_id", flat=True)
    )
    live = library_sessions(library).select_related("playthrough").in_bulk(rest)
    for key in rest:
        row = live.get(key)
        if key in recorded:
            sentence = ALREADY_RECORDED
        elif row is None:
            sentence = NOT_AVAILABLE
        elif row.playthrough.kind == PlaythroughKind.IMPORTED_HISTORY:
            sentence = IN_THE_BUCKET
        elif row.timing_mode != PlayerSessionTimingMode.DURATION_ONLY:
            sentence = NOT_WRITTEN
        else:
            sentence = UNDER_THRESHOLD
        refused.append(Refused(keys[key], sentence))
    return Classified(
        tuple(convertible), tuple(refused), posted=len(keys) + len(refused) - len(rest)
    )


def _convert_each(
    request: HttpRequest, user: User, classified: Classified, token: str
) -> None:
    """Convert each; refusal a sentence, defect stops."""
    correlation_id = new_correlation_id()
    recorded = 0
    sentences: list[str] = []

    def left(key: object, sentence: str, cause: object = None) -> None:
        if sentence not in sentences:
            sentences.append(sentence)
        #: The page prints sentences; the log, keys.
        logger.info(
            "Session %s of library %s was not recorded under %s: %s%s",
            key,
            user.library.pk,
            correlation_id,
            sentence,
            "" if cause is None else f" ({cause})",
        )

    def say() -> None:
        if recorded:
            level = messages.SUCCESS
        elif sentences == [ALREADY_RECORDED]:
            level = messages.INFO
        else:
            level = messages.ERROR
        notify(
            request,
            f"{recorded} of {classified.posted} sessions recorded as historical "
            "playtime.",
            level=level,
        )
        for sentence in sentences:
            notify(
                request,
                sentence,
                level=messages.INFO if sentence == ALREADY_RECORDED else messages.ERROR,
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
            #: One type; the status tells defect apart.
            if failure.status_code != CONFLICT_STATUS:
                say()
                raise CommandFailed(
                    f"{recorded} of {classified.posted} sessions were recorded "
                    "before a problem on our side stopped the request. The "
                    "problem has been reported, and the review still lists the "
                    "rest.",
                    failure.status_code,
                ) from failure
            left(row.pk, failure.message, failure.__cause__)
            continue
        recorded += 1
    say()


@login_required
def reclassify_reviewed_sessions(request: HttpRequest) -> HttpResponse:
    user = cast(User, request.user)
    #: GET the filter; POST the page's keys.
    if request.method == "POST":
        classified = _classified(user.library, request.POST.getlist("session"))
    else:
        classified = Classified(tuple(_reviewable(user.library)), (), posted=0)
    rows = classified.convertible
    token = request.POST.get("submission") or str(uuid.uuid7())
    return confirm_and_apply(
        request,
        action=partial(_convert_each, request, user, classified, token),
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
    """Every row, not one page of them."""
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


#: The panel has no permanent home yet.
TEMPORARY_NOTE = (
    "This section is temporary. It moves into the Playtime page once that "
    "page can hold it."
)


def PlaytimeReviewPanel(library: UserLibrary, *, origin: OriginUrl) -> Node:
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
        P(class_="text-type-body text-body mb-4")[
            "Nothing is thrown away. Moving one session offers an Undo; moving "
            "all of them at once does not."
        ],
        Div(class_="flex flex-wrap items-center gap-2")[
            ControlButton(href=review_url(), color="gray")["See these sessions"],
            ControlButton(
                href=action_url("games:reclassify_reviewed_sessions", origin=origin),
                color="blue",
            )[f"Move all {waiting} to historical playtime"],
        ],
    )
