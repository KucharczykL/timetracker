"""Adding an edition and a release from the game page, in a browser."""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Edition, Game, Release


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    _login(page, live_server)
    return page


def test_a_person_adds_an_edition_from_the_game_page(
    authenticated_page: Page, live_server, e2e_library
):
    game = Game.objects.create(library=e2e_library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    page = authenticated_page

    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    page.get_by_role("link", name="Add edition").click()
    page.fill("#id_name", "Gold")
    page.get_by_role("button", name="Submit").click()

    #: The heading is server-rendered, thus the write has committed.
    expect(page.locator("text=Gold")).to_be_visible()
    assert Edition.objects.filter(game=game, name="Gold").exists()


def test_the_release_form_hosts_a_working_temporal_field(
    authenticated_page: Page, live_server, e2e_library
):
    game = Game.objects.create(library=e2e_library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    page = authenticated_page

    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    page.get_by_role("link", name="Add release").click()
    #: The element hides the number inputs and shows the segments. If
    #: the module never loaded, this selector never appears.
    page.wait_for_selector("[data-temporal-segments='start']:not([hidden])")
    page.click("[data-date-part='year'][data-date-side='start']")
    page.keyboard.type("1984")
    page.get_by_role("button", name="Submit").click()

    expect(page.locator("text=1984")).to_be_visible()
    release = Release.objects.get(edition=edition)
    assert release.release_date is not None
    assert release.release_date.year == 1984
