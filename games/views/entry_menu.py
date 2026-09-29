"""What one Library row offers."""

from common.components import DropdownLinkItem, RowActionMenu
from common.components.core import Node
from common.returns import OriginUrl, action_url
from games.bulk_removal import REMOVE_ENTRY
from games.endpoints import ENTRY_ACCESS_END
from games.models import LibraryEntry
from games.reads.endpoints import stated
from games.reads.releases import platform_words


def entry_row_menu(entry: LibraryEntry, origin: OriginUrl | None) -> Node:
    """Each act's page; an ended copy's end is edited or resumed."""
    game = entry.player_game.game
    ended = stated(entry, ENTRY_ACCESS_END) is not None

    def page(route: str) -> str:
        return action_url(route, entry.pk, origin=origin)

    end_items = (
        [
            DropdownLinkItem(
                page("games:edit_library_entry_end"), "Edit end", icon="end"
            ),
            DropdownLinkItem(
                page("games:resume_library_entry"), "Resume", icon="reset"
            ),
        ]
        if ended
        else [
            DropdownLinkItem(page("games:end_library_entry"), "End access", icon="end")
        ]
    )
    return RowActionMenu(
        [
            DropdownLinkItem(page("games:edit_library_entry"), "Edit", icon="edit"),
            *end_items,
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
