"""A person edits two platforms and takes them back."""

from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Platform


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


def _held(platform: Platform) -> tuple[str, str]:
    row = Platform.objects.get(pk=platform.pk)
    return row.group, row.icon


def _edit_selected(page: Page, listed: str) -> None:
    page.goto(listed)
    boxes = page.locator("tbody [data-selection-checkbox]")
    boxes.nth(0).click()
    boxes.nth(1).click()
    page.get_by_role("button", name="Edit…").first.click()
    #: The picker's host is defined by a module script.
    page.wait_for_load_state()
    expect(page.get_by_role("heading", name="Edit 2 platforms")).to_be_visible()


def test_two_platforms_are_edited_and_the_undo_puts_theirs_back(
    live_server, page: Page, e2e_library
):
    platforms = [
        Platform.objects.create(
            library=e2e_library, name=name, group=group, icon="unspecified"
        )
        for name, group in (("Amiga", "Commodore"), ("DOS", "PC"))
    ]
    _login(page, live_server)
    listed = f"{live_server.url}{reverse('games:list_platforms')}"

    _edit_selected(page, listed)
    group = page.locator("input[name='choice-group']")
    expect(group).to_have_attribute("placeholder", "Keep: mixed")
    group.fill("Home")
    icon = page.locator("search-select[name='choice-icon']")
    icon.locator("[data-search-select-search]").click()
    icon.get_by_role("option", name="steam", exact=True).click()
    page.get_by_role("button", name="Save", exact=True).click()

    page.wait_for_url(listed)
    assert [_held(platform) for platform in platforms] == [("Home", "steam")] * 2

    with page.expect_navigation():
        page.get_by_role("button", name="Undo").click()

    page.wait_for_url(listed)
    assert [_held(platform) for platform in platforms] == [
        ("Commodore", "unspecified"),
        ("PC", "unspecified"),
    ]


def test_the_unset_toggle_takes_the_group_away(live_server, page: Page, e2e_library):
    platforms = [
        Platform.objects.create(library=e2e_library, name=name, group="Home")
        for name in ("Amiga", "DOS")
    ]
    _login(page, live_server)
    listed = f"{live_server.url}{reverse('games:list_platforms')}"

    _edit_selected(page, listed)
    page.get_by_role("button", name="No group").click()
    page.get_by_role("button", name="Save", exact=True).click()

    page.wait_for_url(listed)
    assert [_held(platform)[0] for platform in platforms] == ["", ""]
