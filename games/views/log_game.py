"""Log a game: one press states a game's status, platform, dates, playtime and mastery."""

from collections.abc import Mapping, Sequence
from typing import Final, Literal, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from common.components import (
    AddForm,
    ControlButton,
    Div,
    FieldGroupContainer,
    FormFieldGroup,
    FormFields,
    Fragment,
    ModalDialog,
    ModalPanel,
    Node,
    Span,
)
from common.components.form_dialog import MODAL_SURFACE_CLASS
from common.components.modal import titled_header
from common.components.primitives import custom_element_builder
from common.date_time_presentation import date_time_presentation_for_request
from common.layout import render_page
from games.log_forms import LogGameForm
from games.models import Game, UserLibrary
from games.reads.log_game import HeldFacts, held_facts
from games.views.copy_pages import cancel_url, game_page
from games.views.general import request_calendar_today
from games.views.returns import origin_from
from games.writes.log_game import LogRefused, LogStatement, LogStep, log_game
from games.writes.playergame import new_correlation_id
from timetracker.uuidv7 import UUIDv7ParseError, parse_uuidv7

type NestedSection = Literal["playtime", "more"]

#: The field a refused step's sentence sits on: a section's first field.
REFUSED_FIELD: Final[Mapping[LogStep, str]] = {
    "track": "game",
    "status": "status",
    "platform": "platform",
    "copy": "platform",
    "dates": "started",
    "playtime": "playtime_kind",
    "more": "mastered",
}

#: The fields each nested section holds, in the order the page shows them.
SECTION_FIELDS: Final[Mapping[NestedSection, tuple[str, ...]]] = {
    "playtime": ("playtime_kind", "day", "duration", "device"),
    "more": ("mastered", "note"),
}
#: The fields that state a section held once one of them holds a value.
SECTION_HOLDS: Final[Mapping[NestedSection, tuple[str, ...]]] = {
    "playtime": ("duration_hours", "duration_minutes"),
    "more": ("mastered", "note"),
}
SECTION_TITLES: Final[Mapping[NestedSection, str]] = {
    "playtime": "Add playtime",
    "more": "Mastered and note",
}
SECTION_OPENER: Final[Mapping[NestedSection, tuple[str, str]]] = {
    "playtime": ("Add playtime…", "Playtime added"),
    "more": ("Mastered and note…", "Mastered and note set"),
}
#: Read by ts/elements/log-sections.ts.
SECTION_DIALOG: Final = "data-log-section"
SECTION_DONE: Final = "data-log-section-done"
SECTION_EDIT: Final = "data-log-section-edit"
SECTION_HOLDS_ATTRIBUTE: Final = "data-log-section-holds"
SECTION_IDLE: Final = "data-log-section-idle"
SECTION_HELD: Final = "data-log-section-held"

#: Dates sit side by side from the small breakpoint up.
DATES_ROW_CLASS: Final = "sm:flex-row sm:gap-4 sm:[&>*]:flex-1"
_LogSections = custom_element_builder("log-sections")
_SECTION_PANEL_CLASS: Final = f"flex w-[calc(100%-2rem)] max-w-xl {MODAL_SURFACE_CLASS}"
ATTEMPT_FIELD: Final = "attempt"


def _build(
    request: HttpRequest,
    *,
    data: object,
    held: HeldFacts | None,
    prefill: Game | None = None,
) -> LogGameForm:
    library = cast(User, request.user).library
    return LogGameForm(
        data,
        library=library,
        presentation=date_time_presentation_for_request(request),
        today=request_calendar_today(request, library),
        facts=request.GET,
        held=held,
        prefill=prefill,
    )


def _game_keyed(library: UserLibrary, raw: str) -> Game | None:
    """The game a key names, removed or not; None for no such game."""
    try:
        key = parse_uuidv7(raw)
    except UUIDv7ParseError:
        return None
    return (
        Game.objects.filter(Q(library__isnull=True) | Q(library=library))
        .filter(pk=key)
        .first()
    )


def _named_game(request: HttpRequest, library: UserLibrary) -> Game | None:
    """The game the page is about: posted, opened from, or prefilled."""
    if request.method == "POST":
        raw = request.POST.get("game", "")
    else:
        raw = request.GET.get("game", "")
    return _game_keyed(library, raw) if raw else None


