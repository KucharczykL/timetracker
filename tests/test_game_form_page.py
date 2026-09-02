"""The Edit Game page draws the whole catalog graph."""

import re

import pytest
from django.urls import reverse

from games.catalog_compat import mirror_legacy_columns
from games.catalog_form import LAST_RELEASE, MOST_ROWS, TOO_MANY_ROWS
from games.models import Edition, Game, Platform, Release
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)

_MARK_TAG = re.compile(r'<input[^>]*name="in_library"[^>]*>')
_VALUE = re.compile(r'value="([^"]*)"')


def live(body: str) -> str:
    """The page without the blank rows the browser clones.

    Both templates sit after the area they belong to, so everything
    before the first one is what a person is actually shown.
    """
    return body.split("<template data-catalog-template=")[0]


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
            "wikidata": "",
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
            "wikidata": "",
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
    assert "Select a valid choice" in response.content.decode()


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
            "wikidata": "",
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
            "wikidata": "",
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
            "wikidata": "",
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
            "wikidata": "",
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
            "wikidata": "",
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


def test_the_page_reads_no_more_rows_than_a_person_could_stand(logged_in, plain_game):
    """A count nobody typed is a spent worker, not a form."""
    edition = Edition.objects.get(game=plain_game, is_default=True)

    response = logged_in.post(
        reverse("games:edit_game", args=[plain_game.pk]),
        {
            "name": "Portal",
            "sort_name": "",
            "status": "played",
            "wikidata": "",
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
            "wikidata": "",
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
            "wikidata": "",
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
            "wikidata": "",
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
