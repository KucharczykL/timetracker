"""A written-down session becomes a record, and comes back."""

from datetime import date, timedelta

from django.urls import reverse
from playwright.sync_api import Page, expect
from session_rows import duration_only_row, tracked_run
from tracked_games import create_tracked_game

from games.models import HistoricalPlaytime, PlayerSession


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


def test_a_written_down_session_becomes_a_record_and_comes_back(
    live_server, page: Page, e2e_user, e2e_library
):
    game = create_tracked_game(e2e_library, "Outer Wilds")
    run = tracked_run(e2e_library, game)
    session = duration_only_row(run, date(2026, 3, 5), timedelta(hours=9))
    errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    _login(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    page.get_by_role("link", name="Review estimates").first.click()
    expect(page.get_by_role("row")).to_have_count(2)

    page.get_by_title("Was an estimate").first.click()
    page.get_by_role("button", name="Submit", exact=True).click()

    expect(page.get_by_text("Session recorded as historical playtime.")).to_be_visible()
    session.refresh_from_db()
    assert session.removed_at is not None
    assert session.reclassified_into_id == HistoricalPlaytime.objects.get().pk

    page.get_by_role("button", name="Undo").click()

    expect(page.get_by_text("Session restored.")).to_be_visible()
    assert PlayerSession.objects.alive().count() == 1
    assert HistoricalPlaytime.objects.get().removed_at is not None
    #: The form's module scripts load; a dist module served as a
    #: classic script would be inert and say so here.
    assert errors == []
