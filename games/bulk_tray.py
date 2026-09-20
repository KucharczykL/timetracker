"""The acts a selection line offers, built for one page."""

from collections.abc import Mapping

from common.components import SelectionAction, SelectionCardinality
from common.returns import OriginUrl, action_url
from games.bulk_actions import BULK_ACTIONS, BulkActionName, Cardinality

#: The act's word, in the line's own vocabulary.
#:
#: The mapping is here because `common/` declares no act: it states
#: what it renders, and this layer says which of its words an act is.
SPELLED: Mapping[Cardinality, SelectionCardinality] = {
    Cardinality.ONE: "one",
    Cardinality.MANY: "many",
}


def tray_actions(*names: BulkActionName, origin: OriginUrl) -> list[SelectionAction]:
    """Each named act, as the line renders it.

    A `one` act is left out: the line states no row, and #718 puts the
    row's own pages there. A name no act declares is a defect, not a
    quiet omission: the view stated it.
    """
    offered: list[SelectionAction] = []
    for name in names:
        action = BULK_ACTIONS.get(name)
        if action is None:
            raise ValueError(
                f"{name!r} is no declared act, so the line cannot offer it."
            )
        if action.cardinality is not Cardinality.MANY:
            continue
        offered.append(
            SelectionAction(
                label=action.label,
                url=action_url("games:run_bulk_action", action.name, origin=origin),
                cardinality=SPELLED[action.cardinality],
            )
        )
    return offered
