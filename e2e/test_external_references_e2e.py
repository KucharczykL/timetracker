"""A reference, typed and followed in Chromium."""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.external_references import KEY_TAKEN, state_external_references
from games.models import ExternalReference, Game

pytestmark = pytest.mark.django_db(transaction=True)

#: Log out is a submit button too.
SUBMIT = "#add-form button[type=submit]"


@pytest.fixture
def signed_in(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def saved(page: Page, live_server) -> None:
    """Submit, and wait for the redirect."""
    page.click(SUBMIT)
    page.wait_for_url(f"{live_server.url}{reverse('games:list_games')}**")


def live_key(game: Game) -> str | None:
    return (
        ExternalReference.objects.filter(
            provider="wikidata",
            entity_kind="game",
            game_id=game.pk,
            removed_at__isnull=True,
        )
        .values_list("provider_key", flat=True)
        .first()
    )


def test_add_game_states_a_reference_and_detail_follows_it(
    signed_in, live_server, e2e_library
):
    page = signed_in
    page.goto(f"{live_server.url}{reverse('games:add_game')}")

    page.fill("input[name='name']", "Elite")
    page.fill("input[name='reference_wikidata']", "q123")
    saved(page, live_server)

    written = Game.objects.get(library=e2e_library, name="Elite")
    assert live_key(written) == "Q123"

    page.goto(f"{live_server.url}{written.get_absolute_url()}")
    link = page.get_by_role("link", name="Wikidata Q123")
    expect(link).to_have_attribute("href", "https://www.wikidata.org/wiki/Q123")


def test_editing_the_box_changes_the_key_then_lets_go_of_it(
    signed_in, live_server, e2e_library
):
    page = signed_in
    game = Game.objects.create(library=e2e_library, name="Elite")
    state_external_references(
        target=game, library=e2e_library, keys={"wikidata": "Q123"}
    )
    edit = f"{live_server.url}{reverse('games:edit_game', args=[game.pk])}"

    page.goto(edit)
    box = page.locator("input[name='reference_wikidata']")
    expect(box).to_have_value("Q123")
    box.fill("Q124")
    saved(page, live_server)

    assert live_key(game) == "Q124"

    page.goto(edit)
    page.locator("input[name='reference_wikidata']").fill("")
    saved(page, live_server)

    assert live_key(game) is None
    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    expect(page.get_by_role("link", name="Wikidata Q124")).to_have_count(0)


def test_a_taken_key_answers_beside_the_box_a_person_typed_into(
    signed_in, live_server, e2e_library
):
    """The refusal comes back with the value."""
    page = signed_in
    held = Game.objects.create(library=e2e_library, name="Held")
    state_external_references(
        target=held, library=e2e_library, keys={"wikidata": "Q123"}
    )
    page.goto(f"{live_server.url}{reverse('games:add_game')}")

    page.fill("input[name='name']", "Elite")
    page.fill("input[name='reference_wikidata']", "Q123")
    page.click(SUBMIT)

    expect(page.get_by_text(KEY_TAKEN)).to_be_visible()
    expect(page.locator("input[name='reference_wikidata']")).to_have_value("Q123")
    assert not Game.objects.filter(library=e2e_library, name="Elite").exists()
