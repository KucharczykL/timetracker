"""Remove two devices, then undo."""

from devices import create_device
from django.urls import reverse
from playwright.sync_api import Page, expect

from e2e.helpers import log_in
from games.models import Device


def test_two_devices_are_removed_and_the_undo_puts_them_back(
    live_server, page: Page, e2e_library
):
    devices = [
        create_device(e2e_library, name, Device.HANDHELD)
        for name in ("Steam Deck", "Switch")
    ]
    log_in(page, live_server)

    listed = f"{live_server.url}{reverse('games:list_devices')}"
    page.goto(listed)
    boxes = page.locator("tbody [data-selection-checkbox]")
    boxes.nth(0).click()
    boxes.nth(1).click()
    page.get_by_role("button", name="Remove", exact=True).first.click()

    expect(page.get_by_role("heading", name="Remove 2 devices")).to_be_visible()
    expect(page.locator("[data-bulk-sample-row]")).to_have_count(2)
    page.get_by_role("button", name="Remove", exact=True).click()

    page.wait_for_url(listed)
    expect(page.locator("tbody tr")).to_have_count(0)
    for device in devices:
        device.refresh_from_db()
        assert device.removed_at is not None

    page.get_by_role("button", name="Undo").click()

    #: Server-rendered: the write has landed.
    expect(page.get_by_role("cell", name="Steam Deck").first).to_be_visible()
    for device in devices:
        device.refresh_from_db()
        assert device.removed_at is None


def test_the_row_menu_opens_edit(live_server, page: Page, e2e_library):
    device = create_device(e2e_library, "Steam Deck", Device.HANDHELD)
    log_in(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:list_devices')}")
    page.get_by_role("button", name="Steam Deck (Handheld) actions").click()
    page.get_by_role("menuitem", name="Edit").click()

    dialog = page.locator("dialog[data-modal][open]")
    expect(dialog.locator("[data-form-dialog-title]")).to_have_text("Edit device")
    dialog.locator('input[name="name"]').fill("Steam Deck OLED")
    dialog.get_by_role("button", name="Submit", exact=True).click()

    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)
    expect(page.get_by_role("cell", name="Steam Deck OLED").first).to_be_visible()
    device.refresh_from_db()
    assert device.name == "Steam Deck OLED"


def test_each_row_checkbox_names_its_device_once(live_server, page: Page, e2e_library):
    for name in ("Steam Deck", "PC"):
        create_device(e2e_library, name, Device.PC)
    log_in(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:list_devices')}")

    for name in ("Steam Deck", "PC"):
        expect(page.get_by_role("checkbox", name=name, exact=True)).to_have_count(1)
