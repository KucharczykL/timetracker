"""What one Library row offers."""

import uuid

from common.components import (
    DropdownLinkItem,
    DropdownPostItem,
    Input,
    RowActionMenu,
)
from common.components.core import Node
from common.returns import OriginUrl, action_url
from games.bulk_removal import REMOVE_ENTRY
from games.endpoints import ENTRY_ACCESS_END
from games.models import LibraryEntry
from games.reads.endpoints import stated
from games.reads.releases import platform_words
from games.views.library_cards import SUBMISSION_FIELD


def entry_row_menu(
    entry: LibraryEntry, origin: OriginUrl | None, csrf_token: str
) -> Node:
    """The Game detail row's acts: one click first, then the pages."""
    game = entry.player_game.game
    ended = stated(entry, ENTRY_ACCESS_END) is not None

    def page(route: str) -> str:
        return action_url(route, entry.pk, origin=origin)

    def one_click(route: str, label: str, icon: str) -> Node:
        return DropdownPostItem(
            page(route),
            label,
            csrf_token=csrf_token,
            hidden_fields=Input(
                type="hidden", name=SUBMISSION_FIELD, value=str(uuid.uuid7())
            ),
            icon=icon,
        )

    have = (
        [
            one_click("games:resume_library_entry_now", "I have it again", "reset"),
            DropdownLinkItem(
                page("games:resume_library_entry"), "I have it again, with details…"
            ),
            DropdownLinkItem(page("games:edit_library_entry_end"), "Edit how it left"),
        ]
        if ended
        else [
            one_click("games:end_library_entry_now", "I no longer have it", "end"),
            DropdownLinkItem(
                page("games:end_library_entry"), "I no longer have it, with details…"
            ),
        ]
    )
    return RowActionMenu(
        [
            *have,
            DropdownLinkItem(
                page("games:edit_library_entry"), "Edit details", icon="edit"
            ),
            DropdownLinkItem(
                page("games:remove_library_entry"),
                REMOVE_ENTRY.label,
                icon="delete",
                danger=True,
            ),
        ],
        #: One game may hold several copies; the platform tells them apart.
        label=f"{game.name} ({platform_words(entry.release)}) actions",
        id=f"entry-menu-{entry.pk}",
    )
