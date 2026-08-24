import uuid
from typing import Any, TypedDict

import pytest
from pydantic import ConfigDict, with_config

from games.events.vocabulary import (
    DEFAULT_EVENT_TYPES,
    EVENT_TYPE_MAX_LENGTH,
    EventNameInvalid,
    EventSpec,
    EventTypeRegistry,
    PayloadInvalid,
    SchemaNotConfigured,
    UnregisteredEventType,
    VersionNotUpcastable,
)

STRICT_CONFIG = ConfigDict(extra="forbid", strict=True)


@with_config(STRICT_CONFIG)
class ProbePayload(TypedDict):
    game_id: str
    count: int


@with_config(STRICT_CONFIG)
class RatioPayload(TypedDict):
    ratio: float


class UnconfiguredPayload(TypedDict):
    game_id: str


@with_config(ConfigDict(extra="allow", strict=True))
class PermissivePayload(TypedDict):
    game_id: str


@with_config(ConfigDict(extra="forbid"))
class LenientPayload(TypedDict):
    game_id: str


class NotATypedDict:
    game_id: str


PROBE_RECORDED = EventSpec(
    "library.probe.recorded",
    aggregate_type="probe",
    payload=ProbePayload,
)
RATIO_RECORDED = EventSpec(
    "library.ratio.recorded",
    aggregate_type="probe",
    payload=RatioPayload,
)


@pytest.fixture
def registry() -> EventTypeRegistry:
    built = EventTypeRegistry()
    built.register(PROBE_RECORDED)
    return built


def test_a_registered_spec_round_trips(registry: EventTypeRegistry):
    assert registry.spec_for("library.probe.recorded") is PROBE_RECORDED
    assert "library.probe.recorded" in registry


def test_spec_for_an_unknown_event_type_refuses(registry: EventTypeRegistry):
    with pytest.raises(UnregisteredEventType) as refusal:
        registry.spec_for("library.nothing.happened")

    assert "library.nothing.happened" in str(refusal.value)
    assert "library.nothing.happened" not in registry


def test_registering_a_second_spec_for_one_event_type_refuses(
    registry: EventTypeRegistry,
):
    twin = EventSpec(
        "library.probe.recorded",
        aggregate_type="something-else",
        payload=ProbePayload,
    )

    with pytest.raises(ValueError) as refusal:
        registry.register(twin)

    #: Exactly ValueError: UnregisteredEventType would pass too.
    assert refusal.type is ValueError
    assert "already registered" in str(refusal.value)
    assert "library.probe.recorded" in str(refusal.value)


def test_a_schema_that_is_not_a_typed_dict_refuses():
    with pytest.raises(TypeError) as refusal:
        EventTypeRegistry().register(
            EventSpec(
                "library.probe.recorded",
                aggregate_type="probe",
                payload=NotATypedDict,
            )
        )

    assert "TypedDict" in str(refusal.value)


@pytest.mark.parametrize(
    ("payload", "wrong_key"),
    [
        (UnconfiguredPayload, "with_config"),
        (PermissivePayload, "extra"),
        (LenientPayload, "strict"),
    ],
    ids=["unconfigured", "extra-allow", "not-strict"],
)
def test_a_schema_configured_wrong_refuses(payload: Any, wrong_key: str):
    with pytest.raises(SchemaNotConfigured) as refusal:
        EventTypeRegistry().register(
            EventSpec(
                "library.probe.recorded",
                aggregate_type="probe",
                payload=payload,
            )
        )

    assert wrong_key in str(refusal.value)
    assert "library.probe.recorded" in str(refusal.value)


def test_an_empty_event_type_refuses():
    """Refused here, or as an IntegrityError later."""
    with pytest.raises(EventNameInvalid) as refusal:
        EventTypeRegistry().register(
            EventSpec("", aggregate_type="probe", payload=ProbePayload)
        )

    assert "empty event type" in str(refusal.value)


def test_an_event_type_wider_than_the_column_refuses():
    """The length is read off the column."""
    too_long = "x" * (EVENT_TYPE_MAX_LENGTH + 1)

    with pytest.raises(EventNameInvalid) as refusal:
        EventTypeRegistry().register(
            EventSpec(too_long, aggregate_type="probe", payload=ProbePayload)
        )

    assert str(EVENT_TYPE_MAX_LENGTH) in str(refusal.value)
    assert str(len(too_long)) in str(refusal.value)


