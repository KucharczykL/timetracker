"""Game detail's Library section."""

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
from games.models import EntryAccess, EntryFormat, Game, LibraryEntry, UserLibrary
from games.reads.entries import copy_end, game_entries
from games.reads.releases import edition_words, game_releases, platform_words
from games.views.entry_menu import entry_row_menu, submission_input

EMPTY_LIBRARY = "Nothing in your library yet."
EMPTY_LIBRARY_NOW = "Nothing in your library right now."
#: About four words; hover shows the rest.
NOTE_MAX_WIDTH_CLASS = "max-w-[16ch]"


def release_words(entry: LibraryEntry) -> str:
    """Platform, then a named edition."""
    release = entry.release
    parts = [platform_words(release)]
    if words := edition_words(release.edition):
        parts.append(words)
    return " · ".join(parts)


def _facts(entry: LibraryEntry, presentation: DateTimePresentation) -> str:
    """Access, format, since when."""
    parts = [EntryAccess(entry.access).label, EntryFormat(entry.format).label]
    if entry.acquired is not None:
        parts.append(f"since {present_temporal_value(entry.acquired, presentation)}")
    return " · ".join(parts)


def _note_chip(note: str) -> Node:
    """The note, clipped; whole on hover."""
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
    rows: tuple[Node, ...]
    #: Copies, not rows: a group holds several.
    held: int
    ended: int


def copy_rows(
    game: Game,
    library: UserLibrary,
    presentation: DateTimePresentation,
    origin: OriginUrl,
    csrf_token: str,
) -> CopyRows:
    """Copies had now, grouped by version."""
    entries = (
        game_entries(library, game)
        .select_related("release__edition", "release__platform", "player_game__game")
        .order_by("acquired_lower", "created_at", "id")
    )
    #: Versions in first-acquired order.
    by_version: dict[uuid.UUID, list[LibraryEntry]] = {}
    held = ended = 0
    for entry in entries:
        if copy_end(entry) is not None:
            ended += 1
            continue
        held += 1
        by_version.setdefault(entry.release_id, []).append(entry)
    rows = tuple(
        SummaryGroup(
            label=release_words(copies[0]),
            rows=[
                _copy_row(entry, presentation, origin, csrf_token, label="")
                for entry in copies
            ],
        )
        for copies in by_version.values()
    )
    return CopyRows(rows, held, ended)


def library_add_control(
    game: Game, library: UserLibrary, origin: OriginUrl, csrf_token: str
) -> Node | None:
    """One click, or the page; none if impossible."""
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
