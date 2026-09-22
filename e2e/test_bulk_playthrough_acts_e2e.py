"""A person records that runs were completed today."""

from django.urls import reverse
from playwright.sync_api import Page, expect
from session_rows import tracked_run
from tracked_games import create_tracked_game

from e2e.helpers import open_row_menu
from games.bulk_playthrough_acts import START_RUNS
from games.models import PlayerGame, PlayerGameStatus, Playthrough
from games.reads.calendar import calendar_today

COMPLETE = "Completed today"


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


def _two_tracked_runs(library) -> tuple[Playthrough, Playthrough]:
    return tuple(
        tracked_run(library, create_tracked_game(library, name))
        for name in ("Outer Wilds", "Tunic")
    )


def _select_rows(page: Page, *indexes: int) -> None:
    page.get_by_role("button", name="Select rows").first.click()
    boxes = page.locator("tbody [data-selection-checkbox]")
    for index in indexes:
        boxes.nth(index).click()


def _statused(game_name: str) -> PlayerGameStatus:
    return PlayerGameStatus(PlayerGame.objects.get(game__name=game_name).status)


def test_two_runs_are_completed_today_and_the_undo_takes_it_back(
    live_server, page: Page, e2e_user, e2e_library
):
    first, second = _two_tracked_runs(e2e_library)
    errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    _login(page, live_server)

    listed = f"{live_server.url}{reverse('games:list_playthroughs')}"
    page.goto(listed)
    _select_rows(page, 0, 1)
    page.get_by_role("button", name=COMPLETE).click()

    #: The act's preview, its day and the status it also records.
    expect(
        page.get_by_role(
            "heading", name="Record that these playthroughs were completed today"
        )
    ).to_be_visible()
    expect(page.locator("[data-bulk-sample-row]")).to_have_count(2)
    expect(page.get_by_text("Each game is marked Completed")).to_be_visible()
    expect(
        page.get_by_text(calendar_today(e2e_library).isoformat(), exact=False).first
    ).to_be_visible()
    page.get_by_role("button", name="Record", exact=True).click()

    page.wait_for_url(listed)
    for run in (first, second):
        run.refresh_from_db()
        assert run.completion_recorded_at is not None
        assert run.completed_upper == calendar_today(e2e_library)
    assert _statused("Outer Wilds") == PlayerGameStatus.COMPLETED
    assert _statused("Tunic") == PlayerGameStatus.COMPLETED

    page.get_by_role("button", name="Undo").click()

    #: Server-rendered: the write has landed.
    expect(page.get_by_role("cell", name="Outer Wilds", exact=True)).to_be_visible()
    for run in (first, second):
        run.refresh_from_db()
        assert run.completion_recorded_at is None
        assert run.completed is None
    assert _statused("Outer Wilds") == PlayerGameStatus.UNPLAYED
    assert errors == []


def test_a_row_menu_reaches_the_same_act(
    live_server, page: Page, e2e_user, e2e_library
):
    """One row, one act: the item posts the runner's own statement."""
    run, _ = _two_tracked_runs(e2e_library)
    _login(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:list_playthroughs')}")
    open_row_menu(page, f"run-menu-{run.pk}")
    #: The item is a form of its own, so the act it posts to names it;
    #: every other row holds one too, and only this menu's is shown.
    page.locator(f'form[action*="{START_RUNS.name}"] button[type="submit"]').locator(
        "visible=true"
    ).first.click()

    expect(
        page.get_by_role("heading", name="Record that this playthrough started today")
    ).to_be_visible()
    expect(page.locator("[data-bulk-sample-row]")).to_have_count(1)
    page.get_by_role("button", name="Record", exact=True).click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_playthroughs')}")
    run.refresh_from_db()
    assert run.started_lower == calendar_today(e2e_library)
    assert _statused("Outer Wilds") == PlayerGameStatus.PLAYED
