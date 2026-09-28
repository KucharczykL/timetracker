"""A dropdown whose panel is a grid of icons.

Each tile is a native radio inside its label, so the grid posts as any
radio group does and the arrow keys move the choice. The
``choice-grid`` behavior closes the panel on a pick and copies the
tile's glyph and name onto the trigger.
"""

from collections.abc import Sequence
from typing import NamedTuple

from common.components.core import Node
from common.components.custom_elements import Dropdown, DropdownPanel
from common.components.elements import Fieldset, Legend
from common.components.primitives import (
    ControlButton,
    Icon,
    Input,
    Label,
    Span,
)

#: A tile's value; empty keeps.
type IconChoiceValue = str  # "steam"

_TILE_CLASS = (
    "flex h-10 cursor-pointer items-center justify-center rounded-base border "
    "border-default-medium text-heading hover:bg-neutral-secondary-medium "
    "has-[:checked]:border-brand has-[:checked]:ring-1 has-[:checked]:ring-brand "
    "has-[:checked]:bg-neutral-secondary-soft "
    "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand"
)
_KEEP_TILE_CLASS = f"{_TILE_CLASS} col-span-2 text-type-body"


class IconChoice(NamedTuple):
    """One tile: an icon slug and its name, or "" to keep."""

    value: IconChoiceValue
    label: str


def _glyph(value: IconChoiceValue) -> Node:
    return Span(data_choice_grid_glyph="", class_="flex")[Icon(value) if value else ""]


def _tile(name: str, choice: IconChoice, *, checked: bool) -> Node:
    return Label(
        class_=_KEEP_TILE_CLASS if not choice.value else _TILE_CLASS,
        title=choice.label,
    )[
        Input(
            type="radio",
            name=name,
            value=choice.value,
            checked=checked,
            aria_label=choice.label,
            data_choice_label=choice.label,
            class_="sr-only",
        ),
        _glyph(choice.value) if choice.value else Span()["Keep"],
    ]


def IconPicker(
    *,
    name: str,
    label: str,
    choices: Sequence[IconChoice],
    value: IconChoiceValue,
    id: str,
) -> Node:
    """A "glyph Name ▾" trigger over a grid of icon radios."""
    current = next((choice for choice in choices if choice.value == value), None)
    shown = current or IconChoice(value, value)
    trigger = ControlButton(
        color="gray", variant="outline", aria_haspopup="dialog", class_="w-full"
    )[
        _glyph(shown.value),
        Span(data_choice_grid_label="", class_="grow text-start")[shown.label],
        Icon("arrowdown", size="h-3 w-3"),
    ].as_element()
    panel = DropdownPanel(role="dialog", aria_label=label, width="w-72")[
        Fieldset(class_="grid grid-cols-6 gap-1 border-0 p-0 m-0")[
            Legend(class_="sr-only")[label],
            *(
                _tile(name, choice, checked=choice.value == shown.value)
                for choice in choices
            ),
        ]
    ]
    return Dropdown(
        trigger_element=trigger,
        target_element=panel,
        id=id,
        behavior="choice-grid",
        full_width=True,
    )
