"""Browser coverage for account theme persistence and first-paint behavior."""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import UserPreferences


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


@pytest.mark.parametrize(
    "viewport", [{"width": 390, "height": 844}, {"width": 1280, "height": 900}]
)
def test_login_page_applies_cookie_theme_on_first_frame(
    live_server, page: Page, viewport
):
    page.set_viewport_size(viewport)
    page.emulate_media(color_scheme="light")
    page.context.add_cookies(
        [{"name": "color-theme", "value": "dark", "url": live_server.url}]
    )
    _install_first_frame_probe(page)

    page.goto(f"{live_server.url}{reverse('login')}")

    assert _first_frame(page) == {"preference": "dark", "dark": True}


@pytest.mark.parametrize(
    ("scheme", "expected_dark"), [("light", False), ("dark", True)]
)
def test_auto_theme_matches_operating_system_on_first_frame(
    live_server, page: Page, scheme, expected_dark
):
    page.emulate_media(color_scheme=scheme)
    page.context.add_cookies(
        [{"name": "color-theme", "value": "auto", "url": live_server.url}]
    )
    _install_first_frame_probe(page)

    page.goto(f"{live_server.url}{reverse('login')}")

    assert _first_frame(page) == {"preference": "auto", "dark": expected_dark}


def test_invalid_browser_theme_falls_back_to_operating_system(live_server, page: Page):
    page.emulate_media(color_scheme="dark")
    page.context.add_cookies(
        [{"name": "color-theme", "value": "sepia", "url": live_server.url}]
    )
    page.goto(f"{live_server.url}{reverse('login')}")
    page.evaluate("localStorage.setItem('color-theme', 'contrast')")
    _install_first_frame_probe(page)

    page.reload()

    assert _first_frame(page) == {"preference": "auto", "dark": True}


def test_navbar_toggle_swaps_visible_icon_and_shows_tooltip(live_server, page: Page):
    page.emulate_media(color_scheme="light")
    page.goto(f"{live_server.url}{reverse('login')}")
    toggle = page.locator("theme-toggle [data-pop-over-trigger]")

    expect(toggle.locator('[data-theme-icon="auto"]')).to_be_visible()
    toggle.click()

    expect(toggle.locator('[data-theme-icon="auto"]')).to_be_hidden()
    expect(toggle.locator('[data-theme-icon="light"]')).to_be_visible()
    toggle.hover()
    tooltip = page.locator("[data-theme-tooltip]")
    expect(tooltip).to_be_visible()
    expect(tooltip).to_have_text("Theme: Light — switch to Dark")

    toggle.click()
    expect(toggle.locator('[data-theme-icon="light"]')).to_be_hidden()
    expect(toggle.locator('[data-theme-icon="dark"]')).to_be_visible()
    expect(tooltip).to_have_text("Theme: Dark — switch to Auto")

    toggle.click()
    expect(toggle.locator('[data-theme-icon="dark"]')).to_be_hidden()
    expect(toggle.locator('[data-theme-icon="auto"]')).to_be_visible()
    expect(tooltip).to_have_text("Theme: Auto — switch to Light")


def test_fresh_browser_gets_saved_account_theme_before_redirect_paints(
    live_server, page: Page, django_user_model
):
    user = django_user_model.objects.create_user(username="dark-user", password="pw")
    UserPreferences.objects.create(user=user, theme="dark")
    page.emulate_media(color_scheme="light")
    _install_first_frame_probe(page)

    _login(page, live_server, user.username)

    assert _first_frame(page) == {"preference": "dark", "dark": True}
    expect(page.locator("html")).to_have_class("dark")
    assert page.evaluate("localStorage.getItem('color-theme')") == "dark"


def test_legacy_localstorage_theme_migrates_without_wrong_first_frame(
    live_server, page: Page, django_user_model
):
    user = django_user_model.objects.create_user(username="legacy-user", password="pw")
    page.emulate_media(color_scheme="light")
    _install_first_frame_probe(page)
    page.goto(f"{live_server.url}{reverse('login')}")
    page.evaluate("localStorage.setItem('color-theme', 'dark')")
    page.fill('input[name="username"]', user.username)
    page.fill('input[name="password"]', "pw")

    with page.expect_response(
        lambda response: (
            "/api/settings/user/THEME" in response.url
            and response.request.method == "PATCH"
        )
    ) as migrated:
        page.click('button:has-text("Login")')

    assert migrated.value.status == 200
    page.wait_for_url(f"{live_server.url}/tracker**")
    assert _first_frame(page) == {"preference": "dark", "dark": True}
    preferences = UserPreferences.objects.get(user=user)
    assert preferences.theme == "dark"


def test_settings_and_navbar_share_three_state_theme_controller(
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
    expect(theme).to_have_value("light")

    with page.expect_response(
        lambda response: "/api/settings/user/THEME" in response.url
    ) as saved:
        theme.select_option("dark")
    assert saved.value.status == 200
    expect(page.locator("html")).to_have_class("dark")
    assert page.evaluate("localStorage.getItem('color-theme')") == "dark"

    toggle = page.locator("theme-toggle [data-pop-over-trigger]")
    tooltip = page.locator("[data-theme-tooltip]")
    expect(toggle).to_have_attribute("aria-label", "Theme: Dark — switch to Auto")
    toggle.hover()
    expect(tooltip).to_be_visible()
    with page.expect_response(
        lambda response: "/api/settings/user/THEME" in response.url
    ) as cycled:
        toggle.click()
    assert cycled.value.status == 200
    expect(theme).to_have_value("auto")
    expect(page.locator("html")).not_to_have_class("dark")
    expect(toggle).to_have_attribute("aria-label", "Theme: Auto — switch to Light")
    expect(tooltip).to_be_visible()
    expect(tooltip).to_have_text("Theme: Auto — switch to Light")
