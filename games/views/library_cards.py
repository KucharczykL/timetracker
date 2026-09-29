"""Game detail's Library section: one card per copy."""

import datetime
import uuid
from collections.abc import Sequence
from typing import Literal, NamedTuple, get_args

from django import forms
from django.http import HttpRequest

from common.components import (
    ControlButton,
    CsrfInput,
    Details,
    Div,
    DropdownLinkItem,
    Form,
    FormFields,
    Icon,
    P,
    PageHeading,
    Pill,
    RowActionMenu,
    Span,
    Summary,
)
from common.components.core import Node
from common.components.primitives import ICON_BUTTON_SIZE_CLASS, control_button_class
from common.date_time_presentation import DateTimePresentation
from common.returns import OriginUrl, action_url
from common.temporal_presentation import present_temporal_value
from games.catalog_release import SHARED_GAME_RELEASE
from games.end_ways import END_WAY_LABELS
from games.endpoints import ENTRY_ACCESS_END
from games.entry_forms import (
    EntryAddForm,
    EntryEditForm,
    EntryEndForm,
    EntryResumeForm,
)
from games.models import EntryAccess, EntryFormat, Game, LibraryEntry, UserLibrary
from games.reads.endpoints import stated, way_of
from games.reads.entries import game_entries
from games.reads.releases import UNSPECIFIED_PLATFORM, game_releases

type LibraryAct = Literal["add", "edit", "end", "resume"]
LIBRARY_ACTS: frozenset[str] = frozenset(get_args(LibraryAct.__value__))

ADD_PREFIX = "library-add"
EMPTY_LIBRARY = "Nothing in your library yet."

_SUMMARY_CLASS = (
    f"{control_button_class(color='gray')} cursor-pointer list-none"
    " [&::-webkit-details-marker]:hidden"
)


class OpenForm(NamedTuple):
    """The disclosure a page opens, bound where a POST failed."""

    act: LibraryAct
    entry_id: uuid.UUID | None = None
    form: forms.Form | None = None


def open_form_from_query(request: HttpRequest) -> OpenForm | None:
    """`?library=<act>&copy=<id>`; a bad value opens nothing."""
    act = request.GET.get("library", "")
    if act not in LIBRARY_ACTS:
        return None
    if act == "add":
        return OpenForm("add")
    try:
        entry_id = uuid.UUID(request.GET.get("copy", ""))
    except ValueError:
        return None
    return OpenForm(act, entry_id)  # type: ignore[arg-type]


def copy_anchor(entry_id: uuid.UUID) -> str:
    return f"copy-{entry_id}"


def act_prefix(entry_id: uuid.UUID, act: LibraryAct) -> str:
    return f"copy-{entry_id}-{act}"


def open_url(game: Game, act: LibraryAct, entry_id: uuid.UUID | None = None) -> str:
    """Game detail with one disclosure open."""
    if entry_id is None:
        return f"{game.get_absolute_url()}?library={act}#library"
    return (
        f"{game.get_absolute_url()}?library={act}&copy={entry_id}"
        f"#{copy_anchor(entry_id)}"
    )


def release_words(entry: LibraryEntry) -> str:
    """Platform, then a named edition."""
    release = entry.release
    parts = [
        UNSPECIFIED_PLATFORM if release.platform is None else release.platform.name
    ]
    if release.edition.name:
        parts.append(release.edition.name)
    return " · ".join(parts)


def _facts(entry: LibraryEntry, presentation: DateTimePresentation) -> str:
    parts = [EntryAccess(entry.access).label, EntryFormat(entry.format).label]
    if entry.acquired is not None:
        parts.append(f"since {present_temporal_value(entry.acquired, presentation)}")
    return " · ".join(parts)


def _ended_chip(entry: LibraryEntry, presentation: DateTimePresentation) -> Node:
    ended = stated(entry, ENTRY_ACCESS_END)
    if ended is None:
        return Span()
    words = END_WAY_LABELS[way_of(ended)]
    if ended.when is not None:
        words = f"{words} {present_temporal_value(ended.when, presentation)}"
    return Pill(label=words)


def _disclosure(
    label: str,
    form: forms.Form,
    *,
    action: str,
    submit: str,
    cancel: str,
    is_open: bool,
    request: HttpRequest,
) -> Node:
    """A native disclosure holding one form."""
    return Details(
        open=is_open,
        class_="[&[open]]:basis-full [&[open]>summary]:mb-3",
    )[
        Summary(class_=_SUMMARY_CLASS)[label],
        Form(method="post", action=action, class_="flex flex-col gap-3")[
            CsrfInput(request),
            FormFields(form),
            Div(class_="flex flex-wrap gap-2")[
                ControlButton(type="submit")[submit],
                ControlButton(href=cancel, color="gray")["Cancel"],
            ],
        ],
    ]


class _CardForms(NamedTuple):
    edit: EntryEditForm
    end: EntryEndForm | None
    resume: EntryResumeForm | None


def _card_forms(
    entry: LibraryEntry,
    library: UserLibrary,
    presentation: DateTimePresentation,
    today: datetime.date,
    open_form: OpenForm | None,
) -> _CardForms:
    """Every form a card holds; the failed one bound."""

    def bound[FormT: forms.Form](act: LibraryAct, kind: type[FormT]) -> FormT | None:
        if not _is_open(open_form, act, entry.pk) or open_form is None:
            return None
        return open_form.form if isinstance(open_form.form, kind) else None

    edit = bound("edit", EntryEditForm) or EntryEditForm(
        entry=entry,
        library=library,
        presentation=presentation,
        today=today,
        prefix=act_prefix(entry.pk, "edit"),
    )
    if stated(entry, ENTRY_ACCESS_END) is None:
        end = bound("end", EntryEndForm) or EntryEndForm(
            entry=entry,
            presentation=presentation,
            today=today,
            prefix=act_prefix(entry.pk, "end"),
        )
        return _CardForms(edit, end, None)
    resume = bound("resume", EntryResumeForm) or EntryResumeForm(
        entry=entry,
        presentation=presentation,
        today=today,
        prefix=act_prefix(entry.pk, "resume"),
    )
    return _CardForms(edit, None, resume)


