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
from entries import record_entry
from playwright.sync_api import Locator, Page, expect

from e2e.helpers import held_choice, pick_choice, picker_opened
from games.catalog_compat import mirror_legacy_columns
from games.catalog_form import DUPLICATE_RELEASE_IN_FORM
from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.models import Edition, Game, Platform, PlayerGame, Release
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
    """One default Edition holding one default Release.

    Stated here rather than pulled from `tests/conftest.py`, which
    is not on this package's path.
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
    """One Game as the app leaves it."""
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


def platform_picker(card: Locator) -> Locator:
    return card.locator("search-select[name$='-platform']")


def choose_platform(card: Locator, name: str) -> None:
    """Search the row's picker; pick by label."""
    picker = platform_picker(card)
    with picker_opened(picker):
        picker.locator("[data-search-select-search]").fill(name)
        picker.locator(f'[data-search-select-option][data-label="{name}"]').click()


def type_year(card: Locator, year: str) -> None:
    """The segmented year of one row's release date."""
    segments = card.locator("[data-temporal-segments='start']")
    expect(segments).to_be_visible()
    card.locator("[data-date-part='year'][data-date-side='start']").click()
    card.page.keyboard.type(year)


def type_original_release(page: Page, year: str) -> None:
    """The Game's own Original release year."""
    field = page.locator('temporal-field[field-name="original_release_date"]')
    expect(field.locator("[data-temporal-segments='start']")).to_be_visible()
    field.locator("[data-date-part='year'][data-date-side='start']").click()
    page.keyboard.type(year)


def copy_button(card: Locator) -> Locator:
    return card.locator("[data-temporal-copy]")


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


def test_binning_the_marked_row_moves_the_mark_where_a_person_sees_it(
    signed_in, live_server, game, amiga, dos
):
    """The bin states a removal, and the mark falls to a row that stays.

    A person who bins the marked row and adds its pair back never
    chose a release that is going, so nothing refuses their submit.
    """
    Release.objects.create(
        edition=default_edition(game),
        platform=dos,
        release_date=TemporalValue.from_year(1988),
    )
    page = signed_in
    open_form(page, live_server, game)
    old = live_releases(default_edition(game))[0]

    release_card(page, 0, 0).locator("[data-catalog-remove]").click()

    #: The mark moved while the person was still looking at the page.
    expect(release_card(page, 0, 1).locator("input[name='in_library']")).to_be_checked()

    page.click("[data-catalog-edition='0'] [data-catalog-add='release']")
    added = release_card(page, 0, 2)
    choose_platform(added, "Amiga")
    type_year(added, "1984")
    saved(page, live_server)

    old.refresh_from_db()
    assert old.removed_at is not None
    releases = live_releases(default_edition(game))
    assert sorted(release.platform.name for release in releases) == ["Amiga", "DOS"]
    assert [release.platform for release in releases if release.is_default] == [dos]


def test_undo_takes_the_bin_back_and_the_mark_with_it(
    signed_in, live_server, game, amiga, dos
):
    """An accidental bin leaves the graph as it was."""
    Release.objects.create(
        edition=default_edition(game),
        platform=dos,
        release_date=TemporalValue.from_year(1988),
    )
    page = signed_in
    open_form(page, live_server, game)
    marked = release_card(page, 0, 0)

    marked.locator("[data-catalog-remove]").click()
    expect(marked).to_be_hidden()
    expect(release_card(page, 0, 1).locator("input[name='in_library']")).to_be_checked()
    undo = page.get_by_role("button", name="Undo removing the Amiga release")
    expect(undo).to_be_focused()

    undo.click()
    expect(marked).to_be_visible()
    expect(undo).to_be_hidden()
    expect(marked.locator("input[name='in_library']")).to_be_checked()
    saved(page, live_server)

    releases = live_releases(default_edition(game))
    assert sorted(release.platform.name for release in releases) == ["Amiga", "DOS"]
    assert [release.platform for release in releases if release.is_default] == [amiga]


