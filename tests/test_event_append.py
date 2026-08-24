import uuid
from datetime import date
from decimal import Decimal
from threading import Event, Thread
from typing import Any, TypedDict

import psycopg
import pytest
from django.db import close_old_connections, connection, transaction
from pydantic import ConfigDict, with_config

from games.events.append import (
    AppendResult,
    LockedStream,
    PayloadNotCanonical,
    TransactionRequired,
    lock_stream,
)
from games.events.vocabulary import (
    EventSpec,
    EventTypeRegistry,
    NewEvent,
    PayloadInvalid,
    UnregisteredEventType,
)
from games.events.wiring import EventWiring
from games.models import LibraryEvent, LibraryEventStreamHead
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


STRICT_CONFIG = ConfigDict(extra="forbid", strict=True)


@with_config(STRICT_CONFIG)
class ProbePayload(TypedDict):
    probe: bool


@with_config(STRICT_CONFIG)
class NestedPayload(TypedDict):
    nested: dict[str, str]


@with_config(STRICT_CONFIG)
class ShapesPayload(TypedDict):
    """Every JSON container in one payload, plus the float that widens."""

    tags: list[str]
    counts: dict[str, int]
    ratio: float


@with_config(STRICT_CONFIG)
class OpaquePayload(TypedDict):
    """A field pydantic will not look inside, which is what makes the
    canonicalizer's turn before validation observable."""

    details: dict[str, Any]


PROBE_RECORDED = EventSpec(
    "library.probe.recorded", aggregate_type="probe", payload=ProbePayload
)
#: A second spec, so the row's event type, aggregate type, and schema version
#: are each read off the registered spec rather than off one shared default.
PLAYTHROUGH_STARTED = EventSpec(
    "library.playthrough.started",
    aggregate_type="playthrough",
    payload=NestedPayload,
)
SHAPES_RECORDED = EventSpec(
    "library.shapes.recorded", aggregate_type="probe", payload=ShapesPayload
)
OPAQUE_RECORDED = EventSpec(
    "library.opaque.recorded", aggregate_type="probe", payload=OpaquePayload
)

#: Built but never registered, so an append carrying it has to be refused on the
#: registry's word rather than on the spec object the caller happens to hold.
UNREGISTERED = EventSpec(
    "library.unregistered.happened", aggregate_type="probe", payload=ProbePayload
)
#: A registered event type under a spec nobody registered, disagreeing with the
#: registration about everything the row copies off a spec.
MISDECLARED_PROBE = EventSpec(
    "library.probe.recorded",
    aggregate_type="mistaken",
    payload=ProbePayload,
    version=9,
)

#: This module's own vocabulary: a probe type registered here never enters the
#: one a production stream reads.
EVENT_TYPES = EventTypeRegistry()
for registered_spec in (
    PROBE_RECORDED,
    PLAYTHROUGH_STARTED,
    SHAPES_RECORDED,
    OPAQUE_RECORDED,
):
    EVENT_TYPES.register(registered_spec)
WIRING = EventWiring(event_types=EVENT_TYPES)


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library


def make_new_event(**overrides: Any) -> NewEvent:
    fields: dict[str, Any] = {
        "spec": PROBE_RECORDED,
        "aggregate_id": uuid.uuid7(),
        "payload": {"probe": True},
    }
    fields.update(overrides)
    return NewEvent(**fields)


def append(library, events=None, **overrides: Any) -> AppendResult:
    fields: dict[str, Any] = {
        "actor": None,
        "correlation_id": uuid.uuid7(),
        "idempotency_key": "probe-key",
        "wiring": WIRING,
    }
    fields.update(overrides)
    return lock_stream(library).append(events or [make_new_event()], **fields)


def append_directly(stream: LockedStream, events, **overrides: Any) -> AppendResult:
    """An append that skips `lock_stream`, for a test holding its own stream."""
    fields: dict[str, Any] = {
        "actor": None,
        "correlation_id": uuid.uuid7(),
        "idempotency_key": "probe-key",
        "wiring": WIRING,
    }
    fields.update(overrides)
    return stream.append(events, **fields)


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
        first = append_directly(stream, [make_new_event()], idempotency_key="first")
        second = append_directly(
            stream, [make_new_event(), make_new_event()], idempotency_key="second"
        )

    assert (first.first_sequence, first.last_sequence) == (1, 1)
    assert (second.first_sequence, second.last_sequence) == (2, 3)
    assert stream.current_sequence == 3


