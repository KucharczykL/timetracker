"""What one platform row offers."""

from common.components import DropdownLinkItem, RowActionMenu
from common.components.core import Node
from common.returns import OriginUrl, action_url
from games.bulk_removal import REMOVE_PLATFORM
from games.models import Platform


def platform_row_menu(platform: Platform, origin: OriginUrl | None) -> Node:
    """Edit and Remove."""
    #: Names may repeat across groups.
    named = f"{platform.name} ({platform.group})" if platform.group else platform.name
    return RowActionMenu(
        [
            DropdownLinkItem(
                action_url("games:edit_platform", platform.pk, origin=origin),
                "Edit",
                icon="edit",
            ),
            DropdownLinkItem(
                action_url("games:remove_platform", platform.pk, origin=origin),
                REMOVE_PLATFORM.label,
                icon="delete",
                danger=True,
            ),
        ],
        label=f"{named} actions",
        id=f"platform-menu-{platform.pk}",
    )
