"""The Edit Game page draws the whole catalog graph."""

import re
import uuid

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from common.components.primitives import SECTION_SURFACE_CLASS
from games.catalog_compat import mirror_legacy_columns
from games.catalog_form import LAST_RELEASE, MOST_ROWS, PLATFORM_GONE, TOO_MANY_ROWS
from games.models import Edition, Game, LibraryEvent, Platform, PlayerGame, Release
from games.removal import remove
from games.views.catalog_section import _Name
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)

_MARK_TAG = re.compile(r'<input[^>]*name="in_library"[^>]*>')
_STUB_TAG = re.compile(r"<div[^>]*data-catalog-binned[^>]*>")
_CHOSEN_TAG = re.compile(r'<input[^>]*name="catalog-chosen-mark"[^>]*>')
_VALUE = re.compile(r'value="([^"]*)"')


def live(body: str) -> str:
    """The page without the blank rows the browser clones.

    Both templates sit after the area they belong to, so everything
    before the first one is what a person is actually shown.
    """
    return body.split("<template data-catalog-template=")[0]


def stubs_shown(body: str) -> list[bool]:
    """Each binned line: in sight?"""
    return ["display:none" not in tag for tag in _STUB_TAG.findall(body)]


def chosen(body: str) -> str:
    tag = _CHOSEN_TAG.search(body)
    assert tag is not None
    value = _VALUE.search(tag.group(0))
    return value.group(1) if value else ""


def marks(body: str) -> list[tuple[str, bool]]:
    """Each Release row's mark, and whether it is the chosen one."""
    found = []
    for tag in _MARK_TAG.findall(body):
        value = _VALUE.search(tag)
        found.append((value.group(1) if value else "", "checked" in tag))
    return found


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def plain_game(owned_library, stated_graph):
    """One Game as the app leaves it: a default graph, columns mirrored."""
    graph = stated_graph(
        Game(library=owned_library, name="Portal"),
        owned_library,
        release_date=TemporalValue.from_year(2007),
    )
    mirror_legacy_columns(graph.game)
    return graph.game


def page(logged_in, game: Game) -> str:
    response = logged_in.get(reverse("games:edit_game", args=[game.pk]))
    assert response.status_code == 200
    return response.content.decode()


def test_edit_game_draws_a_block_per_edition(logged_in, owned_library, plain_game):
    """A block per Edition, a card per Release, one group over them all."""
    second = Edition.objects.create(game=plain_game, name="Director's Cut")
    Release.objects.create(
        edition=second, release_date=TemporalValue.from_year(2011), is_default=True
    )

    body = page(logged_in, plain_game)

    assert live(body).count('data-choice-card-group="in_library"') == 2
    assert marks(live(body)) == [
        ("edition-0-release-0", True),
        ("edition-1-release-0", False),
    ]
    assert "Director&#x27;s Cut" in body


def test_the_marked_row_is_the_default_release(logged_in, owned_library, plain_game):
    """The radio that is checked is the one the games list draws."""
    edition = Edition.objects.get(game=plain_game, is_default=True)
    Release.objects.create(
        edition=edition,
        platform=Platform.objects.create(name="Steam"),
        release_date=TemporalValue.from_year(2011),
    )

    body = page(logged_in, plain_game)

    assert marks(live(body)) == [
        ("edition-0-release-0", True),
        ("edition-0-release-1", False),
    ]


def test_the_page_states_how_many_rows_it_holds(logged_in, plain_game):
    """A row is read back by count, the way a formset states it."""
    body = page(logged_in, plain_game)

    assert 'name="editions-count" value="1"' in body
    assert 'name="edition-0-releases-count" value="1"' in body


def test_a_narrow_row_labels_every_control(logged_in, plain_game):
    """Above the breakpoint the labels go sr-only, so they must exist."""
    body = page(logged_in, plain_game)

    assert "@2xl/edition:sr-only" in body
    assert "@2xl/edition:hidden" not in body
    assert 'for="id_edition-0-release-0-platform"' in body
    assert 'for="id_edition-0-release-0-release_date"' in body


