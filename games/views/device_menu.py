"""What one device row offers, behind its trigger.

Not in `common/components/`: reading `games.bulk_actions` there
closes a cycle through that table's foot imports.
"""

from common.components import DropdownLinkItem, RowActionMenu
from common.components.core import Node
from common.returns import OriginUrl, action_url
from games.bulk_removal import REMOVE_DEVICE
from games.models import Device


def device_row_menu(device: Device, origin: OriginUrl | None) -> Node:
    """Edit and Remove, the two acts one device row has."""
    return RowActionMenu(
        [
            DropdownLinkItem(
                action_url("games:edit_device", device.pk, origin=origin),
                "Edit",
                icon="edit",
            ),
            DropdownLinkItem(
                action_url("games:remove_device", device.pk, origin=origin),
                REMOVE_DEVICE.label,
                icon="delete",
                danger=True,
            ),
        ],
        #: The type too: nothing refuses two devices of one name.
        label=f"{device.name} ({device.get_type_display()}) actions",
        id=f"device-menu-{device.pk}",
    )
