"""What one Library row offers."""

import uuid

from common.components import (
    DropdownDivider,
    DropdownLinkItem,
    DropdownPostItem,
    DropdownSubmenuItem,
    Input,
    RowActionMenu,
)
from common.components.core import Node
from common.components.primitives import ButtonSize
from common.returns import OriginUrl, action_url
from games.endpoints import ENTRY_ACCESS_END
from games.models import LibraryEntry
from games.reads.endpoints import stated
from games.reads.releases import platform_words

#: The one-click form's hidden key field.
SUBMISSION_FIELD = "submission"


def submission_input() -> Node:
    """A fresh key: a double press records once."""
    return Input(type="hidden", name=SUBMISSION_FIELD, value=str(uuid.uuid7()))


def entry_row_menu(
    entry: LibraryEntry,
    origin: OriginUrl | None,
    csrf_token: str,
    *,
    size: ButtonSize = "control",
) -> Node:
    """A copy's acts: one click, then pages."""
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
