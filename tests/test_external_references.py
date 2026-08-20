import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from games.external_references import (
    external_reference_url,
    normalize_provider_key,
    resolve_external_reference,
    save_external_reference,
    sync_game_wikidata,
)
from games.models import Edition, ExternalReference, Game, Platform, Release

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("provider", "provider_key", "expected"),
    [
        (" WikiData ", " q123 ", ("wikidata", "Q123")),
        ("wikidata", "Q1", ("wikidata", "Q1")),
        ("wikidata", "Q999999999999999999999999", ("wikidata", "Q999999999999999999999999")),
    ],
)
def test_provider_normalization_canonicalizes_valid_wikidata_tuples(
    provider, provider_key, expected
):
    """A permissive or noncanonical provider tuple would split one identity."""
    assert normalize_provider_key(provider=provider, provider_key=provider_key) == expected


@pytest.mark.parametrize(
    "provider_key",
    ["", "   ", "Q0", "Q01", "Q-1", "Q123x", "Q 123", "P123"],
)
def test_provider_normalization_rejects_invalid_wikidata_keys(provider_key):
    """A malformed key must not become an external identity or trusted link."""
    with pytest.raises(ValidationError, match="Wikidata entity ID"):
        normalize_provider_key(provider="wikidata", provider_key=provider_key)


def test_provider_normalization_rejects_unknown_provider():
    """An unregistered provider must not receive a generic key policy."""
    with pytest.raises(ValidationError, match="Unsupported external-reference provider"):
        normalize_provider_key(provider="igdb", provider_key="123")


def test_external_reference_url_uses_the_trusted_canonical_wikidata_template():
    """Provider-owned URL policies must produce the canonical Wikidata link."""
    assert (
        external_reference_url(
            provider=" WikiData ", entity_kind="game", provider_key=" q123 "
        )
        == "https://www.wikidata.org/wiki/Q123"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"provider": "igdb", "entity_kind": "game", "provider_key": "123"},
        {"provider": "wikidata", "entity_kind": "game", "provider_key": "Q 123"},
        {"provider": "wikidata", "entity_kind": "title", "provider_key": "Q123"},
    ],
)
def test_external_reference_url_rejects_untrusted_or_malformed_input(kwargs):
    """URL construction must never turn invalid input into an outbound URL."""
    with pytest.raises(ValidationError):
        external_reference_url(**kwargs)


def _catalog_targets():
    game = Game.objects.create(name="Reference Game")
    edition = Edition.objects.create(game=game)
    release = Release.objects.create(edition=edition)
    platform = Platform.objects.create(name="Reference Platform")
    return {
        "game": game,
        "edition": edition,
        "release": release,
        "platform": platform,
    }


@pytest.mark.parametrize("entity_kind", ["game", "edition", "release", "platform"])
def test_external_reference_persists_one_canonical_target_per_catalog_kind(
    entity_kind,
):
    """A wrong target field or noncanonical tuple would make identity ambiguous."""
    target = _catalog_targets()[entity_kind]
    reference = ExternalReference.objects.create(
        provider=" WikiData ",
        entity_kind=entity_kind,
        provider_key=" q123 ",
        **{entity_kind: target},
    )

    assert reference.pk.version == 7
    assert (
        reference.provider,
        reference.entity_kind,
        reference.provider_key,
    ) == ("wikidata", entity_kind, "Q123")
    assert [
        target_id
        for target_id in (
            reference.game_id,
            reference.edition_id,
            reference.release_id,
            reference.platform_id,
        )
        if target_id is not None
    ] == [target.pk]
    assert reference.target_uuid == target.pk
    assert reference.external_url == "https://www.wikidata.org/wiki/Q123"
    assert target.external_references.get() == reference