def test_an_empty_aggregate_type_refuses():
    """The registry is this string's only gate."""
    with pytest.raises(EventNameInvalid) as refusal:
        EventTypeRegistry().register(
            EventSpec("library.probe.recorded", aggregate_type="", payload=ProbePayload)
        )

    assert "aggregate type" in str(refusal.value)
    assert "library.probe.recorded" in str(refusal.value)


def test_a_version_above_one_refuses():
    with pytest.raises(VersionNotUpcastable) as refusal:
        EventTypeRegistry().register(
            EventSpec(
                "library.probe.recorded",
                aggregate_type="probe",
                payload=ProbePayload,
                version=2,
            )
        )

    assert "upcast" in str(refusal.value)
    assert "library.probe.recorded" in str(refusal.value)


def test_validate_returns_a_value_of_its_own(registry: EventTypeRegistry):
    payload = {"game_id": "a-game", "count": 3}

    validated = registry.validate("library.probe.recorded", payload)

    assert validated == payload
    assert validated is not payload


def test_validate_refuses_an_unregistered_event_type(registry: EventTypeRegistry):
    with pytest.raises(UnregisteredEventType):
        registry.validate("library.nothing.happened", {})


@pytest.mark.parametrize(
    "payload",
    [
        {"game_id": "a-game", "count": 3, "surprise": True},
        {"game_id": "a-game"},
        {"game_id": "a-game", "count": "3"},
        {"game_id": 1, "count": 3},
        {"game_id": "a-game", "count": True},
    ],
    ids=["extra-key", "missing-key", "str-for-int", "int-for-str", "bool-for-int"],
)
def test_validate_refuses_a_payload_that_does_not_fit(
    registry: EventTypeRegistry, payload: dict[str, Any]
):
    with pytest.raises(PayloadInvalid) as refusal:
        registry.validate("library.probe.recorded", payload)

    assert "library.probe.recorded" in str(refusal.value)


def test_validate_widens_an_integer_to_a_float_field():
    registry = EventTypeRegistry()
    registry.register(RATIO_RECORDED)

    validated = registry.validate("library.ratio.recorded", {"ratio": 1})

    assert validated == {"ratio": 1.0}
    assert isinstance(validated["ratio"], float)


def test_registries_are_independent(registry: EventTypeRegistry):
    other = EventTypeRegistry()

    assert "library.probe.recorded" in registry
    assert "library.probe.recorded" not in other


def test_new_builds_an_event_carrying_its_spec():
    aggregate_id = uuid.uuid7()
    causation_id = uuid.uuid7()

    event = PROBE_RECORDED.new(
        aggregate_id=aggregate_id,
        payload={"game_id": "a-game", "count": 3},
        causation_id=causation_id,
    )

    assert event.spec is PROBE_RECORDED
    assert event.aggregate_id == aggregate_id
    assert event.payload == {"game_id": "a-game", "count": 3}
    assert event.effective_time is None
    assert event.causation_id == causation_id


def test_a_spec_is_hashable():
    assert {PROBE_RECORDED: "handler"}[PROBE_RECORDED] == "handler"


#: Every test event type this suite defines.
TEST_EVENT_TYPES = (
    "library.probe.recorded",
    "library.probe.unhandled",
    "library.probe.awkward",
    "library.probe.forgotten",
    "library.ratio.recorded",
    "library.opaque.recorded",
    "library.playthrough.started",
    "library.shapes.recorded",
    "library.unregistered.happened",
    "library.nothing.happened",
    "test.command.recorded",
    "test.command.twin.recorded",
    "test.command.temporal.recorded",
    "test.command.flaky.recorded",
    "test.projector.recorded",
    "test.projector.other",
    "test.projector.unhandled",
)


@pytest.mark.parametrize("event_type", TEST_EVENT_TYPES)
def test_a_test_registry_leaves_the_default_vocabulary_empty(event_type: str):
    """The vocabulary half of the projector claim."""
    assert event_type not in DEFAULT_EVENT_TYPES
