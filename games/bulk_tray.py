"""The acts a selection line offers, built for one page."""

from common.components import SelectionAction
from common.returns import OriginUrl, action_url
from games.bulk_actions import BULK_ACTIONS, BulkActionName


def tray_actions(
    *names: BulkActionName, origin: OriginUrl | None
) -> list[SelectionAction]:
    """Each named act, as the line renders it.

    Declaration order is priority order: the line lays the acts out in the
    order stated here and moves the rightmost into its overflow first, so a
    view states the act reached for most often first and the destructive act
    last. The order is the one a person reads and the one the narrowest
    window keeps, which is why no view sorts these by anything else.

    A name no act declares is a defect, not a quiet omission: the view
    stated it.
    """
    offered: list[SelectionAction] = []
    for name in names:
        action = BULK_ACTIONS.get(name)
        if action is None:
            raise ValueError(
                f"{name!r} is no declared act, so the line cannot offer it."
            )
        offered.append(
            SelectionAction(
                label=action.label,
                url=action_url("games:run_bulk_action", action.name, origin=origin),
                color=action.color,
            )
        )
    return offered
