"""What a reference looks like on a page."""

import pytest
from django.urls import reverse

from common.components import ExternalReferenceLinks
from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.external_references import state_external_references
from games.models import ExternalReference, Game, Platform
from games.reads.external_references import held_by, references_for

pytestmark = pytest.mark.django_db


def test_a_link_states_its_provider_and_its_key(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )
    references = list(ExternalReference.objects.filter(game=game))

    markup = str(ExternalReferenceLinks(references))

    assert 'href="https://www.wikidata.org/wiki/Q123"' in markup
    assert "Wikidata" in markup
    assert "Q123" in markup


def test_no_reference_renders_nothing_a_reader_reads_as_one():
    """Nothing at all, so a cell of a table stays empty."""
    assert str(ExternalReferenceLinks([])) == ""


def test_the_batch_read_takes_one_query_per_kind(
    owned_library, django_assert_num_queries
):
    games = [
        Game.objects.create(name=f"Game {index}", library=owned_library)
        for index in range(5)
    ]
    for index, game in enumerate(games):
        state_external_references(
            target=game,
            library=owned_library,
            keys={"wikidata": f"Q{index + 1}"},
        )

    with django_assert_num_queries(1):
        found = references_for(games)

    assert len(found) == 5


def test_a_marked_reference_is_not_read(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )
    state_external_references(target=game, library=owned_library, keys={"wikidata": ""})

    assert references_for([game]) == {}


def test_game_detail_shows_the_reference(client, owned_user):
    client.force_login(owned_user)
    game = Game.objects.create(name="Elite", library=owned_user.library)
    state_external_references(
        target=game, library=owned_user.library, keys={"wikidata": "Q123"}
    )

    response = client.get(game.get_absolute_url())

    assert "https://www.wikidata.org/wiki/Q123" in response.content.decode()


def test_the_platform_list_shows_the_reference(client, owned_user):
    client.force_login(owned_user)
    platform = Platform.objects.create(name="Amiga", library=owned_user.library)
    state_external_references(
        target=platform,
        library=owned_user.library,
        keys={"wikidata": "Q100047"},
    )

    response = client.get(reverse("games:list_platforms"))

    assert "https://www.wikidata.org/wiki/Q100047" in response.content.decode()


def test_a_row_with_no_reference_reads_as_an_empty_list(owned_library):
    """The one empty answer, so no reader states its own."""
    game = Game.objects.create(name="Elite", library=owned_library)

    assert held_by(references_for([game]), game.pk) == []


def test_gathering_one_row_does_not_write_into_another(owned_library):
    """Game detail extends what it reads; the map must not feel it."""
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )
    references = references_for([game])

    held_by(references, game.pk).append("not a reference")

    assert len(held_by(references, game.pk)) == 1


def test_the_batch_read_takes_one_query_for_each_kind_present(
    owned_library, stated_graph, django_assert_num_queries
):
    """Three kinds, thus three queries, and no query per row.

    Game detail hands this function a Game, its Editions and their
    Releases at once. A read that grouped by row rather than by
    kind would still pass the one-kind test above.
    """
    game, edition, release = stated_graph(
        Game(name="Elite", library=owned_library), owned_library
    )
    for target, key in ((game, "Q1"), (edition, "Q2"), (release, "Q3")):
        state_external_references(
            target=target, library=owned_library, keys={"wikidata": key}
        )

    with django_assert_num_queries(3):
        found = references_for([game, edition, release])

    assert len(found) == 3
    assert held_by(found, edition.pk)[0].provider_key == "Q2"


def test_the_editions_table_states_the_editions_and_the_releases_keys(
    client, owned_user
):
    """One cell gathers two kinds; nothing else on the page does.

    The section is drawn only for a graph that does not read
    plainly, thus a named Edition holding two Releases.
    """
    library = owned_user.library
    game = Game(name="Elite", library=library)
    game.save()
    written = state_catalog_graph(
        game=game,
        library=library,
        editions=[
            EditionState(
                key="edition-0",
                name="Deluxe",
                is_default=True,
                releases=(
                    ReleaseState(key="release-0", is_default=True),
                    ReleaseState(key="release-1"),
                ),
            )
        ],
    )
    entry = written.editions[0]
    state_external_references(
        target=entry.edition, library=library, keys={"wikidata": "Q2"}
    )
    state_external_references(
        target=entry.releases[1].release, library=library, keys={"wikidata": "Q3"}
    )
    client.force_login(owned_user)

    markup = client.get(game.get_absolute_url()).content.decode()

    assert "Editions of Elite" in markup
    assert "https://www.wikidata.org/wiki/Q2" in markup
    assert "https://www.wikidata.org/wiki/Q3" in markup
