import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.timezone import now

from games.external_references import (
    KEY_TAKEN,
    OTHER_LIBRARY_TARGET,
    PROVIDER_POLICIES,
    REMOVED_TARGET,
    SHARED_TARGET,
    ReferencesRefused,
    external_reference_url,
    mirror_game_wikidata,
    normalize_provider_key,
    provider_labels,
    resolve_external_reference,
    save_external_reference,
    state_external_references,
)
from games.models import Edition, ExternalReference, Game, Platform, Release
from games.removal import remove, restore

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("provider", "provider_key", "expected"),
    [
        (" WikiData ", " q123 ", ("wikidata", "Q123")),
        ("wikidata", "Q1", ("wikidata", "Q1")),
        (
            "wikidata",
            "Q999999999999999999999999",
            ("wikidata", "Q999999999999999999999999"),
        ),
    ],
)
def test_provider_normalization_canonicalizes_valid_wikidata_tuples(
    provider, provider_key, expected
):
    """A permissive or noncanonical provider tuple would split one identity."""
    assert (
        normalize_provider_key(provider=provider, provider_key=provider_key) == expected
    )


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
    with pytest.raises(
        ValidationError, match="Unsupported external-reference provider"
    ):
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


def test_external_reference_save_cannot_reassign_a_same_uuid_target_across_kinds():
    """A shared UUID in separate target tables must not hide a kind reassignment."""
    original = Game.objects.create(name="Original Cross-Kind Target")
    edition = Edition.objects.create(
        id=original.pk,
        game=Game.objects.create(name="Cross-Kind Edition Game"),
    )
    reference = ExternalReference.objects.create(
        provider="wikidata",
        entity_kind="game",
        provider_key="Q123",
        game=original,
    )

    reference.entity_kind = "edition"
    reference.game = None
    reference.edition = edition

    with pytest.raises(ValidationError, match="already mapped"):
        reference.save()

    reference.refresh_from_db()
    assert reference.entity_kind == "game"
    assert reference.game_id == original.pk


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

    with pytest.raises(ValidationError) as exc_info:
        save_external_reference(
            provider="wikidata", provider_key="Q123", target=replacement
        )

    assert exc_info.value.message_dict == {
        "provider_key": [
            "This external reference already maps to another catalog target."
        ]
    }
    reference.refresh_from_db()
    assert reference.target_uuid == original.pk
    assert ExternalReference.objects.count() == 1


def test_save_external_reference_rejects_an_unsupported_target_class():
    """The write boundary must accept only the four catalog target models."""
    with pytest.raises(ValidationError, match="Unsupported catalog target"):
        save_external_reference(
            provider="wikidata", provider_key="Q123", target=object()
        )


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


def test_the_mirror_writes_the_column_from_the_live_reference(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )

    mirror_game_wikidata(game)

    game.refresh_from_db()
    assert game.wikidata == "Q123"


def test_the_mirror_empties_the_column_when_no_reference_is_live(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library, wikidata="Q1")

    mirror_game_wikidata(game)

    game.refresh_from_db()
    assert game.wikidata == ""


def test_the_mirror_ignores_a_marked_reference(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )
    state_external_references(target=game, library=owned_library, keys={"wikidata": ""})

    mirror_game_wikidata(game)

    game.refresh_from_db()
    assert game.wikidata == ""


def test_a_removed_game_keeps_the_column_a_restore_wants(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )
    mirror_game_wikidata(game)

    remove(game)

    game.refresh_from_db()
    assert game.wikidata == "Q123"


def test_a_restore_that_loses_the_key_empties_the_column(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=first, library=owned_library, keys={"wikidata": "Q123"}
    )
    mirror_game_wikidata(first)
    remove(first)
    second = Game.objects.create(name="Elite II", library=owned_library)
    state_external_references(
        target=second, library=owned_library, keys={"wikidata": "Q123"}
    )

    restore(first)

    first.refresh_from_db()
    assert first.wikidata == ""


def test_a_marked_reference_lets_go_of_its_provider_key(owned_library):
    """#976: a removed row does not hold a key against a later entry."""
    first = Game.objects.create(name="Elite", library=owned_library)
    second = Game.objects.create(name="Elite II", library=owned_library)
    reference = ExternalReference.objects.create(
        provider="wikidata", entity_kind="game", provider_key="Q123", game=first
    )
    ExternalReference.objects.filter(pk=reference.pk).update(removed_at=now())

    taken = ExternalReference.objects.create(
        provider="wikidata", entity_kind="game", provider_key="Q123", game=second
    )

    assert taken.pk != reference.pk


