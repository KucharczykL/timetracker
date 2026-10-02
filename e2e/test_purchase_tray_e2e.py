"""The Purchases tray: Edit, Remove, Undo."""

from decimal import Decimal

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect
from tracked_games import create_tracked_game

from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.commands.endpoint import ActStatement
from games.commands.libraryentry import EntryStatement
from games.commands.purchase import StatedPrice
from games.models import Purchase, Release, UserLibrary
from games.writes.playergame import new_correlation_id
from games.writes.purchase import PurchaseDraft, record_purchase


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def _release(library: UserLibrary, name: str) -> Release:
    game = create_tracked_game(library, name)
    state_catalog_graph(
        game=game,
        library=library,
        editions=[
            EditionState(
                key="edition",
                is_default=True,
                releases=(ReleaseState(key="release", is_default=True),),
            )
        ],
    )
    return Release.objects.get(edition__game=game)


@pytest.fixture
def purchases(e2e_user, e2e_library) -> None:
    for name in ("Tunic", "Hades"):
        record_purchase(
            e2e_user,
            PurchaseDraft(
                copy=EntryStatement(
                    release_id=_release(e2e_library, name).pk,
                    access="owned",
                    format="digital",
                    note="",
                    acquired=ActStatement(None, ""),
                ),
                kind="game",
                name="",
                price=StatedPrice(Decimal("19.99"), "EUR"),
                note="",
                purchased=ActStatement(None, ""),
            ),
            correlation_id=new_correlation_id(),
        )


def _amounts() -> list[Decimal | None]:
    return list(Purchase.objects.order_by("amount").values_list("amount", flat=True))


def _select_both(page: Page) -> None:
    boxes = page.locator("tbody [data-selection-checkbox]")
    boxes.nth(0).click()
    boxes.nth(1).click()


def test_two_purchases_are_made_free_and_the_undo_puts_their_prices_back(
    authenticated_page: Page, live_server, purchases
):
    page = authenticated_page
    listed = f"{live_server.url}{reverse('games:list_purchases')}"
    page.goto(listed)
    _select_both(page)
    page.get_by_role("button", name="Edit…").first.click()
    page.wait_for_load_state()

    expect(page.get_by_role("heading", name="Edit 2 purchases")).to_be_visible()
    expect(page.get_by_text("Keep: 19.99 EUR")).to_be_visible()
    page.get_by_role("radio", name="Free").check()
    page.get_by_role("button", name="Save", exact=True).click()

    page.wait_for_url(listed)
    assert _amounts() == [Decimal("0.00"), Decimal("0.00")]

    with page.expect_navigation():
        page.get_by_role("button", name="Undo").click()

    page.wait_for_url(listed)
    assert _amounts() == [Decimal("19.99"), Decimal("19.99")]


def test_two_purchases_are_removed_from_the_tray(
    authenticated_page: Page, live_server, purchases
):
    page = authenticated_page
    listed = f"{live_server.url}{reverse('games:list_purchases')}"
    page.goto(listed)
    _select_both(page)
    page.get_by_role("button", name="Remove").first.click()
    page.wait_for_load_state()

    expect(page.get_by_role("heading", name="Remove 2 purchases")).to_be_visible()
    page.get_by_role("button", name="Remove", exact=True).click()

    page.wait_for_url(listed)
    assert not Purchase.objects.filter(removed_at__isnull=True).exists()