def test_the_page_threads_the_temporal_element(logged_in, plain_game):
    """A widget renders to text, so its Media never bubbles."""
    body = page(logged_in, plain_game)

    assert "dist/elements/temporal-field.js" in body
    assert "dist/elements/catalog-editor.js" in body


def test_every_release_row_offers_the_original_release(logged_in, plain_game):
    """One button per row, inert until upgrade."""
    Release.objects.create(
        edition=Edition.objects.get(game=plain_game, is_default=True),
        release_date=TemporalValue.from_year(2011),
    )
    body = live(page(logged_in, plain_game))

    assert body.count('data-temporal-copy="original_release_date"') == 2
    button = re.search(r"<button[^>]*data-temporal-copy[^>]*>", body)
    assert button is not None
    assert 'type="button"' in button.group(0)
    # The bare words also occur in `focus:outline-hidden` and
    # `disabled:opacity-50`, thus both are matched as attributes.
    assert 'hidden="hidden"' in button.group(0)
    assert 'disabled="disabled"' in button.group(0)
    assert "Use original release" in body


def test_the_original_release_names_itself_to_the_rows(logged_in, plain_game):
    """No form prefix, thus one per page."""
    body = live(page(logged_in, plain_game))

    assert body.count('field-name="original_release_date"') == 1
    assert 'field-name="edition-0-release-0-release_date"' in body


def test_a_cloned_row_carries_the_button_too(logged_in, plain_game):
    """The clone source needs one too.

    `live()` cuts at the first template, thus this reads the whole
    body on purpose.
    """
    body = page(logged_in, plain_game)
    templates = body.split("<template data-catalog-template=")[1:]

    assert templates
    assert all(
        'data-temporal-copy="original_release_date"' in each for each in templates
    )


def test_add_game_offers_the_original_release_too(logged_in):
    """Add Game hosts the same area."""
    response = logged_in.get(reverse("games:add_game"))
    body = response.content.decode()

    assert 'data-temporal-copy="original_release_date"' in live(body)
    assert 'field-name="original_release_date"' in live(body)


def test_every_row_carries_the_input_the_bin_states(logged_in, plain_game):
    """The bin writes `removed`, thus the row has to post it.

    `removed` is a BooleanField, and the widget stamper turns one into
    a checkbox. A checkbox is not hidden, so the row renderer leaves it
    out, the POST carries nothing, and the bin removes nothing.
    """
    body = live(page(logged_in, plain_game))

    assert 'type="hidden" name="edition-0-removed"' in body
    assert 'type="hidden" name="edition-0-release-0-removed"' in body


def test_the_page_ships_the_rows_the_browser_clones(logged_in, plain_game):
    """A blank row and a blank block, each numbered by placeholder."""
    body = page(logged_in, plain_game)

    assert 'data-catalog-template="release"' in body
    assert 'data-catalog-template="edition"' in body
    #: The row template numbers both; the block's one row is row zero.
    assert 'name="edition-__edition__-release-__release__-platform"' in body
    assert 'name="edition-__edition__-releases-count" value="1"' in body
    assert 'name="edition-__edition__-name"' in body
    #: A live row is numbered, and the templates left it alone.
    assert 'data-catalog-edition="0"' in body
    assert 'data-catalog-release="0"' in body


