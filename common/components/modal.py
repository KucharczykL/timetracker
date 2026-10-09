"""The dialog every modal on the modal layer wears."""

from collections.abc import Mapping
from typing import Literal, NamedTuple

from common.components.core import (
    Attributes,
    Child,
    Element,
    HTMLAttribute,
    require_every_key,
)
from common.components.elements import Dialog, Div, P, PlainH2, Span
from common.components.primitives import ControlButton

type ModalAlign = Literal["center", "end"]
#: Which entry and exit a panel plays; a sheet slides, a centred modal fades.
type ModalMotion = Literal["centred", "sheet"]
type ModalAttributeRole = Literal[
    "modal",
    "dismiss",
    "initial_focus",
    "covered",
    "over",
    "panel",
    "header",
    "trail",
    "depth",
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
    "panel": "data-modal-panel",
    "header": "data-modal-header",
    "trail": "data-modal-trail",
    "depth": "data-modal-depth",
}

#: Transparent hit area; the child panel shows.
#: No transform/filter/contain: toast region needs viewport.
#: clip: hidden lets focus scroll the panel.
#: The backdrop fades in at entry and out under the held leave.
_MODAL_DIALOG_CLASS = (
    "group/modal fixed inset-0 m-0 h-dvh max-h-none w-full max-w-none overflow-clip "
    "border-0 bg-transparent p-0 text-inherit open:flex open:justify-center "
    "backdrop:bg-dark-backdrop/70 "
    "backdrop:transition-opacity backdrop:duration-(--duration-medium) backdrop:ease-enter "
    "starting:open:backdrop:opacity-0 "
    "data-[motion=leaving]:backdrop:opacity-0 "
    "data-[motion=leaving]:backdrop:duration-(--duration-medium-exit) "
    "data-[motion=leaving]:backdrop:ease-exit "
    "motion-reduce:backdrop:duration-(--duration-reduced)! "
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


_HEADER_CLASS = "flex shrink-0 items-center justify-between gap-4 py-1.5 pl-4 pr-1.5"
_DIVIDED_HEADER_CLASS = "border-b border-default-medium bg-surface-overlay"

#: The layer writes them; lengths in px.
#: Arbitrary transform: the depth cue owns transform.
#: The scrim is the panel's ::after; its opacity is --modal-scrim.
#: Its opacity never dims the panel: the page stays hidden.
_MODAL_PANEL_CLASS = (
    "relative mt-[var(--modal-reserve,0px)] origin-top "
    "data-modal-depth:[transform:translateY(var(--modal-shift))_scale(var(--modal-scale))] "
    "after:pointer-events-none after:absolute after:inset-0 after:content-[''] "
    "after:rounded-[inherit] after:bg-dark-backdrop "
    "after:opacity-[var(--modal-scrim,0)] after:transition-opacity "
    "after:duration-(--duration-medium) after:ease-enter"
)
#: A centred modal fades and scales in; a held leave fades it out.
_CENTRED_PANEL_MOTION_CLASS = (
    "transition-[opacity,scale,transform] duration-(--duration-medium) ease-enter "
    "starting:opacity-0 starting:scale-96 "
    "group-data-[motion=leaving]/modal:opacity-0 "
    "group-data-[motion=leaving]/modal:scale-96 "
    "group-data-[motion=leaving]/modal:duration-(--duration-medium-exit) "
    "group-data-[motion=leaving]/modal:ease-exit "
    "motion-reduce:scale-100! motion-reduce:duration-(--duration-reduced)!"
)
#: A sheet slides; under reduced motion it only crossfades.
_SHEET_PANEL_MOTION_CLASS = (
    "transition-[translate,opacity] duration-(--duration-slow) ease-sheet "
    "translate-y-full group-data-[sheet-state=open]/sheet:translate-y-0 "
    "group-data-[motion=leaving]/sheet:duration-(--duration-slow-exit) "
    "motion-reduce:translate-none! motion-reduce:opacity-0 "
    "motion-reduce:duration-(--duration-reduced)! "
    "group-data-[sheet-state=open]/sheet:motion-reduce:opacity-100"
)
_PANEL_MOTION_CLASS: Mapping[ModalMotion, str] = {
    "centred": _CENTRED_PANEL_MOTION_CLASS,
    "sheet": _SHEET_PANEL_MOTION_CLASS,
}


require_every_key(ModalAttributeRole, MODAL_ATTRIBUTES)
require_every_key(ModalAlign, _MODAL_ALIGN_CLASS)
require_every_key(ModalMotion, _PANEL_MOTION_CLASS)


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


def ModalPanel(
    attributes: Attributes = (),
    *,
    class_: str = "",
    motion: ModalMotion = "centred",
) -> Element:
    """A modal's visible panel; steps back when covered."""
    return Div(
        [(MODAL_ATTRIBUTES["panel"], ""), *attributes],
        class_=f"{_MODAL_PANEL_CLASS} {_PANEL_MOTION_CLASS[motion]} {class_}".strip(),
    )


def ModalPanelHeader(
    title: Child,
    *,
    title_id: ElementId | None,
    close_label: str | None = "Close dialog",
    attributes: Attributes = (),
    title_attributes: Attributes = (),
    divided: bool = True,
) -> Element:
    """A modal panel's title row; no label, no ×.

    `title_id` beats an id in `title_attributes`;
    `None` leaves the id to the client.
    `divided`: a line over a scrolling body.
    """
    close_button = (
        None
        if close_label is None
        else ControlButton(
            [
                (MODAL_ATTRIBUTES["dismiss"], ""),
                ("aria-label", close_label),
                ("class", "shrink-0 focus:ring-inset"),
            ],
            variant="ghost",
            size="compact",
        )[Span(aria_hidden="true", class_="text-type-section leading-none")["×"]]
    )
    return Div(
        [(MODAL_ATTRIBUTES["header"], ""), *attributes],
        class_=f"{_HEADER_CLASS} {_DIVIDED_HEADER_CLASS if divided else ''}".strip(),
    )[
        Div(class_="flex min-w-0 flex-col")[
            P(
                [(MODAL_ATTRIBUTES["trail"], ""), ("hidden", "")],
                class_="text-type-micro text-body",
            ),
            PlainH2(
                [
                    *([] if title_id is None else [("id", title_id)]),
                    *title_attributes,
                    ("class", "text-type-section text-heading"),
                ],
            )[title],
        ],
        close_button,
    ]


class TitledHeader(NamedTuple):
    """A header and the attribute naming its dialog."""

    labelled_by: HTMLAttribute
    header: Element


def titled_header(
    title: Child,
    *,
    title_id: ElementId,
    close_label: str | None = "Close dialog",
    attributes: Attributes = (),
    title_attributes: Attributes = (),
    divided: bool = True,
) -> TitledHeader:
    """Pairs a header with its dialog's name."""
    return TitledHeader(
        ("aria-labelledby", title_id),
        ModalPanelHeader(
            title,
            title_id=title_id,
            close_label=close_label,
            attributes=attributes,
            title_attributes=title_attributes,
            divided=divided,
        ),
    )
