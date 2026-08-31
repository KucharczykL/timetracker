import uuid
from typing import Any, NotRequired, TypedDict

import pytest
from django.db import transaction
from pydantic import ConfigDict, with_config

from games.events.append import canonical_json, lock_stream
from games.events.envelope import RecordedEvent
from games.events.references import (
    DEFAULT_REFERENCE_KINDS,
    Reference,
    ReferenceArity,
    ReferenceFieldUnsupported,
    ReferenceKind,
    ReferenceKindRegistry,
    Resolution,
    UnknownReferenceKind,
    UnmappedReferenceModel,
    canonical_uuid_text,
    capture_reference,
    reference_fields,
    references_in,
)
from games.events.vocabulary import (
    EventSpec,
    EventTypeRegistry,
    PayloadInvalid,
)
from games.events.wiring import EventWiring
from games.models import Device, Edition, Game, LibraryEvent, Platform, Release

STRICT_CONFIG = ConfigDict(extra="forbid", strict=True)


@with_config(STRICT_CONFIG)
class OneReferencePayload(TypedDict):
    device: Reference
    note: str


@with_config(STRICT_CONFIG)
class EveryArityPayload(TypedDict):
    device: Reference
    game: Reference | None
    platforms: list[Reference]
    absent: NotRequired[Reference]
    tags: list[str]


@with_config(STRICT_CONFIG)
class NoReferencePayload(TypedDict):
    probe: bool


@with_config(STRICT_CONFIG)
class HiddenReferencePayload(TypedDict):
    """A reference nothing could enumerate."""

    by_slot: dict[str, Reference]


@with_config(STRICT_CONFIG)
class NestedSchema(TypedDict):
    device: Reference


@with_config(STRICT_CONFIG)
class BuriedReferencePayload(TypedDict):
    """A reference one schema deeper."""

    inner: NestedSchema


DEVICE_RECORDED = EventSpec(
    "library.device.recorded", aggregate_type="probe", payload=OneReferencePayload
)
EVERYTHING_RECORDED = EventSpec(
    "library.everything.recorded", aggregate_type="probe", payload=EveryArityPayload
)
PROBE_RECORDED = EventSpec(
    "library.probe.recorded", aggregate_type="probe", payload=NoReferencePayload
)

#: This module's own vocabulary, never production's.
EVENT_TYPES = EventTypeRegistry()
for registered_spec in (DEVICE_RECORDED, EVERYTHING_RECORDED, PROBE_RECORDED):
    EVENT_TYPES.register(registered_spec)
WIRING = EventWiring(event_types=EVENT_TYPES)


@pytest.fixture
def device(owned_library):
    return Device.objects.create(
        library=owned_library, name="Steam Deck", type=Device.HANDHELD
    )


@pytest.fixture
def game(owned_library):
    return Game.objects.create(
        library=owned_library, name="Baldur's Gate 3", year_released=2023
    )


@pytest.fixture
def platform(owned_library):
    return Platform.objects.create(
        library=owned_library, name="Steam", group="PC storefronts"
    )


# --- the identity text ------------------------------------------------------


def test_canonical_text_passes_through():
    identity = str(uuid.uuid7())
    assert canonical_uuid_text(identity) == identity


#: Literal: xdist workers must collect identical ids.
A_UUIDV7 = "0198c0d3-2b4e-7a10-9f3c-5c1d2e3f4a5b"


@pytest.mark.parametrize(
    "text",
    [
        "not-a-uuid",
        "",
        "3fd1f686-c31d-4df7-a850-31f8f7849428",  # a v4
        A_UUIDV7.upper(),
        "{" + A_UUIDV7 + "}",
        f"urn:uuid:{A_UUIDV7}",
        A_UUIDV7.replace("-", ""),
    ],
)
def test_uncanonical_text_is_refused(text):
    with pytest.raises(ValueError):
        canonical_uuid_text(text)


def test_a_refused_identity_names_the_form_it_would_be_recorded_in():
    identity = uuid.uuid7()
    with pytest.raises(ValueError, match=str(identity)):
        canonical_uuid_text(str(identity).upper())


# --- the recorded shape -----------------------------------------------------


def _validated(payload: dict[str, Any]) -> dict[str, Any]:
    return EVENT_TYPES.validate(DEVICE_RECORDED.event_type, payload)


def _reference() -> Reference:
    return Reference(
        kind="device", id=str(uuid.uuid7()), label="Steam Deck", detail="Handheld"
    )


def test_a_well_formed_reference_validates():
    payload = {"device": _reference(), "note": "moved"}
    assert _validated(payload) == payload


def test_an_extra_key_is_refused():
    reference = {**_reference(), "colour": "black"}
    with pytest.raises(PayloadInvalid):
        _validated({"device": reference, "note": ""})


