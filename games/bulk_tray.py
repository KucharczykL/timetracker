"""The acts a selection line offers, built for one page."""

import json
import uuid

from common.components import (
    SELECTION_STATEMENT_FIELD,
    ButtonColor,
    Input,
    SelectionAction,
)
from common.components.core import Node
from common.returns import OriginUrl, action_url
from games.bulk_actions import BULK_ACTIONS, BulkActionName

#: The colours a line of acts keeps: one adds, one takes away.
#:
#: Blue is the page's primary colour, and four primaries beside each other
#: name none of them. An act's own colour still leads its confirmation,
#: where one press is the primary one.
_LINE_COLOURS: frozenset[ButtonColor] = frozenset({"green", "red"})


def tray_actions(
    *names: BulkActionName, origin: OriginUrl | None
) -> list[SelectionAction]:
    """Each named act, as the line renders it.

    Declaration order is priority order: the line lays the acts out in
    the order stated here and overflows the rightmost first. State them
    in the order the row's menu states them, so one act keeps one place.

    A name no act declares is a defect, not a quiet omission.
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
                color=action.color if action.color in _LINE_COLOURS else "gray",
            )
        )
    return offered


def one_row_statement(row_id: uuid.UUID) -> Node:
    """The runner's statement, naming one row.

    A menu item hands its row to a tray act through this, so the act
    grows no per-row route.
    """
    return Input(
        type="hidden",
        name=SELECTION_STATEMENT_FIELD,
        value=json.dumps({"mode": "some", "keys": [str(row_id)]}),
    )
