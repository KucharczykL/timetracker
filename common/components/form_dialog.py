"""Links that open their form page in a modal."""

from collections.abc import Mapping
from typing import Final, Literal, TypedDict

from common.components.core import Attributes, Node
from common.components.custom_elements import OVERLAY_SURFACE_CLASS
from common.components.elements import Div, Template
from common.components.modal import (
    ElementId,
    ModalDialog,
    require_every_key,
    titled_header,
)
from common.components.primitives import FORM_MAX_WIDTH_CLASS, custom_element_builder
from common.notices import ToastPayload

type FormDialogChrome = Literal["header", "bare"]
type FormDialogPart = Literal["template", "header", "title", "body"]
type FormDialogAttribute = str  # e.g. "data-form-dialog", "data-form-dialog-body"
type AttributeName = str  # e.g. "aria-controls"
type AbsoluteUrl = str  # e.g. "https://example.com/devices"
type ModulePath = str  # static URL: a path, or absolute when hosted
type DocumentTitle = str  # e.g. "Add New Device"
type HtmlText = str  # rendered markup
type ChromeMarker = str  # the marker's value: "" or "bare"


class PageAnswer(TypedDict):
    """The page's content, for the dialog."""

    kind: Literal["page"]
    title: DocumentTitle
    html: HtmlText
    modules: list[ModulePath]
    messages: list[ToastPayload]


class DoneAnswer(TypedDict):
    """Finished; `url` is where it landed."""

    kind: Literal["done"]
    url: AbsoluteUrl
    messages: list[ToastPayload]


class ContinueAnswer(TypedDict):
    """Fetch `url` into the same dialog."""

    kind: Literal["continue"]
    url: AbsoluteUrl


#: What a dialog's redirect becomes.
type RedirectAnswer = DoneAnswer | ContinueAnswer
#: Every answer kind the dialog reads.
type DialogAnswer = PageAnswer | RedirectAnswer


FORM_DIALOG_ATTRIBUTE: Final[FormDialogAttribute] = "data-form-dialog"

#: The marker's value per chrome.
FORM_DIALOG_CHROME_VALUES: Mapping[FormDialogChrome, ChromeMarker] = {
    "header": "",
    "bare": "bare",
}

#: The template parts ts/elements/form-dialog.ts finds.
FORM_DIALOG_PARTS: Mapping[FormDialogPart, FormDialogAttribute] = {
    "template": "data-form-dialog-template",
    "header": "data-form-dialog-header",
    "title": "data-form-dialog-title",
    "body": "data-form-dialog-body",
}

#: Attributes naming one id; the dialog prefixes them.
FORM_DIALOG_ID_ATTRIBUTES: tuple[AttributeName, ...] = (
    "list",
    "form",
    "popovertarget",
    "aria-activedescendant",
)
#: Attributes naming a list of ids.
FORM_DIALOG_ID_LIST_ATTRIBUTES: tuple[AttributeName, ...] = (
    "for",
    "headers",
    "aria-labelledby",
    "aria-describedby",
    "aria-controls",
    "aria-owns",
    "aria-flowto",
    "aria-errormessage",
    "aria-details",
)

require_every_key(FormDialogChrome, FORM_DIALOG_CHROME_VALUES)
#: The client decodes a marker back to its chrome.
FORM_DIALOG_CHROME_BY_MARKER: Mapping[ChromeMarker, FormDialogChrome] = {
    marker: chrome for chrome, marker in FORM_DIALOG_CHROME_VALUES.items()
}
if len(FORM_DIALOG_CHROME_BY_MARKER) != len(FORM_DIALOG_CHROME_VALUES):
    raise TypeError("FORM_DIALOG_CHROME_VALUES markers must differ")
require_every_key(FormDialogPart, FORM_DIALOG_PARTS)

#: Prefixed per dialog, like every template id.
_TITLE_ID: ElementId = "form-dialog-title"

_PANEL_CLASS = (
    f"flex w-[calc(100%-2rem)] {FORM_MAX_WIDTH_CLASS} max-h-[calc(100dvh-2rem)] "
    "flex-col overflow-hidden rounded-base border border-default-medium "
    f"shadow-lg/50 {OVERLAY_SURFACE_CLASS}"
)

#: The link loading, or the body submitting.
_BUSY_CLASS = "aria-busy:cursor-progress aria-busy:opacity-60"

_FormDialog = custom_element_builder("form-dialog")


def form_dialog_link(chrome: FormDialogChrome = "header") -> Attributes:
    """Marks a link to open in a dialog."""
    return (
        (FORM_DIALOG_ATTRIBUTE, FORM_DIALOG_CHROME_VALUES[chrome]),
        ("class", _BUSY_CLASS),
    )


def FormDialogHost() -> Node:
    """The page's one host and its chrome template."""
    titled = titled_header(
        "",
        title_id=_TITLE_ID,
        attributes=[(FORM_DIALOG_PARTS["header"], "")],
        title_attributes=[(FORM_DIALOG_PARTS["title"], "")],
    )
    return _FormDialog()[
        Template([(FORM_DIALOG_PARTS["template"], "")])[
            ModalDialog([titled.labelled_by])[
                Div(class_=_PANEL_CLASS)[
                    titled.header,
                    Div(
                        [(FORM_DIALOG_PARTS["body"], "")],
                        class_=f"min-h-0 overflow-y-auto overscroll-contain p-4 {_BUSY_CLASS}",
                    ),
                ]
            ]
        ]
    ]