def test_rolled_back_append_leaves_no_events_and_no_advance(owned_library):
    with transaction.atomic():
        append(owned_library)

    with pytest.raises(RuntimeError, match="rolled back"), transaction.atomic():
        append(owned_library)
        raise RuntimeError("rolled back")

    head = LibraryEventStreamHead.objects.get(library=owned_library)
    assert head.current_sequence == 1
    assert LibraryEvent.objects.count() == 1


def test_empty_event_sequence_is_rejected(owned_library):
    with transaction.atomic():
        stream = lock_stream(owned_library)
        with pytest.raises(ValueError, match="at least one event"):
            append_directly(stream, [])

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
    assert (
        other.stream_id != LibraryEventStreamHead.objects.get(library=owned_library).id
    )


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
                    spec=PLAYTHROUGH_STARTED,
                    aggregate_id=aggregate_id,
                    payload={"nested": {"id": str(aggregate_id)}},
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
    assert event.effective_time == effective_time
    assert event.causation_id == causation_id
    assert event.source_metadata == {"origin": "manual"}


def test_the_row_is_built_from_the_registered_spec(owned_library):
    """The carried spec is a caller's word; the registration is the vocabulary.

    Nothing a caller passes decides the recorded version -- an upcaster reads it
    to know which schema a payload was written against, so a writer naming its
    own would leave that reader guessing.
    """
    with transaction.atomic():
        append(owned_library, [make_new_event(spec=MISDECLARED_PROBE)])

    event = LibraryEvent.objects.get()
    assert event.payload_schema_version == PROBE_RECORDED.version == 1
    assert event.aggregate_type == "probe"


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


#: Each one reaches PostgreSQL as something other than itself, or not at all: a
#: tuple as a list, an integer key as a string, and the rest not at all. None of
#: them fits any schema, deliberately: they are inputs the canonicalizer refuses,
#: not payloads a spec could declare.
NON_CANONICAL_VALUES = [
    pytest.param({"tags": ("first", "second")}, id="tuple"),
    pytest.param({1: "first"}, id="integer-key"),
    pytest.param({"price": Decimal("5.50")}, id="decimal"),
    pytest.param({"tags": {"first", "second"}}, id="set"),
    pytest.param({"ratio": float("nan")}, id="nan"),
    pytest.param({"when": date(2026, 8, 21)}, id="date"),
]


@pytest.mark.parametrize("payload", NON_CANONICAL_VALUES)
def test_a_non_canonical_payload_is_refused(owned_library, payload):
    with transaction.atomic():
        stream = lock_stream(owned_library)
        with pytest.raises(PayloadNotCanonical, match="payload"):
            append_directly(stream, [make_new_event(payload=payload)])

    assert not LibraryEvent.objects.exists()


@pytest.mark.parametrize("source_metadata", NON_CANONICAL_VALUES)
def test_non_canonical_source_metadata_is_refused(owned_library, source_metadata):
    with transaction.atomic():
        stream = lock_stream(owned_library)
        with pytest.raises(PayloadNotCanonical, match="source metadata"):
            append_directly(stream, [make_new_event()], source_metadata=source_metadata)

    assert not LibraryEvent.objects.exists()


def test_a_value_hidden_under_an_any_field_is_still_refused(owned_library):
    """What fixes the canonicalizer's turn ahead of validation.

    `details` is typed `dict[str, Any]`, so pydantic hands the Decimal straight
    back. Validating first would put a value on disk that PostgreSQL returns as
    a string.
    """
    with transaction.atomic():
        stream = lock_stream(owned_library)
        with pytest.raises(PayloadNotCanonical, match="payload"):
            append_directly(
                stream,
                [
                    make_new_event(
                        spec=OPAQUE_RECORDED,
                        payload={"details": {"price": Decimal("5.50")}},
                    )
                ],
            )

    assert not LibraryEvent.objects.exists()


def test_a_refused_payload_leaves_the_head_where_it_was(owned_library):
    with transaction.atomic():
        append(owned_library)

    with transaction.atomic():
        stream = lock_stream(owned_library)
        with pytest.raises(PayloadNotCanonical):
            append_directly(
                stream,
                [make_new_event(), make_new_event(payload={"tags": ()})],
                idempotency_key="second",
            )

    assert (
        LibraryEventStreamHead.objects.get(library=owned_library).current_sequence == 1
    )
    assert LibraryEvent.objects.count() == 1