def test_a_missing_key_is_refused():
    reference = _reference()
    del reference["detail"]
    with pytest.raises(PayloadInvalid):
        _validated({"device": reference, "note": ""})


def test_a_non_text_value_is_refused():
    reference = {**_reference(), "label": 7}
    with pytest.raises(PayloadInvalid):
        _validated({"device": reference, "note": ""})


def test_an_uncanonical_identity_is_refused_by_the_payload_schema():
    reference = {**_reference(), "id": str(uuid.uuid7()).upper()}
    with pytest.raises(PayloadInvalid):
        _validated({"device": reference, "note": ""})


def test_an_unregistered_kind_is_refused_at_validation():
    reference = {**_reference(), "kind": "catalog.gmae"}
    with pytest.raises(PayloadInvalid, match="catalog.gmae"):
        _validated({"device": reference, "note": ""})


def test_a_reference_survives_canonical_json_unchanged():
    reference = _reference()
    assert canonical_json(reference, label="reference") == reference


# --- capturing --------------------------------------------------------------


@pytest.mark.django_db
def test_a_device_captures_its_name_and_type(device):
    assert capture_reference(device) == Reference(
        kind="device", id=str(device.pk), label="Steam Deck", detail="Handheld"
    )


@pytest.mark.django_db
def test_a_game_captures_its_name_and_year(game):
    assert capture_reference(game) == Reference(
        kind="catalog.game",
        id=str(game.pk),
        label="Baldur's Gate 3",
        detail="2023",
    )


@pytest.mark.django_db
def test_a_game_without_a_year_captures_an_empty_detail(owned_library):
    undated = Game.objects.create(library=owned_library, name="Unknown Quantity")
    assert capture_reference(undated)["detail"] == ""


@pytest.mark.django_db
def test_a_platform_captures_its_name_and_group(platform):
    assert capture_reference(platform) == Reference(
        kind="catalog.platform",
        id=str(platform.pk),
        label="Steam",
        detail="PC storefronts",
    )


@pytest.mark.django_db
def test_a_release_captures_the_games_name_and_its_platform(game, platform):
    """A Release has no words of its own; both are joins."""
    release = Release.objects.create(
        edition=Edition.objects.create(game=game), platform=platform
    )

    assert capture_reference(release) == Reference(
        kind="catalog.release",
        id=str(release.pk),
        label="Baldur's Gate 3",
        detail="Steam",
    )


@pytest.mark.django_db
def test_a_release_on_no_platform_captures_an_empty_detail(game):
    release = Release.objects.create(edition=Edition.objects.create(game=game))

    assert capture_reference(release)["detail"] == ""


@pytest.mark.django_db
def test_every_captured_reference_validates_as_one(device, game, platform):
    for instance in (device, game, platform):
        payload = {"device": capture_reference(instance), "note": ""}
        assert _validated(payload) == payload


@pytest.mark.django_db
def test_a_model_no_kind_captures_is_refused(game):
    edition = Edition.objects.create(game=game)
    with pytest.raises(UnmappedReferenceModel, match="Edition"):
        capture_reference(edition)


# --- the kind registry ------------------------------------------------------


def test_a_duplicate_kind_name_is_refused():
    kinds = ReferenceKindRegistry()
    kinds.register(
        ReferenceKind(
            name="device",
            model=Device,
            capture=lambda instance: _reference(),
            resolution=Resolution.REQUIRED,
        )
    )
    with pytest.raises(ValueError, match="already registered"):
        kinds.register(
            ReferenceKind(
                name="device",
                model=Game,
                capture=lambda instance: _reference(),
                resolution=Resolution.REQUIRED,
            )
        )


def test_a_second_kind_for_one_model_is_refused():
    kinds = ReferenceKindRegistry()
    kinds.register(
        ReferenceKind(
            name="device",
            model=Device,
            capture=lambda instance: _reference(),
            resolution=Resolution.REQUIRED,
        )
    )
    with pytest.raises(ValueError, match="already captured"):
        kinds.register(
            ReferenceKind(
                name="hardware",
                model=Device,
                capture=lambda instance: _reference(),
                resolution=Resolution.REQUIRED,
            )
        )


def test_an_empty_kind_name_is_refused():
    kinds = ReferenceKindRegistry()
    with pytest.raises(ValueError, match="empty reference kind"):
        kinds.register(
            ReferenceKind(
                name="",
                model=Device,
                capture=lambda instance: _reference(),
                resolution=Resolution.REQUIRED,
            )
        )


def test_an_unknown_kind_name_is_refused():
    with pytest.raises(UnknownReferenceKind, match="catalog.publisher"):
        DEFAULT_REFERENCE_KINDS.kind_for("catalog.publisher")


