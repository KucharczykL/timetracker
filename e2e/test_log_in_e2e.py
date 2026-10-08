"""The cookie login every browser test takes."""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from e2e.helpers import E2E_LOGIN, Credentials, log_in


def test_the_cookie_signs_the_page_in(live_server, page: Page, e2e_user):
    log_in(page, live_server)
    page.goto(f"{live_server.url}{reverse('games:index')}")

    expect(
        page.get_by_role("button", name=f"Open account menu for {e2e_user.username}")
    ).to_be_visible()


def test_a_wrong_password_fails_at_once(live_server, page: Page, e2e_user):
    wrong = Credentials(E2E_LOGIN.username, "not-the-password")

    with pytest.raises(AssertionError, match="tester was not signed in"):
        log_in(page, live_server, wrong)
    assert page.context.cookies() == []
