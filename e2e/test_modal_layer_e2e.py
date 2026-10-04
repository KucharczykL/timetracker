"""The modal layer in a real browser."""

from django.test import override_settings
from playwright.sync_api import Page, expect

from common.components.custom_elements import modal_dialog_class

on_kit = override_settings(ROOT_URLCONF="e2e.test_settings_ui_kit_e2e")

MOUNT_NESTED_MODALS = """async (dialogClass) => {
    const { attachModal } = await import("/static/js/dist/elements/modal-layer.js");
    const mount = (parent) => {
        const dialog = document.createElement("dialog");
        dialog.setAttribute("data-modal", "");
        dialog.className = dialogClass;
        dialog.innerHTML = '<div style="background:white;padding:16px">'
            + "<button>Inside</button></div>";
        parent.append(dialog);
        return dialog;
    };
    const opener = document.createElement("button");
    opener.id = "opener";
    opener.textContent = "Opener";
    document.body.prepend(opener);
    const lower = mount(document.body);
    const inner = mount(lower.firstElementChild);
    const beside = mount(document.body);
    window.modals = {
        lower: attachModal(lower),
        inner: attachModal(inner),
        beside: attachModal(beside),
    };
    window.scrollTo(0, 200);
    opener.focus({ preventScroll: true });
    window.modals.lower.open(opener);
    window.modals.inner.open();
    window.modals.beside.open();
}"""


def _mount_nested_modals(page: Page, live_server) -> None:
    page.set_viewport_size({"width": 390, "height": 600})
    page.goto(f"{live_server.url}/settings-kit-test/")
    page.evaluate(MOUNT_NESTED_MODALS, modal_dialog_class())


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

    # A toast press is no backdrop press.
    toast.locator("[data-toast-dismiss]").click()
    expect(page.locator("[data-toast-id]")).to_have_count(0)
    expect(dialog).to_have_attribute("open", "")


@on_kit
def test_escape_closes_nested_modals_from_the_top(live_server, page: Page):
    _mount_nested_modals(page, live_server)

    # Chrome may group code-opened modals into one Escape.
    while (count := _modal_count(page)) > 0:
        page.keyboard.press("Escape")
        page.wait_for_function(f"document.querySelectorAll(':modal').length < {count}")
        assert page.evaluate("window.modals.lower.isOpen()") == (_modal_count(page) > 0)

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
