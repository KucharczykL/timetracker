"""The device selector's "No device" clear entry clears the device (issue #290).

The entry has data-value=""; with empty_is_null enabled the select behavior
must send {"device_id": null}. This is the end-to-end guard for that branch in
ts/elements/behaviors/select.ts.
"""

import json
from datetime import UTC, datetime

import pytest
from devices import create_device
from django.urls import reverse
from playwright.sync_api import Page


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def test_no_device_option_clears_device(
    authenticated_page: Page, live_server, e2e_library
):
    from session_rows import session_row as seed_session

    from games.models import Game

    game = Game.objects.create(library=e2e_library, name="Test Game")
    desktop = create_device(library=e2e_library, name="Desktop")
    session = seed_session(
        game, device=desktop, started_at=datetime(2025, 1, 1, tzinfo=UTC)
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    session_row = page.locator(f"#session-row-{session.pk}")
    host = session_row.locator('drop-down[behavior="select"]')
    host.wait_for(state="attached")

    host.locator("[data-toggle]").click()
    host.locator("[data-menu]").wait_for(state="visible")

    with page.expect_response(
        lambda response: (
            "/api/session/" in response.url
            and "/device" in response.url
            and response.request.method == "PATCH"
        )
    ) as response_info:
        host.locator('[data-option][data-value=""]').click()

    patch_response = response_info.value
    assert patch_response.status == 204
    # Parse, don't string-compare: JSON.stringify emits no whitespace.
    post_data = patch_response.request.post_data
    assert post_data is not None
    assert json.loads(post_data) == {"device_id": None}

    # Optimistic UI: the trigger label swaps to the clear entry's label.
    assert host.locator("[data-label]").inner_text().strip() == "No device"

    session.refresh_from_db()
    assert session.device is None
