"""The page's toasts: an empty tag the element fills."""

from typing import TypedDict

from common.components.core import Node
from common.components.custom_elements import register_element
from common.components.primitives import custom_element_builder

_ToastStack = custom_element_builder("toast-stack")

#: The corner the toasts stack in; the element adds the toasts.
TOAST_STACK_CLASS = (
    "fixed z-50 bottom-0 right-0 flex flex-col items-end pointer-events-none p-4"
)


class ToastStackProps(TypedDict):
    pass


register_element("toast-stack", "ToastStack", ToastStackProps)


def ToastStack() -> Node:
    """The notifications region, one a page, no `tabindex`."""
    return _ToastStack(
        role="region",
        aria_label="Notifications",
        aria_atomic="true",
        class_=TOAST_STACK_CLASS,
    )
