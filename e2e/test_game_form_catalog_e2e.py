"""The whole catalog graph, written from the Game form in a real browser.

One page owns Game, Edition and Release, and one Submit states all
three. The rows a person adds are clones of a server-rendered template,
so nothing here is proven by the unit suite: only a browser runs
`<catalog-editor>` and `<temporal-field>`.

A UI assertion is not a database assertion. The choice card marks
itself on click, before anything is posted, so every ORM read below
waits for the page the redirect lands on first.
"""

import pytest
from django.urls import reverse
from playwright.sync_api import Locator, Page, expect

from games.catalog_compat import mirror_legacy_columns
from games.catalog_form import DUPLICATE_RELEASE_IN_FORM
from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.models import Edition, Game, Platform, Release
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def signed_in(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.fixture
def amiga(e2e_library) -> Platform:
    return Platform.objects.create(library=e2e_library, name="Amiga")


@pytest.fixture
def dos(e2e_library) -> Platform:
    return Platform.objects.create(library=e2e_library, name="DOS")


def state_default_graph(game: Game, library, *, platform=None, release_date=None):
    """One Game as the app leaves it: one default Edition and Release.

    Stated here rather than pulled from `tests/conftest.py`, which is
    not on this package's path.
    """
    game.save()
    return state_catalog_graph(
        game=game,
        library=library,
        editions=[
            EditionState(
                key="edition-0",
                is_default=True,
                releases=(
                    ReleaseState(
                        key="edition-0-release-0",
                        platform=platform,
                        release_date=release_date,
                        is_default=True,
                    ),
                ),
            )
        ],
    )


@pytest.fixture
def game(e2e_library, amiga) -> Game:
    """One Game as the app leaves it: a default graph, columns mirrored."""
    written = state_default_graph(
        Game(library=e2e_library, name="Elite"),
        e2e_library,
        platform=amiga,
        release_date=TemporalValue.from_year(1984),
    )
    mirror_legacy_columns(written.game)
    return written.game


def default_edition(game: Game) -> Edition:
    return Edition.objects.get(game=game, is_default=True)


def live_releases(edition: Edition) -> list[Release]:
    return list(edition.releases.alive().order_by("pk"))


def _upgraded(page: Page) -> None:
    """Wait for the elements that draw a row."""
    page.wait_for_function("() => customElements.get('catalog-editor') !== undefined")
    page.wait_for_selector(
        "[data-catalog-release='0'] [data-temporal-segments='start']:not([hidden])"
    )


def open_form(page: Page, live_server, game: Game) -> None:
    """Edit Game, once the elements that draw a row have upgraded."""
    page.goto(f"{live_server.url}{reverse('games:edit_game', args=[game.pk])}")
    _upgraded(page)


def open_add_form(page: Page, live_server) -> None:
    """Add Game, which hosts the very same area."""
    page.goto(f"{live_server.url}{reverse('games:add_game')}")
    _upgraded(page)


def release_card(page: Page, edition: int, release: int) -> Locator:
    return page.locator(
        f"[data-catalog-edition='{edition}'] [data-catalog-release='{release}']"
    )


def choose_platform(card: Locator, name: str) -> None:
    card.locator("select[name$='-platform']").select_option(label=name)


def type_year(card: Locator, year: str) -> None:
    """The segmented year of one row's release date."""
    segments = card.locator("[data-temporal-segments='start']")
    expect(segments).to_be_visible()
    card.locator("[data-date-part='year'][data-date-side='start']").click()
    card.page.keyboard.type(year)


#: The navbar's Log out is a submit button too, thus the form's own.
SUBMIT = "#add-form button[type=submit]"


def saved(page: Page, live_server) -> None:
    """Press Submit and wait for the page the write redirects to."""
    page.click(SUBMIT)
    page.wait_for_url(f"{live_server.url}{reverse('games:list_games')}**")


def test_a_cloned_row_adds_a_release(signed_in, live_server, game, amiga, dos):
    """One more row, and the mark stays where it was."""
    page = signed_in
    open_form(page, live_server, game)

    page.click("[data-catalog-edition='0'] [data-catalog-add='release']")
    added = release_card(page, 0, 1)
    choose_platform(added, "DOS")
    type_year(added, "1988")
    saved(page, live_server)

    releases = live_releases(default_edition(game))
    assert [release.platform for release in releases] == [amiga, dos]
    assert [release.release_date.serialize() for release in releases] == [
        "1984",
        "1988",
    ]
    game.refresh_from_db()
    assert game.platform == amiga


def test_the_mark_moves_to_the_row_a_person_chose(
    signed_in, live_server, e2e_library, game, dos
):
    """The radio says which release the games list draws."""
    Release.objects.create(
        edition=default_edition(game),
        platform=dos,
        release_date=TemporalValue.from_year(1988),
    )
    page = signed_in
    open_form(page, live_server, game)

    release_card(page, 0, 1).locator("input[name='in_library']").check()
    saved(page, live_server)

    releases = live_releases(default_edition(game))
    assert [release.is_default for release in releases] == [False, True]
    game.refresh_from_db()
    assert game.platform == dos


def test_the_bin_takes_one_release_and_leaves_the_other(
    signed_in, live_server, e2e_library, game, amiga, dos
):
    """A removed row stays in the form and is stamped on submit."""
    going = Release.objects.create(
        edition=default_edition(game),
        platform=dos,
        release_date=TemporalValue.from_year(1988),
    )
    page = signed_in
    open_form(page, live_server, game)

    release_card(page, 0, 1).locator("[data-catalog-remove]").click()
    saved(page, live_server)

    going.refresh_from_db()
    assert going.removed_at is not None
    releases = live_releases(default_edition(game))
    assert [release.platform for release in releases] == [amiga]
    assert releases[0].is_default


def test_binning_a_release_and_re_adding_its_pair_keeps_the_new_row(
    signed_in, live_server, game, amiga
):
    """One submit, one statement: the re-add is not eaten by the removal."""
    page = signed_in
    open_form(page, live_server, game)
    old = live_releases(default_edition(game))[0]

    release_card(page, 0, 0).locator("[data-catalog-remove]").click()
    page.click("[data-catalog-edition='0'] [data-catalog-add='release']")
    added = release_card(page, 0, 1)
    choose_platform(added, "Amiga")
    type_year(added, "1984")
    added.locator("input[name='in_library']").check()
    saved(page, live_server)

    old.refresh_from_db()
    assert old.removed_at is not None
    releases = live_releases(default_edition(game))
    assert [release.platform for release in releases] == [amiga]
    assert releases[0].pk != old.pk
    assert releases[0].is_default


def test_a_cloned_block_adds_an_edition(signed_in, live_server, game, amiga, dos):
    """A second Edition, named, and the default did not move."""
    page = signed_in
    open_form(page, live_server, game)

    page.click("[data-catalog-add='edition']")
    added = page.locator("[data-catalog-edition='1']")
    added.locator("input[name='edition-1-name']").fill("Gold")
    choose_platform(release_card(page, 1, 0), "DOS")
    saved(page, live_server)

    editions = list(Edition.objects.alive().filter(game=game).order_by("pk"))
    assert [edition.name for edition in editions] == ["", "Gold"]
    assert [edition.is_default for edition in editions] == [True, False]
    game.refresh_from_db()
    assert game.platform == amiga


def test_a_refused_release_reads_inside_its_own_row(
    signed_in, live_server, e2e_library, game, amiga, dos
):
    """Two alike say nothing apart, and the row says so."""
    standing = Release.objects.create(
        edition=default_edition(game),
        platform=dos,
        release_date=TemporalValue.from_year(1984),
    )
    page = signed_in
    open_form(page, live_server, game)

    refused = release_card(page, 0, 1)
    choose_platform(refused, "Amiga")
    page.click(SUBMIT)

    expect(release_card(page, 0, 1)).to_contain_text(DUPLICATE_RELEASE_IN_FORM)
    standing.refresh_from_db()
    assert standing.platform == dos


def test_a_new_game_states_two_editions_at_once(
    signed_in, live_server, e2e_library, amiga, dos
):
    """Add Game writes the Game and its whole graph in one Submit.

    The marked row is the default the service makes, thus the first
    Edition holds the stated Release rather than an empty one beside
    it.
    """
    page = signed_in
    open_add_form(page, live_server)

    page.fill("input[name='name']", "Elite")
    choose_platform(release_card(page, 0, 0), "Amiga")
    type_year(release_card(page, 0, 0), "1984")
    page.click("[data-catalog-add='edition']")
    page.locator("input[name='edition-1-name']").fill("Gold")
    choose_platform(release_card(page, 1, 0), "DOS")
    saved(page, live_server)

    written = Game.objects.get(library=e2e_library, name="Elite")
    editions = list(Edition.objects.alive().filter(game=written).order_by("pk"))
    assert [edition.name for edition in editions] == ["", "Gold"]
    assert [edition.is_default for edition in editions] == [True, False]
    releases = live_releases(editions[0])
    assert [release.platform for release in releases] == [amiga]
    assert releases[0].release_date.serialize() == "1984"
    assert [release.platform for release in live_releases(editions[1])] == [dos]
    assert (written.platform, written.year_released) == (amiga, 1984)


def test_a_row_names_its_controls_at_both_widths(signed_in, live_server, game):
    """Narrow, each control keeps a label; wide, one header stands over them."""
    page = signed_in
    page.set_viewport_size({"width": 390, "height": 900})
    open_form(page, live_server, game)
    card = release_card(page, 0, 0)
    headings = page.get_by_text("In library")

    #: The date is a group of parts, thus the role tells it from the
    #: shape select the same label also names.
    released = card.get_by_role("group", name="Released")

    expect(headings).to_be_hidden()
    expect(card.get_by_label("Platform", exact=True)).to_be_visible()
    expect(released).to_be_visible()

    page.set_viewport_size({"width": 1200, "height": 900})

    expect(headings).to_be_visible()
    expect(card.get_by_label("Platform", exact=True)).to_be_visible()
    expect(released).to_be_visible()
