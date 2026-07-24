"""Browser acceptance coverage for the superuser Admin settings page."""

import json
import re

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from timetracker import config as config_module
from timetracker import settings_resolver

SITE_SETTING_KEYS = (
    "DEFAULT_CURRENCY",
    "DEFAULT_DEVICE",
    "DEFAULT_LANDING_PAGE",
    "DEFAULT_PAGE_SIZE",
    "THEME",
    "DISPLAY_TIME_ZONE",
    "DATE_FORMAT_LOCALE",
    "DATETIME_FORMAT",
)


@pytest.fixture
def editable_site_setting_sources(monkeypatch, tmp_path, settings):
    """Keep source precedence deterministic for browser writes."""
    settings.DEFAULT_CURRENCY = "CZK"
    for key in SITE_SETTING_KEYS:
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(f"{key}__FILE", raising=False)
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    config_module.reset_caches()
    settings_resolver.clear_cache()
    yield
    config_module.reset_caches()
    settings_resolver.clear_cache()


@pytest.fixture
def superuser_page(
    live_server,
    page: Page,
    django_user_model,
    editable_site_setting_sources,
) -> Page:
    django_user_model.objects.create_superuser(
        username="settings-admin",
        password="secret123",
    )
    page.goto(f"{live_server.url}{reverse('login')}")
    page.get_by_label("Username").fill("settings-admin")
    page.get_by_label("Password").fill("secret123")
    page.get_by_role("button", name="Login", exact=True).click()
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def _wait_for_live_settings(page: Page) -> None:
    page.wait_for_load_state("load")
    page.wait_for_function("customElements.get('live-setting-fields') !== undefined")
    expect(page.locator("live-setting-fields")).to_be_attached()


def _site_patch(response, key: str) -> bool:
    return (
        f"/api/settings/site/{key}" in response.url
        and response.request.method == "PATCH"
    )


def _source_badge(page: Page, key: str):
    return page.locator(f'setting-source-badge[key="{key}"] [data-setting-origin]')


@pytest.mark.parametrize(
    ("viewport", "mobile"),
    [
        ({"width": 390, "height": 844}, True),
        ({"width": 1280, "height": 900}, False),
    ],
)
def test_superuser_navbar_opens_responsive_admin_settings(
    live_server,
    superuser_page: Page,
    viewport,
    mobile,
):
    page = superuser_page
    page.set_viewport_size(viewport)
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    main_menu = page.locator("#navbar-dropdown")
    if mobile:
        expect(main_menu).to_be_hidden()
        page.get_by_role("button", name="Open main menu", exact=True).click()
    expect(main_menu).to_be_visible()

    page.get_by_role("button", name="Menu", exact=True).click()
    admin_link = page.get_by_role("menuitem", name="Admin settings", exact=True)
    expect(admin_link).to_be_visible()
    with page.expect_navigation(wait_until="load"):
        admin_link.click()

    expect(page).to_have_url(f"{live_server.url}{reverse('games:admin_settings')}")
    expect(
        page.get_by_role("heading", name="Admin settings", exact=True)
    ).to_be_visible()
    section_trigger = page.locator("[data-section-nav-trigger]")
    section_rail = page.locator("[data-section-nav-rail]")
    if mobile:
        expect(section_trigger).to_be_visible()
        expect(section_rail).to_be_hidden()
    else:
        expect(section_trigger).to_be_hidden()
        expect(section_rail).to_be_visible()


