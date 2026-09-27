"""A field joined to a ⊘ stating none."""

from typing import Literal

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

type PostedName = str  # a posted field name, e.g. "edit-device"

_UNSET_SUFFIX = "-unset"

#: Joined, or beside a composite.
type UnsetLayout = Literal["joined", "beside"]

_HIDDEN_UNTIL_DEFINED = "[unset-field:not(:defined)_&]:hidden"
_HIDDEN_ONCE_DEFINED = "[unset-field:defined_&]:hidden"
# Dark hover text outranks bare pressed fill.
_PRESSED_CLASS = (
    "aria-pressed:solid-brand aria-pressed:border-brand dark:aria-pressed:solid-brand"
)
_MEMBER_CLASS = "flex-1 min-w-0 focus-within:z-10"


def unset_input_name(name: PostedName) -> PostedName:
    """The checkbox's posted name."""
    return f"{name}{_UNSET_SUFFIX}"


def UnsetField(
    *,
    name: PostedName,
    none_label: NoneLabel,
    field: ShapedMember,
    unset: bool = False,
    describedby: str | None = None,
    layout: UnsetLayout = "joined",
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

    row = (
        SegmentedField(field=member, trailing=toggle, class_="w-full")
        if layout == "joined"
        # A composite draws its own box.
        else Div(class_="flex items-start gap-2")[member("full"), toggle("full")]
    )
    return _UnsetField(name=name, none_label=none_label, class_="block")[row]
