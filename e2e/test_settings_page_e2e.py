"""Mobile/desktop end-to-end coverage for the personal settings page."""

import json
import re

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Device, Game


@pytest.fixture
def authenticated_page(
    live_server, page: Page, django_user_model
) -> tuple[Page, Device]:
    django_user_model.objects.create_user(username="tester", password="secret123")
    preferred = Device.objects.create(name="Steam Deck", type=Device.HANDHELD)
    Game.objects.bulk_create([Game(name=f"Game {index:02}") for index in range(51)])
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
    badge = page.locator(f'setting-source-badge[key="{key}"] [data-setting-origin]')
    expect(badge).to_have_attribute("data-setting-origin", "user")
    expect(badge).to_have_text("Personal")
    expect(badge).to_have_class(re.compile(r"\bbg-brand-soft\b"))
    status = badge.locator("xpath=ancestor::pop-over//*[@data-setting-source-status]")
    expect(status).to_contain_text("Non-default source (default source: “Default”)")


def _wait_for_live_settings(page: Page) -> None:
    page.wait_for_load_state("load")
    page.wait_for_function("customElements.get('live-setting-fields') !== undefined")
    expect(page.locator("live-setting-fields")).to_be_attached()


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

    device_badge = page.locator(
        'setting-source-badge[key="DEFAULT_DEVICE"] [data-setting-origin]'
    )
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
    _save_select(
        page,
        "DEFAULT_PAGE_SIZE",
        "default_page_size",
        "50",
    )

    page.reload()
    expect(currency).to_have_value("EUR")
    expect(page.locator('select[name="default_device"]')).to_have_value(
        str(preferred.pk)
    )
    expect(page.locator('select[name="default_landing_page"]')).to_have_value(
        "games:list_games"
    )
    expect(page.locator('select[name="default_page_size"]')).to_have_value("50")

    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")
    expect(page.locator('input[name="price_currency"]')).to_have_value("EUR")
    page.goto(f"{live_server.url}{reverse('games:add_session')}")
    expect(page.locator('input[name="device"][type="hidden"]')).to_have_value(
        str(preferred.pk)
    )
    page.goto(f"{live_server.url}{reverse('games:index')}")
    expect(page).to_have_url(f"{live_server.url}{reverse('games:list_games')}")
    expect(page).not_to_have_url(re.compile(r"[?&]per_page="))
    expect(page.locator("#page-sizeLink")).to_have_text("50")


@pytest.mark.parametrize(
    "viewport",
    [{"width": 390, "height": 844}, {"width": 1280, "height": 900}],
)
def test_presentation_preferences_reload_with_the_updated_contract(
    live_server, authenticated_page, viewport
):
    page, _preferred = authenticated_page
    page.set_viewport_size(viewport)
    page.goto(f"{live_server.url}{reverse('games:settings')}")
    _wait_for_live_settings(page)

    with page.expect_navigation(wait_until="load"):
        with page.expect_response(
            lambda response: (
                "/api/settings/user/DISPLAY_TIME_ZONE" in response.url
                and response.request.method == "PATCH"
            )
        ) as time_zone_saved:
            page.locator('select[name="display_time_zone"]').select_option(
                "Pacific/Kiritimati"
            )
    assert time_zone_saved.value.status == 200
    _wait_for_live_settings(page)
    page.wait_for_function(
        "document.documentElement.dataset.dateTimePresentation.includes('Pacific/Kiritimati')"
    )
    expect(page.locator('select[name="display_time_zone"]')).to_have_value(
        "Pacific/Kiritimati"
    )

    with page.expect_navigation(wait_until="load"):
        with page.expect_response(
            lambda response: (
                "/api/settings/user/DATE_FORMAT_LOCALE" in response.url
                and response.request.method == "PATCH"
            )
        ) as locale_saved:
            page.locator('select[name="date_format_locale"]').select_option("cs")
    assert locale_saved.value.status == 200
    _wait_for_live_settings(page)
    page.wait_for_function(
        "JSON.parse(document.documentElement.dataset.dateTimePresentation).locale === 'cs'"
    )
    contract = json.loads(
        page.locator("html").get_attribute("data-date-time-presentation") or "{}"
    )
    assert contract["time_zone"] == "Pacific/Kiritimati"
    assert contract["locale"] == "cs"

    with page.expect_navigation(wait_until="load"):
        with page.expect_response(
            lambda response: (
                "/api/settings/user/DATETIME_FORMAT" in response.url
                and response.request.method == "PATCH"
            )
        ) as format_saved:
            page.locator('select[name="datetime_format"]').select_option("mdy_12h")
    assert format_saved.value.status == 200
    _wait_for_live_settings(page)
    page.wait_for_function(
        """
        (() => {
          const config = JSON.parse(
            document.documentElement.dataset.dateTimePresentation
          );
          return config.profile.date_parts[0].name === "month"
            && config.profile.hour_cycle === "h12";
        })()
        """
    )
    expect(page.locator('select[name="datetime_format"]')).to_have_value("mdy_12h")

    page.reload()
    _wait_for_live_settings(page)
    contract = json.loads(
        page.locator("html").get_attribute("data-date-time-presentation") or "{}"
    )
    assert contract["profile"]["date_parts"][0]["name"] == "month"
    assert contract["profile"]["hour_cycle"] == "h12"
    expect(page.locator('select[name="datetime_format"]')).to_have_value("mdy_12h")


def test_user_page_ignores_a_synthetic_site_namespace_event(
    live_server,
    authenticated_page,
):
    """Mirror of test_site_page_ignores_a_synthetic_user_namespace_event, in
    the other direction: a synthetic site-namespace event for a key also
    shown on the user page must not update this page's badge."""
    page, _preferred = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:settings')}")
    _wait_for_live_settings(page)

    badge = page.locator(
        'setting-source-badge[key="DEFAULT_CURRENCY"] [data-setting-origin]'
    )
    before = badge.get_attribute("data-setting-origin")

    page.evaluate(
        """() => {
            document.body.dispatchEvent(new CustomEvent("setting-committed", {
                detail: {
                    key: "DEFAULT_CURRENCY",
                    value: "USD",
                    source: "database",
                    locked: false,
                    namespace: "site",
                },
                bubbles: true,
            }));
        }"""
    )

    expect(badge).to_have_attribute("data-setting-origin", before)
