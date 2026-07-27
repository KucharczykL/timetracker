"""Mobile/desktop end-to-end coverage for the personal settings page."""

import json
import re

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Device, Game


@pytest.fixture
def superuser_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_superuser(
        username="infra-admin", password="secret123"
    )
    page.goto(f"{live_server.url}{reverse('login')}")
    page.get_by_label("Username").fill("infra-admin")
    page.get_by_label("Password").fill("secret123")
    page.get_by_role("button", name="Login", exact=True).click()
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


_INFRA_KEYS = (
    "TZ",
    "DEBUG",
    "SECRET_KEY",
    "APP_URL",
    "DEV_LOGIN_PREFILL",
    "ALLOWED_HOSTS",
    "DATA_DIR",
    "HASHED_STATIC",
)


@pytest.mark.parametrize(
    ("viewport", "mobile"),
    [
        ({"width": 390, "height": 844}, True),
        ({"width": 1280, "height": 900}, False),
    ],
)
def test_superuser_sees_infrastructure_section_on_admin_settings(
    live_server,
    superuser_page: Page,
    viewport,
    mobile,
):
    page = superuser_page
    page.set_viewport_size(viewport)
    page.goto(f"{live_server.url}{reverse('games:admin_settings')}")
    page.wait_for_load_state("load")

    expect(
        page.get_by_role("heading", name="Infrastructure", exact=True)
    ).to_be_visible()

    section_trigger = page.locator("[data-section-nav-trigger]")
    section_rail = page.locator("[data-section-nav-rail]")
    if mobile:
        expect(section_trigger).to_be_visible()
        expect(section_rail).to_be_hidden()
    else:
        expect(section_trigger).to_be_hidden()
        expect(section_rail).to_be_visible()

    for key in _INFRA_KEYS:
        expect(page.get_by_text(key, exact=True).first).to_be_visible()

    # Scope to the infrastructure section: the site-defaults section alone
    # renders >= 8 badges, so a page-wide count would pass even if this section
    # rendered none.
    infra_badges = page.locator("#infrastructure [data-setting-origin]")
    assert infra_badges.count() >= len(_INFRA_KEYS)


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
          return config.profile.segments[0].name === "month"
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
    assert contract["profile"]["segments"][0]["name"] == "month"
    assert contract["profile"]["hour_cycle"] == "h12"
    expect(page.locator('select[name="datetime_format"]')).to_have_value("mdy_12h")
