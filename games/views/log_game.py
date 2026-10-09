"""Views for the Log a game modal."""

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, QueryDict
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
from common.opener_facts import LOGGED_VALUE_LENGTH
from games.log_forms import STALE_GAME, UNTRACKED_STATUS, LogGameForm, canonical_text
from games.models import Game, UserLibrary
from games.reads.endpoints import StatedEndpoint
from games.reads.log_game import HeldFacts, held_facts
from games.views.copy_pages import cancel_url, game_page
from games.views.general import request_calendar_today
from games.views.returns import origin_from
from games.writes.log_game import LogRefused, LogStatement, LogStep, log_game
from games.writes.playergame import new_correlation_id
from timetracker.uuidv7 import UUIDv7ParseError, parse_uuidv7

type NestedSection = Literal["playtime", "more"]
type FieldName = str

logger = logging.getLogger("games.opener_facts")

#: Field where a refusal's sentence sits.
REFUSED_FIELD: Final[Mapping[LogStep, FieldName]] = {
    "track": "game",
    "status": "status",
    "platform": "platform",
    "copy": "platform",
    "dates": "started",
    "note": "note",
    "playtime": "playtime_kind",
    "mastered": "mastered",
}

#: Each written step's words, in order.
SAVED_WORDS: Final[Mapping[LogStep, str]] = {
    "copy": "the copy",
    "dates": "the dates",
    "note": "the note",
    "playtime": "the playtime",
    "mastered": "mastered",
    "status": "the status",
}
TRACKED_WORDS: Final = "the game in your library"

#: Seen fields each written step refreshes.
SEEN_FIELDS: Final[Mapping[LogStep, tuple[FieldName, ...]]] = {
    "track": (
        "status_seen",
        "platform_seen",
        "started_seen",
        "completed_seen",
        "note_seen",
        "mastered_seen",
        "run",
    ),
    "copy": ("platform_seen",),
    "platform": ("platform_seen",),
    "dates": ("started_seen", "completed_seen", "run"),
    "note": ("note_seen", "run"),
    "playtime": ("run",),
    "mastered": ("mastered_seen",),
    "status": ("status_seen",),
}


@dataclass(frozen=True, slots=True)
class SectionSpec:
    """One nested section and its opener."""

    title: str
    fields: tuple[FieldName, ...]
    #: Fields whose value marks the section held.
    holds: tuple[FieldName, ...]
    idle: str
    held: str


SECTIONS: Final[Mapping[NestedSection, SectionSpec]] = {
    "playtime": SectionSpec(
        title="Add playtime",
        fields=("playtime_kind", "day", "duration", "device"),
        holds=("duration_hours", "duration_minutes"),
        idle="Add playtime…",
        held="Playtime added",
    ),
    "more": SectionSpec(
        title="Mastered and note",
        fields=("mastered", "note"),
        holds=("mastered", "note"),
        idle="Mastered and note…",
        held="Mastered and note set",
    ),
}

#: Read by ts/elements/log-sections.ts.
SECTION_DIALOG: Final = "data-log-section"
SECTION_DONE: Final = "data-log-section-done"
SECTION_EDIT: Final = "data-log-section-edit"
SECTION_HOLDS_ATTRIBUTE: Final = "data-log-section-holds"
SECTION_IDLE: Final = "data-log-section-idle"
SECTION_HELD: Final = "data-log-section-held"

#: Dates side by side from sm up.
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
    """Game a key names; None if absent."""
    try:
        key = parse_uuidv7(raw)
    except UUIDv7ParseError:
        return None
    return (
        Game.objects.filter(Q(library__isnull=True) | Q(library=library))
        .filter(pk=key)
        .first()
    )


def _prefill_game(library: UserLibrary, raw: str) -> Game | None:
    """The navbar's pick; warns on a bad one."""
    if not raw:
        return None
    game = _game_keyed(library, raw)
    if game is None:
        logger.warning(
            "Opener fact %s.%s=%s %s.",
            LogGameForm.__name__,
            "prefill_game",
            repr(raw)[:LOGGED_VALUE_LENGTH],
            "is malformed or names no game this library holds",
        )
    return game


