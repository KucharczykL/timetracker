"""Game detail's Library section: have it, no longer have it."""

import uuid

from common.components import (
    ControlButton,
    DropdownLinkItem,
    Icon,
    Input,
    SummaryAction,
    SummaryRow,
)
from common.components.core import Node
from common.components.custom_elements import SplitButtonDropdown
from common.components.primitives import ICON_BUTTON_SIZE_CLASS
from common.date_time_presentation import DateTimePresentation
from common.returns import OriginUrl, action_url
from common.temporal_presentation import present_temporal_value
from games.end_ways import END_WAY_LABELS
from games.endpoints import ENTRY_ACCESS_END
from games.models import EntryAccess, EntryFormat, Game, LibraryEntry, UserLibrary
from games.reads.endpoints import stated, way_of
from games.reads.entries import game_entries
from games.reads.releases import game_releases, platform_words

EMPTY_LIBRARY = "Nothing in your library yet."
#: The hidden field a one-click form posts; `library_entry` reads it.
SUBMISSION_FIELD = "submission"


def release_words(entry: LibraryEntry) -> str:
    """Platform, then a named edition."""
    release = entry.release
    parts = [platform_words(release)]
    if release.edition.name:
        parts.append(release.edition.name)
    return " · ".join(parts)


def _facts(entry: LibraryEntry, presentation: DateTimePresentation) -> str:
    """Access, format, since when, and how it left."""
    parts = [EntryAccess(entry.access).label, EntryFormat(entry.format).label]
    if entry.acquired is not None:
        parts.append(f"since {present_temporal_value(entry.acquired, presentation)}")
    ended = stated(entry, ENTRY_ACCESS_END)
    if ended is not None:
        words = END_WAY_LABELS[way_of(ended)]
        if ended.when is not None:
            words = f"{words} {present_temporal_value(ended.when, presentation)}"
        parts.append(words)
    return " · ".join(parts)


def _one_click(
    *,
    route: str,
    target: uuid.UUID,
    label: str,
    details: list[Node],
    origin: OriginUrl | None,
    csrf_token: str,
    menu_id: str,
) -> Node:
    """One POST that states the common case; its ▾ holds the rest."""
    return SplitButtonDropdown(
        primary=ControlButton(
            method="post",
            action=action_url(route, target, origin=origin),
            csrf_token=csrf_token,
            hidden_fields=Input(
                type="hidden", name=SUBMISSION_FIELD, value=str(uuid.uuid7())
            ),
            color="gray",
        )[label],
        items=details,
        id=menu_id,
        aria_label=f"More ways to say {label.lower()}",
        menu_width="w-56",
    )


def copy_control(
    entry: LibraryEntry, origin: OriginUrl | None, csrf_token: str
) -> Node:
    """I no longer have it, or I have it again; details in the ▾."""
    if stated(entry, ENTRY_ACCESS_END) is None:
        return _one_click(
            route="games:end_library_entry_now",
            target=entry.pk,
            label="I no longer have it",
            details=[
                DropdownLinkItem(
                    action_url("games:end_library_entry", entry.pk, origin=origin),
                    "…and add details",
                )
            ],
            origin=origin,
            csrf_token=csrf_token,
            menu_id=f"copy-control-{entry.pk}",
        )
    return _one_click(
        route="games:resume_library_entry_now",
        target=entry.pk,
        label="I have it again",
        details=[
            DropdownLinkItem(
                action_url("games:resume_library_entry", entry.pk, origin=origin),
                "…and add details",
            ),
            DropdownLinkItem(
                action_url("games:edit_library_entry_end", entry.pk, origin=origin),
                "Edit how it left",
            ),
        ],
        origin=origin,
        csrf_token=csrf_token,
        menu_id=f"copy-control-{entry.pk}",
    )


def copy_rows(
    game: Game,
    library: UserLibrary,
    presentation: DateTimePresentation,
    origin: OriginUrl,
    csrf_token: str,
) -> list[Node]:
    """One row per live copy, earliest acquired first."""
    entries = (
        game_entries(library, game)
        .select_related("release__edition", "release__platform", "player_game__game")
        .order_by("acquired_lower", "created_at", "id")
    )
    return [
        SummaryRow(
            label=release_words(entry),
            subtitle=_facts(entry, presentation),
            control=copy_control(entry, origin, csrf_token),
            actions=[
                SummaryAction(
                    "Edit details",
                    action_url("games:edit_library_entry", entry.pk, origin=origin),
                ),
                SummaryAction(
                    "Remove",
                    action_url("games:remove_library_entry", entry.pk, origin=origin),
                ),
            ],
            detail=entry.note or None,
        )
        for entry in entries
    ]


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
            hidden_fields=Input(
                type="hidden", name=SUBMISSION_FIELD, value=str(uuid.uuid7())
            ),
            color="gray",
            title="Add a copy of this game to your library",
        )[Icon("plus", size=ICON_BUTTON_SIZE_CLASS), "Add to library"],
        items=[DropdownLinkItem(details, "…with details")],
        id=f"library-add-{game.pk}",
        aria_label="More ways to add to library",
        menu_width="w-56",
    )