def test_undo_takes_back_the_bin_of_an_edition(
    signed_in, live_server, game, amiga, dos
):
    """The block comes back, and the mark inside it."""
    second = Edition.objects.create(game=game, name="Remaster")
    Release.objects.create(
        edition=second, platform=dos, release_date=TemporalValue.from_year(1990)
    )
    page = signed_in
    open_form(page, live_server, game)
    block = page.locator("[data-catalog-edition='0']")

    block.locator(":scope > div [data-catalog-remove]").first.click()
    expect(block).to_be_hidden()
    undo = page.get_by_role("button", name="Undo removing the unnamed edition")
    undo.click()
    expect(block).to_be_visible()
    expect(release_card(page, 0, 0).locator("input[name='in_library']")).to_be_checked()
    saved(page, live_server)

    editions = Edition.objects.filter(game=game, removed_at=None)
    assert editions.count() == 2
    assert [release.platform for release in live_releases(default_edition(game))] == [
        amiga
    ]
    assert live_releases(default_edition(game))[0].is_default


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
    """Narrow, each control keeps a label; wide, one header stands over them.

    The form width never reaches the grid, so the cap is lifted.
    """
    page = signed_in
    page.set_viewport_size({"width": 390, "height": 900})
    open_form(page, live_server, game)
    card = release_card(page, 0, 0)
    headings = page.get_by_text("In library")

    #: The date is a group of parts, thus the role tells it from the
    #: shape select the same label also names.
    released = card.get_by_role("group", name="Released")

    expect(headings).to_be_hidden()
    expect(
        card.get_by_role("button", name="Platform, Amiga", exact=True)
    ).to_be_visible()
    expect(released).to_be_visible()

    page.set_viewport_size({"width": 1200, "height": 900})
    page.locator("#add-form").evaluate(
        "form => { form.parentElement.style.maxWidth = 'none'; }"
    )

    expect(headings).to_be_visible()
    expect(card.get_by_role("combobox", name="Platform", exact=True)).to_be_visible()
    expect(released).to_be_visible()


def test_a_cloned_row_takes_the_original_release(
    signed_in, live_server, e2e_library, amiga, dos
):
    """A cloned row fills itself from the Game."""
    page = signed_in
    open_add_form(page, live_server)

    page.fill("input[name='name']", "Grim Fandango")
    type_original_release(page, "1998")
    choose_platform(release_card(page, 0, 0), "Amiga")
    page.click("[data-catalog-edition='0'] [data-catalog-add='release']")
    added = release_card(page, 0, 1)
    choose_platform(added, "DOS")
    copy_button(added).click()
    expect(
        added.locator("[data-date-part='year'][data-date-side='start']")
    ).to_have_value("1998")
    saved(page, live_server)

    written = Game.objects.get(library=e2e_library, name="Grim Fandango")
    releases = live_releases(default_edition(written))
    assert [release.platform for release in releases] == [amiga, dos]
    assert releases[1].release_date.serialize() == "1998"
    # The button sits in the row, not inside the mark's label.
    assert [release.is_default for release in releases] == [True, False]


def test_the_button_wakes_when_the_original_release_fills(signed_in, live_server):
    """The button wakes with no reload.

    Here a real key reaches the real engine across two upgraded
    elements, which jsdom states but does not run.
    """
    page = signed_in
    open_add_form(page, live_server)
    button = copy_button(release_card(page, 0, 0))
    expect(button).to_be_disabled()

    type_original_release(page, "1998")

    expect(button).to_be_enabled()


def mark_text(card: Locator) -> Locator:
    """The text naming a row's mark."""
    return card.locator("label [data-catalog-name-of='platform']")


