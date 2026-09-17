"""Historical playtime is recorded, restated, removed and restored from a game."""

from django.urls import reverse
from playwright.sync_api import Page, expect
from stated_runs import another_run
from tracked_games import create_tracked_game

from games.models import HistoricalPlaytime


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


def test_a_record_goes_through_every_act_from_game_detail(
    live_server, page: Page, e2e_user, e2e_library
):
    game = create_tracked_game(e2e_library, "Outer Wilds")
    another_run(e2e_user, game)
    _login(page, live_server)
    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    section = page.locator("#historical-playtime-container")
    rows = section.locator("tbody tr")
    expect(section.get_by_text("No historical playtime.")).to_be_visible()

    section.get_by_role("link", name="Add").click()
    page.get_by_label("Playthrough 1").check()
    page.get_by_label("Playthrough 2").check()
    page.fill('input[name="duration_hours"]', "100")
    page.fill('input[name="duration_minutes"]', "0")
    page.select_option('select[name="when-kind"]', "date")
    page.wait_for_selector("[data-temporal-segments='start']:not([hidden])")
    page.click("[data-date-part='year'][data-date-side='start']")
    page.keyboard.type("2005")
    page.get_by_label("Estimated").check()
    page.get_by_role("button", name="Submit", exact=True).click()

    expect(page.get_by_text("Historical playtime recorded.")).to_be_visible()
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Playthrough 1, Playthrough 2")
    expect(rows.first).to_contain_text("2005")

    rows.first.locator('a[href*="/edit"]').click()
    page.get_by_label("Playthrough 2").uncheck()
    page.get_by_role("button", name="Submit", exact=True).click()

    expect(page.get_by_text("Historical playtime saved.")).to_be_visible()
    expect(rows.first).not_to_contain_text("Playthrough 2")
    expect(rows.first).to_contain_text("Playthrough 1")
    assert HistoricalPlaytime.objects.get().runs.count() == 1

    rows.first.locator('a[href*="/remove"]').click()
    page.click('button:has-text("Remove")')

    expect(page.get_by_text("Historical playtime removed.")).to_be_visible()
    expect(rows).to_have_count(0)
    assert HistoricalPlaytime.objects.get().removed_at is not None

    page.get_by_role("button", name="Undo").click()

    expect(page.get_by_text("Historical playtime restored.")).to_be_visible()
    expect(rows).to_have_count(1)
    assert HistoricalPlaytime.objects.get().removed_at is None
