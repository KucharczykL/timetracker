"""A person selects rows and acts on them, in a real browser."""

from datetime import date, timedelta

from django.urls import reverse
from playwright.sync_api import Page, expect
from session_rows import duration_only_row, tracked_run
from tracked_games import create_tracked_game

from games.commands.playthrough import ActStatement
from games.models import PlayerSession, Playthrough
from games.writes.playergame import new_correlation_id
from games.writes.playthrough import RunDraft, record_run
from timetracker.temporal import TemporalValue


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


def _select_rows(page: Page, *indexes: int) -> None:
    """Turn the mode on, and tick those rows."""
    page.get_by_role("button", name="Select rows").first.click()
    boxes = page.locator("tbody [data-selection-checkbox]")
    for index in indexes:
        boxes.nth(index).click()


def test_two_rows_are_removed_from_the_line_and_put_back(
    live_server, page: Page, e2e_user, e2e_library
):
    """The whole act, as a person walks it.

    The confirmation states the act's own columns, so what is pressed is
    what was read.
    """
    game = create_tracked_game(e2e_library, "Outer Wilds")
    run = tracked_run(e2e_library, game)
    for day in (5, 6, 7):
        duration_only_row(run, date(2026, 3, day), timedelta(hours=2))
    _login(page, live_server)

    listed = f"{live_server.url}{reverse('games:list_sessions')}"
    page.goto(listed)
    _select_rows(page, 0, 1)
    expect(page.locator("[data-selection-count]")).to_have_text("2 selected")
    page.get_by_role("button", name="Remove", exact=True).click()

    #: The act's preview: its three columns, and one row apiece.
    expect(page.get_by_role("heading", name="Remove these sessions")).to_be_visible()
    expect(page.locator("[data-bulk-sample-row]")).to_have_count(2)
    for heading in ("Game", "Day", "Duration"):
        expect(page.get_by_role("columnheader", name=heading)).to_be_visible()

    page.get_by_role("button", name="Remove", exact=True).click()

    #: Server-rendered, so the rows are committed by the time it shows.
    page.wait_for_url(f"{listed}**")
    expect(page.locator("tbody tr[data-selection-key]")).to_have_count(1)
    assert PlayerSession.objects.alive().count() == 1

    page.get_by_role("button", name="Undo").click()

    expect(page.locator("tbody tr[data-selection-key]")).to_have_count(3)
    assert PlayerSession.objects.alive().count() == 3


def test_a_refused_row_states_its_sentence_while_the_rest_are_removed(
    live_server, page: Page, e2e_user, e2e_library
):
    """A run its game holds alone is the command's refusal, one row.

    The batch goes on: the sibling is removed, and the sentence names
    the remedy rather than ending the act.
    """
    alone = create_tracked_game(e2e_library, "Celeste")
    tracked_run(e2e_library, alone)
    shared = create_tracked_game(e2e_library, "Outer Wilds")
    for day in (date(2026, 1, 2), date(2026, 4, 9)):
        record_run(
            e2e_user,
            shared,
            RunDraft(
                started=ActStatement(TemporalValue.from_day(day)),
                completed=ActStatement(None),
                note="",
            ),
            correlation_id=new_correlation_id(),
        )
    _login(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:list_playthroughs')}")
    #: Every run this library holds: one alone, two sharing a game.
    _select_rows(page, 0, 1, 2)
    page.get_by_role("button", name="Remove", exact=True).click()
    page.get_by_role("button", name="Remove", exact=True).click()

    expect(
        page.get_by_text("This is the only playthrough of that game")
    ).to_be_visible()
    #: One of each game stands: the sole run was refused, and of the
    #: two that shared a game one went and the other became the last.
    live = Playthrough.objects.filter(removed_at__isnull=True)
    assert live.filter(player_game__game=alone).count() == 1
    assert live.filter(player_game__game=shared).count() == 1