def test_the_form_writes_the_graph_it_posted(logged_in, owned_library, plain_game):
    """One submit states the Game and its whole graph."""
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = edition.releases.get(is_default=True)

    response = logged_in.post(
        reverse("games:edit_game", args=[plain_game.pk]),
        {
            "name": "Portal",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "1",
            "edition-0-edition_id": str(edition.pk),
            "edition-0-name": "Definitive Edition",
            "edition-0-releases-count": "1",
            "edition-0-release-0-release_id": str(release.pk),
            "edition-0-release-0-platform": "",
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 302
    edition.refresh_from_db()
    assert edition.name == "Definitive Edition"


def test_a_bad_row_leaves_the_rows_after_it_readable(
    logged_in, owned_library, plain_game
):
    """One invalid row is a sentence, not a traceback.

    `all()` over a generator stops at the first false one, and a row it
    never reached holds no `cleaned_data`. The set validator reads every
    row's `removed`, so an unread one answers with `AttributeError`.
    """
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = edition.releases.get(is_default=True)
    second = Release.objects.create(
        edition=edition, release_date=TemporalValue.from_year(2011)
    )

    response = logged_in.post(
        reverse("games:edit_game", args=[plain_game.pk]),
        {
            "name": "Portal",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "1",
            "edition-0-edition_id": str(edition.pk),
            "edition-0-name": "",
            "edition-0-releases-count": "2",
            "edition-0-release-0-release_id": str(release.pk),
            "edition-0-release-0-platform": "not-a-platform",
            "edition-0-release-1-release_id": str(second.pk),
            "edition-0-release-1-platform": "",
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    assert PLATFORM_GONE in response.content.decode()


def test_add_game_draws_the_same_area(logged_in):
    """A Game nobody has written yet gets one blank block, one blank row."""
    response = logged_in.get(reverse("games:add_game"))
    body = response.content.decode()

    assert response.status_code == 200
    assert 'name="editions-count" value="1"' in body
    assert 'name="edition-0-releases-count" value="1"' in body
    assert marks(live(body)) == [("edition-0-release-0", True)]
    assert 'data-catalog-template="edition"' in body
    assert "dist/elements/catalog-editor.js" in body
    assert "dist/elements/temporal-field.js" in body


def test_add_game_writes_the_whole_graph_it_posted(logged_in, owned_library):
    """One submit states the Game and every Edition under it.

    The marked row is the one block zero states, thus the default
    Edition holds one Release rather than the stated one beside an
    empty one nobody asked for.
    """
    steam = Platform.objects.create(name="Steam")

    response = logged_in.post(
        reverse("games:add_game"),
        {
            "name": "Portal",
            "sort_name": "",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "2",
            "edition-0-name": "",
            "edition-0-releases-count": "1",
            "edition-0-release-0-platform": str(steam.pk),
            "edition-0-release-0-release_date-kind": "date",
            "edition-0-release-0-release_date-year": "2007",
            "edition-1-name": "Director's Cut",
            "edition-1-releases-count": "1",
            "edition-1-release-0-platform": "",
            "edition-1-release-0-release_date-kind": "date",
            "edition-1-release-0-release_date-year": "2011",
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 302
    game = Game.objects.get(library=owned_library, name="Portal")
    default = Edition.objects.get(game=game, is_default=True)
    assert default.name == ""
    #: Sorted: the model states no ordering, so the rows come back in
    #: whatever order the last write left them in.
    assert sorted(edition.name for edition in Edition.objects.filter(game=game)) == [
        "",
        "Director's Cut",
    ]
    release = default.releases.get()
    assert release.platform == steam
    assert release.release_date == TemporalValue.from_year(2007)
    #: The flat columns follow the graph in the same transaction.
    game.refresh_from_db()
    assert (game.platform, game.year_released) == (steam, 2007)


def test_a_refused_page_draws_a_binned_row_out_of_sight(logged_in, plain_game):
    """The page comes back the way the person left it, bin and all."""
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = Release.objects.get(edition=edition)

    response = logged_in.post(
        reverse("games:edit_game", args=[plain_game.pk]),
        {
            "name": "Portal",
            "sort_name": "",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "1",
            "edition-0-edition_id": str(edition.pk),
            "edition-0-name": "",
            "edition-0-releases-count": "1",
            "edition-0-release-0-release_id": str(release.pk),
            "edition-0-release-0-platform": "",
            "edition-0-release-0-removed": "on",
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    body = live(response.content.decode())
    row = re.search(r"<div[^>]*data-catalog-release=\"0\"[^>]*>", body)
    assert row is not None
    assert "hidden" in row.group(0)
    assert "display:none" in row.group(0)


def test_a_refused_game_still_lets_the_mark_fall(logged_in, owned_library, plain_game):
    """The Game's own refusal does not stop the graph from reading.

    The mark falls to a row that stays whatever else the page says,
    or the person is shown a mark they cannot see and no way to move
    it.
    """
    edition = Edition.objects.get(game=plain_game, is_default=True)
    binned = Release.objects.get(edition=edition)
    staying = Release.objects.create(
        edition=edition,
        platform=Platform.objects.create(library=owned_library, name="DOS"),
        release_date=TemporalValue.from_year(2011),
    )

    response = logged_in.post(
        reverse("games:edit_game", args=[plain_game.pk]),
        {
            #: The Game form refuses this, and only the Game form.
            "name": "",
            "sort_name": "",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "1",
            "edition-0-edition_id": str(edition.pk),
            "edition-0-name": "",
            "edition-0-releases-count": "2",
            "edition-0-release-0-release_id": str(binned.pk),
            "edition-0-release-0-platform": "",
            "edition-0-release-0-removed": "on",
            "edition-0-release-1-release_id": str(staying.pk),
            "edition-0-release-1-platform": str(staying.platform_id),
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    assert marks(live(response.content.decode())) == [
        ("edition-0-release-0", False),
        ("edition-0-release-1", True),
    ]


def test_a_refused_game_still_says_an_edition_keeps_one_release(logged_in, plain_game):
    """Every row is out of sight, thus the block itself has to say why."""
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = Release.objects.get(edition=edition)

    response = logged_in.post(
        reverse("games:edit_game", args=[plain_game.pk]),
        {
            "name": "",
            "sort_name": "",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "1",
            "edition-0-edition_id": str(edition.pk),
            "edition-0-name": "",
            "edition-0-releases-count": "1",
            "edition-0-release-0-release_id": str(release.pk),
            "edition-0-release-0-platform": "",
            "edition-0-release-0-removed": "on",
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    assert LAST_RELEASE in live(response.content.decode())


def test_a_binned_row_with_a_sentence_stays_in_sight(logged_in, plain_game):
    """A refusal drawn inside a hidden row tells nobody why.

    A posted id nothing can read is a sentence on a hidden field, and
    both the row and the sentence have to reach the page.
    """
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = Release.objects.get(edition=edition)

    response = logged_in.post(
        reverse("games:edit_game", args=[plain_game.pk]),
        {
            "name": "Portal",
            "sort_name": "",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "1",
            "edition-0-edition_id": str(edition.pk),
            "edition-0-name": "",
            "edition-0-releases-count": "2",
            "edition-0-release-0-release_id": "not-a-uuid",
            "edition-0-release-0-platform": "",
            "edition-0-release-0-removed": "on",
            "edition-0-release-1-release_id": str(release.pk),
            "edition-0-release-1-platform": "",
            "in_library": "edition-0-release-1",
        },
    )

    assert response.status_code == 200
    body = live(response.content.decode())
    row = re.search(r"<div[^>]*data-catalog-release=\"0\"[^>]*>", body)
    assert row is not None
    assert "display:none" not in row.group(0)
    assert "Enter a valid UUID." in body
    # Release 0, release 1, then edition's line.
    assert stubs_shown(body) == [True, False, False]


def test_the_page_reads_no_more_rows_than_a_person_could_stand(logged_in, plain_game):
    """A count nobody typed is a spent worker, not a form."""
    edition = Edition.objects.get(game=plain_game, is_default=True)

    response = logged_in.post(
        reverse("games:edit_game", args=[plain_game.pk]),
        {
            "name": "Portal",
            "sort_name": "",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "5000000",
            "edition-0-edition_id": str(edition.pk),
            "edition-0-name": "Definitive",
            "edition-0-releases-count": "5000000",
            "edition-0-release-0-platform": "",
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    body = live(response.content.decode())
    #: Bounded work, and a sentence rather than a page served short.
    assert body.count('name="in_library"') == MOST_ROWS
    assert TOO_MANY_ROWS in body
    edition.refresh_from_db()
    assert edition.name == ""


def test_a_refused_graph_adds_no_game(logged_in, owned_library):
    """The page comes back, and the catalog is as it was."""
    response = logged_in.post(
        reverse("games:add_game"),
        {
            "name": "Portal",
            "sort_name": "",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "2",
            "edition-0-name": "",
            "edition-0-releases-count": "1",
            "edition-0-release-0-platform": "",
            "edition-1-name": "",
            "edition-1-releases-count": "1",
            "edition-1-release-0-platform": "",
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    assert "Name this edition." in response.content.decode()
    assert not Game.objects.filter(name="Portal").exists()


def test_a_refused_identity_leaves_no_half_made_game(logged_in, plain_game):
    """The Game and its graph go back together.

    `plain_game` already holds (Portal, no platform, 2007). A second
    Game stating the same three reaches the mirror's check, which
    raises after the Game row and its default graph are written.
    """
    response = logged_in.post(
        reverse("games:add_game"),
        {
            "name": "Portal",
            "sort_name": "",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "1",
            "edition-0-name": "",
            "edition-0-releases-count": "1",
            "edition-0-release-0-platform": "",
            "edition-0-release-0-release_date-kind": "date",
            "edition-0-release-0-release_date-year": "2007",
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    assert Game.objects.filter(name="Portal").count() == 1
    assert Edition.objects.count() == 1


def test_a_refused_row_re_renders_beside_its_sentence(
    logged_in, owned_library, plain_game
):
    """A second unnamed Edition reads as the Game's name twice."""
    response = logged_in.post(
        reverse("games:edit_game", args=[plain_game.pk]),
        {
            "name": "Portal",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "2",
            "edition-0-name": "",
            "edition-0-releases-count": "1",
            "edition-0-release-0-platform": "",
            "edition-1-name": "",
            "edition-1-releases-count": "1",
            "edition-1-release-0-platform": "",
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    assert "Name this edition." in response.content.decode()
    assert Edition.objects.filter(game=plain_game).count() == 1


def templates(body: str) -> str:
    """Only the blank rows the browser clones."""
    return body.split("<template data-catalog-template=", 1)[1]


def edit_url(game: Game) -> str:
    return reverse("games:edit_game", args=[game.pk])


def test_a_row_names_its_stored_platform(logged_in, owned_library, plain_game):
    amiga = Platform.objects.create(library=owned_library, name="Amiga")
    Release.objects.filter(edition__game=plain_game).update(platform=amiga)

    body = live(page(logged_in, plain_game))

    assert ">Show the Amiga release in the library</span>" in body
    assert 'aria-label="Remove the Amiga release"' in body


def test_a_refused_page_names_what_the_person_posted(
    logged_in, owned_library, plain_game
):
    """Not the stored Amiga the person replaced."""
    amiga = Platform.objects.create(library=owned_library, name="Amiga")
    dos = Platform.objects.create(library=owned_library, name="DOS")
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = edition.releases.get(is_default=True)
    Release.objects.filter(pk=release.pk).update(platform=amiga)

    response = logged_in.post(
        edit_url(plain_game),
        {
            "name": "Portal",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "1",
            "edition-0-edition_id": str(edition.pk),
            "edition-0-name": "Gold",
            "edition-0-releases-count": "2",
            "edition-0-release-0-release_id": str(release.pk),
            "edition-0-release-0-platform": str(dos.pk),
            # An unoffered key refuses the page.
            "edition-0-release-1-platform": str(uuid.uuid4()),
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    body = live(response.content.decode())
    assert ">Show the DOS release in the library</span>" in body
    assert 'aria-label="Remove the DOS release"' in body
    assert "Amiga release" not in body
    assert ">Show the Unspecified release in the library</span>" in body
    assert ">Gold</legend>" in body
    assert 'aria-label="Remove the Gold edition"' in body


def _one_release_post(edition, release, platform: str) -> dict[str, str]:
    return {
        "name": "Portal",
        "status": "played",
        "reference_wikidata": "",
        "editions-count": "1",
        "edition-0-edition_id": str(edition.pk),
        "edition-0-name": "",
        "edition-0-releases-count": "1",
        "edition-0-release-0-release_id": str(release.pk),
        "edition-0-release-0-platform": platform,
        "in_library": "edition-0-release-0",
    }


def test_a_removed_stored_platform_is_named_and_kept(
    logged_in, owned_library, plain_game
):
    amiga = Platform.objects.create(library=owned_library, name="Amiga")
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = edition.releases.get(is_default=True)
    Release.objects.filter(pk=release.pk).update(platform=amiga)
    remove(amiga)

    body = live(page(logged_in, plain_game))
    response = logged_in.post(
        edit_url(plain_game), _one_release_post(edition, release, str(amiga.pk))
    )

    assert ">Show the Amiga (removed) release in the library</span>" in body
    assert response.status_code == 302
    release.refresh_from_db()
    assert release.platform == amiga


def test_a_refused_page_names_no_foreign_platform(
    logged_in, owned_library, plain_game, django_user_model
):
    other = django_user_model.objects.create_user(username="other", password="p")
    hidden = Platform.objects.create(library=other.library, name="Hidden")
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = edition.releases.get(is_default=True)

    response = logged_in.post(
        edit_url(plain_game), _one_release_post(edition, release, str(hidden.pk))
    )

    assert response.status_code == 200
    assert "Hidden" not in response.content.decode()


def test_a_posted_key_in_another_spelling_is_named(
    logged_in, owned_library, plain_game
):
    dos = Platform.objects.create(library=owned_library, name="DOS")
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = edition.releases.get(is_default=True)
    posted = _one_release_post(edition, release, str(dos.pk).upper())
    #: An unnamed second edition refuses the page.
    posted |= {
        "editions-count": "2",
        "edition-1-name": "",
        "edition-1-releases-count": "1",
        "edition-1-release-0-platform": "",
    }

    body = live(logged_in.post(edit_url(plain_game), posted).content.decode())

    assert ">Show the DOS release in the library</span>" in body


def test_a_blank_edition_name_is_unnamed(logged_in, plain_game):
    """Whitespace is no name."""
    response = logged_in.post(
        edit_url(plain_game),
        {
            "name": "Portal",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "2",
            "edition-0-name": "   ",
            "edition-0-releases-count": "1",
            "edition-0-release-0-platform": "",
            "edition-1-name": "",
            "edition-1-releases-count": "1",
            "edition-1-release-0-platform": "",
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    body = live(response.content.decode())
    assert body.count(">Unnamed edition</legend>") == 2
    assert body.count('aria-label="Remove the unnamed edition"') == 2
    assert "Remove the    " not in body


def test_the_cloned_rows_carry_their_name_patterns(logged_in, plain_game):
    blank = templates(page(logged_in, plain_game))

    assert 'data-catalog-name="Show the {} release in the library"' in blank
    assert 'data-catalog-name="Remove the {} release"' in blank
    assert 'data-catalog-name-of="platform"' in blank
    assert ">Show the Unspecified release in the library</span>" in blank
    assert 'data-catalog-name="Remove the {} edition"' in blank
    assert 'data-catalog-name-empty="Remove the unnamed edition"' in blank
    assert 'data-catalog-name-empty="Unnamed edition"' in blank
    assert 'data-catalog-name-of="name"' in blank
    assert ">Unnamed edition</legend>" in blank


def test_naming_the_rows_reads_no_more_per_row(logged_in, owned_library, plain_game):
    """One Platform read serves every row."""
    amiga = Platform.objects.create(library=owned_library, name="Amiga")
    edition = Edition.objects.get(game=plain_game, is_default=True)
    Release.objects.filter(edition=edition).update(platform=amiga)

    def queries() -> int:
        with CaptureQueriesContext(connection) as captured:
            logged_in.get(edit_url(plain_game))
        return len(captured.captured_queries)

    one = queries()
    for year in (2011, 2012):
        Release.objects.create(
            edition=edition, platform=amiga, release_date=TemporalValue.from_year(year)
        )

    assert queries() == one


def _tag(pattern: str, body: str) -> str:
    found = re.search(pattern, body)
    assert found, pattern
    return found.group(0)


def test_a_live_row_carries_every_name_hook(logged_in, plain_game):
    """The element reads these on live rows."""
    body = live(page(logged_in, plain_game))

    mark = _tag(r'<span[^>]*data-catalog-name="Show the \{\} release[^>]*>', body)
    assert 'data-catalog-name-of="platform"' in mark
    assert "data-catalog-name-empty" not in mark

    legend = _tag(r"<legend[^>]*data-catalog-name=[^>]*>", body)
    assert 'data-catalog-name="{}"' in legend
    assert 'data-catalog-name-of="name"' in legend
    assert 'data-catalog-name-empty="Unnamed edition"' in legend

    release_bin = _tag(
        r'<button[^>]*data-catalog-name="Remove the \{\} release"[^>]*>', body
    )
    assert 'data-catalog-name-of="platform"' in release_bin
    assert 'aria-label="Remove the Unspecified release"' in release_bin
    assert 'title="Remove the Unspecified release"' in release_bin

    edition_bin = _tag(
        r'<button[^>]*data-catalog-name="Remove the \{\} edition"[^>]*>', body
    )
    assert 'data-catalog-name-of="name"' in edition_bin
    assert 'data-catalog-name-empty="Remove the unnamed edition"' in edition_bin
    assert 'aria-label="Remove the unnamed edition"' in edition_bin


def test_a_platform_the_library_cannot_see_is_unspecified(
    logged_in, plain_game, django_user_model
):
    """Its select shows the empty option too."""
    other = django_user_model.objects.create_user(username="other", password="p")
    hidden = Platform.objects.create(library=other.library, name="Hidden")
    Release.objects.filter(edition__game=plain_game).update(platform=hidden)

    body = live(page(logged_in, plain_game))

    assert ">Show the Unspecified release in the library</span>" in body
    assert "Hidden" not in body


def test_a_platform_name_is_trimmed_as_the_element_trims(
    logged_in, owned_library, plain_game
):
    amiga = Platform.objects.create(library=owned_library, name="  Amiga ")
    Release.objects.filter(edition__game=plain_game).update(platform=amiga)

    body = live(page(logged_in, plain_game))

    assert ">Show the Amiga release in the library</span>" in body


def test_a_name_pattern_needs_its_slot():
    with pytest.raises(ValueError, match="no slot"):
        _Name("Remove the release", "platform")


def _posted_with(plain_game, **extra: str) -> dict[str, str]:
    """An edit submit stating only `extra`."""
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = edition.releases.get(is_default=True)
    return {
        "name": plain_game.name,
        "status": "played",
        "reference_wikidata": "",
        "editions-count": "1",
        "edition-0-edition_id": str(edition.pk),
        "edition-0-name": edition.name,
        "edition-0-releases-count": "1",
        "edition-0-release-0-release_id": str(release.pk),
        "edition-0-release-0-platform": "",
        "in_library": "edition-0-release-0",
        **extra,
    }


EXCLUSIONS = ["excluded_from_unfinished", "excluded_from_dropped"]


def _exclusion_box(body: str, fact: str) -> str:
    found = re.search(rf'<input[^>]*name="{fact}"[^>]*>', body)
    assert found is not None
    return found[0]


def test_the_visibility_fieldset_holds_both_boxes(logged_in, plain_game):
    body = page(logged_in, plain_game)
    opening = body[body.rindex("<fieldset", 0, body.index('id="visibility"')) :]
    assert SECTION_SURFACE_CLASS in opening.split(">", 1)[0]
    fieldset = body.split('id="visibility"', 1)[1].split("</fieldset>", 1)[0]

    assert "Visibility</legend>" in fieldset
    assert "Leave this game out of:" in fieldset
    assert [
        re.search(r'name="(\w+)"', box)[1]
        for box in re.findall(r"<input[^>]*>", fieldset)
    ] == EXCLUSIONS


@pytest.mark.parametrize("fact", EXCLUSIONS)
def test_the_box_reads_the_tracked_row(logged_in, plain_game, fact):
    assert "checked" not in _exclusion_box(page(logged_in, plain_game), fact)
    PlayerGame.objects.filter(game=plain_game).update(**{fact: True})

    assert "checked" in _exclusion_box(page(logged_in, plain_game), fact)


@pytest.mark.parametrize("fact", EXCLUSIONS)
def test_a_ticked_box_states_the_exclusion_once(logged_in, plain_game, fact):
    response = logged_in.post(
        reverse("games:edit_game", args=[plain_game.pk]),
        _posted_with(plain_game, **{fact: "on"}),
    )

    assert response.status_code == 302
    row = PlayerGame.objects.get(game=plain_game)
    assert [getattr(row, each) for each in EXCLUSIONS] == [
        each == fact for each in EXCLUSIONS
    ]
    assert (
        LibraryEvent.objects.filter(
            event_type__startswith="library.playergame.excluded_from_"
        )
        .values_list("event_type", flat=True)
        .get()
        == f"library.playergame.{fact}_changed"
    )


@pytest.mark.parametrize("fact", EXCLUSIONS)
def test_an_empty_box_includes_the_game_again(logged_in, plain_game, fact):
    PlayerGame.objects.filter(game=plain_game).update(**{fact: True})

    logged_in.post(
        reverse("games:edit_game", args=[plain_game.pk]), _posted_with(plain_game)
    )

    assert getattr(PlayerGame.objects.get(game=plain_game), fact) is False


@pytest.mark.parametrize("fact", EXCLUSIONS)
def test_add_game_states_the_exclusion(logged_in, owned_library, fact):
    response = logged_in.post(
        reverse("games:add_game"),
        {
            "name": "Endless Farm",
            "sort_name": "",
            "status": "played",
            fact: "on",
            "reference_wikidata": "",
            "editions-count": "1",
            "edition-0-name": "",
            "edition-0-releases-count": "1",
            "edition-0-release-0-platform": "",
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 302
    game = Game.objects.get(library=owned_library, name="Endless Farm")
    assert getattr(PlayerGame.objects.get(game=game), fact) is True


def test_a_live_row_hides_the_line_a_bin_leaves(logged_in, plain_game):
    body = page(logged_in, plain_game)

    # The release's line, then the edition's.
    assert stubs_shown(live(body)) == [False, False]
    assert ">Unspecified release will be removed</span>" in live(body)
    assert 'aria-label="Undo removing the Unspecified release"' in live(body)
    assert ">Unnamed edition will be removed</span>" in live(body)
    assert 'aria-label="Undo removing the unnamed edition"' in live(body)


def test_both_templates_carry_the_line_a_bin_leaves(logged_in, plain_game):
    body = templates(page(logged_in, plain_game))

    # Release template's, then edition template's two.
    assert stubs_shown(body) == [False, False, False]


def test_a_refused_page_shows_the_line_of_a_binned_row(logged_in, plain_game):
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = Release.objects.get(edition=edition)

    response = logged_in.post(
        edit_url(plain_game),
        {
            "name": "",
            "sort_name": "",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "1",
            "edition-0-edition_id": str(edition.pk),
            "edition-0-name": "",
            "edition-0-releases-count": "1",
            "edition-0-release-0-release_id": str(release.pk),
            "edition-0-release-0-platform": "",
            "edition-0-release-0-removed": "on",
            "in_library": "edition-0-release-0",
            "catalog-chosen-mark": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    body = live(response.content.decode())
    assert stubs_shown(body) == [True, False]
    assert chosen(body) == "edition-0-release-0"


def test_the_chosen_mark_starts_at_the_stored_one(logged_in, plain_game):
    assert chosen(live(page(logged_in, plain_game))) == "edition-0-release-0"


def test_a_post_without_a_chosen_mark_keeps_the_posted_one(logged_in, plain_game):
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = Release.objects.get(edition=edition)

    response = logged_in.post(
        edit_url(plain_game),
        {
            "name": "",
            "sort_name": "",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "1",
            "edition-0-edition_id": str(edition.pk),
            "edition-0-name": "",
            "edition-0-releases-count": "1",
            "edition-0-release-0-release_id": str(release.pk),
            "edition-0-release-0-platform": "",
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    assert chosen(live(response.content.decode())) == "edition-0-release-0"


def test_a_refused_page_shows_the_line_of_a_binned_edition(logged_in, plain_game):
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = Release.objects.get(edition=edition)

    response = logged_in.post(
        edit_url(plain_game),
        {
            "name": "",
            "sort_name": "",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "2",
            "edition-0-edition_id": str(edition.pk),
            "edition-0-name": "",
            "edition-0-removed": "on",
            "edition-0-releases-count": "1",
            "edition-0-release-0-release_id": str(release.pk),
            "edition-0-release-0-platform": "",
            "edition-1-edition_id": "",
            "edition-1-name": "Remaster",
            "edition-1-releases-count": "1",
            "edition-1-release-0-release_id": "",
            "edition-1-release-0-platform": "",
            "in_library": "edition-1-release-0",
        },
    )

    assert response.status_code == 200
    # Edition 0's release, edition 0, edition 1's release, edition 1.
    assert stubs_shown(live(response.content.decode())) == [False, True, False, False]
