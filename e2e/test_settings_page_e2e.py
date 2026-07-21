"""Mobile/desktop end-to-end coverage for the personal settings page."""

import re

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Device


@pytest.fixture
def authenticated_page(
    live_server, page: Page, django_user_model
) -> tuple[Page, Device]:
    django_user_model.objects.create_user(username="tester", password="secret123")
    preferred = Device.objects.create(name="Steam Deck", type=Device.HANDHELD)
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page, preferred


def _save_select(page: Page, key: str, name: str, value: str) -> None:
    with page.expect_response(
        lambda response: (
            f"/api/settings/user/{key}" in response.url
            and response.request.method == "PATCH"
        )
    ) as saved:
        page.locator(f'select[name="{name}"]').select_option(value)
    assert saved.value.status == 200
    badge = page.locator(f'[data-setting-source-key="{key}"]')
    expect(badge).to_have_attribute("data-setting-origin", "user")
    expect(badge).to_have_text("Personal")
    expect(badge).to_have_class(re.compile(r"\bbg-brand-soft\b"))


@pytest.mark.parametrize(
    ("viewport", "mobile"),
    [
        ({"width": 390, "height": 844}, True),
        ({"width": 1280, "height": 900}, False),
    ],
)
def test_personal_settings_persist_and_drive_consumers(
    live_server,
    authenticated_page,
    viewport,
    mobile,
):
    page, preferred = authenticated_page
    page.set_viewport_size(viewport)
    page.goto(f"{live_server.url}{reverse('games:settings')}")

    expect(page.get_by_role("heading", name="Settings", exact=True)).to_be_visible()
    expect(page.locator("[data-settings-scaffold]")).to_be_visible()
    trigger = page.locator("[data-section-nav-trigger]")
    rail = page.locator("[data-section-nav-rail]")
    if mobile:
        expect(trigger).to_be_visible()
        expect(rail).to_be_hidden()
    else:
        expect(trigger).to_be_hidden()
        expect(rail).to_be_visible()

    device_badge = page.locator('[data-setting-source-key="DEFAULT_DEVICE"]')
    expect(device_badge).to_have_attribute("data-setting-origin", "default")
    expect(device_badge).to_have_class(re.compile(r"\bbg-neutral-quaternary\b"))

    currency = page.locator('input[name="default_currency"]')
    currency.fill("EUR")
    with page.expect_response(
        lambda response: (
            "/api/settings/user/DEFAULT_CURRENCY" in response.url
            and response.request.method == "PATCH"
        )
    ) as currency_saved:
        currency.press("Tab")
    assert currency_saved.value.status == 200
    _save_select(
        page,
        "DEFAULT_DEVICE",
        "default_device",
        str(preferred.pk),
    )
    _save_select(
        page,
        "DEFAULT_LANDING_PAGE",
        "default_landing_page",
        "games:list_games",
    )

    page.reload()
    expect(currency).to_have_value("EUR")
    expect(page.locator('select[name="default_device"]')).to_have_value(
        str(preferred.pk)
    )
    expect(page.locator('select[name="default_landing_page"]')).to_have_value(
        "games:list_games"
    )

    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")
    expect(page.locator('input[name="price_currency"]')).to_have_value("EUR")
    page.goto(f"{live_server.url}{reverse('games:add_session')}")
    expect(page.locator('input[name="device"][type="hidden"]')).to_have_value(
        str(preferred.pk)
    )
    page.goto(f"{live_server.url}{reverse('games:index')}")
    expect(page).to_have_url(f"{live_server.url}{reverse('games:list_games')}")
