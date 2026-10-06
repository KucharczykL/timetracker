"""The Library page's default device picker."""

import pytest
from devices import create_device, end_device_access
from django.urls import reverse
from playwright.sync_api import Page, expect

from e2e.helpers import held_choice, pick_choice
from games.models import Device, UserLibraryPreferences
from timetracker import settings_commands

DEFAULT_DEVICE_URL = "/api/library/default-device"


@pytest.fixture
def library_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.fixture
def devices(e2e_library) -> dict[str, Device]:
    deck = create_device(e2e_library, "Deck")
    phone = create_device(e2e_library, "Phone")
    end_device_access(create_device(e2e_library, "Old laptop"))
    settings_commands.change_library_default_device(e2e_library, deck)
    return {"deck": deck, "phone": phone}


def _open(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('games:library')}")
    page.wait_for_function("customElements.get('live-setting-fields') !== undefined")


def _search(page: Page):
    return page.locator(
        'search-select[name="default_device"] [data-search-select-search]'
    )


def _saved(page: Page):
    return page.expect_response(
        lambda response: (
            DEFAULT_DEVICE_URL in response.url and response.request.method == "PATCH"
        )
    )


def _stored(e2e_library):
    return UserLibraryPreferences.objects.get(library=e2e_library).default_device_id


def test_a_pick_saves_and_none_saves_null(
    library_page: Page, live_server, e2e_library, devices
):
    page = library_page
    deck, phone = devices["deck"], devices["phone"]
    _open(page, live_server)
    picker = page.locator('search-select[name="default_device"]')

    _search(page).click()
    expect(picker.get_by_role("option", name="Phone")).to_be_visible()
    expect(picker.get_by_role("option", name="Old laptop")).to_have_count(0)
    with _saved(page) as picked:
        picker.get_by_role("option", name="Phone").click()
    assert picked.value.request.post_data_json == {"value": str(phone.pk)}
    assert picked.value.status == 200
    _open(page, live_server)
    expect(held_choice(page, "default_device")).to_have_value(str(phone.pk))
    expect(_search(page)).to_have_value("Phone")

    with _saved(page) as cleared:
        picker.locator("[data-search-select-clear]").click()
    assert cleared.value.request.post_data_json == {"value": None}
    expect(_search(page)).to_have_value("No device")
    assert _stored(e2e_library) is None

    with _saved(page):
        pick_choice(page, "default_device", str(deck.pk))
    with _saved(page) as none:
        pick_choice(page, "default_device", "")
    assert none.value.request.post_data_json == {"value": None}
    expect(_search(page)).to_have_value("No device")
    assert _stored(e2e_library) is None


def test_a_refused_save_restores_the_stored_device(
    library_page: Page, live_server, devices
):
    page = library_page
    deck = devices["deck"]
    _open(page, live_server)
    page.route(
        f"**{DEFAULT_DEVICE_URL}",
        lambda route: route.fulfill(
            status=422,
            content_type="application/json",
            body='{"detail": "refused"}',
        ),
    )
    picker = page.locator('search-select[name="default_device"]')

    _search(page).click()
    with page.expect_response(lambda response: "q=Ph" in response.url):
        _search(page).fill("Ph")
    expect(
        picker.locator(f'[data-search-select-option][data-value="{deck.pk}"]')
    ).to_have_count(0)
    with _saved(page):
        picker.get_by_role("option", name="Phone").click()

    expect(_search(page)).to_have_value("Deck")
    expect(held_choice(page, "default_device")).to_have_value(str(deck.pk))
