"""Browser coverage for account-authoritative theme state and first paint."""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import SiteSetting, UserPreferences
from timetracker import settings_resolver


def _install_first_frame_probe(page: Page) -> None:
    page.add_init_script(
        """
        window.__themeAtFirstFrame = null;
        requestAnimationFrame(() => {
            window.__themeAtFirstFrame = {
                preference: document.documentElement.dataset.themePreference,
                dark: document.documentElement.classList.contains("dark"),
            };
        });
        """
    )


def _first_frame(page: Page) -> dict:
    page.wait_for_function("window.__themeAtFirstFrame !== null")
    return page.evaluate("window.__themeAtFirstFrame")


def _login(page: Page, live_server, username: str, password: str = "pw") -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


def _set_anonymous_theme(page: Page, live_server, value: str) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.evaluate("value => localStorage.setItem('color-theme', value)", value)


@pytest.mark.parametrize(
    "viewport", [{"width": 390, "height": 844}, {"width": 1280, "height": 900}]
)
def test_login_page_applies_anonymous_storage_theme_on_first_frame(
    live_server, page: Page, viewport
):
    page.set_viewport_size(viewport)
    page.emulate_media(color_scheme="light")
    _set_anonymous_theme(page, live_server, "dark")
    _install_first_frame_probe(page)

    page.reload()

    assert _first_frame(page) == {"preference": "dark", "dark": True}


@pytest.mark.parametrize(
    ("scheme", "expected_dark"), [("light", False), ("dark", True)]
)
def test_system_theme_matches_operating_system_on_first_frame(
    live_server, page: Page, scheme, expected_dark
):
    page.emulate_media(color_scheme=scheme)
    _set_anonymous_theme(page, live_server, "system")
    _install_first_frame_probe(page)

    page.reload()

    assert _first_frame(page) == {"preference": "system", "dark": expected_dark}


def test_invalid_browser_theme_falls_back_to_system(live_server, page: Page):
    page.emulate_media(color_scheme="dark")
    _set_anonymous_theme(page, live_server, "auto")
    _install_first_frame_probe(page)

    page.reload()

    assert _first_frame(page) == {"preference": "system", "dark": True}


def test_navbar_toggle_swaps_visible_icon_and_reopens_hovered_tooltip(
    live_server, page: Page
):
    page.emulate_media(color_scheme="light")
    page.goto(f"{live_server.url}{reverse('login')}")
    toggle = page.locator("theme-toggle [data-pop-over-trigger]")
    tooltip = page.locator("[data-theme-tooltip]")

    expect(toggle.locator('[data-theme-icon="system"]')).to_be_visible()
    toggle.hover()
    expect(tooltip).to_be_visible()
    expect(tooltip).to_have_text("Theme: System — switch to Light")

    toggle.click()
    expect(toggle.locator('[data-theme-icon="system"]')).to_be_hidden()
    expect(toggle.locator('[data-theme-icon="light"]')).to_be_visible()
    expect(tooltip).to_be_visible()
    expect(tooltip).to_have_text("Theme: Light — switch to Dark")

    toggle.click()
    expect(toggle.locator('[data-theme-icon="dark"]')).to_be_visible()
    expect(tooltip).to_have_text("Theme: Dark — switch to System")

    toggle.click()
    expect(toggle.locator('[data-theme-icon="system"]')).to_be_visible()
    expect(tooltip).to_have_text("Theme: System — switch to Light")


def test_account_theme_wins_before_redirect_paints_without_touching_storage(
    live_server, page: Page, django_user_model
):
    user = django_user_model.objects.create_user(username="dark-user", password="pw")
    UserPreferences.objects.create(user=user, theme="dark")
    page.emulate_media(color_scheme="light")
    _set_anonymous_theme(page, live_server, "light")
    _install_first_frame_probe(page)

    page.fill('input[name="username"]', user.username)
    page.fill('input[name="password"]', "pw")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")

    assert _first_frame(page) == {"preference": "dark", "dark": True}
    expect(page.locator("html")).to_have_class("dark")
    assert page.evaluate("localStorage.getItem('color-theme')") == "light"


def test_prelogin_storage_is_ignored_and_not_migrated_to_account(
    live_server, page: Page, django_user_model
):
    user = django_user_model.objects.create_user(username="new-user", password="pw")
    page.emulate_media(color_scheme="light")
    _set_anonymous_theme(page, live_server, "dark")
    _install_first_frame_probe(page)

    page.fill('input[name="username"]', user.username)
    page.fill('input[name="password"]', "pw")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")

    assert _first_frame(page) == {"preference": "system", "dark": False}
    assert not UserPreferences.objects.filter(user=user).exists()
    assert page.evaluate("localStorage.getItem('color-theme')") == "dark"


def test_settings_and_navbar_share_account_coordinator(
    live_server, page: Page, django_user_model
):
    user = django_user_model.objects.create_user(
        username="settings-user", password="pw"
    )
    UserPreferences.objects.create(user=user, theme="light")
    page.emulate_media(color_scheme="light")
    _login(page, live_server, user.username)
    page.goto(f"{live_server.url}{reverse('games:settings')}")
    theme = page.locator('select[name="theme"]')
    toggle = page.locator("theme-toggle [data-pop-over-trigger]")
    tooltip = page.locator("[data-theme-tooltip]")
    expect(theme).to_have_value("light")

    with page.expect_response(
        lambda response: "/api/settings/user/THEME" in response.url
    ):
        theme.select_option("dark")
    expect(page.locator("html")).to_have_class("dark")
    expect(toggle).to_have_attribute("aria-label", "Theme: Dark — switch to System")

    toggle.hover()
    expect(tooltip).to_be_visible()
    with page.expect_response(
        lambda response: "/api/settings/user/THEME" in response.url
    ):
        toggle.click()
    expect(theme).to_have_value("system")
    expect(page.locator("html")).not_to_have_class("dark")
    expect(tooltip).to_be_visible()
    expect(tooltip).to_have_text("Theme: System — switch to Light")


def test_failed_theme_save_restores_inherited_selection_class_and_source(
    live_server, page: Page, django_user_model
):
    user = django_user_model.objects.create_user(
        username="rollback-user", password="pw"
    )
    SiteSetting.objects.create(key="THEME", value="dark")
    settings_resolver.clear_cache()
    page.emulate_media(color_scheme="light")
    _login(page, live_server, user.username)
    page.goto(f"{live_server.url}{reverse('games:settings')}")
    theme = page.locator('select[name="theme"]')
    source = page.locator('setting-source-badge[key="THEME"] [data-setting-origin]')
    expect(theme).to_have_value("")
    expect(source).to_have_attribute("data-setting-origin", "database")
    expect(page.locator("html")).to_have_class("dark")
    page.route(
        "**/api/settings/user/THEME",
        lambda route: route.fulfill(status=500, body="save failed"),
    )

    theme.select_option("light")

    expect(theme).to_have_value("")
    expect(theme).to_be_enabled()
    expect(page.locator("html")).to_have_class("dark")
    expect(source).to_have_attribute("data-setting-origin", "database")
