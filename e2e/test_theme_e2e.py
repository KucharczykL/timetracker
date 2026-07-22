"""Browser coverage for account-authoritative theme state and first paint."""

import pytest
from django.urls import reverse
from playwright.sync_api import Browser, Page, expect

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


@pytest.mark.parametrize(
    ("preference", "scheme", "expected_dark", "anonymous"),
    [
        ("system", "dark", True, "light"),
        ("light", "dark", False, "dark"),
        ("dark", "light", True, "light"),
    ],
)
def test_account_theme_wins_before_redirect_paints_without_touching_storage(
    live_server,
    page: Page,
    django_user_model,
    preference,
    scheme,
    expected_dark,
    anonymous,
):
    user = django_user_model.objects.create_user(
        username=f"{preference}-user", password="pw"
    )
    UserPreferences.objects.create(user=user, theme=preference)
    page.emulate_media(color_scheme=scheme)
    _set_anonymous_theme(page, live_server, anonymous)
    _install_first_frame_probe(page)

    page.fill('input[name="username"]', user.username)
    page.fill('input[name="password"]', "pw")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")

    assert _first_frame(page) == {
        "preference": preference,
        "dark": expected_dark,
    }
    assert page.evaluate("localStorage.getItem('color-theme')") == anonymous


def test_logout_restores_the_anonymous_browser_preference(
    live_server, page: Page, django_user_model
):
    user = django_user_model.objects.create_user(username="logout-user", password="pw")
    UserPreferences.objects.create(user=user, theme="dark")
    page.emulate_media(color_scheme="light")
    _set_anonymous_theme(page, live_server, "light")
    page.fill('input[name="username"]', user.username)
    page.fill('input[name="password"]', "pw")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    expect(page.locator("html")).to_have_class("dark")

    page.get_by_role("button", name="Log out").click()
    page.wait_for_url(f"{live_server.url}{reverse('login')}**")

    expect(page.locator("html")).to_have_attribute("data-theme-preference", "light")
    expect(page.locator("html")).not_to_have_class("dark")
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


def test_second_browser_reconciles_account_theme_on_navigation(
    live_server, browser: Browser, django_user_model
):
    user = django_user_model.objects.create_user(username="two-browser", password="pw")
    UserPreferences.objects.create(user=user, theme="light")
    first_context = browser.new_context()
    second_context = browser.new_context()
    first = first_context.new_page()
    second = second_context.new_page()
    try:
        _login(first, live_server, user.username)
        _login(second, live_server, user.username)
        first.goto(f"{live_server.url}{reverse('games:settings')}")
        second.goto(f"{live_server.url}{reverse('games:settings')}")
        expect(second.locator("html")).to_have_attribute(
            "data-theme-preference", "light"
        )

        with first.expect_response(
            lambda response: "/api/settings/user/THEME" in response.url
        ):
            first.locator('select[name="theme"]').select_option("dark")

        expect(second.locator("html")).to_have_attribute(
            "data-theme-preference", "light"
        )
        second.reload()
        expect(second.locator("html")).to_have_attribute(
            "data-theme-preference", "dark"
        )
        expect(second.locator("html")).to_have_class("dark")
    finally:
        first_context.close()
        second_context.close()


def test_clearing_personal_theme_commits_inherited_value_and_source(
    live_server, page: Page, django_user_model
):
    user = django_user_model.objects.create_user(username="inherit-user", password="pw")
    UserPreferences.objects.create(user=user, theme="light")
    SiteSetting.objects.create(key="THEME", value="dark")
    settings_resolver.clear_cache()
    _login(page, live_server, user.username)
    page.goto(f"{live_server.url}{reverse('games:settings')}")
    theme = page.locator('select[name="theme"]')
    source = page.locator('setting-source-badge[key="THEME"] [data-setting-origin]')

    with page.expect_response(
        lambda response: "/api/settings/user/THEME" in response.url
    ):
        theme.select_option("")

    expect(theme).to_have_value("")
    expect(page.locator("html")).to_have_attribute("data-theme-preference", "dark")
    expect(page.locator("html")).to_have_class("dark")
    expect(source).to_have_attribute("data-setting-origin", "database")


def test_failed_theme_save_restores_system_state_then_allows_retry(
    live_server, page: Page, django_user_model
):
    user = django_user_model.objects.create_user(
        username="rollback-user", password="pw"
    )
    SiteSetting.objects.create(key="THEME", value="system")
    settings_resolver.clear_cache()
    page.emulate_media(color_scheme="dark")
    _login(page, live_server, user.username)
    page.goto(f"{live_server.url}{reverse('games:settings')}")
    theme = page.locator('select[name="theme"]')
    source = page.locator('setting-source-badge[key="THEME"] [data-setting-origin]')
    toggle = page.locator("theme-toggle [data-pop-over-trigger]")
    tooltip = page.locator("[data-theme-tooltip]")
    expect(theme).to_have_value("")
    expect(source).to_have_attribute("data-setting-origin", "database")
    expect(page.locator("html")).to_have_class("dark")
    toggle.hover()
    page.route(
        "**/api/settings/user/THEME",
        lambda route: route.fulfill(status=500, body="save failed"),
    )

    theme.select_option("light")

    expect(theme).to_have_value("")
    expect(theme).to_be_enabled()
    expect(page.locator("html")).to_have_class("dark")
    expect(page.locator("html")).to_have_attribute("data-theme-preference", "system")
    expect(source).to_have_attribute("data-setting-origin", "database")
    expect(toggle.locator('[data-theme-icon="system"]')).to_be_visible()
    expect(tooltip).to_be_visible()
    expect(tooltip).to_have_text("Theme: System — switch to Light")
    expect(page.get_by_text("Couldn't save your theme", exact=False)).to_be_visible()

    page.unroute("**/api/settings/user/THEME")
    with page.expect_response(
        lambda response: "/api/settings/user/THEME" in response.url
    ):
        theme.select_option("light")
    expect(theme).to_have_value("light")
    expect(page.locator("html")).not_to_have_class("dark")
