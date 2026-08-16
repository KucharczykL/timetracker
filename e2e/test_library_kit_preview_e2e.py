import pytest
from django.urls import path, reverse
from playwright.sync_api import Page, expect

from games.views.library_kit_preview import library_kit_preview
from timetracker.urls import urlpatterns as base_urlpatterns

urlpatterns = [
    *base_urlpatterns,
    path(
        "tracker/library-kit-preview/",
        library_kit_preview,
        name="library_kit_preview_e2e",
    ),
]


@pytest.fixture
def authenticated_page(settings, live_server, page: Page, e2e_user) -> Page:
    settings.DEBUG = True
    settings.INTERNAL_IPS = []
    settings.ROOT_URLCONF = __name__
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.mark.parametrize(
    ("width", "height", "wide"),
    [(390, 844, False), (1280, 900, True)],
)
def test_library_kit_responsive_interactions_and_static_toasts(
    authenticated_page: Page,
    live_server,
    width: int,
    height: int,
    wide: bool,
):
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": height})
    requested_urls: list[str] = []
    page.on("request", lambda request: requested_urls.append(request.url))
    page.goto(f"{live_server.url}{reverse('library_kit_preview_e2e')}")
    page.wait_for_load_state("networkidle")
    requested_urls.clear()

    section_nav = page.locator("section-nav")
    section_trigger = section_nav.locator("[data-section-nav-trigger]")
    section_rail = section_nav.locator("[data-section-nav-rail]")
    wide_actions = page.locator("[data-entity-summary-wide-actions]").first
    overflow = page.locator("[data-entity-summary-overflow]").first
    if wide:
        expect(section_trigger).to_be_hidden()
        expect(section_rail).to_be_visible()
        expect(wide_actions).to_be_visible()
        expect(overflow).to_be_hidden()
    else:
        expect(section_trigger).to_be_visible()
        expect(section_rail).to_be_hidden()
        expect(wide_actions).to_be_hidden()
        expect(overflow).to_be_visible()

        entity_trigger = page.get_by_role("button", name="Games actions")
        entity_menu = entity_trigger.locator("xpath=ancestor::drop-down").locator(
            "[data-menu]"
        )
        entity_trigger.click()
        expect(entity_menu).to_be_visible()
        page.keyboard.press("Escape")
        expect(entity_menu).to_be_hidden()
        expect(entity_trigger).to_be_focused()

    admin_trigger = page.get_by_role(
        "button",
        name="Open account menu for alexandra-with-a-deliberately-long-username",
    )
    admin_menu = admin_trigger.locator("xpath=ancestor::drop-down").locator(
        "[data-menu]"
    )
    admin_trigger.click()
    expect(admin_menu).to_be_visible()
    expect(admin_menu.get_by_role("menuitem", name="Admin settings")).to_have_count(1)
    page.keyboard.press("Escape")
    expect(admin_menu).to_be_hidden()
    expect(admin_trigger).to_be_focused()

    user_trigger = page.get_by_role(
        "button",
        name="Open account menu for preview-normal-user",
    )
    user_menu = user_trigger.locator("xpath=ancestor::drop-down").locator("[data-menu]")
    user_trigger.click()
    expect(user_menu).to_be_visible()
    expect(user_menu.get_by_role("menuitem", name="Admin settings")).to_have_count(0)
    page.keyboard.press("Escape")
    expect(user_trigger).to_be_focused()

    copy_button = page.locator("[data-copy-control]")
    copy_label = page.locator("[data-copy-label]")
    notifications = page.locator(
        '[aria-label="Notifications"] [x-text="toast.message"]'
    )
    page.evaluate(
        """mode => {
            Object.defineProperty(navigator, 'clipboard', {
                configurable: true,
                value: {
                    writeText: () => mode === 'resolve'
                        ? Promise.resolve()
                        : Promise.reject(new Error('denied')),
                },
            });
        }""",
        "resolve",
    )
    copy_button.click()
    expect(copy_label).to_have_text("Copied!")
    page.wait_for_timeout(2_100)
    expect(copy_label).to_have_text("Copy")

    page.evaluate(
        """Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: { writeText: () => Promise.reject(new Error('denied')) },
        })"""
    )
    copy_button.click()
    expect(copy_label).to_have_text("Couldn't copy")
    page.wait_for_timeout(2_100)
    expect(copy_label).to_have_text("Couldn't copy")
    expect(notifications).to_have_count(0)

    running = (
        "Prices are being converted. Totals will update when conversion is complete."
    )
    failed = (
        "Prices couldn't be converted. Existing totals are still available. "
        "We'll retry automatically."
    )
    complete = "Prices converted. Totals are now up to date."
    page.get_by_role("button", name="Show running").click()
    expect(notifications).to_have_text(running)
    page.get_by_role("button", name="Show failed").click()
    expect(notifications).to_have_text(failed)
    page.get_by_role("button", name="Show completed").click()
    expect(notifications).to_have_text(complete)
    assert not any("library-conversion" in url for url in requested_urls)
