"""A device's access ends on its form, shows on the list, and is taken back."""

import pytest
from devices import create_device
from django.urls import reverse
from playwright.sync_api import Page, expect


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def _row(page: Page, name: str):
    return page.locator("tbody tr", has_text=name)


def test_selling_a_device_shows_on_the_list_and_in_the_picker(
    authenticated_page: Page, live_server, e2e_library
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    create_device(e2e_library, "Desk PC")

    page.goto(f"{live_server.url}{reverse('games:edit_device', args=[deck.pk])}")
    page.select_option('select[name="access"]', "sold")
    page.wait_for_selector("[data-temporal-segments='start']:not([hidden])")
    page.click("[data-date-part='year'][data-date-side='start']")
    page.keyboard.type("2021")
    page.click("[data-date-part='month'][data-date-side='start']")
    page.keyboard.type("05")
    page.fill('textarea[name="access_note"]', "to a friend")
    page.get_by_role("button", name="Submit", exact=True).click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_devices')}**")
    expect(_row(page, "Deck")).to_contain_text("Sold · May 2021")
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
    page.select_option('select[name="access"]', "")
    page.get_by_role("button", name="Submit", exact=True).click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_devices')}**")
    expect(_row(page, "Deck")).to_contain_text("Held")
