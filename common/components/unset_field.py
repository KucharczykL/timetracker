"""A field joined to a ⊘ toggle that states none.

Wired by ``ts/elements/unset-field.ts``. The checkbox is the posted state;
the toggle is its face once the element is defined.
"""

from common.components.core import Node
from common.components.custom_elements import _UnsetField
from common.components.primitives import (
    CHECKBOX_LOOK_CLASS,
    ButtonShape,
    ControlButton,
    Div,
    Fragment,
    Icon,
    Input,
    Label,
    SegmentedField,
    ShapedMember,
    control_button_class,
)
from common.components.search_select import NoneLabel

type FieldName = str  # a posted field name, e.g. "edit-device"

UNSET_SUFFIX = "-unset"

_HIDDEN_UNTIL_DEFINED = "[unset-field:not(:defined)_&]:hidden"
_HIDDEN_ONCE_DEFINED = "[unset-field:defined_&]:hidden"
# The dark hover and focus text outrank a bare pressed fill.
_PRESSED_CLASS = (
    "aria-pressed:solid-brand aria-pressed:border-brand dark:aria-pressed:solid-brand"
)
_MEMBER_CLASS = "flex-1 min-w-0 focus-within:z-10"


def unset_input_name(name: FieldName) -> FieldName:
    """The checkbox's posted name."""
    return f"{name}{UNSET_SUFFIX}"


def UnsetField(
    *,
    name: FieldName,
    none_label: NoneLabel,
    field: ShapedMember,
    unset: bool = False,
    describedby: str | None = None,
) -> Node:
    """``field`` and its ⊘; ``unset`` renders it pressed."""

    def member(shape: ButtonShape) -> Node:
        return Div(data_unset_field_member="", class_=_MEMBER_CLASS)[field(shape)]

    def toggle(shape: ButtonShape) -> Node:
        button = ControlButton(
            variant="segmented",
            color="gray",
            shape=shape,
            data_unset_field_toggle="",
            aria_pressed="true" if unset else "false",
            aria_label=none_label,
            title=none_label,
            aria_describedby=describedby,
            class_=f"{_HIDDEN_UNTIL_DEFINED} {_PRESSED_CLASS}",
        )[Icon("no-symbol", [("aria-hidden", "true"), ("class", "size-5")])]
        # Without scripting, the checkbox is the control.
        fallback = Label(
            class_=(
                f"{control_button_class(variant='segmented', color='gray', shape=shape)}"
                f" gap-2 {_HIDDEN_ONCE_DEFINED}"
            ),
        )[
            Input(
                type="checkbox",
                name=unset_input_name(name),
                value="1",
                checked=unset,
                autocomplete="off",
                data_unset_field_state="",
                class_=CHECKBOX_LOOK_CLASS,
            ),
            none_label,
        ]
        return Fragment(button, fallback)

    return _UnsetField(name=name, none_label=none_label, class_="block")[
        SegmentedField(field=member, trailing=toggle, class_="w-full")
    ]
