"""Hiding the conversion review reloads without it."""

import uuid

import pytest
from django.db import transaction
from django.urls import reverse
from playwright.sync_api import Page, expect
from tracked_games import create_tracked_game

from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.commands.endpoint import ActStatement
from games.commands.libraryentry import RecordEntry
from games.conversion_review import ORIGIN, REVIEW_WORDS, Category
from games.events.dispatch import append_command
from games.models import UserLibrary


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def _rental(library: UserLibrary) -> None:
    game = create_tracked_game(library, "Tunic")
    graph = state_catalog_graph(
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
    with transaction.atomic():
        append_command(
            RecordEntry(
                release_id=graph.editions[0].releases[0].release.pk,
                access="rented",
                format="digital",
                note="",
                acquired=ActStatement(None, ""),
            ),
            actor=library.user,
            library=library,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
            source_metadata={"origin": ORIGIN, "review": [str(Category.RENTAL)]},
        )


def test_hiding_the_review_reloads_without_its_rows(
    authenticated_page: Page, live_server, e2e_library
):
    _rental(e2e_library)
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:library')}")
    label = REVIEW_WORDS[Category.RENTAL].label
    expect(page.get_by_text(label, exact=True)).to_be_visible()

    with page.expect_navigation():
        page.get_by_label("Hide this review").check()

    expect(page.get_by_text(label, exact=True)).to_have_count(0)
    expect(page.get_by_label("Hide this review")).to_be_checked()
