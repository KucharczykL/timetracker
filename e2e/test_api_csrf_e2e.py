"""Verify that the session device PATCH passes CSRF in a real browser.

The pytest Client is CSRF-exempt; only a real browser exercises the
X-CSRFToken header path.  A 403 response here means CSRF was rejected —
typically because csrf=True on the API auth broke the cookie/header flow.
"""

import pytest
from django.urls import reverse
from playwright.sync_api import Page


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.mark.django_db
def test_device_patch_passes_csrf(authenticated_page: Page, live_server):
    """Changing the device on a session row must return 204, not 403.

    403 would indicate CSRF rejection — i.e. the browser's X-CSRFToken header
    is missing or mismatched after the API-wide django_auth (csrf=True) was
    enabled.  The pytest Client is CSRF-exempt, so this test is the only guard
    for that regression path.
    """
    from games.models import Device, Game, Platform, Session

    platform = Platform.objects.create(name="TestPlatform", icon="pc")
    game = Game.objects.create(name="Test Game", platform=platform)
    desktop = Device.objects.create(name="Desktop")
    deck = Device.objects.create(name="Deck")
    session = Session.objects.create(
        game=game,
        device=desktop,
        timestamp_start="2025-01-01 00:00:00+00:00",
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    # The device selector is a drop-down[behavior="select"] custom element.
    # Each session row is identified by id="session-row-{session.pk}".
    session_row = page.locator(f"#session-row-{session.pk}")
    host = session_row.locator('drop-down[behavior="select"]')
    host.wait_for(state="attached")

    # Open the listbox.
    host.locator("[data-toggle]").click()
    host.locator("[data-menu]").wait_for(state="visible")

    # Click the option for the second device; capture the PATCH response.
    with page.expect_response(
        lambda response: (
            "/api/session/" in response.url
            and "/device" in response.url
            and response.request.method == "PATCH"
        )
    ) as response_info:
        host.locator(f'[data-option][data-value="{deck.id}"]').click()

    patch_response = response_info.value
    assert patch_response.status != 403, (
        "device PATCH returned 403 — CSRF was rejected. "
        "Check that select.ts sends X-CSRFToken and that the csrftoken cookie "
        "is set on the session-list page."
    )
    assert patch_response.status < 400, (
        f"device PATCH returned unexpected status {patch_response.status}; "
        "expected a 2xx success (the API endpoint returns 204 on success)."
    )
