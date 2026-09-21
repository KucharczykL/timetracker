"""A person moves sessions out of the bucket, in a real browser.

The act asks a question the others do not, so the pass is about the
picker: what it offers, and that the press carries the answer.
"""

import uuid
from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import Page, expect
from session_rows import duration_only_row, tracked_run
from tracked_games import create_tracked_game

from games.commands.playersession import CreateSession, DurationOnlyTiming
from games.events.dispatch import dispatch
from games.models import PlayerGame, PlayerSession, Playthrough, PlaythroughKind
from games.reads.session_run_labels import IMPORTED_HISTORY_LABEL
from games.writes.playersession import move_session

ACT = "Move to playthrough…"


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


def _a_game_with_a_bucket(library, actor) -> tuple[Playthrough, Playthrough]:
    """One ordinary run beside a bucket holding two sessions.

    Recorded and then moved, which is the one way into a bucket and
    what the legacy conversion did: a command refuses to record there,
    and the Undo reads the row's own stream for where it sat.
    """
    game = create_tracked_game(library, "Outer Wilds")
    run = tracked_run(library, game)
    bucket = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=library,
        player_game=PlayerGame.objects.get(library=library, game=game),
        kind=PlaythroughKind.IMPORTED_HISTORY,
        name=IMPORTED_HISTORY_LABEL,
        created_at=timezone.now(),
    )
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
        session = PlayerSession.objects.get(
            playthrough=run, stated_day=date(2026, 3, day)
        )
        move_session(actor, session, bucket.pk, correlation_id=uuid.uuid7())
    return run, bucket


def _select_rows(page: Page, *indexes: int) -> None:
    page.get_by_role("button", name="Select rows").first.click()
    boxes = page.locator("tbody [data-selection-checkbox]")
    for index in indexes:
        boxes.nth(index).click()


def test_two_sessions_leave_the_bucket_and_the_undo_puts_them_back(
    live_server, page: Page, e2e_user, e2e_library
):
    run, bucket = _a_game_with_a_bucket(e2e_library, e2e_user)
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
    expect(page.get_by_text(IMPORTED_HISTORY_LABEL).first).to_be_visible()
    _select_rows(page, 0, 1)
    page.get_by_role("button", name=ACT).click()

    #: The act's own preview, and the question the others do not ask.
    expect(
        page.get_by_role("heading", name="Move these sessions to a playthrough")
    ).to_be_visible()
    expect(page.locator("[data-bulk-sample-row]")).to_have_count(2)
    for heading in ("Playthrough", "Day", "Duration", "Device", "Note"):
        expect(page.get_by_role("columnheader", name=heading)).to_be_visible()

    picker = page.locator("search-select[name='choice']")
    picker.locator("[data-search-select-search]").click()
    picker.locator("[data-search-select-option]").first.click()
    page.get_by_role("button", name="Move", exact=True).click()

    page.wait_for_url(listed)
    assert PlayerSession.objects.filter(playthrough=run).count() == 2
    bucket.refresh_from_db()
    assert bucket.removed_at is not None

    page.get_by_role("button", name="Undo").click()

    #: Server-rendered: the label is back only once the write landed.
    expect(page.get_by_text(IMPORTED_HISTORY_LABEL).first).to_be_visible()
    assert PlayerSession.objects.filter(playthrough=bucket).count() == 2
    bucket.refresh_from_db()
    assert bucket.removed_at is None
    assert errors == []


def test_sessions_at_two_games_are_refused_before_the_question(
    live_server, page: Page, e2e_user, e2e_library
):
    """A playthrough belongs to one game, so the act asks about one."""
    _a_game_with_a_bucket(e2e_library, e2e_user)
    other = create_tracked_game(e2e_library, "Celeste")
    duration_only_row(
        tracked_run(e2e_library, other), date(2026, 3, 7), timedelta(hours=2)
    )
    _login(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    _select_rows(page, 0, 1, 2)
    page.get_by_role("button", name=ACT).click()

    expect(page.get_by_text("2 different games")).to_be_visible()
    expect(page.locator("search-select[name='choice']")).to_have_count(0)