def _named_game(request: HttpRequest, library: UserLibrary) -> Game | None:
    """Page's game: posted or opener-stated."""
    source = request.POST if request.method == "POST" else request.GET
    raw = source.get("game", "")
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
        prefill = _prefill_game(library, request.GET.get("prefill_game", ""))
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

    if data is not None and form.stale_game and game is not None:
        # Stale seen values: show this game fresh.
        messages.error(request, STALE_GAME)
        fresh = held_facts(library, game)
        return _render(
            request,
            _build(request, data=None, held=fresh, prefill=game),
            game=game,
            held=fresh,
            status=200,
        )

    return _render(request, form, game=game or prefill, held=held, status=200)


def _endpoint_seen(endpoint: StatedEndpoint | None) -> str:
    return canonical_text(None if endpoint is None else endpoint.when)


def _seen_values(held: HeldFacts) -> dict[FieldName, str]:
    """Seen fields for a held game."""
    status = UNTRACKED_STATUS if held.status is None else held.status
    return {
        "status_seen": status.value,
        "platform_seen": "" if held.platform is None else str(held.platform.pk),
        "started_seen": _endpoint_seen(held.started),
        "completed_seen": _endpoint_seen(held.completed),
        "note_seen": held.note,
        "mastered_seen": "True" if held.mastered else "False",
        "run": "" if held.run is None else str(held.run.pk),
    }


def _reseen(
    data: QueryDict, held: HeldFacts, written: frozenset[LogStep], tracked: bool
) -> None:
    """Refresh seen values the written steps changed."""
    fresh = _seen_values(held)
    steps: Iterable[LogStep] = ("track",) if tracked else written
    names = {name for step in steps for name in SEEN_FIELDS[step]}
    for name in names:
        data[name] = fresh[name]


def _join(words: Sequence[str]) -> str:
    if len(words) == 1:
        return words[0]
    return f"{', '.join(words[:-1])} and {words[-1]}"


def _saved_line(written: frozenset[LogStep], tracked: bool) -> str | None:
    """What a refused press kept, if anything."""
    words = [TRACKED_WORDS] if tracked else []
    words += [word for step, word in SAVED_WORDS.items() if step in written]
    if not words:
        return None
    return f"Saved: {_join(words)}. Fix the field below and save again."


def _refused(
    request: HttpRequest, refused: LogRefused, statement: LogStatement
) -> HttpResponse:
    """Rebuild a refused form; sentence, section open."""
    data = request.POST.copy()
    if "playtime" in refused.written:
        data["duration_hours"] = ""
        data["duration_minutes"] = ""
    if refused.written:
        # A kept write keys its retry apart from the first press.
        data[ATTEMPT_FIELD] = str(statement.attempt + 1)
    library = cast(User, request.user).library
    held = held_facts(library, statement.game)
    kept = _saved_line(refused.written, refused.tracked_the_game)
    if kept is not None:
        _reseen(data, held, refused.written, refused.tracked_the_game)
    rebuilt = _build(request, data=data, held=held)
    rebuilt.is_valid()
    if kept is not None:
        rebuilt.add_error(None, kept)
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
        open_section=_open_section(form) or "",
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


def _open_section(form: LogGameForm) -> NestedSection | None:
    """The first nested section a refusal names."""
    if not form.is_bound:
        return None
    for section, spec in SECTIONS.items():
        if any(form.has_error(name) for name in spec.fields):
            return section
    return None


def _groups() -> list[FormFieldGroup]:
    """Inline fields, then nested dialogs' fieldsets."""
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
            SECTIONS["playtime"].fields,
            look="hidden",
            container=_section_dialog("playtime"),
        ),
        FormFieldGroup(
            "Mastered and note",
            SECTIONS["more"].fields,
            look="hidden",
            container=_section_dialog("more"),
        ),
    ]


def _section_dialog(section: NestedSection) -> FieldGroupContainer:
    """Section's opener and its dialog fieldsets."""
    spec = SECTIONS[section]
    titled = titled_header(spec.title, title_id=f"log-section-{section}-title")
    holds = " ".join(spec.holds)

    def contain(fieldsets: Sequence[Node]) -> Node:
        return Fragment(
            ControlButton([(SECTION_EDIT, section)], variant="outline", class_="mt-2")[
                Span([(SECTION_IDLE, "")])[spec.idle],
                Span([(SECTION_HELD, ""), ("hidden", "")])[spec.held],
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
