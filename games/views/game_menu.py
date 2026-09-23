"""What one game row offers, behind its trigger.

Not in `common/components/`: reading `games.bulk_actions` there
closes a cycle through that table's foot imports.
"""

from common.components import DropdownLinkItem, RowActionMenu
from common.components.core import Node
from common.returns import OriginUrl, action_url
from games.bulk_removal import REMOVE_GAME
from games.models import Game


def game_row_menu(game: Game, origin: OriginUrl | None) -> Node:
    """Edit where the library may edit the row, and Remove on every row.

    A shared catalog game is read-only for everyone, the rule Game
    detail applies to its catalog controls, so it offers no Edit.
    """
    items: list[Node] = []
    if game.library_id is not None:
        items.append(
            DropdownLinkItem(
                action_url("games:edit_game", game.pk, origin=origin),
                "Edit",
                icon="edit",
            )
        )
    items.append(
        DropdownLinkItem(
            action_url("games:remove_game", game.pk, origin=origin),
            REMOVE_GAME.label,
            icon="delete",
            danger=True,
        )
    )
    platform = f" ({game.platform.name})" if game.platform is not None else ""
    return RowActionMenu(
        items,
        label=f"{game.name}{platform} actions",
        id=f"game-menu-{game.pk}",
    )
