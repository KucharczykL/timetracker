"""What a removal does to the keys a row claimed (#976)."""

import pytest
from django.db import IntegrityError

from games.external_references import state_external_references
from games.models import ExternalReference, Game, Platform, Release
from games.removal import remove, restore

pytestmark = pytest.mark.django_db


def _reference(kind, row, provider_key):
    """One live reference of one kind, on the row it names."""
    return ExternalReference.objects.create(
        provider="wikidata",
        entity_kind=kind,
        provider_key=provider_key,
        **{kind: row},
    )


def test_removing_a_game_marks_the_references_it_holds(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    reference = _reference("game", game, "Q123")

    remove(game)

    reference.refresh_from_db()
    assert reference.removed_at is not None


def test_a_second_game_may_take_the_key_a_removed_game_held(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    _reference("game", first, "Q123")
    remove(first)

    second = Game.objects.create(name="Elite II", library=owned_library)
    taken = _reference("game", second, "Q123")

    assert taken.game_id == second.pk


def test_restoring_a_game_takes_back_a_key_that_is_free(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    reference = _reference("game", game, "Q123")
    remove(game)

    restore(game)

    reference.refresh_from_db()
    assert reference.removed_at is None


def test_restoring_leaves_a_key_another_record_has_taken(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    reference = _reference("game", first, "Q123")
    remove(first)
    second = Game.objects.create(name="Elite II", library=owned_library)
    _reference("game", second, "Q123")

    restore(first)

    reference.refresh_from_db()
    first.refresh_from_db()
    assert first.removed_at is None
    assert reference.removed_at is not None


def test_restoring_takes_back_only_the_key_the_row_went_out_with(owned_library):
    """A corrected key stays corrected.

    Changing a key marks the row the record used to state. That
    mark is not the removal's, thus a restore must leave it, or
    the record comes back holding two keys of one provider.
    """
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q1"}
    )
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q2"}
    )
    remove(game)

    restore(game)

    live = ExternalReference.objects.filter(game=game, removed_at__isnull=True)
    assert list(live.values_list("provider_key", flat=True)) == ["Q2"]


def test_restoring_does_not_state_a_key_a_person_let_go_of(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q1"}
    )
    state_external_references(target=game, library=owned_library, keys={"wikidata": ""})
    remove(game)

    restore(game)

    game.refresh_from_db()
    assert game.wikidata == ""
    assert not ExternalReference.objects.filter(
        game=game, removed_at__isnull=True
    ).exists()


def test_a_removed_platform_lets_go_of_its_key(owned_library):
    platform = Platform.objects.create(name="Amiga", library=owned_library)
    reference = _reference("platform", platform, "Q100047")

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
    reference = _reference("release", release, "Q999")

    remove(game)

    reference.refresh_from_db()
    assert reference.removed_at is None

    #: Still claimed, thus no other Release may take it. The tuple
    #: constraint scopes by kind, so the collision must be stated
    #: against a Release rather than against any other row.
    other = Release.objects.create(edition=edition)
    with pytest.raises(IntegrityError):
        _reference("release", other, "Q999")


def test_removing_an_edition_marks_the_reference_it_holds(owned_library, stated_graph):
    _, edition, _ = stated_graph(
        Game(name="Elite", library=owned_library), owned_library
    )
    reference = _reference("edition", edition, "Q500")

    remove(edition)

    reference.refresh_from_db()
    assert reference.removed_at is not None


def test_removing_a_release_marks_the_reference_it_holds(owned_library, stated_graph):
    _, _, release = stated_graph(
        Game(name="Elite", library=owned_library), owned_library
    )
    reference = _reference("release", release, "Q501")

    remove(release)

    reference.refresh_from_db()
    assert reference.removed_at is not None


def test_restoring_an_edition_takes_back_a_key_that_is_free(
    owned_library, stated_graph
):
    _, edition, _ = stated_graph(
        Game(name="Elite", library=owned_library), owned_library
    )
    reference = _reference("edition", edition, "Q500")
    remove(edition)

    restore(edition)

    reference.refresh_from_db()
    assert reference.removed_at is None


def test_restoring_a_platform_takes_back_a_key_that_is_free(owned_library):
    platform = Platform.objects.create(name="Amiga", library=owned_library)
    reference = _reference("platform", platform, "Q100047")
    remove(platform)

    restore(platform)

    reference.refresh_from_db()
    assert reference.removed_at is None


def test_restoring_a_release_leaves_a_key_another_release_took(
    owned_library, stated_graph
):
    """The taken-meanwhile branch, on a kind that is not a Game.

    Freedom is read per provider, kind and key, thus the Release
    that came back must read the Release that took its key, and
    nothing else that happens to state the same one.
    """
    _, edition, release = stated_graph(
        Game(name="Elite", library=owned_library), owned_library
    )
    reference = _reference("release", release, "Q501")
    remove(release)
    other = Release.objects.create(edition=edition)
    _reference("release", other, "Q501")

    restore(release)

    reference.refresh_from_db()
    release.refresh_from_db()
    assert release.removed_at is None
    assert reference.removed_at is not None