def test_a_changed_row_names_its_new_platform(signed_in, live_server, game, dos):
    """Narrow: visible text. Wide: the radio's name."""
    page = signed_in
    page.set_viewport_size({"width": 390, "height": 900})
    open_form(page, live_server, game)
    card = release_card(page, 0, 0)

    choose_platform(card, "DOS")

    expect(mark_text(card)).to_be_visible()
    expect(mark_text(card)).to_have_text("Show the DOS release in the library")
    expect(
        card.get_by_role("button", name="Remove the DOS release", exact=True)
    ).to_be_visible()

    page.set_viewport_size({"width": 1200, "height": 900})

    expect(
        card.get_by_role(
            "radio", name="Show the DOS release in the library", exact=True
        )
    ).to_be_visible()


def test_a_cloned_row_names_the_platform_chosen_in_it(
    signed_in, live_server, game, dos
):
    page = signed_in
    open_form(page, live_server, game)
    page.click("[data-catalog-edition='0'] [data-catalog-add='release']")
    added = release_card(page, 0, 1)

    expect(
        added.get_by_role(
            "radio", name="Show the Unspecified release in the library", exact=True
        )
    ).to_be_visible()
    choose_platform(added, "DOS")

    expect(
        added.get_by_role(
            "radio", name="Show the DOS release in the library", exact=True
        )
    ).to_be_visible()
    expect(
        added.get_by_role("button", name="Remove the DOS release", exact=True)
    ).to_be_visible()
    expect(
        release_card(page, 0, 0).get_by_role(
            "radio", name="Show the Amiga release in the library", exact=True
        )
    ).to_be_visible()


def test_a_cloned_edition_names_what_is_typed_in_it(
    signed_in, live_server, game, amiga
):
    page = signed_in
    open_form(page, live_server, game)
    page.click("[data-catalog-add='edition']")
    block = page.locator("[data-catalog-edition='1']")

    expect(block).to_have_accessible_name("Unnamed edition")
    block.locator("input[name='edition-1-name']").fill("Gold")

    expect(block).to_have_accessible_name("Gold")
    expect(
        block.get_by_role("button", name="Remove the Gold edition", exact=True)
    ).to_be_visible()

    first = release_card(page, 1, 0)
    choose_platform(first, "Amiga")
    expect(
        first.get_by_role(
            "radio", name="Show the Amiga release in the library", exact=True
        )
    ).to_be_visible()


def radio_named(scope: Locator, platform: str) -> Locator:
    return scope.get_by_role(
        "radio", name=f"Show the {platform} release in the library", exact=True
    )


def test_back_shows_the_stored_platform_and_names_it(
    signed_in, live_server, game, amiga, dos
):
    """Back restores no pick; the stored one stands."""
    page = signed_in
    open_form(page, live_server, game)
    choose_platform(release_card(page, 0, 0), "DOS")
    page.fill("input[name='edition-0-name']", "Gold")

    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    page.go_back()
    _upgraded(page)

    card = release_card(page, 0, 0)
    assert (
        page.evaluate("performance.getEntriesByType('navigation')[0].type")
        == "back_forward"
    )
    picker = platform_picker(card)
    expect(picker.locator("[data-search-select-search]")).to_have_value("Amiga")
    expect(picker.locator("[data-search-select-pills] input")).to_have_value(
        str(amiga.pk)
    )
    expect(radio_named(card, "Amiga")).to_be_visible()
    expect(
        card.get_by_role("button", name="Remove the Amiga release", exact=True)
    ).to_be_visible()
    expect(page.locator("[data-catalog-edition='0']")).to_have_accessible_name("Gold")


def test_a_cloned_row_creates_a_platform_from_its_create_row(
    signed_in, live_server, game, amiga, e2e_library
):
    """Typed, created, named; one submit."""
    page = signed_in
    open_form(page, live_server, game)
    page.click("[data-catalog-edition='0'] [data-catalog-add='release']")
    added = release_card(page, 0, 1)
    search = platform_picker(added).locator("[data-search-select-search]")
    search.click()
    search.fill("Atari ST")
    platform_picker(added).locator("[data-search-select-create]").click()

    expect(radio_named(added, "Atari ST")).to_be_visible()
    saved(page, live_server)

    created = Platform.objects.get(library=e2e_library, name="Atari ST")
    releases = live_releases(default_edition(game))
    assert [release.platform for release in releases] == [amiga, created]


