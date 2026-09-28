"""Remove two platforms, then undo."""

from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Platform


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


def test_two_platforms_are_removed_and_the_undo_puts_them_back(
    live_server, page: Page, e2e_library
):
    platforms = [
        Platform.objects.create(library=e2e_library, name=name, group="Home")
        for name in ("Amiga", "Atari ST")
    ]
    _login(page, live_server)

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
    _login(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:list_platforms')}")
    page.get_by_role("button", name="Amiga (Home) actions").click()
    page.get_by_role("menuitem", name="Edit").click()

    page.wait_for_url(f"**{reverse('games:edit_platform', args=[platform.pk])}**")
