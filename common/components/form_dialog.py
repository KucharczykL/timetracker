"""Links that open their form page in a modal."""

from collections.abc import Mapping
from typing import Final, Literal, TypedDict

from common.components.core import Attributes, Node
from common.components.custom_elements import OVERLAY_SURFACE_CLASS
from common.components.elements import Div, P, Template
from common.components.modal import (
    MODAL_ATTRIBUTES,
    ElementId,
    ModalDialog,
    ModalPanel,
    require_every_key,
    titled_header,
)
from common.components.primitives import (
    PAGE_WIDTH_CLASSES,
    AttributeName,
    ControlButton,
    PageWidth,
    custom_element_builder,
)
from common.notices import ToastPayload

type FormDialogChrome = Literal["header", "bare"]
type FormDialogPart = Literal["template", "header", "title", "body"]
type UnsavedWarningPart = Literal["template", "discard", "save"]
type FormDialogAttribute = str  # e.g. "data-form-dialog", "data-form-dialog-body"
type AbsoluteUrl = str  # e.g. "https://example.com/devices"
type ModulePath = str  # static URL: a path, or absolute when hosted
type DocumentTitle = str  # e.g. "Add New Device"
type HtmlText = str  # rendered markup
type ChromeMarker = str  # the marker's value: "" or "bare"


class PageAnswer(TypedDict):
    """The page's content, for the dialog."""

    kind: Literal["page"]
    title: DocumentTitle
    width: PageWidth
    html: HtmlText
    modules: list[ModulePath]
    messages: list[ToastPayload]


class DoneAnswer(TypedDict):
    """Finished; `url` is where it landed."""

    kind: Literal["done"]
    url: AbsoluteUrl
    messages: list[ToastPayload]


class CreatedOption(TypedDict):
    """The made row, as its picker shows it."""

    value: str
    label: str
    data: dict[str, str]


class CreatedAnswer(TypedDict):
    """Done, with the row it made."""

    kind: Literal["created"]
    url: AbsoluteUrl
    messages: list[ToastPayload]
    option: CreatedOption


class ContinueAnswer(TypedDict):
    """Fetch `url` into the same dialog."""

    kind: Literal["continue"]
    url: AbsoluteUrl


#: What a dialog's redirect becomes.
type RedirectAnswer = DoneAnswer | CreatedAnswer | ContinueAnswer
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

#: The warning template's parts.
UNSAVED_WARNING_PARTS: Mapping[UnsavedWarningPart, FormDialogAttribute] = {
    "template": "data-form-dialog-unsaved",
    "discard": "data-form-dialog-discard",
    "save": "data-form-dialog-save",
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
require_every_key(UnsavedWarningPart, UNSAVED_WARNING_PARTS)

#: Prefixed per dialog, like every template id.
_TITLE_ID: ElementId = "form-dialog-title"
_UNSAVED_TITLE_ID: ElementId = "form-dialog-unsaved-title"
_UNSAVED_MESSAGE_ID: ElementId = "form-dialog-unsaved-message"

_SURFACE_CLASS = (
    "max-h-[calc(100dvh-2rem-var(--modal-reserve,0px))] flex-col overflow-hidden rounded-base border "
    f"border-default-medium shadow-lg/50 {OVERLAY_SURFACE_CLASS}"
)
#: The panel states its page's width here.
PAGE_WIDTH_ATTRIBUTE: Final[FormDialogAttribute] = "data-page-width"
#: Every width, for the client to check.
PAGE_WIDTHS: tuple[PageWidth, ...] = tuple(PAGE_WIDTH_CLASSES)

#: Literal for Tailwind's scanner; checked below.
_PANEL_WIDTH_CLASSES: Mapping[PageWidth, str] = {
    "form": "data-[page-width=form]:max-w-xl",
    "wide": "data-[page-width=wide]:max-w-4xl",
    "full": "data-[page-width=full]:max-w-7xl",
}
require_every_key(PageWidth, _PANEL_WIDTH_CLASSES)
for _width, _class in _PANEL_WIDTH_CLASSES.items():
    _name = PAGE_WIDTH_ATTRIBUTE.removeprefix("data-")
    if _class != f"data-[{_name}={_width}]:{PAGE_WIDTH_CLASSES[_width]}":
        raise TypeError(f"_PANEL_WIDTH_CLASSES[{_width!r}] drifted from the page's")

_PANEL_CLASS = (
    f"flex w-[calc(100%-2rem)] {' '.join(_PANEL_WIDTH_CLASSES.values())} "
    f"{_SURFACE_CLASS}"
)
_WARNING_PANEL_CLASS = f"flex w-[calc(100%-2rem)] max-w-sm {_SURFACE_CLASS}"

#: The link loading, or the body submitting.
_BUSY_CLASS = "aria-busy:cursor-progress aria-busy:opacity-60"

_FormDialog = custom_element_builder("form-dialog")


def form_dialog_link(chrome: FormDialogChrome = "header") -> Attributes:
    """Marks a link to open in a dialog."""
    return (
        (FORM_DIALOG_ATTRIBUTE, FORM_DIALOG_CHROME_VALUES[chrome]),
        ("class", _BUSY_CLASS),
    )


def _UnsavedWarning() -> Node:
    """Asks before unsaved changes are lost."""
    titled = titled_header(
        "Unsaved changes", title_id=_UNSAVED_TITLE_ID, close_label=None, divided=False
    )
    return Template([(UNSAVED_WARNING_PARTS["template"], "")])[
        ModalDialog(
            [
                ("role", "alertdialog"),
                titled.labelled_by,
                ("aria-describedby", _UNSAVED_MESSAGE_ID),
            ]
        )[
            ModalPanel(class_=_WARNING_PANEL_CLASS)[
                titled.header,
                Div(class_="flex flex-col gap-3 px-4 pt-3 pb-4")[
                    P(id=_UNSAVED_MESSAGE_ID, class_="text-body")[
                        "Your changes are not saved."
                    ],
                    Div(class_="mt-2 flex flex-col gap-2 sm:flex-row")[
                        ControlButton(
                            [(UNSAVED_WARNING_PARTS["discard"], "")],
                            color="red",
                            class_="sm:mr-auto",
                        )["Discard"],
                        ControlButton(
                            [
                                (MODAL_ATTRIBUTES["dismiss"], ""),
                                (MODAL_ATTRIBUTES["initial_focus"], ""),
                            ],
                            color="gray",
                        )["Return to edit"],
                        ControlButton([(UNSAVED_WARNING_PARTS["save"], "")])["Save"],
                    ],
                ],
            ]
        ]
    ]


def FormDialogHost() -> Node:
    """The page's one host and its templates."""
    titled = titled_header(
        "",
        title_id=_TITLE_ID,
        attributes=[(FORM_DIALOG_PARTS["header"], "")],
        title_attributes=[(FORM_DIALOG_PARTS["title"], "")],
    )
    return _FormDialog()[
        Template([(FORM_DIALOG_PARTS["template"], "")])[
            ModalDialog([titled.labelled_by])[
                ModalPanel(
                    [(PAGE_WIDTH_ATTRIBUTE, "form")],
                    class_=_PANEL_CLASS,
                )[
                    titled.header,
                    Div(
                        [(FORM_DIALOG_PARTS["body"], "")],
                        class_=f"min-h-0 overflow-y-auto overscroll-contain p-4 {_BUSY_CLASS}",
                    ),
                ]
            ]
        ],
        _UnsavedWarning(),
    ]
