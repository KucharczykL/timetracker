"""What a removal does to the keys a row claimed (#976)."""

import pytest
from django.db import IntegrityError

from games.models import ExternalReference, Game, Platform, Release
from games.removal import remove, restore

pytestmark = pytest.mark.django_db


def _reference(game, provider_key):
    return ExternalReference.objects.create(
        provider="wikidata",
        entity_kind="game",
        provider_key=provider_key,
        game=game,
    )


def test_removing_a_game_marks_the_references_it_holds(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    reference = _reference(game, "Q123")

    remove(game)

    reference.refresh_from_db()
    assert reference.removed_at is not None


def test_a_second_game_may_take_the_key_a_removed_game_held(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    _reference(first, "Q123")
    remove(first)

    second = Game.objects.create(name="Elite II", library=owned_library)
    taken = _reference(second, "Q123")

    assert taken.game_id == second.pk


def test_restoring_a_game_takes_back_a_key_that_is_free(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    reference = _reference(game, "Q123")
    remove(game)

    restore(game)

    reference.refresh_from_db()
    assert reference.removed_at is None


def test_restoring_leaves_a_key_another_record_has_taken(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    reference = _reference(first, "Q123")
    remove(first)
    second = Game.objects.create(name="Elite II", library=owned_library)
    _reference(second, "Q123")

    restore(first)

    reference.refresh_from_db()
    first.refresh_from_db()
    assert first.removed_at is None
    assert reference.removed_at is not None


def test_a_removed_platform_lets_go_of_its_key(owned_library):
    platform = Platform.objects.create(name="Amiga", library=owned_library)
    reference = ExternalReference.objects.create(
        provider="wikidata",
        entity_kind="platform",
        provider_key="Q100047",
        platform=platform,
    )

    remove(platform)

    reference.refresh_from_db()
    assert reference.removed_at is not None


def test_a_live_release_under_a_removed_game_keeps_its_key(owned_library, stated_graph):
    """Only the row a person removed lets go.

    A Game's mark hides its children without stamping them, thus
    their references are not stamped either, and a restore brings
    the whole subtree back unchanged.
    """
    game, edition, release = stated_graph(
        Game(name="Elite", library=owned_library), owned_library
    )
    reference = ExternalReference.objects.create(
        provider="wikidata",
        entity_kind="release",
        provider_key="Q999",
        release=release,
    )

    remove(game)

    reference.refresh_from_db()
    assert reference.removed_at is None

    #: Still claimed, thus no other Release may take it. The tuple
    #: constraint scopes by kind, so the collision must be stated
    #: against a Release rather than against any other row.
    other = Release.objects.create(edition=edition)
    with pytest.raises(IntegrityError):
        ExternalReference.objects.create(
            provider="wikidata",
            entity_kind="release",
            provider_key="Q999",
            release=other,
        )
