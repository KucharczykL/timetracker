"""The modal layer in a real browser."""

from django.test import override_settings
from playwright.sync_api import Page, expect

on_kit = override_settings(ROOT_URLCONF="e2e.test_settings_ui_kit_e2e")

MOUNT_NESTED_MODALS = """async () => {
    const { attachModal } = await import("/static/js/dist/elements/modal-layer.js");
    const mount = (parent) => {
        const dialog = document.createElement("dialog");
        dialog.setAttribute("data-modal", "");
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
    window.modals.lower.open(opener);
    window.modals.inner.open();
    window.modals.beside.open();
}"""


@on_kit
def test_closing_the_lowest_modal_leaves_no_modal_behind(live_server, page: Page):
    page.set_viewport_size({"width": 390, "height": 600})
    page.goto(f"{live_server.url}/settings-kit-test/")
    page.evaluate(MOUNT_NESTED_MODALS)
    assert page.evaluate("document.querySelectorAll(':modal').length") == 3
    expect(page.locator("body")).to_have_css("position", "fixed")

    page.evaluate("window.modals.lower.close()")

    # A modal left inside traps invisibly.
    assert page.evaluate("document.querySelectorAll(':modal').length") == 0
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
