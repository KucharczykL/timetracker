"""End-to-end Playwright tests for the DateTimeField element (issue #511):
the Session form's two timestamps under different account display profiles,
the calendar's Now/day-pick footer, the copy-to-the-other-timestamp arrow, and
Now/copy semantics under per-timestamp zones.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from playwright.sync_api import Browser, expect

from games.models import Game, Session, UserPreferences

ACCOUNT_TIME_ZONE = "Pacific/Kiritimati"  # UTC+14 year-round, no DST
BROWSER_TIME_ZONE = "Pacific/Honolulu"  # UTC-10 year-round — 24 hours apart

START_FIELD = 'date-time-field[field-name="timestamp_start"]'
END_FIELD = 'date-time-field[field-name="timestamp_end"]'


def _login(page, live_server, username="tester", password="secret123"):
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


@pytest.fixture
def authenticated_page(live_server, page, e2e_user):
    _login(page, live_server)
    return page, e2e_user


def _set_preferences(user, **changes) -> None:
    preferences = UserPreferences.objects.get(user=user)
    for field, value in changes.items():
        setattr(preferences, field, value)
    preferences.save(update_fields=list(changes))


def _select_first_game(page):
    games = page.locator('search-select[name="game"]')
    games.locator("[data-search-select-search]").click()
    games.locator("[data-search-select-option]").first.click()


def _fill_segments(page, container: str, values: dict) -> None:
    for part, value in values.items():
        page.locator(f'{container} input[data-date-part="{part}"]').click()
        page.keyboard.type(value)


def test_session_timestamps_render_date_and_time_segments(
    authenticated_page, live_server
):
    """Default (ISO, 24-hour) account: one flat run of date and time segments,
    and no day period."""
    page, user = authenticated_page
    Game.objects.create(library=user.library, name="Alpha Game")

    page.goto(f"{live_server.url}{reverse('games:add_session')}")
    parts = page.locator(f"{START_FIELD} input[data-date-part]")
    part_names = parts.evaluate_all("(els) => els.map(e => e.dataset.datePart)")
    assert part_names == ["year", "month", "day", "hour", "minute"]


def test_typed_wall_clock_means_the_picked_zone(
    browser: Browser, live_server, e2e_user
):
    """The reverse-engineered check for the reported bug: account zone Prague,
    zone picker flipped to Tokyo, typed 15:37 → the stored instant must be
    06:37 UTC (15:37 Tokyo), not 13:37 UTC (15:37 Prague)."""
    user = e2e_user
    _set_preferences(user, display_time_zone="Europe/Prague")
    Game.objects.create(library=user.library, name="Alpha Game")
    # Browser pinned to the account zone: the capture default stamps Prague,
    # so the flip to Tokyo below is a deliberate user act, as in the report.
    context = browser.new_context(timezone_id="Europe/Prague")
    try:
        page = context.new_page()
        _login(page, live_server)
        page.goto(f"{live_server.url}{reverse('games:add_session')}")
        _select_first_game(page)
        # Digits first, zone second — the order that exercises the live
        # reinterpretation, not just encode-at-typing-time.
        _fill_segments(
            page,
            START_FIELD,
            {"year": "2026", "month": "07", "day": "28", "hour": "15", "minute": "37"},
        )
        start_zone_row = page.locator(
            'time-zone-row[field-name="timestamp_start_timezone"]'
        )
        start_zone_row.locator('button[aria-haspopup="dialog"]').click()
        start_zone_row.locator("input[data-search-select-search]").fill("Tokyo")
        start_zone_row.locator(
            '[data-search-select-option][data-value="Asia/Tokyo"]'
        ).click()
        expect(
            page.locator(f"{START_FIELD} input[data-date-time-hidden]")
        ).to_have_value("2026-07-28T15:37:00.000000+09:00")

        with page.expect_navigation():
            page.get_by_role("button", name="Submit", exact=True).click()

        session = Session.objects.get()
        assert session.timestamp_start_timezone == "Asia/Tokyo"
        assert session.timestamp_start == dt.datetime(2026, 7, 28, 6, 37, tzinfo=dt.UTC)
        assert session.timestamp_start != dt.datetime(
            2026, 7, 28, 13, 37, tzinfo=dt.UTC
        ), "digits were interpreted in the account zone, not the picked zone"
    finally:
        context.close()


def test_capture_default_makes_typed_digits_mean_the_browser_zone(
    browser: Browser, live_server, e2e_user
):
    """Browser in Tokyo, account in Prague, and the zone picker never touched:
    the capture default alone must make the typed 15:37 a Tokyo wall clock
    (06:37 UTC), not a Prague one (13:37 UTC)."""
    user = e2e_user
    _set_preferences(user, display_time_zone="Europe/Prague")
    Game.objects.create(library=user.library, name="Alpha Game")
    context = browser.new_context(timezone_id="Asia/Tokyo")
    try:
        page = context.new_page()
        _login(page, live_server)
        page.goto(f"{live_server.url}{reverse('games:add_session')}")
        _select_first_game(page)
        # Not one click on the zone picker below this line.
        _fill_segments(
            page,
            START_FIELD,
            {"year": "2026", "month": "07", "day": "28", "hour": "15", "minute": "37"},
        )
        expect(
            page.locator(f"{START_FIELD} input[data-date-time-hidden]")
        ).to_have_value("2026-07-28T15:37:00.000000+09:00")

        with page.expect_navigation():
            page.get_by_role("button", name="Submit", exact=True).click()

        session = Session.objects.get()
        assert session.timestamp_start_timezone == "Asia/Tokyo"
        assert session.timestamp_start == dt.datetime(2026, 7, 28, 6, 37, tzinfo=dt.UTC)
        assert session.timestamp_start != dt.datetime(
            2026, 7, 28, 13, 37, tzinfo=dt.UTC
        ), "the capture default's zone never reached the datetime field"
    finally:
        context.close()


def test_typed_session_timestamp_persists_as_the_instant_it_shows(
    browser: Browser, live_server, e2e_user
):
    """Browser pinned to the account zone, so the capture default stamps
    Europe/Prague and the typed digits mean exactly what they show."""
    user = e2e_user
    _set_preferences(user, display_time_zone="Europe/Prague")
    Game.objects.create(library=user.library, name="Alpha Game")
    context = browser.new_context(timezone_id="Europe/Prague")
    try:
        page = context.new_page()
        _login(page, live_server)
        page.goto(f"{live_server.url}{reverse('games:add_session')}")
        _select_first_game(page)
        # The field is seeded with "now"; retype it wholesale.
        _fill_segments(
            page,
            START_FIELD,
            {"year": "2026", "month": "03", "day": "15", "hour": "14", "minute": "30"},
        )

        with page.expect_navigation():
            page.get_by_role("button", name="Submit", exact=True).click()

        session = Session.objects.get()
        # 14:30 in Prague on 2026-03-15 is CET (+01:00).
        assert session.timestamp_start == dt.datetime(
            2026, 3, 15, 13, 30, tzinfo=dt.UTC
        )
    finally:
        context.close()


def test_a_12_hour_account_gets_a_day_period_segment(authenticated_page, live_server):
    page, user = authenticated_page
    _set_preferences(user, datetime_format="mdy_12h")
    Game.objects.create(library=user.library, name="Alpha Game")

    page.goto(f"{live_server.url}{reverse('games:add_session')}")
    parts = page.locator(f"{START_FIELD} input[data-date-part]")
    part_names = parts.evaluate_all("(els) => els.map(e => e.dataset.datePart)")
    assert part_names == ["month", "day", "year", "hour", "minute", "day_period"]


def test_copy_arrow_fills_the_other_timestamp(browser: Browser, live_server, e2e_user):
    """The dominant real-world case — filling in one session's start and end
    together — has both endpoints in the same zone: the browser is pinned to
    match the account zone, so the start's capture default and the end's
    display-zone fallback agree, and the copy preserves identical digits and
    identical instants. (When the two zones genuinely differ, the copy still
    carries the digits verbatim per decision 4 — see the date-time-field
    vitest suite for that case; two fields landing on different capture
    defaults purely by machine happenstance is not the scenario this test is
    about.)"""
    user = e2e_user
    _set_preferences(user, display_time_zone="Europe/Prague")
    Game.objects.create(library=user.library, name="Alpha Game")
    context = browser.new_context(timezone_id="Europe/Prague")
    try:
        page = context.new_page()
        _login(page, live_server)
        page.goto(f"{live_server.url}{reverse('games:add_session')}")
        _fill_segments(
            page,
            START_FIELD,
            {"year": "2026", "month": "03", "day": "15", "hour": "14", "minute": "30"},
        )
        start_value = page.locator(
            f"{START_FIELD} input[data-date-time-hidden]"
        ).input_value()

        page.locator(f"{START_FIELD} [data-date-time-copy]").click()

        expect(page.locator(f"{END_FIELD} input[data-date-time-hidden]")).to_have_value(
            start_value
        )
    finally:
        context.close()


def test_picking_a_calendar_day_keeps_the_typed_time(authenticated_page, live_server):
    page, user = authenticated_page
    Game.objects.create(library=user.library, name="Alpha Game")

    page.goto(f"{live_server.url}{reverse('games:add_session')}")
    _fill_segments(
        page,
        START_FIELD,
        {"year": "2026", "month": "03", "day": "15", "hour": "14", "minute": "30"},
    )
    page.locator(f"{START_FIELD} [data-date-picker-calendar-toggle]").click()
    page.locator(f'{START_FIELD} button[data-date="2026-03-04"]').click()

    expect(page.locator(f'{START_FIELD} input[data-date-part="day"]')).to_have_value(
        "04"
    )
    expect(page.locator(f'{START_FIELD} input[data-date-part="hour"]')).to_have_value(
        "14"
    )


@pytest.fixture
def account_in_kiritimati(e2e_user) -> None:
    _set_preferences(e2e_user, display_time_zone=ACCOUNT_TIME_ZONE)


@pytest.mark.usefixtures("account_in_kiritimati")
def test_now_writes_the_selected_zones_wall_clock(browser: Browser, live_server):
    """The add form's capture default selects the *browser* zone, so "Now"
    writes the browser's wall clock with the browser zone's offset — the pair
    that names the true current instant. The account's wall clock (a full day
    away here) with that offset would be an instant the user never meant."""
    context = browser.new_context(timezone_id=BROWSER_TIME_ZONE)
    try:
        page = context.new_page()
        _login(page, live_server)
        page.goto(f"{live_server.url}{reverse('games:add_session')}")
        hidden = page.locator(f"{START_FIELD} input[data-date-time-hidden]")
        expect(hidden).to_be_attached()

        page.locator(f"{START_FIELD} [data-date-picker-calendar-toggle]").click()
        page.locator(f"{START_FIELD} [data-date-range-now]").click()
        expect(hidden).not_to_have_value("")

        written = dt.datetime.fromisoformat(hidden.input_value())
        assert written.utcoffset() is not None, "Now must commit offset-qualified"
        # The digits are the selected (browser) zone's wall clock…
        wall_clock = written.replace(tzinfo=None)
        browser_now = dt.datetime.now(ZoneInfo(BROWSER_TIME_ZONE)).replace(tzinfo=None)
        assert abs(wall_clock - browser_now) < dt.timedelta(minutes=2)
        # …and digits + offset together name the actual current instant.
        assert abs(written - dt.datetime.now(dt.UTC)) < dt.timedelta(minutes=2)
    finally:
        context.close()


def test_editing_a_session_without_touching_it_keeps_its_microseconds(
    authenticated_page, live_server
):
    """duration_calculated is a generated column over both timestamps, so an
    untouched edit that dropped sub-minute precision would shift the duration.
    The segments only go down to minutes; the residual rides along."""
    page, user = authenticated_page
    game = Game.objects.create(library=user.library, name="Alpha Game")
    started = dt.datetime(2026, 3, 15, 13, 30, 41, 123456, tzinfo=dt.UTC)
    session = Session.objects.create(
        game=game,
        timestamp_start=started,
        timestamp_end=started + dt.timedelta(hours=1),
    )

    page.goto(f"{live_server.url}{reverse('games:edit_session', args=[session.id])}")
    expect(page.locator(f'{START_FIELD} input[data-date-part="minute"]')).to_have_value(
        "30"
    )
    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()

    session.refresh_from_db()
    assert session.timestamp_start == started


def test_a_typed_edit_keeps_the_stored_microseconds(authenticated_page, live_server):
    page, user = authenticated_page
    game = Game.objects.create(library=user.library, name="Alpha Game")
    started = dt.datetime(2026, 3, 15, 13, 30, 41, 123456, tzinfo=dt.UTC)
    session = Session.objects.create(game=game, timestamp_start=started)

    page.goto(f"{live_server.url}{reverse('games:edit_session', args=[session.id])}")
    _fill_segments(page, START_FIELD, {"minute": "45"})
    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()

    session.refresh_from_db()
    assert session.timestamp_start == started.replace(minute=45)
