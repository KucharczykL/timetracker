"""A batch walks its own chunks, with nobody pressing Continue.

The act is offered by the selection line, so the pass starts where a
person starts: the session list, narrowed to the review.
"""

from datetime import date, timedelta

from django.urls import reverse
from playwright.sync_api import Page, expect
from session_rows import duration_only_row, tracked_run
from tracked_games import create_tracked_game

from games.models import HistoricalPlaytime, PlayerSession
from games.views.session_reclassification import review_url

ACT = "Record as historical playtime"


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


def _long_sessions(library, days: tuple[int, ...]) -> None:
    game = create_tracked_game(library, "Outer Wilds")
    run = tracked_run(library, game)
    for day in days:
        duration_only_row(run, date(2026, 3, day), timedelta(hours=9))


def _state_the_whole_review(page: Page, live_server, count: int) -> str:
    """Stand on the review, and name every row it holds.

    The wider statement, not the keys: it is what a person presses when
    the list says how many match.
    """
    listed = f"{live_server.url}{review_url()}"
    page.goto(listed)
    page.get_by_role("button", name="Select rows").first.click()
    page.get_by_role("button", name=f"Select all {count} matching").click()
    return listed


def test_a_batch_carries_itself_from_one_chunk_to_the_next(
    live_server, page: Page, e2e_user, e2e_library, monkeypatch
):
    """Three rows, one a chunk, and one press.

    The budget is nothing, so each request acts on a single row and the
    two that follow are the element's doing. Stop is not pressed here:
    the element posts as soon as it connects, so which of the two wins a
    real race is a race. That Stop keeps the element quiet is a vitest,
    and that the route ends a batch is `tests/test_bulk_runner.py`.
    """
    monkeypatch.setattr("games.views.bulk.CHUNK_BUDGET", timedelta(0))
    _long_sessions(e2e_library, (5, 6, 7))
    errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    _login(page, live_server)

    listed = _state_the_whole_review(page, live_server, 3)
    page.get_by_role("button", name=ACT).click()
    page.get_by_role("button", name=ACT).click()

    #: Server-rendered, and the last thing the batch does, so the rows
    #: are committed by the time it shows.
    expect(page.get_by_text("3 of 3 done.")).to_be_visible()
    page.wait_for_url(listed)
    assert PlayerSession.objects.alive().count() == 0
    assert HistoricalPlaytime.objects.alive().count() == 3
    assert errors == []


def test_the_batchs_toast_offers_an_undo_that_puts_every_session_back(
    live_server, page: Page, e2e_user, e2e_library
):
    """The press the act's words promise."""
    _long_sessions(e2e_library, (5, 6))
    _login(page, live_server)

    _state_the_whole_review(page, live_server, 2)
    page.get_by_role("button", name=ACT).click()
    page.get_by_role("button", name=ACT).click()
    expect(page.get_by_text("2 of 2 done.")).to_be_visible()

    page.get_by_role("button", name="Undo").click()

    #: The review lists the two again, which only a committed undo
    #: makes it say. A toast would say the same before the write lands.
    expect(page.locator("tbody tr[data-selection-key]")).to_have_count(2)
    assert PlayerSession.objects.alive().count() == 2
    assert HistoricalPlaytime.objects.alive().count() == 0
