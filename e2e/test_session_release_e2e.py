"""A session names its Release, end to end."""

from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect
from tracked_games import create_tracked_game

from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.commands.endpoint import ActStatement
from games.commands.libraryentry import EntryStatement
from games.commands.playersession import TimedTiming
from games.models import Platform, PlayerSession, Playthrough, Release
from games.reads.calendar import calendar_day_zone
from games.writes.libraryentry import record_entry
from games.writes.playergame import new_correlation_id
from games.writes.playersession import SessionDraft, record_session


def _held_game(user, library, name: str, platforms: list[Platform]) -> Release:
    """A tracked game whose first platform's Release a copy holds."""
    game = create_tracked_game(library, name)
    state_catalog_graph(
        game=game,
        library=library,
        editions=[
            EditionState(
                key="edition",
                is_default=True,
                releases=tuple(
                    ReleaseState(
                        key=f"release-{index}",
                        platform=platform,
                        is_default=index == 0,
                    )
                    for index, platform in enumerate(platforms)
                ),
            )
        ],
    )
    held = Release.objects.get(edition__game=game, platform=platforms[0])
    record_entry(
        user,
        EntryStatement(
            release_id=held.pk,
            access="owned",
            format="digital",
            note="",
            acquired=ActStatement(None, ""),
        ),
        correlation_id=new_correlation_id(),
    )
    return held


@pytest.fixture
def platforms() -> list[Platform]:
    return [
        Platform.objects.create(name=name, group="Consoles")
        for name in ("PS5", "Xbox", "Switch")
    ]


@pytest.fixture
def session(e2e_user, e2e_library, platforms) -> PlayerSession:
    held = _held_game(e2e_user, e2e_library, "Tunic", platforms[:2])
    game = held.edition.game
    started = datetime(2026, 1, 5, 12, tzinfo=UTC)
    session_id = record_session(
        e2e_user,
        SessionDraft(
            playthrough_id=Playthrough.objects.get(player_game__game=game).pk,
            timing=TimedTiming(
                started_at=started,
                ended_at=started + timedelta(hours=1),
                day_zone=calendar_day_zone(e2e_library).key,
            ),
            device_id=None,
            note="",
            emulated=False,
            release_id=None,
        ),
        correlation_id=new_correlation_id(),
        implies_played=False,
    )
    return PlayerSession.objects.get(pk=session_id)


def test_the_picker_offers_the_held_release_and_the_edit_states_it(
    authenticated_page: Page, live_server, session
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:edit_session', args=[session.pk])}")

    picker = page.locator('search-select[name="release"]')
    picker.locator("[data-search-select-search]").click()
    options = picker.locator("[data-search-select-options] [data-value]")
    expect(options.filter(has_text="PS5")).to_have_count(1)
    expect(options.filter(has_text="Xbox")).to_have_count(0)
    options.filter(has_text="PS5").click()
    page.get_by_role("button", name="Submit", exact=True).click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_sessions')}**")
    session.refresh_from_db()
    assert session.release is not None
    assert session.release.platform is not None
    assert session.release.platform.name == "PS5"


def test_the_picker_searches_again_when_the_game_changes(
    authenticated_page: Page, live_server, session, e2e_user, e2e_library, platforms
):
    _held_game(e2e_user, e2e_library, "Celeste", platforms[2:])
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:edit_session', args=[session.pk])}")

    game_picker = page.locator('search-select[name="game"]')
    game_picker.locator("[data-search-select-search]").fill("Celeste")
    game_picker.locator("[data-search-select-options] [data-value]").filter(
        has_text="Celeste"
    ).first.click()
    picker = page.locator('search-select[name="release"]')
    picker.locator("[data-search-select-search]").click()

    options = picker.locator("[data-search-select-options] [data-value]")
    expect(options.filter(has_text="Switch")).to_have_count(1)
    expect(options.filter(has_text="PS5")).to_have_count(0)
