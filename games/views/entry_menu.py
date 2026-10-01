"""What one Library row offers."""

from collections.abc import Sequence

from common.components import (
    DropdownDivider,
    DropdownLinkItem,
    DropdownPostItem,
    DropdownSubmenuItem,
    RowActionMenu,
)
from common.components.core import Node
from common.components.primitives import ButtonSize
from common.returns import OriginUrl, action_url
from games.endpoints import ENTRY_ACCESS_END
from games.models import LibraryEntry, Purchase
from games.reads.endpoints import stated
from games.reads.releases import platform_words
from games.views.purchase_menu import price_words, purchase_items, purchase_label
from games.views.submission import submission_input


def entry_row_menu(
    entry: LibraryEntry,
    origin: OriginUrl | None,
    csrf_token: str,
    *,
    purchases: Sequence[Purchase],
    size: ButtonSize = "control",
) -> Node:
    """A copy's acts, then its purchases'."""
    game = entry.player_game.game
    ended = stated(entry, ENTRY_ACCESS_END) is not None

    def page(route: str) -> str:
        return action_url(route, entry.pk, origin=origin)

    def now(route: str, label: str, description: str) -> Node:
        return DropdownPostItem(
            page(route),
            label,
            csrf_token=csrf_token,
            hidden_fields=submission_input(),
            description=description,
        )

    have: list[Node] = (
        [
            DropdownSubmenuItem(
                "I have it again",
                icon="reset",
                id=f"entry-menu-{entry.pk}-again",
                items=[
                    now(
                        "games:resume_library_entry_now",
                        "Just add it back",
                        "Dated today",
                    ),
                    DropdownLinkItem(
                        page("games:resume_library_entry"),
                        "With details…",
                        description="Pick the day, add a note",
                    ),
                ],
            ),
            DropdownLinkItem(
                page("games:edit_library_entry_end"), "Edit how it left…", icon="end"
            ),
        ]
        if ended
        else [
            DropdownSubmenuItem(
                "I no longer have it",
                icon="end",
                id=f"entry-menu-{entry.pk}-gone",
                items=[
                    now(
                        "games:end_library_entry_now",
                        "Just mark it gone",
                        "Dated today, no reason given",
                    ),
                    DropdownLinkItem(
                        page("games:end_library_entry"),
                        "With details…",
                        description="Pick the day and what happened",
                    ),
                ],
            ),
        ]
    )
    return RowActionMenu(
        [
            *have,
            DropdownDivider(),
            DropdownLinkItem(page("games:edit_library_entry"), "Edit…", icon="edit"),
            DropdownDivider(),
            DropdownLinkItem(page("games:add_purchase"), "Add purchase…", icon="plus"),
            *(
                DropdownSubmenuItem(
                    f"{purchase_label(purchase)} · {price_words(purchase)}",
                    id=f"entry-menu-{entry.pk}-purchase-{purchase.pk}",
                    items=purchase_items(purchase, origin, csrf_token),
                )
                for purchase in purchases
            ),
            DropdownDivider(),
            DropdownLinkItem(
                page("games:remove_library_entry"),
                "Remove…",
                icon="delete",
                danger=True,
            ),
        ],
        #: The platform tells copies apart.
        label=f"{game.name} ({platform_words(entry.release)}) actions",
        id=f"entry-menu-{entry.pk}",
        size=size,
    )
