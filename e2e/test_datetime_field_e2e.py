"""End-to-end Playwright tests for the DateTimeField element (issue #511):
the Session form's two timestamps under different account display profiles,
the calendar's Now/day-pick footer, the copy-to-the-other-timestamp arrow, and
the timezone guard that issue #535 added to the button this widget absorbed.
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
def authenticated_page(live_server, page, django_user_model):
    user = django_user_model.objects.create_user(
        username="tester", password="secret123"
    )
    _login(page, live_server)
    return page, user


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
    page, _user = authenticated_page
    Game.objects.create(name="Alpha Game")

    page.goto(f"{live_server.url}{reverse('games:add_session')}")
    parts = page.locator(f"{START_FIELD} input[data-date-part]")
    part_names = parts.evaluate_all("(els) => els.map(e => e.dataset.datePart)")
    assert part_names == ["year", "month", "day", "hour", "minute"]


def test_typed_session_timestamp_persists_as_the_instant_it_shows(
    authenticated_page, live_server
):
    page, user = authenticated_page
    UserPreferences.objects.create(user=user, display_time_zone="Europe/Prague")
    Game.objects.create(name="Alpha Game")

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
    assert session.timestamp_start == dt.datetime(2026, 3, 15, 13, 30, tzinfo=dt.UTC)


def test_a_12_hour_account_gets_a_day_period_segment(authenticated_page, live_server):
    page, user = authenticated_page
    UserPreferences.objects.create(user=user, datetime_format="mdy_12h")
    Game.objects.create(name="Alpha Game")

    page.goto(f"{live_server.url}{reverse('games:add_session')}")
    parts = page.locator(f"{START_FIELD} input[data-date-part]")
    part_names = parts.evaluate_all("(els) => els.map(e => e.dataset.datePart)")
    assert part_names == ["month", "day", "year", "hour", "minute", "day_period"]


def test_copy_arrow_fills_the_other_timestamp(authenticated_page, live_server):
    page, _user = authenticated_page
    Game.objects.create(name="Alpha Game")

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


def test_picking_a_calendar_day_keeps_the_typed_time(authenticated_page, live_server):
    page, _user = authenticated_page
    Game.objects.create(name="Alpha Game")

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
def account_in_kiritimati(django_user_model) -> None:
    user = django_user_model.objects.create_user(
        username="tester", password="secret123"
    )
    UserPreferences.objects.create(user=user, display_time_zone=ACCOUNT_TIME_ZONE)


@pytest.mark.usefixtures("account_in_kiritimati")
def test_now_writes_the_account_wall_clock(browser: Browser, live_server):
    """Issue #535, carried over from <session-timestamp-buttons>: the server
    reads this field in the *account's* timezone, so writing the browser's wall
    clock would store a wrong instant for anyone whose two zones differ. The
    browser here is deliberately a full day away from the account."""
    context = browser.new_context(timezone_id=BROWSER_TIME_ZONE)
    try:
        page = context.new_page()
        _login(page, live_server)
        assert (
            page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
            == BROWSER_TIME_ZONE
        )

        page.goto(f"{live_server.url}{reverse('games:add_session')}")
        hidden = page.locator(f"{START_FIELD} input[data-date-time-hidden]")
        expect(hidden).to_be_attached()

        page.locator(f"{START_FIELD} [data-date-picker-calendar-toggle]").click()
        page.locator(f"{START_FIELD} [data-date-range-now]").click()
        expect(hidden).not_to_have_value("")

        written = dt.datetime.fromisoformat(hidden.input_value()).replace(tzinfo=None)
        account_now = dt.datetime.now(ZoneInfo(ACCOUNT_TIME_ZONE)).replace(tzinfo=None)
        browser_now = dt.datetime.now(ZoneInfo(BROWSER_TIME_ZONE)).replace(tzinfo=None)

        assert abs(written - account_now) < dt.timedelta(minutes=2), (
            f"'Now' wrote {written}, but the account's wall clock in "
            f"{ACCOUNT_TIME_ZONE} is {account_now}. A value near {browser_now} "
            "means the browser's clock was used, so the stored instant is wrong."
        )
    finally:
        context.close()


def test_editing_a_session_without_touching_it_keeps_its_microseconds(
    authenticated_page, live_server
):
    """duration_calculated is a generated column over both timestamps, so an
    untouched edit that dropped sub-minute precision would shift the duration.
    The segments only go down to minutes; the residual rides along."""
    page, _user = authenticated_page
    game = Game.objects.create(name="Alpha Game")
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
    page, _user = authenticated_page
    game = Game.objects.create(name="Alpha Game")
    started = dt.datetime(2026, 3, 15, 13, 30, 41, 123456, tzinfo=dt.UTC)
    session = Session.objects.create(game=game, timestamp_start=started)

    page.goto(f"{live_server.url}{reverse('games:edit_session', args=[session.id])}")
    _fill_segments(page, START_FIELD, {"minute": "45"})
    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()

    session.refresh_from_db()
    assert session.timestamp_start == started.replace(minute=45)
