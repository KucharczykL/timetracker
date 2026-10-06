"""The modal layer in a real browser."""

import re

from django.test import override_settings
from playwright.sync_api import FloatRect, Page, expect

from common.components import (
    ControlButton,
    Div,
    Fragment,
    ModalDialog,
    ModalPanel,
    Node,
)
from common.components.form_dialog import _PANEL_CLASS
from common.components.modal import titled_header

on_kit = override_settings(ROOT_URLCONF="e2e.test_settings_ui_kit_e2e")

MOUNT_NESTED_MODALS = """async (markup) => {
    const { attachModal } = await import("/static/js/dist/elements/modal-layer.js");
    document.body.insertAdjacentHTML("beforeend", markup);
    const opener = document.createElement("button");
    opener.id = "opener";
    opener.textContent = "Opener";
    document.body.prepend(opener);
    const modal = (id) => attachModal(document.getElementById(id));
    window.modals = { lower: modal("lower"), inner: modal("inner"), beside: modal("beside") };
    window.scrollTo(0, 200);
    opener.focus({ preventScroll: true });
    window.modals.lower.open(opener);
    window.modals.inner.open();
    window.modals.beside.open();
}"""


def _nested_modals_markup() -> str:
    """A modal inside another, and one beside them."""

    def panel(*children: Node) -> Node:
        return Div(style="background:white;padding:16px")[
            ControlButton()["Inside"], *children
        ]

    inner = ModalDialog([("id", "inner")])[panel()]
    lower = ModalDialog([("id", "lower")])[panel(inner)]
    beside = ModalDialog([("id", "beside")])[panel()]
    return str(Fragment(lower, beside))


def _mount_nested_modals(page: Page, live_server) -> None:
    page.set_viewport_size({"width": 390, "height": 600})
    page.goto(f"{live_server.url}/settings-kit-test/")
    page.evaluate(MOUNT_NESTED_MODALS, _nested_modals_markup())


def _modal_count(page: Page) -> int:
    return page.evaluate("document.querySelectorAll(':modal').length")


@on_kit
def test_closing_the_lowest_modal_leaves_no_modal_behind(live_server, page: Page):
    _mount_nested_modals(page, live_server)
    assert _modal_count(page) == 3
    expect(page.locator("body")).to_have_css("position", "fixed")

    page.evaluate("window.modals.lower.close()")

    # A modal left inside traps invisibly.
    assert _modal_count(page) == 0
    expect(page.locator("body")).not_to_have_css("position", "fixed")
    assert page.evaluate("window.scrollY") == 200
    expect(page.locator("#opener")).to_be_focused()


@on_kit
def test_a_toast_under_the_sheet_sits_above_its_panel(live_server, page: Page):
    page.set_viewport_size({"width": 390, "height": 600})
    page.goto(f"{live_server.url}/settings-kit-test/")
    dialog = page.locator("dialog[data-bottom-sheet]")
    panel = dialog.locator("[data-sheet-panel]")
    page.locator("[data-section-nav-trigger]").click()
    expect(dialog).to_have_attribute("data-sheet-state", "open")

    page.evaluate(
        """window.dispatchEvent(new CustomEvent("show-toast", {
            detail: { message: "Saved under the sheet", type: "error" },
        }))"""
    )

    toast = dialog.locator("[data-toast-id]")
    expect(toast).to_be_visible()
    toast_box = toast.bounding_box()
    panel_box = panel.bounding_box()
    assert toast_box and panel_box
    assert toast_box["y"] + toast_box["height"] <= panel_box["y"]

    # Escape on a focused toast spares the sheet.
    toast.focus()
    page.keyboard.press("Escape")
    expect(page.locator("[data-toast-id]")).to_have_count(0)
    expect(dialog).to_have_attribute("open", "")

    # A toast press is no backdrop press.
    page.evaluate(
        """window.dispatchEvent(new CustomEvent("show-toast", {
            detail: { message: "Pressed under the sheet", type: "error" },
        }))"""
    )
    dialog.locator("[data-toast-dismiss]").click()
    expect(page.locator("[data-toast-id]")).to_have_count(0)
    expect(dialog).to_have_attribute("open", "")


