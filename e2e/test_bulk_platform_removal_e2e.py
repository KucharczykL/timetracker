"""Remove two platforms, then undo."""

from django.urls import reverse
from playwright.sync_api import Page, expect

from e2e.helpers import log_in
from games.models import Platform


def test_two_platforms_are_removed_and_the_undo_puts_them_back(
    live_server, page: Page, e2e_library
):
    platforms = [
        Platform.objects.create(library=e2e_library, name=name, group="Home")
        for name in ("Amiga", "Atari ST")
    ]
    log_in(page, live_server)

    listed = f"{live_server.url}{reverse('games:list_platforms')}"
    page.goto(listed)
    boxes = page.locator("tbody [data-selection-checkbox]")
    boxes.nth(0).click()
    boxes.nth(1).click()
    page.get_by_role("button", name="Remove", exact=True).first.click()

    expect(page.get_by_role("heading", name="Remove 2 platforms")).to_be_visible()
    expect(page.locator("[data-bulk-sample-row]")).to_have_count(2)
    page.get_by_role("button", name="Remove", exact=True).click()

    page.wait_for_url(listed)
    expect(page.locator("tbody tr")).to_have_count(0)
    for platform in platforms:
        platform.refresh_from_db()
        assert platform.removed_at is not None

    page.get_by_role("button", name="Undo").click()

    #: Server-rendered: the write has landed.
    expect(page.get_by_role("cell", name="Amiga").first).to_be_visible()
    for platform in platforms:
        platform.refresh_from_db()
        assert platform.removed_at is None


def test_the_row_menu_opens_edit(live_server, page: Page, e2e_library):
    platform = Platform.objects.create(library=e2e_library, name="Amiga", group="Home")
    log_in(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:list_platforms')}")
    page.get_by_role("button", name="Amiga (Home) actions").click()
    page.get_by_role("menuitem", name="Edit").click()

    dialog = page.locator("dialog[data-modal][open]")
    expect(dialog.locator("[data-form-dialog-title]")).to_have_text("Edit Platform")
    expect(dialog.locator('input[name="name"]')).to_have_value("Amiga")
    platform.refresh_from_db()
    assert platform.name == "Amiga"
