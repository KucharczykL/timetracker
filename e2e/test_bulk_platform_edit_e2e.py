"""A person edits two platforms and takes them back."""

from django.urls import reverse
from playwright.sync_api import Page, expect

from e2e.helpers import log_in
from games.models import Platform


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
    log_in(page, live_server)
    listed = f"{live_server.url}{reverse('games:list_platforms')}"

    _edit_selected(page, listed)
    group = page.locator(
        "search-select[name='choice-group'] [data-search-select-search]"
    )
    expect(group).to_have_attribute("placeholder", "Keep: mixed")
    group.fill("Home")
    page.get_by_role("option", name="Use “Home”").click()
    expect(page.locator("input[type='hidden'][name='choice-group']")).to_have_value(
        "Home"
    )
    page.get_by_role("button", name="Keep: Unspecified").click()
    icons = page.get_by_role("dialog", name="Icon")
    icons.get_by_title("Steam", exact=True).click()
    expect(icons).to_be_hidden()
    expect(page.get_by_role("button", name="Steam")).to_be_visible()
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
    log_in(page, live_server)
    listed = f"{live_server.url}{reverse('games:list_platforms')}"

    _edit_selected(page, listed)
    page.get_by_role("button", name="No group").click()
    page.get_by_role("button", name="Save", exact=True).click()

    page.wait_for_url(listed)
    assert [_held(platform)[0] for platform in platforms] == ["", ""]


def test_the_platform_form_picks_an_icon_from_the_grid(
    live_server, page: Page, e2e_library
):
    platform = Platform.objects.create(
        library=e2e_library, name="Amiga", icon="unspecified"
    )
    log_in(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:edit_platform', args=[platform.pk])}")
    trigger = page.get_by_role("button", name="Unspecified")
    icons = page.get_by_role("dialog", name="Icon")
    trigger.click()
    expect(icons.get_by_role("radio", name="Unspecified")).to_be_focused()
    # The toggle closes the panel it opened.
    trigger.click()
    expect(icons).to_be_hidden()
    trigger.click()
    expect(icons.get_by_role("radio", name="Unspecified")).to_be_focused()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Enter")
    expect(icons).to_be_hidden()
    page.get_by_role("button", name="Submit").click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_platforms')}**")
    assert Platform.objects.get(pk=platform.pk).icon == "battlenet"


def test_the_platform_form_picks_a_group_the_library_holds(
    live_server, page: Page, e2e_library
):
    Platform.objects.create(library=e2e_library, name="Amiga", group="Commodore")
    platform = Platform.objects.create(library=e2e_library, name="C64")
    log_in(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:edit_platform', args=[platform.pk])}")
    page.locator("search-select[name='group'] [data-search-select-search]").fill("com")
    page.get_by_role("option", name="Commodore", exact=True).click()
    page.get_by_role("button", name="Submit").click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_platforms')}**")
    assert Platform.objects.get(pk=platform.pk).group == "Commodore"


def test_a_typed_group_is_saved_without_picking_it(
    live_server, page: Page, e2e_library
):
    platform = Platform.objects.create(library=e2e_library, name="C64", group="PC")
    log_in(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:edit_platform', args=[platform.pk])}")
    page.locator("search-select[name='group'] [data-search-select-search]").fill(
        "Retro"
    )
    page.get_by_role("button", name="Submit").click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_platforms')}**")
    assert Platform.objects.get(pk=platform.pk).group == "Retro"


def test_a_group_typed_in_bulk_is_saved_without_picking_it(
    live_server, page: Page, e2e_library
):
    platforms = [
        Platform.objects.create(library=e2e_library, name=name, group="PC")
        for name in ("Amiga", "DOS")
    ]
    log_in(page, live_server)
    listed = f"{live_server.url}{reverse('games:list_platforms')}"

    _edit_selected(page, listed)
    page.locator("search-select[name='choice-group'] [data-search-select-search]").fill(
        "Retro"
    )
    page.get_by_role("button", name="Save", exact=True).click()

    page.wait_for_url(listed)
    assert [_held(platform)[0] for platform in platforms] == ["Retro", "Retro"]
