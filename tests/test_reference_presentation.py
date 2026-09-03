"""What a reference looks like on a page."""

import pytest
from django.urls import reverse

from common.components import ExternalReferenceLinks
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


def test_no_reference_renders_nothing_a_reader_reads_as_one(owned_library):
    assert str(ExternalReferenceLinks([])).strip() in ("", "—")


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