def _is_open(open_form: OpenForm | None, act: LibraryAct, entry_id) -> bool:
    return (
        open_form is not None
        and open_form.act == act
        and open_form.entry_id == entry_id
    )


def _copy_card(
    entry: LibraryEntry,
    game: Game,
    library: UserLibrary,
    *,
    presentation: DateTimePresentation,
    today: datetime.date,
    open_form: OpenForm | None,
    origin: OriginUrl,
    request: HttpRequest,
) -> Node:
    forms_ = _card_forms(entry, library, presentation, today, open_form)
    cancel = f"{game.get_absolute_url()}#{copy_anchor(entry.pk)}"
    disclosures = [
        _disclosure(
            "Edit",
            forms_.edit,
            action=action_url("games:edit_library_entry", entry.pk, origin=origin),
            submit="Save",
            cancel=cancel,
            is_open=_is_open(open_form, "edit", entry.pk),
            request=request,
        )
    ]
    if forms_.end is not None:
        disclosures.append(
            _disclosure(
                "End access",
                forms_.end,
                action=action_url("games:end_library_entry", entry.pk, origin=origin),
                submit="End access",
                cancel=cancel,
                is_open=_is_open(open_form, "end", entry.pk),
                request=request,
            )
        )
    if forms_.resume is not None:
        disclosures.append(
            _disclosure(
                "Resume",
                forms_.resume,
                action=action_url(
                    "games:resume_library_entry", entry.pk, origin=origin
                ),
                submit="Resume",
                cancel=cancel,
                is_open=_is_open(open_form, "resume", entry.pk),
                request=request,
            )
        )
    words = release_words(entry)
    menu = RowActionMenu(
        [
            DropdownLinkItem(
                action_url("games:remove_library_entry", entry.pk, origin=origin),
                "Remove",
                icon="delete",
                danger=True,
            )
        ],
        label=f"{words} copy actions",
        id=f"copy-menu-{entry.pk}",
    )
    return Div(
        id=copy_anchor(entry.pk),
        data_library_copy="",
        class_=(
            "flex flex-col gap-3 rounded-base border border-neutral-200 p-4"
            " dark:border-neutral-700"
        ),
    )[
        Div(class_="flex flex-wrap items-center gap-x-3 gap-y-1")[
            Span(class_="font-semibold")[words],
            Span(class_="text-neutral-600 dark:text-neutral-300")[
                _facts(entry, presentation)
            ],
            _ended_chip(entry, presentation),
            Div(class_="ml-auto")[menu],
        ],
        Div(class_="flex flex-wrap items-start gap-2")[*disclosures],
    ]


def _add_disclosure(
    game: Game,
    library: UserLibrary,
    *,
    presentation: DateTimePresentation,
    today: datetime.date,
    open_form: OpenForm | None,
    origin: OriginUrl,
    request: HttpRequest,
) -> Node:
    releases = list(game_releases(library, game)[:2])
    if not releases and game.library_id is None:
        return P(class_="text-neutral-600 dark:text-neutral-300")[SHARED_GAME_RELEASE]
    bound = open_form.form if open_form is not None and open_form.act == "add" else None
    form = bound or EntryAddForm(
        library=library,
        presentation=presentation,
        today=today,
        game=game,
        prefix=ADD_PREFIX,
        initial={"release": releases[0].pk} if len(releases) == 1 else None,
    )
    return Details(open=open_form is not None and open_form.act == "add")[
        Summary(class_=_SUMMARY_CLASS)[
            Icon("plus", size=ICON_BUTTON_SIZE_CLASS), "Add to library"
        ],
        Div(class_="mt-3")[
            Form(
                method="post",
                action=action_url("games:add_library_entry", game.pk, origin=origin),
                class_="flex flex-col gap-3",
            )[
                CsrfInput(request),
                FormFields(form),
                Div(class_="flex flex-wrap gap-2")[
                    ControlButton(type="submit")["Add"],
                    ControlButton(
                        href=f"{game.get_absolute_url()}#library", color="gray"
                    )["Cancel"],
                ],
            ]
        ],
    ]


def library_section(
    request: HttpRequest,
    game: Game,
    library: UserLibrary,
    *,
    presentation: DateTimePresentation,
    today: datetime.date,
    open_form: OpenForm | None,
) -> Node:
    """Heading, Add, and one card per live copy."""
    origin = game.get_absolute_url()
    entries: Sequence[LibraryEntry] = list(
        game_entries(library, game)
        .select_related("release__edition", "release__platform", "player_game__game")
        .order_by("acquired_lower", "created_at", "id")
    )
    cards = [
        _copy_card(
            entry,
            game,
            library,
            presentation=presentation,
            today=today,
            open_form=open_form,
            origin=origin,
            request=request,
        )
        for entry in entries
    ]
    count = len(entries)
    return Div(id="library", class_="mb-6 flex flex-col gap-4")[
        PageHeading(children=["Library"], badge=str(count) if count else ""),
        _add_disclosure(
            game,
            library,
            presentation=presentation,
            today=today,
            open_form=open_form,
            origin=origin,
            request=request,
        ),
        *(cards or [P()[EMPTY_LIBRARY]]),
    ]
