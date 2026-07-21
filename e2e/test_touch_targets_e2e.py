"""WCAG 2.5.8 touch-target size for small popover triggers (#454).

The truncation-reveal button is shown only on no-hover (touch) devices, where it
must be at least 24x24. This drives a mobile, no-hover context and proves the
button is visible, meets the minimum size, and activates on a press.
"""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game, Platform


@pytest.fixture
def touch_page(live_server, browser, django_user_model):
    django_user_model.objects.create_user(username="tester", password="secret123")
    context = browser.new_context(
        has_touch=True, is_mobile=True, viewport={"width": 390, "height": 844}
    )
    page = context.new_page()
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    yield page
    context.close()


def test_reveal_button_meets_min_touch_target(touch_page: Page, live_server):
    page = touch_page
    platform = Platform.objects.create(name="Steam", icon="steam", group="PC")
    Game.objects.create(
        name="A Very Long Game Name That Exceeds The Thirty Char Limit",
        platform=platform,
    )
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    button = page.locator("pop-over button[data-pop-over-trigger]").first
    expect(button).to_be_visible()  # shown on a no-hover device
    box = button.bounding_box()
    assert box is not None
    assert box["width"] >= 24, f"reveal button width {box['width']} < 24px"
    assert box["height"] >= 24, f"reveal button height {box['height']} < 24px"

    panel = page.locator("pop-over [data-pop-over-panel]").first
    expect(panel).to_be_hidden()
    button.tap()
    expect(panel).to_be_visible()
