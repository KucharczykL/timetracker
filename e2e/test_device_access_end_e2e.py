"""Ending a device's access, end to end."""

from devices import create_device
from django.urls import reverse
from playwright.sync_api import Page, expect

from e2e.helpers import pick_choice


def _row(page: Page, name: str):
    return page.locator("tbody tr", has_text=name)


def test_selling_a_device_shows_on_the_list_and_in_the_picker(
    authenticated_page: Page, live_server, e2e_library
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    create_device(e2e_library, "Desk PC")

    page.goto(f"{live_server.url}{reverse('games:edit_device', args=[deck.pk])}")
    pick_choice(page, "access", "sold")
    page.wait_for_selector("[data-temporal-segments='start']:not([hidden])")
    page.click("[data-date-part='year'][data-date-side='start']")
    page.keyboard.type("2021")
    page.click("[data-date-part='month'][data-date-side='start']")
    page.keyboard.type("05")
    page.locator("[data-temporal-disclosure]").first.click()
    page.locator('input[name="access_day-uncertain"]').check()
    page.fill('textarea[name="access_note"]', "to a friend")
    page.get_by_role("button", name="Submit", exact=True).click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_devices')}**")
    expect(_row(page, "Deck")).to_contain_text("Sold · May 2021")
    deck.refresh_from_db()
    assert deck.access_ended.canonical == "2021-05?"
    expect(_row(page, "Desk PC")).to_contain_text("Held")

    page.goto(f"{live_server.url}{reverse('games:add_session')}")
    picker = page.locator('search-select[name="device"]')
    picker.locator("[data-search-select-search]").click()
    options = picker.locator("[data-search-select-options] [data-value]")
    expect(options).to_have_count(2)
    expect(options.nth(0)).to_have_attribute("data-label", "Desk PC")
    expect(options.nth(1)).to_have_attribute("data-label", "Deck")
    expect(options.nth(1).locator("[data-search-select-hint]")).to_have_text("Sold")

    page.goto(f"{live_server.url}{reverse('games:edit_device', args=[deck.pk])}")
    pick_choice(page, "access", "")
    page.get_by_role("button", name="Submit", exact=True).click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_devices')}**")
    expect(_row(page, "Deck")).to_contain_text("Held")