def test_a_cloned_row_creates_a_platform_in_a_dialog(
    signed_in, live_server, game, amiga, e2e_library
):
    """The + opens Add Platform; its row lands."""
    page = signed_in
    open_form(page, live_server, game)
    page.click("[data-catalog-edition='0'] [data-catalog-add='release']")
    added = release_card(page, 0, 1)
    platform_picker(added).get_by_role("link", name="New platform").click()
    dialog = page.locator("dialog[data-modal][open]")
    expect(dialog.locator("[data-form-dialog-title]")).to_have_text("Add New Platform")
    dialog.locator('input[name="name"]').fill("Atari ST")
    dialog.get_by_role("button", name="Submit", exact=True).click()

    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)
    expect(radio_named(added, "Atari ST")).to_be_visible()
    saved(page, live_server)

    created = Platform.objects.get(library=e2e_library, name="Atari ST")
    releases = live_releases(default_edition(game))
    assert [release.platform for release in releases] == [amiga, created]


def test_a_refused_page_names_the_posted_platform(signed_in, live_server, game, dos):
    """Two unnamed editions refuse the page."""
    page = signed_in
    open_form(page, live_server, game)
    choose_platform(release_card(page, 0, 0), "DOS")
    page.click("[data-catalog-add='edition']")

    page.click(SUBMIT)
    expect(page.get_by_text("Name this edition.").first).to_be_visible()
    _upgraded(page)

    card = release_card(page, 0, 0)
    expect(radio_named(card, "DOS")).to_be_visible()
    expect(
        card.get_by_role("button", name="Remove the DOS release", exact=True)
    ).to_be_visible()


def test_a_row_added_after_a_bin_names_its_own_platform(
    signed_in, live_server, game, dos
):
    page = signed_in
    open_form(page, live_server, game)
    add = "[data-catalog-edition='0'] [data-catalog-add='release']"
    page.click(add)
    release_card(page, 0, 1).get_by_role(
        "button", name="Remove the Unspecified release", exact=True
    ).click()
    page.click(add)

    added = release_card(page, 0, 2)
    choose_platform(added, "DOS")

    expect(radio_named(added, "DOS")).to_be_visible()
    expect(radio_named(release_card(page, 0, 0), "Amiga")).to_be_visible()


def test_an_excluded_game_leaves_the_unfinished_list(
    signed_in, live_server, game, e2e_library
):
    """Ticked: detail names it, stats drop it."""
    page = signed_in
    record_entry(
        e2e_library,
        default_edition(game).releases.get(),
        acquired=TemporalValue.parse("2026-03-05"),
    )
    stats = f"{live_server.url}{reverse('games:stats_alltime')}"
    page.goto(stats)
    expect(page.get_by_role("row", name="Unfinished 1 (100%)")).to_be_visible()

    open_form(page, live_server, game)
    page.get_by_role("group", name="Visibility").get_by_label(
        "Unfinished lists"
    ).check()
    saved(page, live_server)

    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    expect(page.get_by_text("Left out of unfinished lists")).to_be_visible()
    page.goto(stats)
    expect(page.get_by_role("row", name="Unfinished 0 (0%)")).to_be_visible()
    assert PlayerGame.objects.get(game=game).excluded_from_unfinished is True


def test_the_parent_row_follows_the_kind(signed_in, live_server, game):
    """Hidden for main, shown for add-ons, cleared."""
    page = signed_in
    open_add_form(page, live_server)
    parent_row = page.locator("[data-field-row='parent']")
    expect(parent_row).to_be_hidden()

    pick_choice(page, "kind", "dlc")
    expect(parent_row).to_be_visible()
    picker = page.locator("search-select[name='parent']")
    picker.locator("[data-search-select-search]").click()
    picker.get_by_role("option", name="Elite").first.click()
    expect(parent_row.locator("input[type=hidden][name='parent']")).to_have_value(
        str(game.pk)
    )

    pick_choice(page, "kind", "main")
    expect(parent_row).to_be_hidden()
    expect(parent_row.locator("input[type=hidden][name='parent']")).to_have_count(0)


