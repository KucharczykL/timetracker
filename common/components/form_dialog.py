"""Links that open their form page in a modal."""

from collections.abc import Mapping
from typing import Final, Literal

from common.components.core import HTMLAttribute, Node
from common.components.custom_elements import OVERLAY_SURFACE_CLASS
from common.components.elements import Div, Template
from common.components.modal import ModalDialog, ModalPanelHeader, require_every_key
from common.components.primitives import FORM_MAX_WIDTH_CLASS, custom_element_builder

type FormDialogChrome = Literal["header", "bare"]
type FormDialogPart = Literal["template", "panel", "header", "title", "body"]
type FormDialogAttribute = str  # e.g. "data-form-dialog-body"

FORM_DIALOG_ATTRIBUTE: Final = "data-form-dialog"

#: The marker's value per chrome.
FORM_DIALOG_CHROME_VALUES: Mapping[FormDialogChrome, str] = {
    "header": "",
    "bare": "bare",
}

#: The template parts ts/elements/form-dialog.ts finds.
FORM_DIALOG_PARTS: Mapping[FormDialogPart, FormDialogAttribute] = {
    "template": "data-form-dialog-template",
    "panel": "data-form-dialog-panel",
    "header": "data-form-dialog-header",
    "title": "data-form-dialog-title",
    "body": "data-form-dialog-body",
}

require_every_key(FormDialogChrome, FORM_DIALOG_CHROME_VALUES)
require_every_key(FormDialogPart, FORM_DIALOG_PARTS)

#: Prefixed per dialog, like every template id.
_TITLE_ID = "form-dialog-title"

_PANEL_CLASS = (
    f"flex w-[calc(100%-2rem)] {FORM_MAX_WIDTH_CLASS} max-h-[calc(100dvh-2rem)] "
    "flex-col overflow-hidden rounded-base border border-default-medium "
    f"shadow-lg/50 {OVERLAY_SURFACE_CLASS}"
)

_FormDialog = custom_element_builder("form-dialog")


def form_dialog_link(chrome: FormDialogChrome = "header") -> HTMLAttribute:
    """Marks a link to open in a dialog."""
    return (FORM_DIALOG_ATTRIBUTE, FORM_DIALOG_CHROME_VALUES[chrome])


def FormDialogHost() -> Node:
    """The page's one host and its chrome template."""
    return _FormDialog()[
        Template([(FORM_DIALOG_PARTS["template"], "")])[
            ModalDialog([("aria-labelledby", _TITLE_ID)])[
                Div([(FORM_DIALOG_PARTS["panel"], "")], class_=_PANEL_CLASS)[
                    ModalPanelHeader(
                        "",
                        title_id=_TITLE_ID,
                        attributes=[(FORM_DIALOG_PARTS["header"], "")],
                        title_attributes=[(FORM_DIALOG_PARTS["title"], "")],
                    ),
                    Div(
                        [(FORM_DIALOG_PARTS["body"], "")],
                        class_="min-h-0 overflow-y-auto overscroll-contain p-4",
                    ),
                ]
            ]
        ]
    ]
