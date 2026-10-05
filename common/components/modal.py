"""The dialog every modal on the modal layer wears."""

from collections.abc import Collection, Mapping
from typing import Literal, TypeAliasType, get_args

from common.components.core import Attributes, Child, Element, HTMLAttribute
from common.components.elements import Dialog, Div, PlainH2, Span
from common.components.primitives import ControlButton

type ModalAlign = Literal["center", "end"]
type ModalAttributeRole = Literal[
    "modal", "dismiss", "initial_focus", "covered", "over"
]
type ModalAttribute = str  # e.g. "data-modal-covered"
type ElementId = str  # e.g. "form-dialog-title"

#: The attributes ts/elements/modal-layer.ts reads and stamps.
MODAL_ATTRIBUTES: Mapping[ModalAttributeRole, ModalAttribute] = {
    "modal": "data-modal",
    "dismiss": "data-modal-dismiss",
    "initial_focus": "data-modal-initial-focus",
    "covered": "data-modal-covered",
    "over": "data-modal-over",
}

#: Transparent hit area; the child panel shows.
#: No transform/filter/contain: toast region needs viewport.
#: clip: hidden lets focus scroll the panel.
_MODAL_DIALOG_CLASS = (
    "fixed inset-0 m-0 h-dvh max-h-none w-full max-w-none overflow-clip "
    "border-0 bg-transparent p-0 text-inherit open:flex open:justify-center "
    "backdrop:bg-dark-backdrop/70 "
    # Only the topmost shown modal dims.
    "data-modal-covered:backdrop:opacity-0! "
    "data-modal-covered:backdrop:transition-none! "
    "data-modal-over:not-data-modal-covered:backdrop:opacity-100! "
    "data-modal-over:backdrop:transition-none!"
)
_MODAL_ALIGN_CLASS: Mapping[ModalAlign, str] = {
    "center": "open:items-center",
    "end": "open:items-end",
}


def require_every_key(alias: TypeAliasType, table: Collection[str]) -> None:
    """Refuses a table missing a Literal member."""
    members = set(get_args(alias.__value__))
    if set(table) != members:
        raise TypeError(f"{alias.__name__} table keys {set(table)} != {members}")


require_every_key(ModalAttributeRole, MODAL_ATTRIBUTES)
require_every_key(ModalAlign, _MODAL_ALIGN_CLASS)


def ModalDialog(
    attributes: Attributes = (),
    *,
    align: ModalAlign = "center",
    class_: str = "",
) -> Element:
    """A ``<dialog data-modal>`` wearing the layer's classes."""
    return Dialog(
        [(MODAL_ATTRIBUTES["modal"], ""), *attributes],
        class_=f"{_MODAL_DIALOG_CLASS} {_MODAL_ALIGN_CLASS[align]} {class_}".strip(),
    )


def labelled_by(title_id: ElementId) -> HTMLAttribute:
    """Names a dialog by its header's title."""
    return ("aria-labelledby", title_id)


def ModalPanelHeader(
    title: Child,
    *,
    title_id: ElementId,
    close_label: str = "Close dialog",
    attributes: Attributes = (),
    title_attributes: Attributes = (),
) -> Element:
    """A modal panel's title row with its ×."""
    close_button = ControlButton(
        [
            (MODAL_ATTRIBUTES["dismiss"], ""),
            ("aria-label", close_label),
            ("class", "shrink-0 focus:ring-inset"),
        ],
        variant="ghost",
    )[Span(aria_hidden="true", class_="text-type-section leading-none")["×"]]
    return Div(
        attributes,
        class_=(
            "flex shrink-0 items-center justify-between gap-4 "
            "border-b border-default-medium bg-surface-overlay px-4 py-3"
        ),
    )[
        PlainH2(
            [
                ("id", title_id),
                *title_attributes,
                ("class", "text-type-section text-heading"),
            ],
        )[title],
        close_button,
    ]
