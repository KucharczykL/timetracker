"""Removing a session offers Undo; Undo puts the row back."""

from datetime import UTC, datetime

from django.urls import reverse
from playwright.sync_api import Page, expect
from session_rows import session_row
from tracked_games import create_tracked_game


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


def test_undo_puts_a_removed_session_back(live_server, page: Page, e2e_library):
    game = create_tracked_game(e2e_library, "Undoable")
    row = session_row(game, started_at=datetime(2024, 6, 1, 12, tzinfo=UTC))
    _login(page, live_server)
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    #: The row, not the navbar's recent games, which name the game too.
    rows = page.locator("tbody tr")
    expect(rows).to_have_count(1)

    page.locator('a[href*="/session/"][href*="/remove"]').first.click()
    page.click('button:has-text("Remove")')

    expect(page.get_by_text("Session removed.")).to_be_visible()
    expect(rows).to_have_count(0)
    row.refresh_from_db()
    assert row.removed_at is not None

    page.get_by_role("button", name="Undo").click()

    #: Server-rendered first, then the row: the toast may lead the write.
    expect(page.get_by_text("Session restored.")).to_be_visible()
    expect(rows).to_have_count(1)
    row.refresh_from_db()
    assert row.removed_at is None
