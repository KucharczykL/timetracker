import uuid
from datetime import UTC, date, datetime, timedelta
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
    StreamSequenceMismatch,
    TransactionRequired,
    lock_stream,
)
from games.events.retry import run_in_transaction
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
    """Every JSON container, plus a widening float."""

    tags: list[str]
    counts: dict[str, int]
    ratio: float


@with_config(STRICT_CONFIG)
class OpaquePayload(TypedDict):
    """A field pydantic will not look inside."""

    details: dict[str, Any]


PROBE_RECORDED = EventSpec(
    "library.probe.recorded", aggregate_type="probe", payload=ProbePayload
)
#: Second spec: version and type from registration.
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

#: Never registered: an append must refuse it.
UNREGISTERED = EventSpec(
    "library.unregistered.happened", aggregate_type="probe", payload=ProbePayload
)
#: Registered type, unregistered spec, disagreeing about everything.
MISDECLARED_PROBE = EventSpec(
    "library.probe.recorded",
    aggregate_type="mistaken",
    payload=ProbePayload,
    version=9,
)

#: This module's own vocabulary, never production's.
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
    """An append that skips `lock_stream`."""
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


def test_an_event_carries_its_recorded_at_in_its_identity(owned_library):
    """A UUIDv7 minted at any moment other than the row's own is a violation.

    `check_ordering` in the identity audit holds every event's identity to its
    `recorded_at` order, and no database constraint enforces it. An append that
    is given a `recorded_at` is therefore given the moment to mint from too.
    """
    moment = datetime(2019, 7, 1, 12, 0, 0, 123_456, tzinfo=UTC)

    with transaction.atomic():
        result = append(owned_library, recorded_at=moment)

    (event,) = result.events
    embedded = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
        milliseconds=event.id.int >> 80
    )
    assert embedded == moment.replace(microsecond=123_000)


def test_backdated_appends_order_by_recorded_at_below_the_millisecond(owned_library):
    """Two moments one millisecond apart still order the way they happened.

    The sample fixture loads hundreds of games in a few milliseconds, so the
    identity has to separate them on the microsecond the row records, not on
    the order the backfill happens to append them in.
    """
    earlier = datetime(2021, 3, 4, 5, 6, 7, 800_500, tzinfo=UTC)
    later = datetime(2021, 3, 4, 5, 6, 7, 800_900, tzinfo=UTC)

    with transaction.atomic():
        append(owned_library, recorded_at=later, idempotency_key="later")
    with transaction.atomic():
        append(owned_library, recorded_at=earlier, idempotency_key="earlier")

    assert list(
        LibraryEvent.objects.order_by("id").values_list("recorded_at", flat=True)
    ) == [earlier, later]


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
    assert event.aggregate_id == aggregate_id
    assert event.payload == {"nested": {"id": str(aggregate_id)}}
    assert event.effective_time == effective_time
    assert event.causation_id == causation_id
    assert event.source_metadata == {"origin": "manual"}


def test_the_row_is_built_from_the_registered_spec(owned_library):
    """The registration decides, not the caller's spec."""
    with transaction.atomic():
        append(owned_library, [make_new_event(spec=MISDECLARED_PROBE)])

    event = LibraryEvent.objects.get()
    assert event.payload_schema_version == PROBE_RECORDED.version == 1
    #: No aggregate_type: the spec alone declares it.
    assert not hasattr(event, "aggregate_type")
    assert EVENT_TYPES.spec_for(event.event_type).aggregate_type == "probe"


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


#: Canonicalizer inputs, not payloads any schema declares.
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
    """Why the canonicalizer runs before validation."""
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
    """Refuse, then show the transaction still commits."""
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
    """The one case equality cannot see."""
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
    #: spec.new types the payload against its schema.
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


def test_require_sequence_accepts_the_current_head(owned_library):
    with transaction.atomic():
        append(owned_library)
        assert lock_stream(owned_library).require_sequence(1) is None


def test_require_sequence_accepts_zero_on_a_provisioned_head(owned_library):
    with transaction.atomic():
        assert lock_stream(owned_library).require_sequence(0) is None

    assert not LibraryEvent.objects.exists()


def test_require_sequence_refuses_an_expectation_the_stream_has_passed(owned_library):
    with transaction.atomic():
        append(owned_library, [make_new_event(), make_new_event()])
        with pytest.raises(StreamSequenceMismatch) as refusal:
            lock_stream(owned_library).require_sequence(1)

    assert refusal.value.expected == 1
    assert refusal.value.actual == 2


def test_require_sequence_refuses_an_expectation_above_the_head(owned_library):
    with transaction.atomic():
        append(owned_library)
        #: A ValueError rather than a mismatch, which is not one.
        with pytest.raises(ValueError, match="never at 7"):
            lock_stream(owned_library).require_sequence(7)


def test_require_sequence_refuses_a_negative_expectation(owned_library):
    with transaction.atomic():
        append(owned_library, [make_new_event() for _ in range(5)])
        #: Also below the head, so this asserts which branch wins.
        with pytest.raises(ValueError, match="never negative"):
            lock_stream(owned_library).require_sequence(-1)


def test_require_sequence_ignores_a_stale_double_locked_stream(owned_library):
    with transaction.atomic():
        stale = lock_stream(owned_library)
        append_directly(lock_stream(owned_library), [make_new_event()])

        assert stale.current_sequence == 0
        assert stale.require_sequence(1) is None


