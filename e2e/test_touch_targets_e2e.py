"""WCAG 2.5.8 touch-target size for small popover triggers (#454).

The small icon-button popover triggers (the truncation reveal, the filter-builder
incomplete "!" cue) are sized to the 24px minimum touch target. This proves the
reveal button's box is at least 24x24 and that a press anywhere in it activates
the trigger.
"""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game, Platform


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def test_reveal_button_meets_min_touch_target(authenticated_page: Page, live_server):
    page = authenticated_page
    platform = Platform.objects.create(name="Steam", icon="steam", group="PC")
    Game.objects.create(
        name="A Very Long Game Name That Exceeds The Thirty Char Limit",
        platform=platform,
    )
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    box = page.evaluate(
        """() => {
        const button = document.querySelector('pop-over button[data-pop-over-trigger]');
        const b = button.getBoundingClientRect();
        return { width: b.width, height: b.height };
      }"""
    )
    assert box["width"] >= 24, f"reveal button width {box['width']} < 24px"
    assert box["height"] >= 24, f"reveal button height {box['height']} < 24px"

    panel = page.locator("pop-over [data-pop-over-panel]").first
    expect(panel).to_be_hidden()
    page.locator("pop-over button[data-pop-over-trigger]").first.click()
    expect(panel).to_be_visible()