def test_two_live_references_of_one_tuple_are_refused(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    second = Game.objects.create(name="Elite II", library=owned_library)
    ExternalReference.objects.create(
        provider="wikidata", entity_kind="game", provider_key="Q123", game=first
    )

    with pytest.raises(IntegrityError):
        ExternalReference.objects.create(
            provider="wikidata", entity_kind="game", provider_key="Q123", game=second
        )


def test_one_live_key_per_record_per_provider(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    ExternalReference.objects.create(
        provider="wikidata", entity_kind="game", provider_key="Q123", game=game
    )

    with pytest.raises(IntegrityError):
        ExternalReference.objects.create(
            provider="wikidata", entity_kind="game", provider_key="Q124", game=game
        )


def test_a_marked_key_frees_the_record_for_another(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    first = ExternalReference.objects.create(
        provider="wikidata", entity_kind="game", provider_key="Q123", game=game
    )
    ExternalReference.objects.filter(pk=first.pk).update(removed_at=now())

    second = ExternalReference.objects.create(
        provider="wikidata", entity_kind="game", provider_key="Q124", game=game
    )

    assert second.pk != first.pk


def test_every_registered_policy_states_a_label_and_a_hint():
    """A provider is one registry entry, UI included."""
    for provider, policy in PROVIDER_POLICIES.items():
        assert policy.label, provider
        assert policy.hint, provider


def test_the_wikidata_policy_reads_as_a_person_would_say_it():
    assert PROVIDER_POLICIES["wikidata"].label == "Wikidata"
    assert "Q123" in PROVIDER_POLICIES["wikidata"].hint


def test_provider_labels_are_the_registry_in_order():
    assert provider_labels() == {"wikidata": "Wikidata"}


def test_stating_a_key_creates_the_reference(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)

    state_external_references(
        target=game, library=owned_library, keys={"wikidata": " q123 "}
    )

    reference = ExternalReference.objects.get(game=game, removed_at=None)
    assert reference.provider_key == "Q123"


def test_stating_a_blank_key_marks_the_reference(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )

    state_external_references(target=game, library=owned_library, keys={"wikidata": ""})

    assert not ExternalReference.objects.filter(game=game, removed_at=None).exists()
    assert ExternalReference.objects.filter(game=game).exists()


def test_stating_a_new_key_replaces_the_old_one(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )

    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q124"}
    )

    live = ExternalReference.objects.get(game=game, removed_at=None)
    assert live.provider_key == "Q124"


def test_a_provider_the_caller_does_not_name_is_left_alone(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )

    state_external_references(target=game, library=owned_library, keys={})

    assert ExternalReference.objects.filter(game=game, removed_at=None).exists()


def test_a_key_another_record_holds_is_refused(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    second = Game.objects.create(name="Elite II", library=owned_library)
    state_external_references(
        target=first, library=owned_library, keys={"wikidata": "Q123"}
    )

    with pytest.raises(ReferencesRefused) as refusal:
        state_external_references(
            target=second, library=owned_library, keys={"wikidata": "Q123"}
        )

    assert refusal.value.provider == "wikidata"
    assert refusal.value.messages[0] == KEY_TAKEN
    assert (
        ExternalReference.objects.get(provider_key="Q123", removed_at=None).game_id
        == first.pk
    )


def test_a_shared_target_is_refused(owned_library):
    shared = Game.objects.create(name="Elite", library=None)

    with pytest.raises(ReferencesRefused) as refusal:
        state_external_references(
            target=shared, library=owned_library, keys={"wikidata": "Q123"}
        )

    assert refusal.value.messages[0] == SHARED_TARGET


def test_another_librarys_target_is_refused(owned_library, django_user_model):
    other = django_user_model.objects.create_user(
        username="other", password="p"
    ).library
    theirs = Game.objects.create(name="Elite", library=other)

    with pytest.raises(ReferencesRefused) as refusal:
        state_external_references(
            target=theirs, library=owned_library, keys={"wikidata": "Q123"}
        )

    assert refusal.value.messages[0] == OTHER_LIBRARY_TARGET


def test_a_removed_target_is_refused(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    remove(game)

    with pytest.raises(ReferencesRefused) as refusal:
        state_external_references(
            target=game, library=owned_library, keys={"wikidata": "Q123"}
        )

    assert refusal.value.messages[0] == REMOVED_TARGET


def test_a_malformed_key_is_refused_under_its_provider(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)

    with pytest.raises(ReferencesRefused) as refusal:
        state_external_references(
            target=game, library=owned_library, keys={"wikidata": "banana"}
        )

    assert refusal.value.provider == "wikidata"
    assert "Q123" in refusal.value.messages[0]


def test_nothing_is_written_when_one_provider_is_refused(owned_library):
    """Every refusal is read before anything is written."""
    game = Game.objects.create(name="Elite", library=owned_library)

    with pytest.raises(ReferencesRefused):
        state_external_references(
            target=game, library=owned_library, keys={"wikidata": "banana"}
        )

    assert not ExternalReference.objects.filter(game=game).exists()