def test_require_sequence_refuses_a_stale_stream_agreeing_with_itself(owned_library):
    with transaction.atomic():
        stale = lock_stream(owned_library)
        append_directly(lock_stream(owned_library), [make_new_event()])

        #: A cached compare would agree with itself.
        with pytest.raises(StreamSequenceMismatch) as refusal:
            stale.require_sequence(0)

    assert (refusal.value.expected, refusal.value.actual) == (0, 1)


def test_require_sequence_ignores_a_stale_head_after_a_savepoint_rollback(
    owned_library,
):
    with transaction.atomic():
        stream = lock_stream(owned_library)
        try:
            with transaction.atomic():
                append_directly(stream, [make_new_event()])
                raise RuntimeError("roll the savepoint back")
        except RuntimeError:
            pass

        assert stream.current_sequence == 1
        assert stream.require_sequence(0) is None

    assert not LibraryEvent.objects.exists()


def test_an_append_with_a_matching_expectation_records_normally(owned_library):
    with transaction.atomic():
        first = append(owned_library, expected_sequence=0)
        second = append(owned_library, expected_sequence=1)

    assert (first.first_sequence, first.last_sequence) == (1, 1)
    assert (second.first_sequence, second.last_sequence) == (2, 2)


def test_an_append_refused_on_its_expectation_writes_nothing(owned_library):
    with transaction.atomic():
        append(owned_library)
        with pytest.raises(StreamSequenceMismatch):
            append(
                owned_library,
                [make_new_event(), make_new_event()],
                expected_sequence=0,
            )

    assert LibraryEvent.objects.count() == 1
    head = LibraryEventStreamHead.objects.get(library=owned_library)
    assert head.current_sequence == 1


def test_an_empty_append_is_refused_before_its_expectation(owned_library):
    with transaction.atomic():
        append(owned_library)
        #: The programming error wins; a stale expectation cannot reclassify it.
        with pytest.raises(ValueError, match="at least one event"):
            append_directly(lock_stream(owned_library), [], expected_sequence=0)


def test_a_refused_append_leaves_the_transaction_committable(
    owned_library, second_library
):
    with transaction.atomic():
        append(owned_library)
        append(second_library, idempotency_key="unrelated")
        with pytest.raises(StreamSequenceMismatch):
            append(owned_library, expected_sequence=0)

    assert LibraryEvent.objects.filter(library=owned_library).count() == 1
    assert LibraryEvent.objects.filter(library=second_library).count() == 1


def test_one_expectation_cannot_serve_two_appends_on_one_stream(owned_library):
    with transaction.atomic():
        stream = lock_stream(owned_library)
        append_directly(stream, [make_new_event()], expected_sequence=0)
        with pytest.raises(StreamSequenceMismatch) as refusal:
            append_directly(stream, [make_new_event()], expected_sequence=0)

    assert (refusal.value.expected, refusal.value.actual) == (0, 1)


@pytest.mark.django_db(transaction=True)
def test_a_sequence_mismatch_is_not_retried_and_rolls_back(owned_library):
    with transaction.atomic():
        append(owned_library)

    attempts = 0

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        append(owned_library, idempotency_key="doomed")
        append(owned_library, expected_sequence=0)

    with pytest.raises(StreamSequenceMismatch):
        run_in_transaction(operation)

    assert attempts == 1
    #: The doomed append went back with the transaction.
    assert LibraryEvent.objects.count() == 1


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


@pytest.mark.django_db(transaction=True)
def test_require_sequence_refuses_an_expectation_formed_before_the_lock(owned_library):
    with transaction.atomic():
        append(owned_library, idempotency_key="seed")

    holder_locked = Event()
    waiter_requested_lock = Event()
    refusals: dict[str, StreamSequenceMismatch] = {}
    errors: list[BaseException] = []

    def run_holder():
        close_old_connections()
        try:
            with transaction.atomic():
                stream = lock_stream(owned_library)
                holder_locked.set()
                append_directly(stream, [make_new_event()], idempotency_key="holder")
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
                waiter_requested_lock.set()
            return execute(sql, params, many, context)

        try:
            assert holder_locked.wait(10)
            #: Non-locking, and before the lock. A FOR UPDATE read here would
            #: release the holder, block, and return the advanced head -- an
            #: expectation that passes, proving nothing.
            expected = LibraryEventStreamHead.objects.get(
                library=owned_library
            ).current_sequence
            with (
                connection.execute_wrapper(announce_lock_request),
                transaction.atomic(),
            ):
                stream = lock_stream(owned_library)
                #: Caught here: the harness fails on anything left in errors.
                try:
                    stream.require_sequence(expected)
                except StreamSequenceMismatch as refusal:
                    refusals["waiter"] = refusal
        except BaseException as error:  # noqa: BLE001 - return thread failures
            errors.append(error)
        finally:
            close_old_connections()

    holder = Thread(target=run_holder, name="sequence-holder")
    waiter = Thread(target=run_waiter, name="sequence-waiter")
    holder.start()
    waiter.start()
    holder.join(20)
    waiter.join(20)

    assert not errors, errors
    assert not holder.is_alive()
    assert not waiter.is_alive()

    refusal = refusals["waiter"]
    assert (refusal.expected, refusal.actual) == (1, 2)
    assert list(
        LibraryEvent.objects.order_by("sequence").values_list("sequence", flat=True)
    ) == [1, 2]
