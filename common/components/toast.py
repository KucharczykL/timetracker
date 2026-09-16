"""The page's toasts: an empty tag."""

from typing import TypedDict

from common.components.core import Node
from common.components.custom_elements import register_element
from common.components.primitives import (
    control_button_class,
    custom_element_builder,
)

_ToastStack = custom_element_builder("toast-stack")

#: The corner the toasts stack in.
TOAST_STACK_CLASS = (
    "fixed z-50 bottom-0 right-0 flex flex-col items-end pointer-events-none p-4"
)


class ToastStackProps(TypedDict):
    #: The class an action button wears: the ghost ControlButton's.
    action_class: str


register_element("toast-stack", "ToastStack", ToastStackProps)


def ToastStack() -> Node:
    """The notifications region; no tabindex, deliberately."""
    return _ToastStack(
        role="region",
        aria_label="Notifications",
        aria_atomic="true",
        action_class=control_button_class(variant="ghost"),
        class_=TOAST_STACK_CLASS,
    )
