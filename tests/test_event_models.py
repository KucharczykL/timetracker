import uuid
from datetime import date

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models import RestrictedError

from games.models import LibraryEvent, LibraryEventStreamHead
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db

CONSTRAINT_NAMES = (
    "unique_library_event_stream_head_library_identity",
    "unique_library_event_stream_sequence",
    "library_event_sequence_positive",
    "library_event_payload_schema_version_positive",
    "library_event_type_not_empty",
    "library_event_aggregate_type_not_empty",
    "library_event_idempotency_key_not_empty",
    "library_event_stream_matches_library",
)


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library


@pytest.fixture
def head(owned_library):
    return LibraryEventStreamHead.objects.create(library=owned_library)


@pytest.fixture
def second_head(second_library):
    return LibraryEventStreamHead.objects.create(library=second_library)


def make_event(stream, **overrides):
    sequence = overrides.get("sequence", 1)
    fields = {
        "library": stream.library,
        "stream": stream,
        "sequence": sequence,
        "event_type": "library.probe.recorded",
        "aggregate_type": "probe",
        "aggregate_id": uuid.uuid7(),
        "correlation_id": uuid.uuid7(),
        "idempotency_key": f"probe-{sequence}",
        "payload": {},
    }
    fields.update(overrides)
    return LibraryEvent.objects.create(**fields)


def test_head_and_event_ids_are_uuidv7(head):
    event = make_event(head)

    assert head.id.version == 7
    assert event.id.version == 7


@pytest.mark.parametrize("field", ["aggregate_id", "correlation_id"])
def test_event_requires_explicit_aggregate_and_correlation_ids(head, field):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_event(head, **{field: None})


@pytest.mark.parametrize("field", ["aggregate_id", "correlation_id", "causation_id"])
def test_explicit_identity_fields_carry_no_database_default(field):
    # The runtime behaviour of db_default=None and db_default=NOT_PROVIDED is
    # identical, so only the field itself can pin which one is in use.
    assert LibraryEvent._meta.get_field(field).has_db_default() is False


def test_causation_id_defaults_to_none(head):
    assert make_event(head).causation_id is None


def test_effective_time_is_optional_and_round_trips(head):
    without_time = make_event(head)
    with_time = make_event(
        head, sequence=2, effective_time=TemporalValue.from_day(date(2026, 8, 21))
    )
    without_time.refresh_from_db()
    with_time.refresh_from_db()

    assert without_time.effective_time is None
    assert with_time.effective_time == TemporalValue.from_day(date(2026, 8, 21))


def test_payload_round_trips_nested_structures(head):
    payload = {
        "references": [
            {"id": str(uuid.uuid7()), "labels": ["first", "second"]},
            {"id": str(uuid.uuid7()), "labels": []},
        ],
        "counts": {"total": 2, "nested": {"depth": 3}},
    }
    event = make_event(head, payload=payload)
    event.refresh_from_db()

    assert event.payload == payload


def test_source_metadata_defaults_are_independent(head):
    first = make_event(head, sequence=1)
    second = make_event(head, sequence=2)

    first.source_metadata["origin"] = "manual"

    assert second.source_metadata == {}


def test_head_current_sequence_starts_at_zero(head):
    head.refresh_from_db()

    assert head.current_sequence == 0


def test_for_library_scopes_events(head, second_head):
    own = make_event(head)
    make_event(second_head)

    assert list(LibraryEvent.objects.for_library(head.library)) == [own]


def test_deleting_actor_preserves_event(head, django_user_model):
    actor = django_user_model.objects.create_user(username="actor", password="p")
    event = make_event(head, actor=actor)

    actor.delete()
    event.refresh_from_db()

    assert event.actor_id is None


def test_head_requires_library():
    with pytest.raises(IntegrityError), transaction.atomic():
        LibraryEventStreamHead.objects.create(library=None)


def test_event_requires_library(head):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_event(head, library=None)


def test_library_has_at_most_one_head(head):
    with pytest.raises(IntegrityError), transaction.atomic():
        LibraryEventStreamHead.objects.create(library=head.library)


def test_sequence_below_one_is_rejected(head):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_event(head, sequence=0)


def test_payload_schema_version_below_one_is_rejected(head):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_event(head, payload_schema_version=0)


@pytest.mark.parametrize("field", ["event_type", "aggregate_type", "idempotency_key"])
def test_blank_text_fields_are_rejected(head, field):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_event(head, **{field: ""})


def test_payload_is_required(head):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_event(head, payload=None)


def test_duplicate_sequence_in_one_stream_is_rejected(head):
    make_event(head, sequence=1)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_event(head, sequence=1, idempotency_key="probe-duplicate")


def test_same_sequence_in_another_stream_is_allowed(head, second_head):
    make_event(head, sequence=1)
    other = make_event(second_head, sequence=1)

    assert other.sequence == 1


def test_event_cannot_use_another_librarys_stream(head, second_head):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_event(second_head, library=head.library)


def test_deleting_library_removes_its_events_and_head(head, second_head):
    make_event(head, sequence=1)
    make_event(head, sequence=2)
    surviving = make_event(second_head, sequence=1)

    head.library.delete()

    assert list(LibraryEvent.objects.all()) == [surviving]
    assert list(LibraryEventStreamHead.objects.all()) == [second_head]


def test_deleting_populated_head_is_restricted(head):
    make_event(head)

    with pytest.raises(RestrictedError), transaction.atomic():
        head.delete()


def test_constraint_names_exist():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE conname = ANY(%s)",
            [list(CONSTRAINT_NAMES)],
        )
        found = {row[0] for row in cursor.fetchall()}

    assert found == set(CONSTRAINT_NAMES)
