"""The index of which rows the recorded events name.

The payloads already hold this. These tests are about the index agreeing with
them, because the retention guard reads the index and never the payloads.
"""

import uuid
from typing import Any, NotRequired, TypedDict

import pytest
from django.db import transaction
from pydantic import ConfigDict, with_config

from games.events.append import lock_stream
from games.events.references import Reference, capture_reference
from games.events.vocabulary import EventSpec, EventTypeRegistry
from games.events.wiring import EventWiring
from games.models import Device, Game, LibraryEvent, LibraryEventReference, Platform
from games.retention import purging_library

pytestmark = pytest.mark.django_db(transaction=True)

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


def append(library, events, *, actor=None, key="index-key"):
    with transaction.atomic():
        return lock_stream(library).append(
            events,
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
            wiring=WIRING,
        )


def indexed() -> set[tuple[str, str, str]]:
    """Every recorded reference, as (kind, id, key)."""
    return {
        (row.kind, str(row.referenced_id), row.payload_key)
        for row in LibraryEventReference.objects.all()
    }


def device_event(device, **overrides: Any):
    payload = OneReferencePayload(device=capture_reference(device), note="moved")
    payload.update(overrides)  # type: ignore[typeddict-item]
    return DEVICE_RECORDED.new(aggregate_id=uuid.uuid7(), payload=payload)


# --- what one append records ------------------------------------------------


def test_one_reference_is_indexed_once(owned_library, device):
    append(owned_library, [device_event(device)])

    assert indexed() == {("device", str(device.pk), "device")}


def test_a_payload_holding_no_reference_indexes_nothing(owned_library):
    append(
        owned_library,
        [PROBE_RECORDED.new(aggregate_id=uuid.uuid7(), payload={"probe": True})],
    )

    assert LibraryEvent.objects.count() == 1
    assert not LibraryEventReference.objects.exists()


def test_every_arity_is_indexed(owned_library, device, game, platform):
    second_platform = Platform.objects.create(
        library=owned_library, name="GOG", group="PC storefronts"
    )
    append(
        owned_library,
        [
            EVERYTHING_RECORDED.new(
                aggregate_id=uuid.uuid7(),
                payload=EveryArityPayload(
                    device=capture_reference(device),
                    game=capture_reference(game),
                    platforms=[
                        capture_reference(platform),
                        capture_reference(second_platform),
                    ],
                    tags=["a", "b"],
                ),
            )
        ],
    )

    assert indexed() == {
        ("device", str(device.pk), "device"),
        ("catalog.game", str(game.pk), "game"),
        ("catalog.platform", str(platform.pk), "platforms"),
        ("catalog.platform", str(second_platform.pk), "platforms"),
    }


def test_an_optional_reference_left_out_indexes_nothing(owned_library, device):
    """`game=None` and an absent `absent` are the two ways to hold no row."""
    append(
        owned_library,
        [
            EVERYTHING_RECORDED.new(
                aggregate_id=uuid.uuid7(),
                payload=EveryArityPayload(
                    device=capture_reference(device),
                    game=None,
                    platforms=[],
                    tags=[],
                ),
            )
        ],
    )

    assert indexed() == {("device", str(device.pk), "device")}


def test_each_event_of_one_append_is_indexed_against_itself(owned_library, device):
    result = append(
        owned_library, [device_event(device), device_event(device)], key="two-events"
    )

    first, second = result.events
    assert LibraryEventReference.objects.filter(event=first).count() == 1
    assert LibraryEventReference.objects.filter(event=second).count() == 1


def test_the_index_row_carries_the_appending_library(owned_library, device):
    append(owned_library, [device_event(device)])

    row = LibraryEventReference.objects.get()
    assert row.library_id == owned_library.pk


def test_the_same_row_referenced_twice_is_indexed_twice(owned_library, device):
    """Two events, two rows: the guard counts events, not distinct rows."""
    append(owned_library, [device_event(device)], key="first")
    append(owned_library, [device_event(device)], key="second")

    assert LibraryEventReference.objects.to_row("device", device.pk).count() == 2


# --- what the index outlives ------------------------------------------------


def test_the_index_is_written_in_the_appending_transaction(owned_library, device):
    """A rolled-back append leaves no index row behind."""
    with pytest.raises(RuntimeError, match="rolled back"), transaction.atomic():
        lock_stream(owned_library).append(
            [device_event(device)],
            actor=None,
            correlation_id=uuid.uuid7(),
            idempotency_key="rolled-back",
            wiring=WIRING,
        )
        raise RuntimeError("rolled back on purpose")

    assert not LibraryEvent.objects.exists()
    assert not LibraryEventReference.objects.exists()


def test_deleting_an_event_takes_its_index_rows(owned_library, device):
    result = append(owned_library, [device_event(device)])

    LibraryEvent.objects.filter(pk=result.events[0].pk).delete()

    assert not LibraryEventReference.objects.exists()


def test_purging_a_library_takes_its_index_rows(owned_user, owned_library, device):
    append(owned_library, [device_event(device)])

    #: The retention guard would otherwise refuse to let the device go; a
    #: whole-library purge is its one exemption. See `tests/test_retention.py`.
    with purging_library():
        owned_user.delete()

    assert not LibraryEventReference.objects.exists()


def test_one_library_index_says_nothing_about_another(
    owned_library, device, django_user_model
):
    other_library = django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library
    other_device = Device.objects.create(
        library=other_library, name="Deck", type=Device.HANDHELD
    )
    append(owned_library, [device_event(device)])
    append(other_library, [device_event(other_device)], key="other-key")

    assert (
        LibraryEventReference.objects.for_library(owned_library).get().referenced_id
        == device.pk
    )
    assert (
        LibraryEventReference.objects.for_library(other_library).get().referenced_id
        == other_device.pk
    )