def test_the_parent_picker_offers_no_addons(signed_in, live_server, e2e_library, game):
    addon = Game.objects.create(library=e2e_library, name="Elite DLC")
    Game.objects.filter(pk=addon.pk).update(kind="dlc", parent=game)
    page = signed_in
    open_add_form(page, live_server)

    pick_choice(page, "kind", "dlc")
    picker = page.locator("search-select[name='parent']")
    picker.locator("[data-search-select-search]").fill("Elite")

    expect(
        picker.get_by_role("option", name="Elite", exact=False).first
    ).to_be_visible()
    expect(picker.get_by_role("option", name="Elite DLC")).to_have_count(0)


def test_a_cloned_edition_saves_its_kind(signed_in, live_server, game):
    page = signed_in
    open_form(page, live_server, game)

    page.click("[data-catalog-add='edition']")
    page.locator("input[name='edition-1-name']").fill("Demo")
    pick_choice(page, "edition-1-kind", "prerelease")
    saved(page, live_server)

    added = Edition.objects.alive().get(game=game, name="Demo")
    assert added.kind == "prerelease"


def test_a_new_dlc_names_its_parent(signed_in, live_server, e2e_library, game):
    page = signed_in
    open_add_form(page, live_server)

    page.fill("input[name='name']", "Elite Expansion")
    pick_choice(page, "kind", "dlc")
    picker = page.locator("search-select[name='parent']")
    picker.locator("[data-search-select-search]").click()
    picker.get_by_role("option", name="Elite").first.click()
    saved(page, live_server)

    written = Game.objects.get(library=e2e_library, name="Elite Expansion")
    assert (written.kind, written.parent_id) == ("dlc", game.pk)
    page.goto(f"{live_server.url}{written.get_absolute_url()}")
    parent_link = page.get_by_role("link", name="Elite", exact=True)
    expect(parent_link).to_have_attribute("href", game.get_absolute_url())


def test_two_cloned_editions_keep_their_own_kind(signed_in, live_server, game):
    """Each clone's picker owns its own list."""
    page = signed_in
    open_form(page, live_server, game)

    page.click("[data-catalog-add='edition']")
    page.click("[data-catalog-add='edition']")
    page.locator("input[name='edition-1-name']").fill("Demo")
    page.locator("input[name='edition-2-name']").fill("Remaster")
    boxes = [
        page.locator(
            f"search-select[name='edition-{index}-kind'] [data-search-select-search]"
        )
        for index in (1, 2)
    ]
    first, second = (box.get_attribute("aria-controls") for box in boxes)
    assert first and second and first != second
    pick_choice(page, "edition-1-kind", "prerelease")
    pick_choice(page, "edition-2-kind", "full")
    saved(page, live_server)

    kinds = dict(
        Edition.objects.alive()
        .filter(game=game, name__in=["Demo", "Remaster"])
        .values_list("name", "kind")
    )
    assert kinds == {"Demo": "prerelease", "Remaster": "full"}


def test_a_keystroke_in_kind_keeps_the_parent(signed_in, live_server, game):
    """Typing drops the value; leaving puts it back."""
    page = signed_in
    open_add_form(page, live_server)
    pick_choice(page, "kind", "dlc")
    picker = page.locator("search-select[name='parent']")
    picker.locator("[data-search-select-search]").click()
    picker.get_by_role("option", name="Elite").first.click()

    kind_box = page.locator("search-select[name='kind'] [data-search-select-search]")
    kind_box.click()
    page.keyboard.type("m")
    page.locator("input[name='name']").click()

    expect(held_choice(page, "kind")).to_have_value("dlc")
    expect(page.locator("[data-field-row='parent']")).to_be_visible()
    expect(held_choice(page, "parent")).to_have_value(str(game.pk))
