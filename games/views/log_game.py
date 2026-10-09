"""Log a game: one press states a copy, its dates, a playtime, a status."""

from collections.abc import Mapping
from typing import Final, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from common.components import (
    AddForm,
    Div,
    FormFieldGroup,
    FormFieldPresentation,
    FormFields,
    Fragment,
    Node,
    P,
)
from common.date_time_presentation import date_time_presentation_for_request
from common.duration_presentation import (
    DurationPresentation,
    duration_presentation_for_request,
)
from common.layout import render_page
from games.log_forms import (
    PANEL_SHOWN,
    RUN_ROW_SHOWN,
    SECTION_LABELS,
    SUMMARY_HIDDEN,
    LogGameForm,
)
from games.models import Game, Playthrough
from games.price_fields import PRICE_GROUP, price_presentations
from games.reads.endpoints import StatedEndpoint
from games.reads.log_game import HeldFacts, held_facts
from games.reads.playthrough_endpoints import stated_completion, stated_start
from games.views.copy_pages import cancel_url, game_page
from games.views.general import request_calendar_today
from games.writes.log_game import (
    SECTIONS,
    LogRefused,
    LogSection,
    LogStatement,
    LogStep,
    log_game,
)
from games.writes.playergame import new_correlation_id

#: The field a refused step's sentence sits on: a section's first field.
REFUSED_FIELD: Final[Mapping[LogStep, str]] = {
    "game": "game",
    "status": "status",
    "copy": "release",
    "dates": "started",
    "playtime": "playtime_kind",
    "more": "mastered",
}

#: The panels of each section, in the order the page shows them.
PANEL_GROUPS: Final[tuple[tuple[str, tuple[str, ...], LogSection], ...]] = (
    ("Your copy", ("release", "format", "access", "acquired"), "copy"),
    ("Price", ("price", "amount", "currency"), "copy"),
    ("Dates", ("started", "completed"), "dates"),
    ("Playtime", ("playtime_kind", "day", "duration", "device"), "playtime"),
    ("Mastered and note", ("mastered", "note"), "more"),
)


def _build(
    request: HttpRequest, *, data: object, held: HeldFacts | None
) -> LogGameForm:
    library = cast(User, request.user).library
    return LogGameForm(
        data,
        library=library,
        presentation=date_time_presentation_for_request(request),
        today=request_calendar_today(request, library),
        facts=request.GET,
        held=held,
    )


@login_required
def log_game_page(request: HttpRequest) -> HttpResponse:
    user = cast(User, request.user)
    library = user.library
    data = request.POST if request.method == "POST" else None
    form = _build(request, data=data, held=None)
    game = form.stated("game", Game)
    held = None
    if game is not None:
        held = held_facts(library, game)
        form = _build(request, data=data, held=held)

    if data is not None and form.is_valid():
        statement = form.statement()
        try:
            logged = log_game(
                user,
                statement,
                correlation_id=new_correlation_id(),
                token=form.cleaned_data["submission"],
            )
        except LogRefused as refused:
            return _partial_refusal(request, refused, statement, held)
        messages.success(request, f"Logged {statement.game.name}.")
        if logged.tracked_the_game:
            messages.info(request, f"{statement.game} is now tracked in your library.")
        return redirect(game_page(request, statement.game))

    return _render(request, form, game=_title_game(form), held=held, status=200)


def _title_game(form: LogGameForm) -> Game | None:
    """The fixed game, else the one the form cleaned, if any."""
    chosen = form.stated("game", Game)
    if chosen is not None:
        return chosen
    return getattr(form, "cleaned_data", {}).get("game")


def _partial_refusal(
    request: HttpRequest,
    refused: LogRefused,
    statement: LogStatement,
    held: HeldFacts | None,
) -> HttpResponse:
    """Rebuild the form with what was written saved; the step's sentence on it."""
    posted_saved = set(request.POST.getlist("saved")) | refused.written
    data = request.POST.copy()
    data.setlist("saved", [section for section in SECTIONS if section in posted_saved])
    data.setlist(
        "sections",
        [
            section
            for section in request.POST.getlist("sections")
            if section not in refused.written
        ],
    )
    rebuilt = _build(request, data=data, held=held)
    rebuilt.fix_field("game", statement.game, statement=statement.game.search_label)
    rebuilt.is_valid()
    rebuilt.add_error(REFUSED_FIELD[refused.step], refused.failure.message)
    return _render(
        request,
        rebuilt,
        game=statement.game,
        held=held,
        status=refused.failure.status_code,
    )


def _render(
    request: HttpRequest,
    form: LogGameForm,
    *,
    game: Game | None,
    held: HeldFacts | None,
    status: int,
) -> HttpResponse:
    durations = duration_presentation_for_request(request)
    presentations: dict[str, FormFieldPresentation] = {
        **price_presentations(),
        "playthrough": FormFieldPresentation(row_class=RUN_ROW_SHOWN),
        "status": FormFieldPresentation(
            after_control=Fragment(
                _saved_lines(form.saved_sections()),
                _summary_lines(held, durations) if held is not None else None,
            )
        ),
    }
    fields = Div(class_="group/log")[
        FormFields(
            form,
            groups=_groups(),
            presentations=presentations,
        )
    ]
    return render_page(
        request,
        AddForm(
            form,
            request=request,
            submit_class="",
            fields=fields,
            submit_label="Log game",
            cancel_url=cancel_url(request, lambda: game),
        ),
        title="Log a game" if game is None else f"Log {game.name}",
        status=status,
        width="form",
    )


def _groups() -> list[FormFieldGroup]:
    """The top fields, the panels, then the Add ticks."""
    groups = [FormFieldGroup("Game", ("game", "status", "playthrough"), look="hidden")]
    for legend, names, section in PANEL_GROUPS:
        shown = PANEL_SHOWN[section]
        groups.append(
            FormFieldGroup(
                legend,
                names,
                look="panel",
                class_=f"{shown} {PRICE_GROUP}" if "price" in names else shown,
            )
        )
    groups.append(FormFieldGroup("Add", ("sections",), look="hidden"))
    return groups


def _saved_lines(saved: frozenset[LogSection]) -> Node | None:
    if not saved:
        return None
    return Fragment(
        *(
            P(class_="text-type-body text-fg-success-strong")[
                f"Saved: {SECTION_LABELS[section]}"
            ]
            for section in SECTIONS
            if section in saved
        )
    )


def _summary_lines(held: HeldFacts, durations: DurationPresentation) -> Node:
    """Each held fact, one muted line; ticking its section hides it."""
    lines: dict[LogSection, str] = {}
    if held.copies:
        more = len(held.copies) - 1
        lines["copy"] = held.copies[0] + (f" and {more} more" if more else "")
    if held.run is not None:
        lines["dates"] = _dates_words(held.run)
    lines["playtime"] = (
        f"{durations.format(held.playtime)} played"
        if held.playtime
        else "No playtime yet"
    )
    lines["more"] = "Mastered" if held.mastered else "Not mastered"
    return Fragment(
        *(
            P(class_=f"text-type-body text-body {SUMMARY_HIDDEN[section]}")[text]
            for section, text in lines.items()
        )
    )


def _dates_words(run: Playthrough) -> str:
    started = _day_words(stated_start(run))
    completed = _day_words(stated_completion(run))
    return f"Started {started} · Finished {completed}"


def _day_words(endpoint: StatedEndpoint | None) -> str:
    if endpoint is None or endpoint.when is None or endpoint.when.canonical is None:
        return "not stated"
    return endpoint.when.canonical
