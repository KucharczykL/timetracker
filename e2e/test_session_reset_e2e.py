"""Browser test for the session-list "Reset start to now" action (issue #33).

Reset is a page, not a modal: the row links to a confirmation that posts to
games:reset_session. Reset overwrites the original start time and is only
recoverable by editing the session, which is why it confirms at all. Covers
both the confirm and cancel paths.
"""

import datetime as dt

import pytest
from django.urls import reverse
from playwright.sync_api import Browser, Page, expect
from session_rows import session_row

from games.models import Game, Platform, PlayerSession
from games.reads.calendar import calendar_day_zone


def _row(game, **columns):
    """A projection row whose day is counted in the library's calendar."""
    library = game.library
    return session_row(game, day_zone=calendar_day_zone(library).key, **columns)


STARTED_AT = dt.datetime(2020, 1, 1, 10, 0, tzinfo=dt.UTC)


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def _make_running_session(library) -> PlayerSession:
    platform = Platform.objects.create(
        library=library, name="PC", icon="pc", group="PC"
    )
    game = Game.objects.create(library=library, name="Reset Game", platform=platform)
    return _row(game, started_at=STARTED_AT)


def _open_row_menu(page, session_id) -> None:
    """A row states its acts behind one trigger, so open it before pressing.

    Every item starts inside a panel that is `hidden`, which is why a press
    that skips this times out rather than failing an assertion. The wait is
    the element's own registration: a press landing on a `<drop-down>` the
    module has not upgraded yet is swallowed, and the timeout that follows
    names the item rather than the cause.
    """
    page.wait_for_function("() => !!customElements.get('drop-down')")
    page.locator(f"#session-menu-{session_id}Link").click()


def test_reset_confirms_on_its_own_page_then_returns_to_the_list(
    authenticated_page: Page, live_server, e2e_library
):
    page = authenticated_page
    session = _make_running_session(e2e_library)

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    row = page.locator(f"#session-row-{session.id}")
    expect(row).to_contain_text("2020")

    _open_row_menu(page, session.id)
    row.get_by_role("menuitem", name="Reset start to now", exact=True).click()

    expect(page.locator("body")).to_contain_text("Reset Game")
    page.locator('button:has-text("Reset to now")').click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_sessions')}*")
    expect(page.locator(f"#session-row-{session.id}")).not_to_contain_text("2020")

    session.refresh_from_db()
    assert session.started_at is not None
    assert session.started_at > STARTED_AT


def test_reset_cancel_leaves_start_unchanged(
    authenticated_page: Page, live_server, e2e_library
):
    page = authenticated_page
    session = _make_running_session(e2e_library)

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    _open_row_menu(page, session.id)
    page.locator(f"#session-row-{session.id}").get_by_role(
        "menuitem", name="Reset start to now", exact=True
    ).click()

    page.locator('a:has-text("Cancel")').click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_sessions')}*")
    expect(page.locator(f"#session-row-{session.id}")).to_contain_text("2020")
    session.refresh_from_db()
    assert session.started_at == STARTED_AT


def test_reset_stamps_the_browser_zone(
    authenticated_page: Page, browser: Browser, live_server, e2e_library
):
    session = _make_running_session(e2e_library)

    context = browser.new_context(timezone_id="Pacific/Honolulu")
    try:
        page = context.new_page()
        page.goto(f"{live_server.url}{reverse('login')}")
        page.fill('input[name="username"]', "tester")
        page.fill('input[name="password"]', "secret123")
        page.click('button:has-text("Login")')
        page.wait_for_url(f"{live_server.url}/tracker**")

        page.goto(
            f"{live_server.url}{reverse('games:reset_session', args=[session.id])}"
        )
        page.locator('button:has-text("Reset to now")').click()
        page.wait_for_url(f"{live_server.url}{reverse('games:list_sessions')}*")

        session.refresh_from_db()
        assert session.started_at_zone == "Pacific/Honolulu"
    finally:
        context.close()