def test_external_reference_database_prevents_duplicate_provider_kind_key():
    """Removing the unique tuple constraint would permit two internal identities."""
    game = Game.objects.create(name="Duplicate Reference Game")
    ExternalReference.objects.create(
        provider="wikidata", entity_kind="game", provider_key="Q123", game=game
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        ExternalReference.objects.create(
            provider="wikidata",
            entity_kind="game",
            provider_key="Q123",
            game=Game.objects.create(name="Other Duplicate Reference Game"),
        )


def test_external_reference_save_cannot_reassign_a_persisted_tuple_target():
    """Changing a saved tuple's target would silently reassign external identity."""
    original = Game.objects.create(name="Original Reference Target")
    replacement = Game.objects.create(name="Replacement Reference Target")
    reference = ExternalReference.objects.create(
        provider="wikidata",
        entity_kind="game",
        provider_key="Q123",
        game=original,
    )

    reference.game = replacement

    with pytest.raises(ValidationError, match="already mapped"):
        reference.save()

    reference.refresh_from_db()
    assert reference.target_uuid == original.pk


def test_external_reference_save_cannot_reassign_an_existing_primary_key_target():
    """A fresh instance with an existing ID must not repoint its saved tuple."""
    original = Game.objects.create(name="Original Existing-ID Target")
    replacement = Game.objects.create(name="Replacement Existing-ID Target")
    reference = ExternalReference.objects.create(
        provider="wikidata",
        entity_kind="game",
        provider_key="Q123",
        game=original,
    )
    replacement_instance = ExternalReference(
        id=reference.pk,
        provider="wikidata",
        entity_kind="game",
        provider_key="Q123",
        game=replacement,
    )

    with pytest.raises(ValidationError, match="already mapped"):
        replacement_instance.save()

    reference.refresh_from_db()
    assert reference.target_uuid == original.pk


def test_external_reference_save_rejects_a_kind_target_mismatch():
    """Model saves must reject an edition label applied to a game target."""
    with pytest.raises(ValidationError, match="edition"):
        ExternalReference.objects.create(
            provider="wikidata",
            entity_kind="edition",
            provider_key="Q123",
            game=Game.objects.create(name="Mismatched Reference Game"),
        )


@pytest.mark.parametrize("scenario", ["mismatched_kind", "multiple_targets"])
def test_external_reference_database_rejects_bypassed_target_contract(scenario):
    """Bulk updates bypass clean(), so the check must protect target integrity."""
    targets = _catalog_targets()
    reference = ExternalReference.objects.create(
        provider="wikidata",
        entity_kind="game",
        provider_key="Q123",
        game=targets["game"],
    )

    updates = (
        {"entity_kind": "edition"}
        if scenario == "mismatched_kind"
        else {"edition_id": targets["edition"].pk}
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        ExternalReference.objects.filter(pk=reference.pk).update(**updates)


def test_external_reference_database_rejects_noncanonical_wikidata_key():
    """A bulk update must not store a key Python normalization would reject."""
    reference = ExternalReference.objects.create(
        provider="wikidata",
        entity_kind="game",
        provider_key="Q123",
        game=Game.objects.create(name="Canonical Key Game"),
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        ExternalReference.objects.filter(pk=reference.pk).update(provider_key="Q01")


@pytest.mark.parametrize("entity_kind", ["game", "edition", "release", "platform"])
def test_deleting_an_external_reference_target_cascades_only_its_reference(entity_kind):
    """A deleted target must remove only its own external identity mapping."""
    targets = _catalog_targets()
    target = targets[entity_kind]
    other = targets["platform"] if entity_kind != "platform" else targets["game"]
    reference = ExternalReference.objects.create(
        provider="wikidata",
        entity_kind=entity_kind,
        provider_key="Q123",
        **{entity_kind: target},
    )
    other_reference = ExternalReference.objects.create(
        provider="wikidata",
        entity_kind=("platform" if entity_kind != "platform" else "game"),
        provider_key="Q456",
        **{"platform" if entity_kind != "platform" else "game": other},
    )

    target.delete()

    assert not ExternalReference.objects.filter(pk=reference.pk).exists()
    assert ExternalReference.objects.filter(pk=other_reference.pk).exists()


@pytest.mark.parametrize("entity_kind", ["game", "edition", "release", "platform"])
def test_save_external_reference_derives_the_kind_and_target_field(entity_kind):
    """A caller-supplied kind could create a tuple pointing at the wrong table."""
    target = _catalog_targets()[entity_kind]

    reference = save_external_reference(
        provider=" WikiData ", provider_key=" q123 ", target=target
    )

    assert (
        reference.provider,
        reference.entity_kind,
        reference.provider_key,
        reference.target_uuid,
    ) == ("wikidata", entity_kind, "Q123", target.pk)
    assert getattr(reference, f"{entity_kind}_id") == target.pk


def test_save_external_reference_reuses_the_uuid_for_a_canonical_equivalent_tuple():
    """Case or surrounding whitespace must not create a second identity row."""
    game = Game.objects.create(name="Canonical Service Game")
    original = save_external_reference(
        provider="wikidata", provider_key="Q123", target=game
    )

    repeated = save_external_reference(
        provider=" WikiData ", provider_key=" q123 ", target=game
    )

    assert repeated.pk == original.pk
    assert ExternalReference.objects.count() == 1


def test_save_external_reference_refuses_to_reassign_a_tuple_to_another_target():
    """A second target must not take ownership of an existing provider tuple."""
    original = Game.objects.create(name="Original Service Target")
    replacement = Game.objects.create(name="Replacement Service Target")
    reference = save_external_reference(
        provider="wikidata", provider_key="Q123", target=original
    )

    with pytest.raises(ValidationError, match="already maps to another catalog target"):
        save_external_reference(
            provider="wikidata", provider_key="Q123", target=replacement
        )

    reference.refresh_from_db()
    assert reference.target_uuid == original.pk
    assert ExternalReference.objects.count() == 1


def test_save_external_reference_rejects_an_unsupported_target_class():
    """The write boundary must accept only the four catalog target models."""
    with pytest.raises(ValidationError, match="Unsupported catalog target"):
        save_external_reference(provider="wikidata", provider_key="Q123", target=object())


@pytest.mark.parametrize("entity_kind", ["game", "edition", "release", "platform"])
def test_resolve_external_reference_returns_only_the_requested_kind_uuid(entity_kind):
    """Resolving through the wrong kind would confuse catalog-level identities."""
    target = _catalog_targets()[entity_kind]
    save_external_reference(provider="wikidata", provider_key="Q123", target=target)

    resolved = resolve_external_reference(
        provider=" WikiData ", entity_kind=entity_kind, provider_key=" q123 "
    )

    assert resolved == target.pk


def test_resolve_external_reference_returns_none_without_cross_kind_fallback():
    """A Game reference must never resolve as an Edition reference with the same key."""
    game = Game.objects.create(name="No Cross-Kind Lookup")
    save_external_reference(provider="wikidata", provider_key="Q123", target=game)

    assert (
        resolve_external_reference(
            provider="wikidata", entity_kind="edition", provider_key="Q123"
        )
        is None
    )
    assert (
        resolve_external_reference(
            provider="wikidata", entity_kind="game", provider_key="Q456"
        )
        is None
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"provider": "igdb", "entity_kind": "game", "provider_key": "Q123"},
        {"provider": "wikidata", "entity_kind": "title", "provider_key": "Q123"},
        {"provider": "wikidata", "entity_kind": "game", "provider_key": "Q0"},
    ],
)
def test_resolve_external_reference_rejects_invalid_tuples(kwargs):
    """Invalid lookup input must not be silently broadened into a valid query."""
    with pytest.raises(ValidationError):
        resolve_external_reference(**kwargs)


def test_sync_game_wikidata_retains_the_existing_reference_for_an_unchanged_key():
    """Synchronizing the same legacy key must preserve its external-reference UUID."""
    game = Game.objects.create(name="Unchanged Wikidata", wikidata=" Q123 ")
    original = save_external_reference(
        provider="wikidata", provider_key="Q123", target=game
    )

    synced = sync_game_wikidata(game=game)

    assert synced is not None
    assert synced.pk == original.pk
    assert game.wikidata == "Q123"


def test_sync_game_wikidata_replaces_an_old_game_mapping_when_the_legacy_key_changes():
    """Keeping an obsolete mapping would make one Game advertise two legacy keys."""
    game = Game.objects.create(name="Changed Wikidata", wikidata="Q456")
    old = save_external_reference(provider="wikidata", provider_key="Q123", target=game)

    synced = sync_game_wikidata(game=game)

    assert synced is not None
    assert synced.provider_key == "Q456"
    assert not ExternalReference.objects.filter(pk=old.pk).exists()
    assert list(
        ExternalReference.objects.filter(game=game).values_list("provider_key", flat=True)
    ) == ["Q456"]


def test_sync_game_wikidata_removes_only_game_mappings_when_legacy_value_is_blank():
    """Clearing a Game's legacy key must not delete another catalog kind's identity."""
    targets = _catalog_targets()
    game_reference = save_external_reference(
        provider="wikidata", provider_key="Q123", target=targets["game"]
    )
    edition_reference = save_external_reference(
        provider="wikidata", provider_key="Q123", target=targets["edition"]
    )
    targets["game"].wikidata = "   "

    synced = sync_game_wikidata(game=targets["game"])

    assert synced is None
    assert not ExternalReference.objects.filter(pk=game_reference.pk).exists()
    assert ExternalReference.objects.filter(pk=edition_reference.pk).exists()
    assert targets["game"].wikidata == ""


def test_sync_game_wikidata_rolls_back_deletion_when_another_game_owns_the_key():
    """A conflicting replacement must restore the first Game's old mapping on rollback."""
    first = Game.objects.create(name="First Wikidata", wikidata="Q456")
    second = Game.objects.create(name="Second Wikidata", wikidata="Q456")
    first_reference = save_external_reference(
        provider="wikidata", provider_key="Q123", target=first
    )
    second_reference = save_external_reference(
        provider="wikidata", provider_key="Q456", target=second
    )

    with pytest.raises(ValidationError, match="already maps to another catalog target"):
        sync_game_wikidata(game=first)

    assert ExternalReference.objects.get(pk=first_reference.pk).target_uuid == first.pk
    assert ExternalReference.objects.get(pk=second_reference.pk).target_uuid == second.pk
