"""The real playthrough list on a phone.

The identity cell states the least there: a run's own
name, and every other fact in the summary under it.
"""

import datetime as dt

import pytest
from django.urls import reverse
from playwright.sync_api import Page, ViewportSize, expect
from session_rows import tracked_run

from games.models import Game, Platform, Playthrough
from timetracker.temporal import TemporalValue

PHONE = ViewportSize(width=375, height=812)

STARTED_ON = dt.date(2026, 3, 5)


@pytest.fixture
def one_run(e2e_library) -> Playthrough:
    """One game, one started run."""
    platform = Platform.objects.create(
        library=e2e_library, name="PC", icon="pc", group="PC"
    )
    game = Game.objects.create(library=e2e_library, name="Tunic", platform=platform)
    run = tracked_run(e2e_library, game)
    Playthrough.objects.filter(pk=run.pk).update(
        start_recorded_at=dt.datetime(2026, 3, 5, tzinfo=dt.UTC),
        started=TemporalValue.from_day(STARTED_ON),
    )
    return run


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.set_viewport_size(PHONE)
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def test_the_summary_names_the_game_where_the_column_has_dropped(
    authenticated_page: Page, live_server, one_run
):
    """Below md every data column is gone but the acts."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_playthroughs')}")

    summary = page.locator("tbody th [data-row-summary]").first
    expect(summary).to_contain_text("Tunic")
    expect(summary).to_contain_text("since 2026-03-05")
    #: The condition, counted against the run's own day.
    expect(summary).to_contain_text("Dormant")
    #: The Game column itself has dropped.
    expect(page.locator("tbody td").first).to_be_hidden()
