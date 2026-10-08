"""Bulk Edit moves sessions out of the bucket."""

import uuid
from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import Page, expect
from session_rows import duration_only_row, tracked_run
from tracked_games import create_tracked_game

from e2e.helpers import log_in
from games.commands.playersession import CreateSession, DurationOnlyTiming
from games.events.dispatch import dispatch
from games.models import PlayerGame, PlayerSession, Playthrough, PlaythroughKind
from games.reads.session_run_labels import IMPORTED_HISTORY_LABEL
from games.writes.playersession import move_session

ACT = "Edit…"


def _a_game_with_a_bucket(library, actor) -> tuple[Playthrough, Playthrough]:
    """One run beside a bucket holding two sessions.

    Recorded and then moved, the one way into a bucket:
    `CreateSession` refuses one outright, and the Undo
    reads the row's own stream for where it sat.
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
                implies_played=False,
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
    boxes = page.locator("tbody [data-selection-checkbox]")
    for index in indexes:
        boxes.nth(index).click()


def _bucket_label(page: Page):
    """The bucket's name where this width shows it.

    The run is named twice: the column, and the summary,
    which is `md:hidden` and so hidden at this width.
    """
    return page.get_by_text(IMPORTED_HISTORY_LABEL).locator("visible=true").first


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
    log_in(page, live_server)

    listed = f"{live_server.url}{reverse('games:list_sessions')}"
    page.goto(listed)
    expect(_bucket_label(page)).to_be_visible()
    _select_rows(page, 0, 1)
    page.get_by_role("button", name=ACT).click()

    expect(page.get_by_role("heading", name="Edit 2 sessions")).to_be_visible()
    expect(page.locator("[data-bulk-sample-row]")).to_have_count(2)
    expect(page.get_by_role("columnheader", name="Playthrough")).to_be_visible()

    picker = page.locator("search-select[name='choice-playthrough']")
    picker.locator("[data-search-select-search]").click()
    picker.get_by_role("option", name="Playthrough 1").click()
    page.get_by_role("button", name="Save", exact=True).click()

    page.wait_for_url(listed)
    assert PlayerSession.objects.filter(playthrough=run).count() == 2
    bucket.refresh_from_db()
    assert bucket.removed_at is not None

    page.get_by_role("button", name="Undo").click()

    #: Server-rendered: the write has landed.
    expect(_bucket_label(page)).to_be_visible()
    assert PlayerSession.objects.filter(playthrough=bucket).count() == 2
    bucket.refresh_from_db()
    assert bucket.removed_at is None
    assert errors == []


def test_sessions_at_two_games_keep_the_form_without_the_picker(
    live_server, page: Page, e2e_user, e2e_library
):
    """A playthrough belongs to one game; the rest still applies."""
    _a_game_with_a_bucket(e2e_library, e2e_user)
    other = create_tracked_game(e2e_library, "Celeste")
    duration_only_row(
        tracked_run(e2e_library, other), date(2026, 3, 7), timedelta(hours=2)
    )
    log_in(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    _select_rows(page, 0, 1, 2)
    page.get_by_role("button", name=ACT).click()

    expect(page.get_by_text("These sessions are at 2 games")).to_be_visible()
    expect(page.locator("search-select[name='choice-playthrough']")).to_have_count(0)
    expect(page.locator("search-select[name='choice-device']")).to_have_count(1)
