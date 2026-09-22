"""Per-timestamp zone rows in a real browser pinned to Asia/Tokyo: the capture
default, the always-visible trigger, and the finish flow stamping the end
zone."""

from datetime import UTC, datetime

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect
from session_rows import session_row

from e2e.helpers import open_row_menu
from games.models import Game, PlayerSession
from games.reads.calendar import calendar_day_zone


def _row(game, **columns):
    """A projection row whose day is counted in the library's calendar."""
    library = game.library
    return session_row(game, day_zone=calendar_day_zone(library).key, **columns)


BROWSER_TIME_ZONE = "Asia/Tokyo"


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


@pytest.fixture
def tokyo_page(live_server, browser, e2e_user):
    """A logged-in page whose browser reports Asia/Tokyo while the account's
    display zone stays the default UTC — a guaranteed mismatch."""
    context = browser.new_context(timezone_id=BROWSER_TIME_ZONE)
    page = context.new_page()
    _login(page, live_server)
    yield page
    context.close()


@pytest.fixture
def matched_zone_page(live_server, browser, e2e_user):
    """The mirror of `tokyo_page`: a browser in the account's own display zone,
    where nothing about the zones is remarkable."""
    context = browser.new_context(timezone_id="UTC")
    page = context.new_page()
    _login(page, live_server)
    yield page
    context.close()


def test_add_form_captures_the_browser_zone(tokyo_page, live_server, e2e_library):
    Game.objects.create(library=e2e_library, name="Hades")
    tokyo_page.goto(f"{live_server.url}{reverse('games:add_session')}")

    start_row = tokyo_page.locator('time-zone-row[field-name="started_at_zone"]')
    # Capture default: the browser zone landed in the submitted channel.
    expect(start_row.locator("[data-time-zone-value]")).to_have_value(BROWSER_TIME_ZONE)
    # And the one control is right there, naming what it captured. (There is
    # nothing to "auto-expand" on an add form: capture just made the effective
    # zone equal the browser zone, so no mismatch can exist here by
    # construction — the mismatch cue is exercised in the vitest suite.)
    trigger = start_row.locator('button[aria-haspopup="dialog"]')
    expect(trigger).to_be_visible()
    expect(trigger).to_contain_text(BROWSER_TIME_ZONE)


def test_submitting_the_form_persists_the_captured_zone(
    tokyo_page, live_server, e2e_library
):
    game = Game.objects.create(library=e2e_library, name="Hades")
    tokyo_page.goto(f"{live_server.url}{reverse('games:add_session')}")

    game_search = tokyo_page.locator("input[data-search-select-search]").first
    game_search.fill("Hades")
    tokyo_page.locator(f'[data-search-select-option][data-value="{game.pk}"]').click()
    #: The run picker searches on the game and holds its one run.
    expect(
        tokyo_page.locator(
            'search-select[name="playthrough"] '
            '[data-search-select-pills] input[type="hidden"]'
        )
    ).to_have_count(1)
    # Text-scoped: the navbar's hidden logout control is also a
    # form button[type="submit"], so that alone is still ambiguous.
    tokyo_page.click('button[type="submit"]:has-text("Submit")')
    tokyo_page.wait_for_url(f"{live_server.url}{reverse('games:list_sessions')}**")

    session = PlayerSession.objects.get()
    assert session.started_at_zone == BROWSER_TIME_ZONE


def test_trigger_is_visible_regardless_of_zone_match(
    matched_zone_page, live_server, e2e_library
):
    """Visibility does not depend on a detected mismatch. A browser in the
    account's own display zone still gets the picker — that is the case a
    mismatch check can never surface, and the reason there is no reveal
    mechanic at all."""
    Game.objects.create(library=e2e_library, name="Hades")
    matched_zone_page.goto(f"{live_server.url}{reverse('games:add_session')}")

    start_row = matched_zone_page.locator('time-zone-row[field-name="started_at_zone"]')
    trigger = start_row.locator('button[aria-haspopup="dialog"]')
    expect(trigger).to_be_visible()
    # Opening it is a user action, never something the page did on load.
    trigger.click()
    expect(start_row.locator("input[data-search-select-search]")).to_be_visible()


def test_finish_stamps_the_end_zone(tokyo_page, live_server, e2e_library):
    game = Game.objects.create(library=e2e_library, name="Hades")
    session = _row(
        game, started_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC), ended_at=None
    )
    tokyo_page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    row = tokyo_page.locator(f"#session-row-{session.pk}")
    open_row_menu(tokyo_page, f"session-menu-{session.pk}")
    row.locator('form[action*="/finish"] button[type="submit"]').click()
    # The list re-renders after the write commits, so waiting for the finish
    # control to vanish is a server-state assertion.
    row = tokyo_page.locator(f"#session-row-{session.pk}")
    expect(row.locator('form[action*="/finish"]')).to_have_count(0)

    session.refresh_from_db()
    assert session.ended_at_zone == BROWSER_TIME_ZONE
    assert session.ended_at is not None
