"""One device on two sessions, then undone."""

import uuid
from datetime import date, timedelta

from devices import create_device
from django.urls import reverse
from playwright.sync_api import Page, expect
from session_rows import tracked_run
from tracked_games import create_tracked_game

from games.commands.playersession import CreateSession, DurationOnlyTiming
from games.events.dispatch import dispatch
from games.models import PlayerSession

ACT = "Edit…"


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


def _two_sessions(library, actor) -> list[PlayerSession]:
    """Recorded by command: the Undo reads events."""
    run = tracked_run(library, create_tracked_game(library, "Outer Wilds"))
    for day in (5, 6):
        dispatch(
            CreateSession(
                playthrough_id=run.pk,
                timing=DurationOnlyTiming(
                    day=date(2026, 3, day), duration=timedelta(hours=2)
                ),
            ),
            actor=actor,
            library=library,
            idempotency_key=str(uuid.uuid7()),
        )
    return list(PlayerSession.objects.filter(playthrough=run))


def test_two_sessions_take_one_device_and_the_undo_takes_it_back(
    live_server, page: Page, e2e_user, e2e_library
):
    sessions = _two_sessions(e2e_library, e2e_user)
    deck = create_device(library=e2e_library, name="Steam Deck")
    errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    _login(page, live_server)

    listed = f"{live_server.url}{reverse('games:list_sessions')}"
    page.goto(listed)
    page.get_by_role("button", name="Select rows").first.click()
    boxes = page.locator("tbody [data-selection-checkbox]")
    boxes.nth(0).click()
    boxes.nth(1).click()
    page.get_by_role("button", name=ACT).click()

    expect(page.get_by_role("heading", name="Edit these sessions")).to_be_visible()
    expect(page.locator("[data-bulk-sample-row]")).to_have_count(2)
    for heading in ("Game", "Day", "Duration", "Device", "Emulated"):
        expect(page.get_by_role("columnheader", name=heading)).to_be_visible()

    picker = page.locator("search-select[name='choice-device']")
    picker.locator("[data-search-select-search]").click()
    picker.locator("[data-search-select-option]", has_text="Steam Deck").click()
    page.get_by_role("button", name="Save", exact=True).click()

    page.wait_for_url(listed)
    for session in sessions:
        session.refresh_from_db()
        assert session.device_id == deck.pk

    page.get_by_role("button", name="Undo").click()

    #: No Undo button: the Undo landed.
    expect(page.get_by_role("button", name="Undo")).to_have_count(0)
    for session in sessions:
        session.refresh_from_db()
        assert session.device_id is None
    assert errors == []
