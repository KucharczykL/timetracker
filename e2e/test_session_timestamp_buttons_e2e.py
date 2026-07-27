"""Browser test for the session form's "Set to now" button (issue #535).

The submitted value is read back in the *account's* timezone
(`TimezoneActivationMiddleware` activates `DISPLAY_TIME_ZONE`, then
`from_current_timezone` attaches it), so writing the *browser's* wall clock
stores a wrong instant for anyone whose two zones differ. This drives a browser
whose zone is deliberately a full day away from the account's.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from playwright.sync_api import Browser, expect

from games.models import UserPreferences

ACCOUNT_TIME_ZONE = "Pacific/Kiritimati"  # UTC+14 year-round, no DST
BROWSER_TIME_ZONE = "Pacific/Honolulu"  # UTC-10 year-round — 24 hours apart


@pytest.fixture
def account_in_kiritimati(django_user_model) -> None:
    user = django_user_model.objects.create_user(
        username="tester", password="secret123"
    )
    UserPreferences.objects.create(user=user, display_time_zone=ACCOUNT_TIME_ZONE)


@pytest.mark.usefixtures("account_in_kiritimati")
def test_set_to_now_writes_the_account_wall_clock(browser: Browser, live_server):
    context = browser.new_context(timezone_id=BROWSER_TIME_ZONE)
    try:
        page = context.new_page()
        page.goto(f"{live_server.url}{reverse('login')}")
        page.fill('input[name="username"]', "tester")
        page.fill('input[name="password"]', "secret123")
        page.click('button:has-text("Login")')
        page.wait_for_url(f"{live_server.url}/tracker**")
        assert (
            page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
            == BROWSER_TIME_ZONE
        )

        page.goto(f"{live_server.url}{reverse('games:add_session')}")
        start = page.locator("#id_timestamp_start")
        expect(start).to_be_visible()
        page.evaluate("document.querySelector('#id_timestamp_start').value = ''")

        page.click('[data-target="timestamp_start"][data-type="now"]')
        expect(start).not_to_have_value("")

        written = dt.datetime.fromisoformat(start.input_value())
        account_now = dt.datetime.now(ZoneInfo(ACCOUNT_TIME_ZONE)).replace(tzinfo=None)
        browser_now = dt.datetime.now(ZoneInfo(BROWSER_TIME_ZONE)).replace(tzinfo=None)

        assert abs(written - account_now) < dt.timedelta(minutes=2), (
            f"'Set to now' wrote {written}, but the account's wall clock in "
            f"{ACCOUNT_TIME_ZONE} is {account_now}. A value near {browser_now} "
            "means the browser's clock was used, so the stored instant is wrong."
        )
    finally:
        context.close()
