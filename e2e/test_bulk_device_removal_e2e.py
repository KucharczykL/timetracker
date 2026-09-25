"""Remove two devices, then undo."""

from devices import create_device
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Device


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


def test_two_devices_are_removed_and_the_undo_puts_them_back(
    live_server, page: Page, e2e_library
):
    devices = [
        create_device(e2e_library, name, Device.HANDHELD)
        for name in ("Steam Deck", "Switch")
    ]
    _login(page, live_server)

    listed = f"{live_server.url}{reverse('games:list_devices')}"
    page.goto(listed)
    page.get_by_role("button", name="Select rows").first.click()
    boxes = page.locator("tbody [data-selection-checkbox]")
    boxes.nth(0).click()
    boxes.nth(1).click()
    page.get_by_role("button", name="Remove", exact=True).first.click()

    expect(page.get_by_role("heading", name="Remove these devices")).to_be_visible()
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
    _login(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:list_devices')}")
    page.get_by_role("button", name="Steam Deck (Handheld) actions").click()
    page.get_by_role("menuitem", name="Edit").click()

    page.wait_for_url(f"**{reverse('games:edit_device', args=[device.pk])}**")
    page.fill('input[name="name"]', "Steam Deck OLED")
    page.get_by_role("button", name="Submit").click()

    expect(page.get_by_role("cell", name="Steam Deck OLED").first).to_be_visible()
    device.refresh_from_db()
    assert device.name == "Steam Deck OLED"
