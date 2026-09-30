"""Game detail's Library section: have it, no longer have it."""

import uuid
from typing import NamedTuple

from common.components import (
    Chip,
    ControlButton,
    DropdownLinkItem,
    Icon,
    Span,
    SummaryGroup,
    SummaryRow,
    TruncatedText,
)
from common.components.core import Fragment, Node
from common.components.custom_elements import SplitButtonDropdown
from common.components.primitives import ICON_BUTTON_SIZE_CLASS
from common.date_time_presentation import DateTimePresentation
from common.returns import OriginUrl, action_url
from common.temporal_presentation import present_temporal_value
from games.endpoints import ENTRY_ACCESS_END
from games.models import EntryAccess, EntryFormat, Game, LibraryEntry, UserLibrary
from games.reads.endpoints import stated
from games.reads.entries import game_entries
from games.reads.releases import game_releases, platform_words
from games.views.entry_menu import entry_row_menu, submission_input

EMPTY_LIBRARY = "Nothing in your library yet."
EMPTY_LIBRARY_NOW = "Nothing in your library right now."
#: About four words of a note show; the rest waits for a hover.
NOTE_MAX_WIDTH_CLASS = "max-w-[16ch]"


def release_words(entry: LibraryEntry) -> str:
    """Platform, then a named edition."""
    release = entry.release
    parts = [platform_words(release)]
    if release.edition.name:
        parts.append(release.edition.name)
    return " · ".join(parts)


def _facts(entry: LibraryEntry, presentation: DateTimePresentation) -> str:
    """Access, format, since when."""
    parts = [EntryAccess(entry.access).label, EntryFormat(entry.format).label]
    if entry.acquired is not None:
        parts.append(f"since {present_temporal_value(entry.acquired, presentation)}")
    return " · ".join(parts)


def _note_chip(note: str) -> Node:
    """The note, clipped to a few words; the whole of it on hover."""
    return Chip(tone="neutral", icon="note")[
        TruncatedText(note, max_width=NOTE_MAX_WIDTH_CLASS)
    ]


def _copy_row(
    entry: LibraryEntry,
    presentation: DateTimePresentation,
    origin: OriginUrl,
    csrf_token: str,
    *,
    label: str,
) -> Node:
    return SummaryRow(
        label=label,
        subtitle=Fragment(
            Span()[_facts(entry, presentation)],
            *([_note_chip(entry.note)] if entry.note else []),
        ),
        control=entry_row_menu(entry, origin, csrf_token),
        dense=not label,
    )


class CopyRows(NamedTuple):
    rows: list[Node]
    #: Copies had now, not rows: a group holds several.
    copies: int
    #: Copies whose access ended; the Library tab lists them.
    had: int


def copy_rows(
    game: Game,
    library: UserLibrary,
    presentation: DateTimePresentation,
    origin: OriginUrl,
    csrf_token: str,
) -> CopyRows:
    """One row per copy had now; a version with several gathers them."""
    entries = (
        game_entries(library, game)
        .select_related("release__edition", "release__platform", "player_game__game")
        .order_by("acquired_lower", "created_at", "id")
    )
    #: First acquired first, by version, keeping that order.
    by_version: dict[uuid.UUID, list[LibraryEntry]] = {}
    count = had = 0
    for entry in entries:
        if stated(entry, ENTRY_ACCESS_END) is not None:
            had += 1
            continue
        count += 1
        by_version.setdefault(entry.release_id, []).append(entry)
    rows: list[Node] = [
        SummaryGroup(
            label=release_words(copies[0]),
            rows=[
                _copy_row(entry, presentation, origin, csrf_token, label="")
                for entry in copies
            ],
        )
        for copies in by_version.values()
    ]
    return CopyRows(rows, count, had)


def library_add_control(
    game: Game, library: UserLibrary, origin: OriginUrl, csrf_token: str
) -> Node | None:
    """Add in one click, or with details; none where nothing can be added.

    With no version yet, only the page can add: it creates one.
    """
    details = action_url("games:add_library_entry", game.pk, origin=origin)
    if not game_releases(library, game).exists():
        if game.library_id != library.pk:
            return None
        return ControlButton(
            href=details,
            color="gray",
            title="Add a copy of this game to your library",
        )[Icon("plus", size=ICON_BUTTON_SIZE_CLASS), "Add to library"]
    return SplitButtonDropdown(
        primary=ControlButton(
            method="post",
            action=action_url("games:add_library_entry_now", game.pk, origin=origin),
            csrf_token=csrf_token,
            hidden_fields=submission_input(),
            color="gray",
            title="Add a copy of this game to your library",
        )[Icon("plus", size=ICON_BUTTON_SIZE_CLASS), "Add to library"],
        items=[DropdownLinkItem(details, "Add to library…")],
        id=f"library-add-{game.pk}",
        aria_label="More ways to add to library",
        menu_width="w-56",
    )
