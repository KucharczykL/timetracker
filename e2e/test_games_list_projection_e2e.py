"""The games list under the inner join, in a real browser."""

from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from historical_playtime_rows import record_row
from playwright.sync_api import Page, expect
from session_rows import session_row, tracked_run

from games.models import Game, PlayerGame, PlayerGameStatus


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def list_url(live_server) -> str:
    return f"{live_server.url}{reverse('games:list_games')}"


@pytest.mark.django_db(transaction=True)
def test_a_tracked_game_is_listed(authenticated_page: Page, live_server, e2e_library):
    Game.objects.create(library=e2e_library, name="Outer Wilds")

    authenticated_page.goto(list_url(live_server))

    #: .first: the name is in the cell and again in its overflow popover.
    expect(authenticated_page.get_by_text("Outer Wilds").first).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_a_removed_game_is_not_listed(
    authenticated_page: Page, live_server, e2e_library
):
    game = Game.objects.create(library=e2e_library, name="Outer Wilds")
    Game.objects.filter(pk=game.pk).update(removed_at=timezone.now())

    authenticated_page.goto(list_url(live_server))

    expect(authenticated_page.get_by_text("Outer Wilds")).to_have_count(0)


@pytest.mark.django_db(transaction=True)
def test_the_status_a_selector_sets_survives_a_reload(
    authenticated_page: Page, live_server, e2e_library
):
    game = Game.objects.create(library=e2e_library, name="Outer Wilds")
    page = authenticated_page
    page.goto(list_url(live_server))

    #: The id names the panel; the trigger is its `Link` sibling.
    panel = page.locator(f"#game-{game.pk}-status")
    trigger = page.locator(f"#game-{game.pk}-statusLink")
    expect(trigger).to_be_attached()
    trigger.click()
    expect(panel).to_be_visible()
    with page.expect_response(
        lambda response: (
            "/status" in response.url and response.request.method == "PATCH"
        )
    ):
        panel.locator('[data-option][data-value="completed"]').click()

    #: The reload is the assertion. The trigger swaps its label
    #: optimistically, so reading it here would pass without a write.
    page.goto(list_url(live_server))
    expect(page.locator(f"#game-{game.pk}-statusLink [data-label]")).to_contain_text(
        "Completed"
    )

    row = PlayerGame.objects.get(library=e2e_library, game=game)
    assert row.status == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_the_playtime_column_adds_historical_records(
    authenticated_page: Page, live_server, e2e_library
):
    start = datetime(2022, 3, 1, 10, tzinfo=UTC)
    recorded = Game.objects.create(library=e2e_library, name="Outer Wilds")
    session_row(recorded, started_at=start, ended_at=start + timedelta(hours=1))
    record_row(
        [tracked_run(e2e_library, recorded)], duration=timedelta(hours=2), when=None
    )
    tracked_only = Game.objects.create(library=e2e_library, name="Tunic")
    session_row(tracked_only, started_at=start, ended_at=start + timedelta(hours=2))
    page = authenticated_page

    page.goto(f"{list_url(live_server)}?sort=-playtime")

    expect(page.locator(f"#duration-game-{recorded.pk}-playtime")).to_contain_text(
        "3 h 00 m"
    )
    expect(page.locator(f"#duration-game-{tracked_only.pk}-playtime")).to_contain_text(
        "2 h 00 m"
    )
    expect(page.locator("tbody tr").first).to_contain_text("Outer Wilds")