@login_required
def log_game_page(request: HttpRequest) -> HttpResponse:
    user = cast(User, request.user)
    library = user.library
    data = request.POST if request.method == "POST" else None
    game = _named_game(request, library)
    held = None if game is None else held_facts(library, game)
    prefill = None
    if data is None and game is None:
        prefill = _game_keyed(library, request.GET.get("prefill_game", ""))
        if prefill is not None:
            held = held_facts(library, prefill)
    form = _build(request, data=data, held=held, prefill=prefill)

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
            return _refused(request, refused, statement)
        messages.success(request, f"Logged {statement.game.name}.")
        if logged.tracked_the_game:
            messages.info(request, f"{statement.game} is now tracked in your library.")
        return redirect(game_page(request, statement.game))

    return _render(request, form, game=game or prefill, held=held, status=200)


def _attempt(raw: str | None) -> int:
    try:
        return int(raw or 0)
    except ValueError:
        return 0


def _refused(
    request: HttpRequest, refused: LogRefused, statement: LogStatement
) -> HttpResponse:
    """Rebuild the form from the post; the step's sentence on it, its section open.

    A playtime the press already wrote leaves the form, and the next one
    posts under a new attempt key.
    """
    data = request.POST.copy()
    if "playtime" in refused.written:
        data["duration_hours"] = ""
        data["duration_minutes"] = ""
        data[ATTEMPT_FIELD] = str(_attempt(request.POST.get(ATTEMPT_FIELD)) + 1)
    library = cast(User, request.user).library
    held = held_facts(library, statement.game)
    rebuilt = _build(request, data=data, held=held)
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
    tracked = held is not None and held.status is not None
    fields = _LogSections(
        open_section=_open_section(form),
        route=reverse("games:log_game"),
        origin=origin_from(request) or "",
        class_="group/log",
    )[FormFields(form, groups=_groups())]
    return render_page(
        request,
        AddForm(
            form,
            request=request,
            submit_class="",
            fields=fields,
            submit_label="Save" if tracked else "Create log",
            cancel_url=cancel_url(request, lambda: game),
        ),
        title="Log a game" if game is None else f"Log {game.name}",
        status=status,
        width="form",
    )


def _open_section(form: LogGameForm) -> NestedSection | Literal[""]:
    """The first nested section a refusal names."""
    if not form.is_bound:
        return ""
    for section, names in SECTION_FIELDS.items():
        if any(form.has_error(name) for name in names):
            return section
    return ""


def _groups() -> list[FormFieldGroup]:
    """The inline fields, then each nested section's fieldsets in its dialog."""
    return [
        FormFieldGroup("Game", ("game", "status", "platform"), look="hidden"),
        FormFieldGroup(
            "Dates",
            ("started", "completed"),
            look="hidden",
            class_=DATES_ROW_CLASS,
        ),
        FormFieldGroup(
            "Playtime",
            SECTION_FIELDS["playtime"],
            look="hidden",
            container=_section_dialog("playtime"),
        ),
        FormFieldGroup(
            "Mastered and note",
            SECTION_FIELDS["more"],
            look="hidden",
            container=_section_dialog("more"),
        ),
    ]


def _section_dialog(section: NestedSection) -> FieldGroupContainer:
    """One section's opener, and its fieldsets in a nested dialog."""
    titled = titled_header(
        SECTION_TITLES[section], title_id=f"log-section-{section}-title"
    )
    idle, held = SECTION_OPENER[section]
    holds = " ".join(SECTION_HOLDS[section])

    def contain(fieldsets: Sequence[Node]) -> Node:
        return Fragment(
            ControlButton([(SECTION_EDIT, section)], variant="outline")[
                Span([(SECTION_IDLE, "")])[idle],
                Span([(SECTION_HELD, ""), ("hidden", "")])[held],
            ],
            ModalDialog(
                [
                    (SECTION_DIALOG, section),
                    (SECTION_HOLDS_ATTRIBUTE, holds),
                    titled.labelled_by,
                ]
            )[
                ModalPanel(class_=_SECTION_PANEL_CLASS)[
                    titled.header,
                    Div(class_="min-h-0 overflow-y-auto overscroll-contain p-4")[
                        *fieldsets,
                        Div(class_="mt-4 flex justify-end")[
                            ControlButton([(SECTION_DONE, "")])["Done"]
                        ],
                    ],
                ]
            ],
        )

    return contain
