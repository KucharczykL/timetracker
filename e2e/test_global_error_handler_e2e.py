"""Browser test for the global uncaught-error handler (issue #328).

Guards two properties the vitest suite cannot see: vitest imports the TS source
directly and never exercises the real <script>-tag load semantics.

1. dist/global-error-handler.js is an ES module (it imports the client-error
   seam); it must load as <script type="module"> or the browser throws
   SyntaxError at parse and registers no listeners (feature silently inert).
2. The handler is actually wired: a synthetic uncaught window error POSTs to
   /api/client-error/.
"""

from django.urls import reverse
from playwright.sync_api import Page

import pytest


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    _login(page, live_server)
    return page


def test_no_syntax_error_on_load(authenticated_page: Page, live_server) -> None:
    """The module loads clean — no SyntaxError from a mis-tagged script."""
    page = authenticated_page
    console_errors: list[str] = []
    page_errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            console_errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.on("pageerror", lambda exception: page_errors.append(str(exception)))
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    page.wait_for_load_state("networkidle")
    assert page_errors == [], f"uncaught page errors on load: {page_errors}"
    assert not any("SyntaxError" in text for text in console_errors), console_errors


def test_uncaught_error_is_reported(authenticated_page: Page, live_server) -> None:
    """A synthetic uncaught window error reaches POST /api/client-error/."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    page.wait_for_load_state("networkidle")
    with page.expect_request(
        lambda request: "/api/client-error/" in request.url and request.method == "POST"
    ) as request_info:
        page.evaluate(
            """() => {
                window.dispatchEvent(new ErrorEvent('error', {
                    message: 'e2e-boom',
                    filename: location.origin + '/static/js/fake.js',
                    lineno: 1, colno: 1,
                    error: new Error('e2e-boom'),
                }));
            }"""
        )
    assert request_info.value.method == "POST"
