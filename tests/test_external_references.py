import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from games.external_references import (
    external_reference_url,
    normalize_provider_key,
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