def test_text_select_and_clear_site_defaults(
    live_server,
    superuser_page: Page,
):
    page = superuser_page
    page.goto(f"{live_server.url}{reverse('games:admin_settings')}")
    _wait_for_live_settings(page)

    currency = page.get_by_label("Default currency", exact=True)
    currency.fill("eur")
    with page.expect_response(
        lambda response: _site_patch(response, "DEFAULT_CURRENCY")
    ) as saved:
        currency.press("Tab")
    assert saved.value.status == 200
    assert saved.value.json() == {
        "key": "DEFAULT_CURRENCY",
        "value": "EUR",
        "source": "database",
        "locked": False,
        "namespace": "site",
    }
    expect(currency).to_have_value("EUR")
    currency_badge = _source_badge(page, "DEFAULT_CURRENCY")
    expect(currency_badge).to_have_attribute("data-setting-origin", "database")
    expect(currency_badge).to_have_text("Database")
    expect(currency_badge).to_have_class(re.compile(r"\bbg-brand-soft\b"))

    page_size = page.get_by_label("Default rows per page", exact=True)
    with page.expect_response(
        lambda response: _site_patch(response, "DEFAULT_PAGE_SIZE")
    ) as selected:
        page_size.select_option("50")
    assert selected.value.status == 200
    assert selected.value.json()["value"] == 50
    expect(page_size).to_have_value("50")
    expect(_source_badge(page, "DEFAULT_PAGE_SIZE")).to_have_attribute(
        "data-setting-origin", "database"
    )

    currency.fill("")
    with page.expect_response(
        lambda response: _site_patch(response, "DEFAULT_CURRENCY")
    ) as cleared:
        currency.press("Tab")
    assert cleared.value.status == 200
    assert cleared.value.json() == {
        "key": "DEFAULT_CURRENCY",
        "value": "CZK",
        "source": "default",
        "locked": False,
        "namespace": "site",
    }
    expect(currency).to_have_value("CZK")
    expect(currency_badge).to_have_attribute("data-setting-origin", "default")
    expect(currency_badge).to_have_text("Default")
    expect(currency_badge).to_have_class(re.compile(r"\bbg-neutral-quaternary\b"))


def test_display_time_zone_save_reloads_presentation_contract(
    live_server,
    superuser_page: Page,
):
    page = superuser_page
    page.goto(f"{live_server.url}{reverse('games:admin_settings')}")
    _wait_for_live_settings(page)

    with page.expect_navigation(wait_until="load"):
        with page.expect_response(
            lambda response: _site_patch(response, "DISPLAY_TIME_ZONE")
        ) as saved:
            page.get_by_label("Time zone", exact=True).select_option(
                "Pacific/Kiritimati"
            )
    assert saved.value.status == 200
    _wait_for_live_settings(page)

    contract = json.loads(
        page.locator("html").get_attribute("data-date-time-presentation") or "{}"
    )
    assert contract["time_zone"] == "Pacific/Kiritimati"
    expect(page.get_by_label("Time zone", exact=True)).to_have_value(
        "Pacific/Kiritimati"
    )


def test_configuration_locked_field_shows_owner_and_explanation(
    live_server,
    superuser_page: Page,
    monkeypatch,
):
    monkeypatch.setenv("DEFAULT_CURRENCY", "USD")
    config_module.reset_caches()
    settings_resolver.clear_cache()
    page = superuser_page
    page.goto(f"{live_server.url}{reverse('games:admin_settings')}")

    currency = page.get_by_label("Default currency", exact=True)
    expect(currency).to_be_disabled()
    expect(currency).to_have_value("USD")
    badge = _source_badge(page, "DEFAULT_CURRENCY")
    expect(badge).to_have_attribute("data-setting-origin", "env")
    expect(badge).to_have_attribute("data-setting-locked", "")
    expect(badge).to_have_text("Environment")
    expect(
        page.locator("[data-setting-metadata]").get_by_text(
            "Managed by Environment; it cannot be changed here.",
            exact=True,
        )
    ).to_be_visible()


def test_site_page_ignores_a_synthetic_user_namespace_event(
    live_server,
    superuser_page: Page,
):
    """A same-key event from the OTHER namespace must not update this page's
    badge — issue #488's core acceptance criterion, exercised in the
    direction real traffic can't reach today (no page hosts both
    namespaces), so the cross-namespace event is injected synthetically."""
    page = superuser_page
    page.goto(f"{live_server.url}{reverse('games:admin_settings')}")
    _wait_for_live_settings(page)

    badge = _source_badge(page, "DEFAULT_CURRENCY")
    before = badge.get_attribute("data-setting-origin")

    page.evaluate(
        """() => {
            document.body.dispatchEvent(new CustomEvent("setting-committed", {
                detail: {
                    key: "DEFAULT_CURRENCY",
                    value: "USD",
                    source: "user",
                    locked: false,
                    namespace: "user",
                },
                bubbles: true,
            }));
        }"""
    )

    expect(badge).to_have_attribute("data-setting-origin", before)
