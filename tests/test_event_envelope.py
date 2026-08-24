"""The recorded event: what it copies off the row, and what it refuses.

The contract test is the load-bearing one. It walks the model's own field list,
so a column added to `LibraryEvent` fails here until somebody decides whether a
projector should see it.
"""

import dataclasses
import uuid
from datetime import UTC, datetime

import pytest
from django.db import transaction

from games.events.append import NewEvent, lock_stream
from games.events.envelope import DeferredRowRefused, RecordedEvent
from games.models import LibraryEvent
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


def append_one(library, actor=None) -> LibraryEvent:
    """Append a row whose every field holds a distinct value.

    Distinct matters: two UUID fields sharing one value would let the contract
    test pass over a `from_row` that read the wrong one.
    """
    event = NewEvent(
        event_type="library.probe.recorded",
        aggregate_type="probe",
        aggregate_id=uuid.uuid7(),
        payload={"probe": True, "tags": ["a", "b"]},
        payload_schema_version=3,
        effective_time=TemporalValue.parse("2024-05-06"),
        causation_id=uuid.uuid7(),
    )
    with transaction.atomic():
        result = lock_stream(library).append(
            [event],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key="envelope-probe-key",
            source_metadata={"origin": "test"},
            recorded_at=datetime(2024, 5, 6, 7, 8, 9, 123456, tzinfo=UTC),
        )
    return result.events[0]


def test_every_concrete_field_arrives_with_its_own_value(owned_library, owned_user):
    row = LibraryEvent.objects.get(pk=append_one(owned_library, owned_user).pk)

    recorded = RecordedEvent.from_row(row)

    for field in LibraryEvent._meta.concrete_fields:
        assert getattr(recorded, field.attname) == getattr(row, field.attname), (
            f"{field.attname} did not survive the conversion"
        )


def test_the_value_carries_no_model(owned_library, owned_user):
    recorded = RecordedEvent.from_row(append_one(owned_library, owned_user))

    for absent in ("actor", "library", "stream", "objects", "save", "_meta"):
        assert not hasattr(recorded, absent)


def test_a_recorded_event_cannot_be_assigned_to(owned_library):
    recorded = RecordedEvent.from_row(append_one(owned_library))

    with pytest.raises(dataclasses.FrozenInstanceError):
        recorded.sequence = 99


def test_converting_a_row_read_back_issues_no_query(
    owned_library, owned_user, django_assert_num_queries
):
    appended = append_one(owned_library, owned_user)
    #: Re-read rather than reused: the appended instance has its relations
    #: cached, so it would pass this for the wrong reason.
    row = LibraryEvent.objects.get(pk=appended.pk)

    with django_assert_num_queries(0):
        RecordedEvent.from_row(row)


def test_a_deferred_row_is_refused_by_name(owned_library):
    appended = append_one(owned_library)
    row = LibraryEvent.objects.only("id", "sequence").get(pk=appended.pk)

    with pytest.raises(DeferredRowRefused) as refusal:
        RecordedEvent.from_row(row)

    assert "payload" in str(refusal.value)
    assert "event_type" in str(refusal.value)


def test_the_appended_row_and_the_row_read_back_convert_alike(
    owned_library, owned_user
):
    appended = append_one(owned_library, owned_user)

    assert RecordedEvent.from_row(appended) == RecordedEvent.from_row(
        LibraryEvent.objects.get(pk=appended.pk)
    )
