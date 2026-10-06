"""A background batch, followed by its toast.

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
    # A first tick shows the line that offers the wider scope.
    page.locator("tbody [data-selection-checkbox]").first.click()
    page.get_by_role("button", name=f"Select all {count} matching").click()
    return listed


def test_a_batch_runs_every_chunk_and_says_so(
    live_server, page: Page, e2e_user, e2e_library, monkeypatch
):
    """Three rows, one a chunk, and one press."""
    monkeypatch.setattr("games.bulk_jobs.CHUNK_BUDGET", timedelta(0))
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

    #: Server-rendered after the chunks ran inline.
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


def test_a_held_batch_can_be_stopped_and_ends_on_the_next_load(
    live_server, page: Page, e2e_user, e2e_library, monkeypatch, held_batches
):
    """Stop, a closed page, then the end's Undo."""
    monkeypatch.setattr("games.bulk_jobs.CHUNK_BUDGET", timedelta(0))
    _long_sessions(e2e_library, (5, 6, 7))
    _login(page, live_server)

    listed = _state_the_whole_review(page, live_server, 3)
    page.get_by_role("button", name=ACT).click()
    page.get_by_role("button", name=ACT).click()
    expect(page.get_by_text("waiting to start.")).to_be_visible()
    held_batches.run_one()

    page.get_by_role("button", name="Stop").click()
    page.wait_for_url(listed)
    expect(page.get_by_text("stopping.")).to_be_visible()
    page.goto(f"{live_server.url}/tracker/library")
    held_batches.run_all()
    page.goto(listed)

    expect(page.get_by_text("stopped. 1 of 3 done, 2 not reached.")).to_be_visible()
    expect(page.get_by_role("button", name="Undo")).to_be_visible()
    assert HistoricalPlaytime.objects.alive().count() == 1


def test_a_page_refreshes_its_batch_while_it_runs(
    live_server, page: Page, e2e_user, e2e_library, held_batches
):
    """The poll replaces the toast in place."""
    _long_sessions(e2e_library, (5, 6))
    _login(page, live_server)

    _state_the_whole_review(page, live_server, 2)
    page.get_by_role("button", name=ACT).click()
    page.get_by_role("button", name=ACT).click()
    expect(page.get_by_text("waiting to start.")).to_be_visible()

    held_batches.run_all()

    expect(page.get_by_text("2 of 2 done.")).to_be_visible()
    expect(page.get_by_text("waiting to start.")).to_have_count(0)


def test_an_undo_inside_a_dialog_shows_its_batch_at_once(
    live_server, page: Page, e2e_user, e2e_library, held_batches
):
    """Its toast shows before the dialog closes."""
    _long_sessions(e2e_library, (5, 6))
    _login(page, live_server)

    _state_the_whole_review(page, live_server, 2)
    page.get_by_role("button", name=ACT).click()
    page.get_by_role("button", name=ACT).click()
    expect(page.get_by_text("waiting to start.")).to_be_visible()
    held_batches.run_all()
    expect(page.get_by_text("2 of 2 done.")).to_be_visible()

    page.evaluate(
        """(href) => {
            window.notReloaded = true;
            const link = document.createElement('a');
            link.href = href;
            link.textContent = 'Add a device';
            link.setAttribute('data-form-dialog', '');
            document.getElementById('main-container').prepend(link);
        }""",
        reverse("games:add_device"),
    )
    page.get_by_role("link", name="Add a device").click()
    dialog = page.locator("dialog[data-modal][open]")
    region = dialog.get_by_role("region", name="Notifications")
    region.get_by_role("button", name="Undo").click()

    expect(region.get_by_text("waiting to start.")).to_be_visible()
    expect(region.get_by_role("button", name="Stop")).to_be_visible()
    expect(region.get_by_role("button", name="Undo")).to_have_count(0)
    expect(dialog).to_be_visible()
    assert page.evaluate("window.notReloaded === true")
