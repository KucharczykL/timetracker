"""The confirmation tells the truth.

The copy is what the user consents to. Assert it in the
browser, not only against the view.
"""

import uuid
from typing import TypedDict

import pytest
from django.db import transaction
from django.urls import reverse
from playwright.sync_api import Page, expect
from pydantic import ConfigDict, with_config

from games.events.append import lock_stream
from games.events.references import Reference, capture_reference
from games.events.vocabulary import EventSpec, EventTypeRegistry
from games.events.wiring import EventWiring
from games.models import Game


@with_config(ConfigDict(extra="forbid", strict=True))
class RowNamedPayload(TypedDict):
    row: Reference


ROW_NAMED = EventSpec(
    "library.row.named", aggregate_type="probe", payload=RowNamedPayload
)

#: This module's own vocabulary, never production's.
EVENT_TYPES = EventTypeRegistry()
EVENT_TYPES.register(ROW_NAMED)
WIRING = EventWiring(event_types=EVENT_TYPES)


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def name_in_an_event(library, instance) -> None:
    with transaction.atomic():
        lock_stream(library).append(
            [
                ROW_NAMED.new(
                    aggregate_id=uuid.uuid7(),
                    payload={"row": capture_reference(instance)},
                )
            ],
            actor=None,
            correlation_id=uuid.uuid7(),
            idempotency_key="e2e-names-the-game",
            wiring=WIRING,
        )


def test_deleting_an_unreferenced_game_promises_a_delete(
    authenticated_page: Page, live_server, e2e_library
):
    game = Game.objects.create(library=e2e_library, name="Forgettable")

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:delete_game', args=[game.pk])}")

    expect(page.get_by_text("This will permanently delete Forgettable")).to_be_visible()

    page.click('button:has-text("Delete")')
    page.wait_for_url(f"{live_server.url}{reverse('games:list_games')}**")
    assert not Game.objects.filter(pk=game.pk).exists()


def test_deleting_a_referenced_game_says_the_record_is_kept(
    authenticated_page: Page, live_server, e2e_library
):
    game = Game.objects.create(library=e2e_library, name="Remembered")
    name_in_an_event(e2e_library, game)

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:delete_game', args=[game.pk])}")

    expect(page.get_by_text("1 recorded event(s) reference Remembered")).to_be_visible()
    expect(page.get_by_text("kept out of sight rather than deleted")).to_be_visible()

    page.click('button:has-text("Delete")')
    page.wait_for_url(f"{live_server.url}{reverse('games:list_games')}**")
    expect(page.get_by_text("Remembered")).to_have_count(0)
    assert Game.objects.get(pk=game.pk).archived_at is not None
