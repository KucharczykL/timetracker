"""The Edit Game page draws the whole catalog graph."""

import re

import pytest
from django.urls import reverse

from games.catalog_compat import mirror_legacy_columns
from games.catalog_writes import add_edition, add_release, save_private_game
from games.models import Edition, Game, Platform
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)

_MARK_TAG = re.compile(r'<input[^>]*name="in_library"[^>]*>')
_VALUE = re.compile(r'value="([^"]*)"')


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
def plain_game(owned_library):
    """One Game as the app leaves it: a default graph, columns mirrored."""
    graph = save_private_game(
        game=Game(library=owned_library, name="Portal"),
        original_release_date=None,
        release_date=TemporalValue.from_year(2007),
        platform=None,
    )
    mirror_legacy_columns(graph.game)
    return graph.game


def page(logged_in, game: Game) -> str:
    response = logged_in.get(reverse("games:edit_game", args=[game.pk]))
    assert response.status_code == 200
    return response.content.decode()


def test_edit_game_draws_a_block_per_edition(logged_in, owned_library, plain_game):
    """A block per Edition, a card per Release, one group over them all."""
    second = add_edition(
        game=plain_game, library=owned_library, name="Director's Cut", is_default=False
    )
    add_release(
        edition=second,
        library=owned_library,
        platform=None,
        release_date=TemporalValue.from_year(2011),
        is_default=True,
    )

    body = page(logged_in, plain_game)

    assert body.count('data-choice-card-group="in_library"') == 2
    assert marks(body) == [
        ("edition-0-release-0", True),
        ("edition-1-release-0", False),
    ]
    assert "Director&#x27;s Cut" in body


def test_the_marked_row_is_the_default_release(logged_in, owned_library, plain_game):
    """The radio that is checked is the one the games list draws."""
    edition = Edition.objects.get(game=plain_game, is_default=True)
    add_release(
        edition=edition,
        library=owned_library,
        platform=Platform.objects.create(name="Steam"),
        release_date=TemporalValue.from_year(2011),
        is_default=False,
    )

    body = page(logged_in, plain_game)

    assert marks(body) == [
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
