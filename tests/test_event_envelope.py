"""The recorded event: what it copies off the row, and what it refuses.

The contract test is the load-bearing one. It walks the model's own field list,
so a column added to `LibraryEvent` fails here until somebody decides whether a
projector should see it.
"""

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import TypedDict

import pytest
from django.db import transaction
from pydantic import ConfigDict, with_config

from games.events.append import lock_stream
from games.events.envelope import DeferredRowRefused, RecordedEvent
from games.events.vocabulary import EventSpec, EventTypeRegistry, NewEvent
from games.events.wiring import EventWiring
from games.models import LibraryEvent
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


@with_config(ConfigDict(extra="forbid", strict=True))
class ProbePayload(TypedDict):
    probe: bool
    tags: list[str]


PROBE_RECORDED = EventSpec(
    "library.probe.recorded", aggregate_type="probe", payload=ProbePayload
)

#: This module's own vocabulary, never production's.
EVENT_TYPES = EventTypeRegistry()
EVENT_TYPES.register(PROBE_RECORDED)
WIRING = EventWiring(event_types=EVENT_TYPES)


@pytest.fixture
def distinct_actor(db, django_user_model):
    """An actor whose id cannot be mistaken for anything else on the event.

    A user allocated the usual small id would carry 1 or 2, which are the
    version and the sequence.
    """
    return django_user_model.objects.create_user(
        id=9001, username="probe-actor", password="p"
    )


def append_probe(library, actor=None) -> LibraryEvent:
    """Append two events and return the second, whose every field holds a
    distinct value.

    Distinct matters: two fields sharing one value would let the contract test
    pass over a `from_row` that read the wrong one, and the pinning test below
    is what keeps that true. The registry stamps the schema version, so every
    event here is version 1 -- returning the second of a pair is what puts the
    sequence at 2 and keeps those two apart, and `distinct_actor` is what keeps
    the actor's id away from both.
    """

    def probe() -> NewEvent:
        return PROBE_RECORDED.new(
            aggregate_id=uuid.uuid7(),
            payload={"probe": True, "tags": ["a", "b"]},
            effective_time=TemporalValue.parse("2024-05-06"),
            causation_id=uuid.uuid7(),
        )

    with transaction.atomic():
        result = lock_stream(library).append(
            [probe(), probe()],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key="envelope-probe-key",
            source_metadata={"origin": "test"},
            recorded_at=datetime(2024, 5, 6, 7, 8, 9, 123456, tzinfo=UTC),
            wiring=WIRING,
        )
    return result.events[1]


def test_no_two_concrete_fields_of_a_probe_share_a_value(owned_library, distinct_actor):
    """What makes the contract below able to fail.

    A `from_row` reading the wrong field is invisible wherever two fields agree,
    so the probe's distinctness is asserted rather than assumed -- a field
    removed from the model, or a probe value edited, cannot quietly turn the
    contract test into one that passes over a mistake.
    """
    row = LibraryEvent.objects.get(pk=append_probe(owned_library, distinct_actor).pk)

    values = [
        (field.attname, getattr(row, field.attname))
        for field in LibraryEvent._meta.concrete_fields
    ]
    for index, (name, value) in enumerate(values):
        for other_name, other_value in values[index + 1 :]:
            assert value != other_value, f"{name} and {other_name} share a value"


def test_every_concrete_field_arrives_with_its_own_value(owned_library, distinct_actor):
    row = LibraryEvent.objects.get(pk=append_probe(owned_library, distinct_actor).pk)

    recorded = RecordedEvent.from_row(row)

    for field in LibraryEvent._meta.concrete_fields:
        assert getattr(recorded, field.attname) == getattr(row, field.attname), (
            f"{field.attname} did not survive the conversion"
        )


def test_the_aggregate_type_is_the_registrys_answer(owned_library):
    """The aggregate type is a function of the event type, so the spec answers
    for it and no envelope carries a second copy to fall out of date."""
    recorded = RecordedEvent.from_row(append_probe(owned_library))

    assert EVENT_TYPES.spec_for(recorded.event_type).aggregate_type == "probe"
    assert not hasattr(recorded, "aggregate_type")


def test_the_payload_arrives_with_its_keys_sorted_at_every_depth():
    """The payload is a canonical value, not the order somebody wrote it in.

    Read off an unsaved row, so this is the conversion alone: the append path
    and the replay path both reach a projector through here, and they carry
    different orders until this sorts them.
    """
    row = LibraryEvent(
        payload={"zz": {"yy": 1, "a": 2}, "aaa": [{"nn": 1, "c": 2}], "b": 3}
    )

    payload = RecordedEvent.from_row(row).payload

    assert list(payload) == ["aaa", "b", "zz"]
    assert list(payload["zz"]) == ["a", "yy"]
    assert list(payload["aaa"][0]) == ["c", "nn"]
    #: Rebuilt, not reordered: the row is untouched.
    assert list(row.payload) == ["zz", "aaa", "b"]


def test_the_value_carries_no_model(owned_library, distinct_actor):
    recorded = RecordedEvent.from_row(append_probe(owned_library, distinct_actor))

    for absent in ("actor", "library", "stream", "objects", "save", "_meta"):
        assert not hasattr(recorded, absent)


def test_a_recorded_event_cannot_be_assigned_to(owned_library):
    recorded = RecordedEvent.from_row(append_probe(owned_library))

    with pytest.raises(dataclasses.FrozenInstanceError):
        recorded.sequence = 99


def test_converting_a_row_read_back_issues_no_query(
    owned_library, distinct_actor, django_assert_num_queries
):
    appended = append_probe(owned_library, distinct_actor)
    #: Re-read rather than reused: the appended instance has its relations
    #: cached, so it would pass this for the wrong reason.
    row = LibraryEvent.objects.get(pk=appended.pk)

    with django_assert_num_queries(0):
        RecordedEvent.from_row(row)


def test_a_deferred_row_is_refused_by_name(owned_library):
    appended = append_probe(owned_library)
    row = LibraryEvent.objects.only("id", "sequence").get(pk=appended.pk)

    with pytest.raises(DeferredRowRefused) as refusal:
        RecordedEvent.from_row(row)

    assert "payload" in str(refusal.value)
    assert "event_type" in str(refusal.value)


def test_the_appended_row_and_the_row_read_back_convert_alike(
    owned_library, distinct_actor
):
    appended = append_probe(owned_library, distinct_actor)

    assert RecordedEvent.from_row(appended) == RecordedEvent.from_row(
        LibraryEvent.objects.get(pk=appended.pk)
    )
