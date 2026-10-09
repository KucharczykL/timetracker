"""One device, emulated or note on two sessions, then undone."""

import uuid
from datetime import date, timedelta

from devices import create_device
from django.urls import reverse
from playwright.sync_api import Page, expect
from session_rows import tracked_run
from tracked_games import create_tracked_game

from e2e.helpers import log_in
from games.commands.playersession import CreateSession, DurationOnlyTiming
from games.events.dispatch import dispatch
from games.models import PlayerSession

ACT = "Edit…"


def _two_sessions(library, actor, device=None) -> list[PlayerSession]:
    """Recorded by command: the Undo reads events."""
    run = tracked_run(library, create_tracked_game(library, "Outer Wilds"))
    for day in (5, 6):
        dispatch(
            CreateSession(
                playthrough_id=run.pk,
                timing=DurationOnlyTiming(
                    day=date(2026, 3, day), duration=timedelta(hours=2)
                ),
                device_id=None if device is None else device.pk,
                implies_played=False,
            ),
            actor=actor,
            library=library,
            idempotency_key=str(uuid.uuid7()),
        )
    return list(PlayerSession.objects.filter(playthrough=run))


def _console_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    return errors


def _edit_both(page: Page, live_server) -> str:
    """Logged in, both rows selected, Edit… pressed."""
    log_in(page, live_server)
    listed = f"{live_server.url}{reverse('games:list_sessions')}"
    page.goto(listed)
    boxes = page.locator("tbody [data-selection-checkbox]")
    boxes.nth(0).click()
    boxes.nth(1).click()
    page.get_by_role("button", name=ACT).click()
    return listed


def test_two_sessions_take_one_device_and_the_undo_takes_it_back(
    live_server, page: Page, e2e_user, e2e_library
):
    sessions = _two_sessions(e2e_library, e2e_user)
    deck = create_device(library=e2e_library, name="Steam Deck")
    errors = _console_errors(page)
    listed = _edit_both(page, live_server)

    expect(page.get_by_role("heading", name="Edit 2 sessions")).to_be_visible()
    expect(page.locator("[data-bulk-sample-row]")).to_have_count(2)
    for heading in ("Game", "Day", "Duration", "Device", "Emulated", "Note"):
        expect(page.get_by_role("columnheader", name=heading)).to_be_visible()

    picker = page.locator("search-select[name='choice-device']")
    picker.locator("[data-search-select-search]").click()
    picker.get_by_role("option", name="Steam Deck").click()
    page.get_by_role("button", name="Save", exact=True).click()

    page.wait_for_url(listed)
    for session in sessions:
        session.refresh_from_db()
        assert session.device_id == deck.pk

    with page.expect_navigation():
        page.get_by_role("button", name="Undo").click()

    #: The redirect follows the Undo's commit.
    page.wait_for_url(listed)
    for session in sessions:
        session.refresh_from_db()
        assert session.device_id is None
    assert errors == []


def test_no_device_and_emulated_are_stated_for_both_sessions(
    live_server, page: Page, e2e_user, e2e_library
):
    deck = create_device(library=e2e_library, name="Steam Deck")
    sessions = _two_sessions(e2e_library, e2e_user, device=deck)
    errors = _console_errors(page)
    listed = _edit_both(page, live_server)

    device = page.locator("search-select[name='choice-device']")
    expect(device.locator("[data-search-select-search]")).to_have_attribute(
        "placeholder", "Keep: Steam Deck"
    )
    toggle = page.get_by_role("button", name="No device")
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    expect(device.locator("[data-search-select-search]")).to_be_disabled()

    page.get_by_role("checkbox", name="Emulated", exact=True).check()
    page.get_by_role("button", name="Save", exact=True).click()

    page.wait_for_url(listed)
    for session in sessions:
        session.refresh_from_db()
        assert session.device_id is None
        assert session.emulated is True
    assert errors == []