def refuse_and_keep_appending(library, refused, raises, match: str) -> None:
    """Refuse `refused`, then show the transaction it ran in still commits.

    The three assertions inside the block are what "a refusal leaves the
    transaction exactly as it found it" means: no row written, no advance, and
    a stream still able to append. The count afterwards is the commit itself.
    """
    with transaction.atomic():
        append(library)

    with transaction.atomic():
        stream = lock_stream(library)
        with pytest.raises(raises, match=match):
            append_directly(stream, [refused], idempotency_key="refused")

        assert LibraryEvent.objects.count() == 1
        assert stream.current_sequence == 1
        assert LibraryEventStreamHead.objects.get(library=library).current_sequence == 1
        append_directly(stream, [make_new_event()], idempotency_key="after")

    assert LibraryEvent.objects.count() == 2
    assert LibraryEventStreamHead.objects.get(library=library).current_sequence == 2


def test_an_unregistered_event_type_is_refused(owned_library):
    refuse_and_keep_appending(
        owned_library,
        make_new_event(spec=UNREGISTERED),
        UnregisteredEventType,
        match="library.unregistered.happened",
    )


def test_a_payload_its_schema_refuses_is_refused(owned_library):
    refuse_and_keep_appending(
        owned_library,
        make_new_event(payload={"probe": "yes"}),
        PayloadInvalid,
        match="library.probe.recorded",
    )


def test_a_stored_payload_equals_what_postgres_returns(owned_library):
    payload = {"tags": ["first", "second"], "counts": {"total": 2}, "ratio": 1.5}

    with transaction.atomic():
        result = append(
            owned_library, [make_new_event(spec=SHAPES_RECORDED, payload=payload)]
        )

    appended = result.events[0]
    assert appended.payload == LibraryEvent.objects.get(pk=appended.pk).payload


def test_an_integer_for_a_float_field_is_stored_as_a_float(owned_library):
    """The one case equality cannot see.

    `{"ratio": 1} == {"ratio": 1.0}`, so only the type of what PostgreSQL hands
    back says whether the row matches the schema it was recorded under.
    """
    with transaction.atomic():
        result = append(
            owned_library,
            [
                make_new_event(
                    spec=SHAPES_RECORDED,
                    payload={"tags": [], "counts": {}, "ratio": 1},
                )
            ],
        )

    stored = LibraryEvent.objects.get(pk=result.events[0].pk).payload
    assert isinstance(stored["ratio"], float)


def test_a_stored_payload_is_not_the_callers_object(owned_library):
    #: Built through spec.new, the one path that types a payload against the
    #: schema its spec names.
    payload: ProbePayload = {"probe": True}
    event = PROBE_RECORDED.new(aggregate_id=uuid.uuid7(), payload=payload)

    with transaction.atomic():
        result = append(owned_library, [event])
    payload["probe"] = False

    #: A projector runs against this row, so an aliased payload would let it
    #: reach back into the NewEvent the command built.
    assert result.events[0].payload is not payload
    assert result.events[0].payload == {"probe": True}
    assert LibraryEvent.objects.get(pk=result.events[0].pk).payload == {"probe": True}


def test_stored_source_metadata_is_not_the_callers_object(owned_library):
    source_metadata = {"origin": "manual"}

    with transaction.atomic():
        result = append(owned_library, source_metadata=source_metadata)

    assert result.events[0].source_metadata == source_metadata
    assert result.events[0].source_metadata is not source_metadata


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
        with (
            psycopg.connect(**connection_params) as probe,
            probe.transaction(),
            pytest.raises(psycopg.errors.LockNotAvailable),
        ):
            probe.execute(
                "SELECT current_sequence FROM games_libraryeventstreamhead"
                " WHERE id = %s FOR UPDATE NOWAIT",
                [head_id],
            )


@pytest.mark.django_db(transaction=True)
def test_concurrent_appends_serialize_into_one_contiguous_range(owned_library):
    #: The head must already be committed. A head this test's holder creates is
    #: invisible to the waiter, whose SELECT ... FOR UPDATE then matches zero
    #: rows and returns without waiting -- the appends would serialize on the
    #: unique index inside get_or_create, and the head lock would go untested.
    with transaction.atomic():
        append(owned_library, idempotency_key="seed")

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
                results["holder"] = append_directly(
                    stream,
                    [make_new_event(), make_new_event()],
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
            with (
                connection.execute_wrapper(announce_lock_request),
                transaction.atomic(),
            ):
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
    assert (holder_result.first_sequence, holder_result.last_sequence) == (2, 3)
    assert (waiter_result.first_sequence, waiter_result.last_sequence) == (4, 5)
    assert holder_result.stream_id == waiter_result.stream_id
    assert list(
        LibraryEvent.objects.order_by("sequence").values_list("sequence", flat=True)
    ) == [1, 2, 3, 4, 5]