def test_every_shipped_kind_must_resolve_at_replay():
    for name in ("device", "catalog.game", "catalog.platform", "catalog.release"):
        assert DEFAULT_REFERENCE_KINDS.kind_for(name).resolution is Resolution.REQUIRED


def test_a_vocabulary_validates_against_the_kinds_it_was_given():
    """An injected registry, rehearsing an unshipped kind."""
    kinds = ReferenceKindRegistry()
    kinds.register(
        ReferenceKind(
            name="catalog.publisher",
            model=Device,
            capture=lambda instance: _reference(),
            resolution=Resolution.EVIDENCE_ONLY,
        )
    )
    own = EventTypeRegistry(reference_kinds=kinds)
    own.register(DEVICE_RECORDED)
    assert own.reference_kinds is kinds

    payload = {
        "device": {**_reference(), "kind": "catalog.publisher"},
        "note": "",
    }
    assert own.validate(DEVICE_RECORDED.event_type, payload) == payload
    #: The same payload, against production's kinds.
    with pytest.raises(PayloadInvalid, match="catalog.publisher"):
        _validated(payload)


# --- enumeration ------------------------------------------------------------


def test_every_declared_arity_is_found():
    assert reference_fields(EveryArityPayload) == {
        "device": ReferenceArity.SINGLE,
        "game": ReferenceArity.OPTIONAL,
        "platforms": ReferenceArity.SEQUENCE,
        "absent": ReferenceArity.SINGLE,
    }


def test_a_payload_without_references_declares_none():
    assert reference_fields(NoReferencePayload) == {}


def test_a_reference_nothing_could_enumerate_is_refused_at_registration():
    hidden = EventSpec(
        "library.hidden.recorded",
        aggregate_type="probe",
        payload=HiddenReferencePayload,
    )
    with pytest.raises(ReferenceFieldUnsupported, match="list\\[Reference\\]"):
        EventTypeRegistry().register(hidden)


def test_a_reference_buried_in_a_nested_schema_is_refused_at_registration():
    """The nesting `get_args` cannot see into."""
    buried = EventSpec(
        "library.buried.recorded",
        aggregate_type="probe",
        payload=BuriedReferencePayload,
    )
    with pytest.raises(ReferenceFieldUnsupported, match="NestedSchema"):
        EventTypeRegistry().register(buried)


def test_references_are_read_from_every_declared_field():
    device, game, first, second = (_reference() for _ in range(4))
    payload = {
        "device": device,
        "game": game,
        "platforms": [first, second],
        "tags": ["moved"],
    }
    found = tuple(references_in(payload, reference_fields(EveryArityPayload)))
    assert found == (
        ("device", device),
        ("game", game),
        ("platforms", first),
        ("platforms", second),
    )


def test_an_absent_or_null_field_yields_nothing():
    payload = {"device": _reference(), "game": None, "platforms": [], "tags": []}
    found = tuple(references_in(payload, reference_fields(EveryArityPayload)))
    assert [entry.key for entry in found] == ["device"]


def test_the_registry_reads_a_recorded_payload():
    reference = _reference()
    found = EVENT_TYPES.references_in(
        DEVICE_RECORDED.event_type, {"device": reference, "note": ""}
    )
    assert found == (("device", reference),)


# --- through an append ------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_snapshot_round_trips_through_an_append(owned_user, owned_library, device):
    reference = capture_reference(device)
    with transaction.atomic():
        stream = lock_stream(owned_library)
        result = stream.append(
            [
                DEVICE_RECORDED.new(
                    aggregate_id=uuid.uuid7(),
                    payload=OneReferencePayload(device=reference, note="moved"),
                )
            ],
            actor=owned_user,
            correlation_id=uuid.uuid7(),
            idempotency_key="reference-round-trip",
            wiring=WIRING,
        )

    row = LibraryEvent.objects.get(pk=result.events[0].pk)
    assert RecordedEvent.from_row(row).payload["device"] == reference


@pytest.mark.django_db(transaction=True)
def test_a_snapshot_is_evidence_rather_than_the_current_row(
    owned_user, owned_library, device
):
    reference = capture_reference(device)
    with transaction.atomic():
        stream = lock_stream(owned_library)
        result = stream.append(
            [
                DEVICE_RECORDED.new(
                    aggregate_id=uuid.uuid7(),
                    payload=OneReferencePayload(device=reference, note="moved"),
                )
            ],
            actor=owned_user,
            correlation_id=uuid.uuid7(),
            idempotency_key="reference-evidence",
            wiring=WIRING,
        )

    device.name = "Steam Deck OLED"
    device.save(update_fields=["name"])

    recorded = result.events[0]
    recorded.refresh_from_db()
    assert recorded.payload["device"]["label"] == "Steam Deck"
    assert recorded.payload["device"]["id"] == str(device.pk)
    assert Device.objects.get(pk=device.pk).name == "Steam Deck OLED"
