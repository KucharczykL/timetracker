"""What one Library row offers."""

from common.components import DropdownLinkItem, RowActionMenu
from common.components.core import Node
from common.returns import OriginUrl, action_url
from games.bulk_removal import REMOVE_ENTRY
from games.endpoints import ENTRY_ACCESS_END
from games.models import LibraryEntry
from games.reads.endpoints import stated
from games.reads.releases import platform_words
from games.views.library_cards import open_url


def entry_row_menu(entry: LibraryEntry, origin: OriginUrl | None) -> Node:
    """Edit, End access or Resume, Remove."""
    game = entry.player_game.game
    ended = stated(entry, ENTRY_ACCESS_END) is not None
    return RowActionMenu(
        [
            DropdownLinkItem(open_url(game, "edit", entry.pk), "Edit", icon="edit"),
            DropdownLinkItem(
                open_url(game, "resume" if ended else "end", entry.pk),
                "Resume" if ended else "End access",
                icon="reset" if ended else "end",
            ),
            DropdownLinkItem(
                action_url("games:remove_library_entry", entry.pk, origin=origin),
                REMOVE_ENTRY.label,
                icon="delete",
                danger=True,
            ),
        ],
        #: One game may hold several copies; the platform tells them apart.
        label=f"{game.name} ({platform_words(entry.release)}) actions",
        id=f"entry-menu-{entry.pk}",
    )
