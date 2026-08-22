import uuid
from datetime import date
from threading import Event, Thread

import psycopg
import pytest
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from games.events.append import (
    AppendResult,
    LockedStream,
    NewEvent,
    TransactionRequired,
    append_events,
    lock_stream,
)
from games.models import LibraryEvent, LibraryEventStreamHead
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library


def make_new_event(**overrides) -> NewEvent:
    fields = {
        "event_type": "library.probe.recorded",
        "aggregate_type": "probe",
        "aggregate_id": uuid.uuid7(),
        "payload": {"probe": True},
    }
    fields.update(overrides)
    return NewEvent(**fields)


def append(library, events=None, **overrides) -> AppendResult:
    fields = {
        "actor": None,
        "correlation_id": uuid.uuid7(),
        "idempotency_key": "probe-key",
    }
    fields.update(overrides)
    return append_events(library, events or [make_new_event()], **fields)


def test_first_append_provisions_a_head_and_starts_at_one(owned_library):
    assert not LibraryEventStreamHead.objects.exists()

    with transaction.atomic():
        result = append(owned_library)

    head = LibraryEventStreamHead.objects.get(library=owned_library)
    assert result.stream_id == head.id
    assert (result.first_sequence, result.last_sequence) == (1, 1)
    assert head.current_sequence == 1


def test_second_append_continues_without_a_gap(owned_library):
    with transaction.atomic():
        append(owned_library)
    with transaction.atomic():
        result = append(owned_library)

    assert (result.first_sequence, result.last_sequence) == (2, 2)
    assert list(
        LibraryEvent.objects.order_by("sequence").values_list("sequence", flat=True)
    ) == [1, 2]


def test_multi_event_append_is_contiguous_and_shares_one_envelope(owned_library):
    correlation_id = uuid.uuid7()

    with transaction.atomic():
        result = append(
            owned_library,
            [make_new_event(), make_new_event(), make_new_event()],
            correlation_id=correlation_id,
        )

    assert (result.first_sequence, result.last_sequence) == (1, 3)
    stored = LibraryEvent.objects.order_by("sequence")
    assert [event.sequence for event in stored] == [1, 2, 3]
    assert {event.correlation_id for event in stored} == {correlation_id}
    assert len({event.recorded_at for event in stored}) == 1


def test_two_appends_on_one_locked_stream_continue_the_range(owned_library):
    with transaction.atomic():
        stream = lock_stream(owned_library)
        first = stream.append(
            [make_new_event()],
            actor=None,
            correlation_id=uuid.uuid7(),
            idempotency_key="first",
        )
        second = stream.append(
            [make_new_event(), make_new_event()],
            actor=None,
            correlation_id=uuid.uuid7(),
            idempotency_key="second",
        )

    assert (first.first_sequence, first.last_sequence) == (1, 1)
    assert (second.first_sequence, second.last_sequence) == (2, 3)
    assert stream.current_sequence == 3


def test_rolled_back_append_leaves_no_events_and_no_advance(owned_library):
    with transaction.atomic():
        append(owned_library)

    with pytest.raises(RuntimeError, match="rolled back"):
        with transaction.atomic():
            append(owned_library)
            raise RuntimeError("rolled back")

    head = LibraryEventStreamHead.objects.get(library=owned_library)
    assert head.current_sequence == 1
    assert LibraryEvent.objects.count() == 1


def test_empty_event_sequence_is_rejected(owned_library):
    with transaction.atomic():
        stream = lock_stream(owned_library)
        with pytest.raises(ValueError, match="at least one event"):
            stream.append(
                [],
                actor=None,
                correlation_id=uuid.uuid7(),
                idempotency_key="probe-key",
            )

    assert not LibraryEvent.objects.exists()


def test_libraries_advance_independently(owned_library, second_library):
    with transaction.atomic():
        append(owned_library)
        append(owned_library)
    with transaction.atomic():
        other = append(second_library)

    assert (other.first_sequence, other.last_sequence) == (1, 1)
    assert LibraryEvent.objects.for_library(second_library).count() == 1
    assert LibraryEvent.objects.for_library(owned_library).count() == 2
    assert other.stream_id != LibraryEventStreamHead.objects.get(
        library=owned_library
    ).id


def test_result_matches_the_persisted_rows(owned_library):
    with transaction.atomic():
        result = append(owned_library, [make_new_event(), make_new_event()])

    stored = list(LibraryEvent.objects.order_by("sequence"))
    assert [event.pk for event in result.events] == [event.pk for event in stored]
    assert result.first_sequence == stored[0].sequence
    assert result.last_sequence == stored[-1].sequence
    assert {event.stream_id for event in stored} == {result.stream_id}


def test_event_fields_round_trip(owned_library):
    aggregate_id = uuid.uuid7()
    causation_id = uuid.uuid7()
    effective_time = TemporalValue.from_day(date(2026, 8, 21))

    with transaction.atomic():
        append(
            owned_library,
            [
                make_new_event(
                    event_type="library.playthrough.started",
                    aggregate_type="playthrough",
                    aggregate_id=aggregate_id,
                    payload={"nested": {"id": str(aggregate_id)}},
                    payload_schema_version=2,
                    effective_time=effective_time,
                    causation_id=causation_id,
                )
            ],
            source_metadata={"origin": "manual"},
        )

    event = LibraryEvent.objects.get()
    assert event.event_type == "library.playthrough.started"
    assert event.aggregate_type == "playthrough"
    assert event.aggregate_id == aggregate_id
    assert event.payload == {"nested": {"id": str(aggregate_id)}}
    assert event.payload_schema_version == 2
    assert event.effective_time == effective_time
    assert event.causation_id == causation_id
    assert event.source_metadata == {"origin": "manual"}