@on_kit
def test_escape_closes_nested_modals_from_the_top(live_server, page: Page):
    _mount_nested_modals(page, live_server)

    # Chrome may group code-opened modals into one Escape.
    presses = 0
    while (count := _modal_count(page)) > 0:
        page.keyboard.press("Escape")
        presses += 1
        page.wait_for_function(f"document.querySelectorAll(':modal').length < {count}")
        lower, inner, beside = page.evaluate(
            "['lower', 'inner', 'beside'].map((name) => window.modals[name].isOpen())"
        )
        # Closed from the top: an open modal has every one below open.
        assert (not beside or inner) and (not inner or lower)
        if presses == 1:
            assert not beside

    expect(page.locator("body")).not_to_have_css("position", "fixed")
    assert page.evaluate("window.scrollY") == 200
    expect(page.locator("#opener")).to_be_focused()


@on_kit
def test_only_the_top_modal_dims(live_server, page: Page):
    _mount_nested_modals(page, live_server)
    opacities = page.evaluate(
        """() => [...document.querySelectorAll("dialog[data-modal][open]")].map(
            (dialog) => getComputedStyle(dialog, "::backdrop").opacity,
        )"""
    )
    assert opacities == ["0", "0", "1"]


MOUNT_STACKED_MODALS = """async (markup) => {
    const { attachModal } = await import("/static/js/dist/elements/modal-layer.js");
    document.body.insertAdjacentHTML("beforeend", markup);
    for (const id of ["lower", "middle", "top"]) {
        attachModal(document.getElementById(id)).open();
    }
}"""

#: Each panel's body height; Lower overflows.
_STACKED_BODIES = {"Lower": 2000, "Middle": 120, "Top": 300}


def _stacked_modals_markup() -> str:
    """Three sibling modals of differing height."""
    dialogs = []
    for name, height in _STACKED_BODIES.items():
        titled = titled_header(name, title_id=f"{name.lower()}-title")
        dialogs.append(
            ModalDialog([("id", name.lower()), titled.labelled_by])[
                ModalPanel(class_=_PANEL_CLASS)[
                    titled.header,
                    Div(class_="min-h-0 overflow-y-auto")[
                        Div(style=f"height:{height}px")
                    ],
                ]
            ]
        )
    return str(Fragment(*dialogs))


@on_kit
def test_covered_modals_step_back_and_the_top_names_them(live_server, page: Page):
    page.emulate_media(reduced_motion="reduce")
    page.set_viewport_size({"width": 800, "height": 700})
    page.goto(f"{live_server.url}/settings-kit-test/")
    page.evaluate(MOUNT_STACKED_MODALS, _stacked_modals_markup())

    def box(selector: str) -> FloatRect:
        found = page.locator(selector).bounding_box()
        assert found, selector
        return found

    for covered, above in (("#lower", "#middle"), ("#middle", "#top")):
        panel = box(f"{covered} [data-modal-panel]")
        over = box(f"{above} [data-modal-panel]")
        title = box(f"{covered} h2")
        assert 0 <= panel["y"] < over["y"]
        # The covered title shows in its strip.
        assert panel["y"] <= title["y"]
        assert title["y"] + title["height"] <= over["y"] + 0.5

    top = page.locator("#top")
    trail = top.locator("[data-modal-trail]")
    expect(trail).to_be_visible()
    expect(trail).to_have_text("Lower › , Middle")
    # Chromium spaces inline spans; spoken alike.
    expect(top).to_have_accessible_description(re.compile(r"^Lower\s*,\s*Middle\s*$"))
    expect(page.locator("#middle [data-modal-trail]")).to_be_hidden()