def test_actor_is_recorded_and_optional(owned_library, django_user_model):
    actor = django_user_model.objects.get(pk=owned_library.user_id)

    with transaction.atomic():
        append(owned_library, actor=actor)
        append(owned_library, actor=None)

    stored = LibraryEvent.objects.order_by("sequence")
    assert [event.actor_id for event in stored] == [actor.pk, None]


def test_absent_source_metadata_is_stored_as_an_empty_object(owned_library):
    with transaction.atomic():
        append(owned_library)

    assert LibraryEvent.objects.get().source_metadata == {}


def test_convenience_function_matches_the_primitive(owned_library, second_library):
    correlation_id = uuid.uuid7()
    recorded_at = timezone.now()
    events = [make_new_event()]

    with transaction.atomic():
        through_function = append_events(
            owned_library,
            events,
            actor=None,
            correlation_id=correlation_id,
            idempotency_key="same",
            recorded_at=recorded_at,
        )
    with transaction.atomic():
        through_primitive = lock_stream(second_library).append(
            events,
            actor=None,
            correlation_id=correlation_id,
            idempotency_key="same",
            recorded_at=recorded_at,
        )

    compared = ("sequence", "event_type", "correlation_id", "recorded_at", "payload")
    assert [
        [getattr(event, name) for name in compared] for event in through_function.events
    ] == [
        [getattr(event, name) for name in compared]
        for event in through_primitive.events
    ]


def test_lock_stream_returns_the_same_head_for_a_provisioned_library(owned_library):
    with transaction.atomic():
        first = lock_stream(owned_library)
        assert isinstance(first, LockedStream)
        second = lock_stream(owned_library)

    assert first.stream_id == second.stream_id
    assert LibraryEventStreamHead.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_locking_outside_a_transaction_is_refused(owned_library):
    with pytest.raises(TransactionRequired, match="open transaction"):
        lock_stream(owned_library)

    assert not LibraryEventStreamHead.objects.exists()
    assert not LibraryEvent.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_the_head_is_locked_for_the_whole_transaction(owned_library):
    #: The head must already be committed: a row this transaction created would
    #: be invisible to the probe, which would then lock nothing and pass for the
    #: wrong reason.
    with transaction.atomic():
        head_id = append(owned_library).stream_id

    connection.ensure_connection()
    connection_params = connection.get_connection_params()

    with transaction.atomic():
        lock_stream(owned_library)
        with psycopg.connect(**connection_params) as probe:
            with probe.transaction():
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    probe.execute(
                        "SELECT current_sequence FROM games_libraryeventstreamhead"
                        " WHERE id = %s FOR UPDATE NOWAIT",
                        [head_id],
                    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_appends_serialize_into_one_contiguous_range(owned_library):
    holder_locked = Event()
    waiter_requested_lock = Event()
    results: dict[str, AppendResult] = {}
    errors: list[BaseException] = []

    def run_holder():
        close_old_connections()
        try:
            with transaction.atomic():
                stream = lock_stream(owned_library)
                holder_locked.set()
                results["holder"] = stream.append(
                    [make_new_event(), make_new_event()],
                    actor=None,
                    correlation_id=uuid.uuid7(),
                    idempotency_key="holder",
                )
                if not waiter_requested_lock.wait(10):
                    raise TimeoutError("waiter never requested the head lock")
        except BaseException as error:  # noqa: BLE001 - return thread failures
            errors.append(error)
        finally:
            close_old_connections()

    def run_waiter():
        close_old_connections()

        def announce_lock_request(execute, sql, params, many, context):
            if "games_libraryeventstreamhead" in sql and "FOR UPDATE" in sql:
                #: Fires immediately before the statement blocks, so the holder
                #: is released only once this request is genuinely outstanding.
                waiter_requested_lock.set()
            return execute(sql, params, many, context)

        try:
            assert holder_locked.wait(10)
            with connection.execute_wrapper(announce_lock_request), transaction.atomic():
                results["waiter"] = append(
                    owned_library,
                    [make_new_event(), make_new_event()],
                    idempotency_key="waiter",
                )
        except BaseException as error:  # noqa: BLE001 - return thread failures
            errors.append(error)
        finally:
            close_old_connections()

    holder = Thread(target=run_holder, name="stream-holder")
    waiter = Thread(target=run_waiter, name="stream-waiter")
    holder.start()
    waiter.start()
    holder.join(20)
    waiter.join(20)

    assert not errors, errors
    assert not holder.is_alive()
    assert not waiter.is_alive()

    holder_result = results["holder"]
    waiter_result = results["waiter"]
    assert (holder_result.first_sequence, holder_result.last_sequence) == (1, 2)
    assert (waiter_result.first_sequence, waiter_result.last_sequence) == (3, 4)
    assert holder_result.stream_id == waiter_result.stream_id
    assert list(
        LibraryEvent.objects.order_by("sequence").values_list("sequence", flat=True)
    ) == [1, 2, 3, 4]
