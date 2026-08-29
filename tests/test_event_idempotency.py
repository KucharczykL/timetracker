import contextlib
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from threading import Event, Thread
from typing import Any, TypedDict

import pytest
from django.db import (
    IntegrityError,
    close_old_connections,
    connection,
    migrations,
    transaction,
)
from django.db.migrations.loader import MigrationLoader
from pydantic import ConfigDict, with_config

from games.events.append import AppendResult, LockedStream, lock_stream
from games.events.conflicts import CommandConflict
from games.events.idempotency import (
    FINGERPRINT_VERSION,
    IdempotencyKeyMismatch,
    ReplayedAppend,
    UnchangedAppend,
    _encode_command_value,
    fingerprint_command_input,
    idempotent_append,
)
from games.events.vocabulary import EventSpec, EventTypeRegistry, NewEvent, Unchanged
from games.events.wiring import EventWiring
from games.models import (
    LibraryEvent,
    LibraryEventStreamHead,
    LibraryIdempotencyRecord,
)
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db

IDEMPOTENCY_MIGRATION = ("games", "0024_libraryidempotencyrecord")


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library


def make_record(library, **overrides: Any) -> LibraryIdempotencyRecord:
    fields: dict[str, Any] = {
        "library": library,
        "idempotency_key": "probe-key",
        "request_fingerprint": "f" * 64,
        "fingerprint_version": 1,
        "first_sequence": 1,
        "last_sequence": 1,
    }
    fields.update(overrides)
    return LibraryIdempotencyRecord.objects.create(**fields)


def test_a_key_is_unique_within_one_library(owned_library):
    make_record(owned_library)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_record(owned_library)


def test_two_libraries_may_use_the_same_key(owned_library, second_library):
    first = make_record(owned_library)
    second = make_record(second_library)

    assert first.idempotency_key == second.idempotency_key
    assert LibraryIdempotencyRecord.objects.count() == 2


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {"first_sequence": 0, "last_sequence": 0}, id="sequence-below-one"
        ),
        pytest.param({"first_sequence": 3, "last_sequence": 2}, id="range-inverted"),
        pytest.param({"first_sequence": None}, id="only-the-first-absent"),
        pytest.param({"last_sequence": None}, id="only-the-last-absent"),
        pytest.param({"idempotency_key": ""}, id="empty-key"),
        pytest.param({"request_fingerprint": ""}, id="empty-fingerprint"),
        pytest.param({"fingerprint_version": 0}, id="version-below-one"),
    ],
)
def test_rejected_records(owned_library, overrides: dict[str, Any]):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_record(owned_library, **overrides)


def test_a_record_may_carry_no_range_at_all(owned_library):
    """A command that changed nothing still claims its key."""
    record = make_record(owned_library, first_sequence=None, last_sequence=None)

    record.refresh_from_db()
    assert (record.first_sequence, record.last_sequence) == (None, None)


@with_config(ConfigDict(extra="forbid", strict=True))
class ProbePayload(TypedDict):
    probe: bool


PROBE_RECORDED = EventSpec(
    "library.probe.recorded", aggregate_type="probe", payload=ProbePayload
)

#: This module's own vocabulary, never production's.
EVENT_TYPES = EventTypeRegistry()
EVENT_TYPES.register(PROBE_RECORDED)
WIRING = EventWiring(event_types=EVENT_TYPES)


def make_new_event(**overrides: Any) -> NewEvent:
    fields: dict[str, Any] = {
        "spec": PROBE_RECORDED,
        "aggregate_id": uuid.uuid7(),
        "payload": {"probe": True},
    }
    fields.update(overrides)
    return NewEvent(**fields)


def run_command(library, events: list[NewEvent] | None = None, **overrides: Any):
    fields: dict[str, Any] = {
        "idempotency_key": "probe-key",
        "command_input": {"probe": True},
        "build": lambda _stream: events if events is not None else [make_new_event()],
        "actor": None,
        "correlation_id": uuid.uuid7(),
        "wiring": WIRING,
    }
    fields.update(overrides)
    return idempotent_append(library, **fields)


def test_a_fresh_command_appends_and_records_its_range(owned_library):
    with transaction.atomic():
        result = run_command(owned_library, [make_new_event(), make_new_event()])

    record = LibraryIdempotencyRecord.objects.get()
    assert (record.first_sequence, record.last_sequence) == (1, 2)
    assert (result.first_sequence, result.last_sequence) == (1, 2)
    assert record.fingerprint_version == FINGERPRINT_VERSION
    assert record.request_fingerprint == fingerprint_command_input({"probe": True})
    assert LibraryEvent.objects.count() == 2


def test_repeating_a_key_replays_the_original_range(owned_library):
    with transaction.atomic():
        original = run_command(owned_library, [make_new_event(), make_new_event()])

    with transaction.atomic():
        replay = run_command(owned_library)

    assert isinstance(replay, ReplayedAppend)
    assert replay.stream_id == original.stream_id
    assert (replay.first_sequence, replay.last_sequence) == (1, 2)
    assert LibraryEvent.objects.count() == 2
    assert LibraryIdempotencyRecord.objects.count() == 1
    assert LibraryEventStreamHead.objects.get().current_sequence == 2


def test_a_replay_never_builds_its_events(owned_library):
    builds: list[str] = []

    def build(_stream) -> list[NewEvent]:
        builds.append("built")
        return [make_new_event()]

    with transaction.atomic():
        run_command(owned_library, build=build)
    with transaction.atomic():
        run_command(owned_library, build=build)

    assert builds == ["built"]


def test_a_key_reused_over_different_input_is_refused(owned_library):
    with transaction.atomic():
        run_command(owned_library)

    with transaction.atomic():
        with pytest.raises(IdempotencyKeyMismatch, match="probe-key"):
            run_command(owned_library, command_input={"probe": False})

        #: The mismatch is raised before any write, so the caller's transaction
        #: survives it -- unlike every failure in the append module.
        result = run_command(
            owned_library, idempotency_key="second-key", command_input={"probe": False}
        )

    assert (result.first_sequence, result.last_sequence) == (2, 2)
    assert LibraryIdempotencyRecord.objects.count() == 2


def test_a_record_from_another_fingerprint_version_replays_unchecked(owned_library):
    with transaction.atomic():
        run_command(owned_library)

    LibraryIdempotencyRecord.objects.update(
        fingerprint_version=FINGERPRINT_VERSION + 1,
        request_fingerprint="0" * 64,
    )

    with transaction.atomic():
        replay = run_command(owned_library, command_input={"probe": "different"})

    assert isinstance(replay, ReplayedAppend)
    assert LibraryEvent.objects.count() == 1


def test_one_key_in_two_libraries_is_two_commands(owned_library, second_library):
    with transaction.atomic():
        first = run_command(owned_library)
    with transaction.atomic():
        second = run_command(second_library)

    assert first.stream_id != second.stream_id
    assert LibraryIdempotencyRecord.objects.count() == 2
    assert LibraryEvent.objects.count() == 2


def test_a_command_recording_nothing_claims_no_key(owned_library):
    with transaction.atomic(), pytest.raises(ValueError, match="at least one event"):
        run_command(owned_library, [])

    assert not LibraryIdempotencyRecord.objects.exists()

    with transaction.atomic():
        result = run_command(owned_library)

    assert result.first_sequence == 1


def test_a_command_that_changes_nothing_records_no_event(owned_library):
    with transaction.atomic():
        result = run_command(
            owned_library, build=lambda _stream: Unchanged("nothing to do")
        )

    assert isinstance(result, UnchangedAppend)
    assert result.reason == "nothing to do"
    assert not LibraryEvent.objects.exists()
    assert LibraryEventStreamHead.objects.get().current_sequence == 0


def test_a_command_that_changes_nothing_still_claims_its_key(owned_library):
    with transaction.atomic():
        run_command(owned_library, build=lambda _stream: Unchanged("nothing to do"))

    record = LibraryIdempotencyRecord.objects.get()
    assert (record.first_sequence, record.last_sequence) == (None, None)
    assert record.request_fingerprint == fingerprint_command_input({"probe": True})
    assert record.fingerprint_version == FINGERPRINT_VERSION


def test_a_claimed_no_op_key_cannot_append_after_the_state_moves(owned_library):
    """The lost update the record exists to close."""
    with transaction.atomic():
        run_command(owned_library, build=lambda _stream: Unchanged("nothing to do"))

    #: The state has moved under the same key, so this build would append.
    with transaction.atomic():
        replay = run_command(owned_library, build=lambda _stream: [make_new_event()])

    assert isinstance(replay, UnchangedAppend)
    #: The build never ran, so there is no sentence to hand back.
    assert replay.reason is None
    assert not LibraryEvent.objects.exists()
    assert LibraryIdempotencyRecord.objects.count() == 1


def test_a_no_op_never_rebuilds_on_a_repeat(owned_library):
    builds: list[str] = []

    def build(_stream: LockedStream) -> Unchanged:
        builds.append("built")
        return Unchanged("nothing to do")

    with transaction.atomic():
        run_command(owned_library, build=build)
    with transaction.atomic():
        run_command(owned_library, build=build)

    assert builds == ["built"]


def test_a_rolled_back_command_leaves_its_key_usable(owned_library):
    with contextlib.suppress(RuntimeError), transaction.atomic():
        run_command(owned_library)
        raise RuntimeError("the command failed after appending")

    assert not LibraryEvent.objects.exists()
    assert not LibraryIdempotencyRecord.objects.exists()

    with transaction.atomic():
        result = run_command(owned_library)

    assert (result.first_sequence, result.last_sequence) == (1, 1)


@pytest.mark.django_db(transaction=True)
def test_one_key_issued_concurrently_appends_once(owned_library):
    #: The head must already be committed. A head the holder creates is
    #: invisible to the waiter, whose SELECT ... FOR UPDATE would then match
    #: zero rows and return without waiting, leaving the blocking path this
    #: test exists to exercise untouched.
    with transaction.atomic():
        run_command(owned_library, idempotency_key="seed")

    holder_locked = Event()
    waiter_requested_lock = Event()
    results: dict[str, AppendResult | ReplayedAppend] = {}
    errors: list[BaseException] = []

    def duplicate_command(library):
        return run_command(
            library,
            [make_new_event(), make_new_event()],
            idempotency_key="shared",
            command_input={"shared": True},
        )

    def run_holder():
        close_old_connections()
        try:
            with transaction.atomic():
                #: idempotent_append owns both the lock and the append, leaving
                #: no seam to signal from. Taking the lock here first is
                #: re-entrant within this transaction and restores the seam.
                lock_stream(owned_library)
                holder_locked.set()
                results["holder"] = duplicate_command(owned_library)
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
            with (
                connection.execute_wrapper(announce_lock_request),
                transaction.atomic(),
            ):
                results["waiter"] = duplicate_command(owned_library)
        except BaseException as error:  # noqa: BLE001 - return thread failures
            errors.append(error)
        finally:
            close_old_connections()

    holder = Thread(target=run_holder, name="duplicate-holder")
    waiter = Thread(target=run_waiter, name="duplicate-waiter")
    holder.start()
    waiter.start()
    holder.join(20)
    waiter.join(20)

    assert not errors, errors
    assert not holder.is_alive()
    assert not waiter.is_alive()

    ranges = {
        (result.first_sequence, result.last_sequence) for result in results.values()
    }
    assert ranges == {(2, 3)}
    #: Which thread won is the scheduler's business; that exactly one appended
    #: is not.
    assert sorted(type(result).__name__ for result in results.values()) == [
        "AppendResult",
        "ReplayedAppend",
    ]
    assert LibraryEvent.objects.count() == 3
    assert (
        LibraryIdempotencyRecord.objects.filter(idempotency_key="shared").count() == 1
    )


def test_key_order_does_not_change_the_digest():
    assert fingerprint_command_input(
        {"note": "played", "game": "Tunic"}
    ) == fingerprint_command_input({"game": "Tunic", "note": "played"})


def test_nested_dictionaries_are_sorted_too():
    assert fingerprint_command_input(
        {"session": {"note": "played", "game": "Tunic"}}
    ) == fingerprint_command_input({"session": {"game": "Tunic", "note": "played"}})


def test_list_order_is_significant():
    assert fingerprint_command_input(
        {"games": ["Tunic", "Hades"]}
    ) != fingerprint_command_input({"games": ["Hades", "Tunic"]})


def test_a_changed_value_changes_the_digest():
    assert fingerprint_command_input({"game": "Tunic"}) != fingerprint_command_input(
        {"game": "Hades"}
    )


def test_the_digest_is_lowercase_hexadecimal_sha256():
    digest = fingerprint_command_input({"game": "Tunic"})

    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(uuid.uuid7(), id="uuid"),
        pytest.param(datetime(2026, 8, 22, 11, tzinfo=UTC), id="datetime"),
        pytest.param(date(2026, 8, 22), id="date"),
        pytest.param(Decimal("19.99"), id="decimal"),
        pytest.param(TemporalValue.from_day(date(2026, 8, 22)), id="temporal-value"),
    ],
)
def test_accepted_command_input_values(value: Any):
    assert len(fingerprint_command_input({"value": value})) == 64


def test_a_datetime_and_its_date_differ():
    """The same calendar day is not the same input as a moment within it."""
    day = date(2026, 8, 22)
    moment = datetime(2026, 8, 22, tzinfo=UTC)

    assert fingerprint_command_input({"when": day}) != fingerprint_command_input(
        {"when": moment}
    )


def test_an_unsupported_value_is_refused():
    with pytest.raises(TypeError):
        fingerprint_command_input({"platforms": {"pc", "switch"}})


@pytest.mark.parametrize(
    ("written", "same_value"),
    [
        pytest.param("1.1", "1.10", id="trailing-zero"),
        pytest.param("100", "1E+2", id="exponent-form"),
        pytest.param("0.00", "-0.00", id="signed-zero"),
    ],
)
def test_a_decimal_is_the_number_not_the_text(written: str, same_value: str):
    """A form renders 12.50, the browser retries with 12.5, and one honest
    retry must not be answered as a conflict."""
    assert fingerprint_command_input(
        {"price": Decimal(written)}
    ) == fingerprint_command_input({"price": Decimal(same_value)})


def test_two_decimals_that_differ_keep_separate_digests():
    assert fingerprint_command_input(
        {"price": Decimal("1.1")}
    ) != fingerprint_command_input({"price": Decimal("1.11")})


def test_a_decimal_differing_past_the_context_precision_is_a_different_input():
    """normalize() rounds to the context's 28 digits, so both of these would
    reach one canonical form and the second command would be answered with the
    first one's range. No shorter pair catches that."""
    assert fingerprint_command_input(
        {"price": Decimal("1.000000000000000000000000000000001")}
    ) != fingerprint_command_input(
        {"price": Decimal("1.000000000000000000000000000000002")}
    )


def test_a_decimal_digest_ignores_the_active_context():
    """The canonical form is read from the value, so no thread-local setting
    in this process can move it."""
    price = Decimal("1.100000001")

    with localcontext() as context:
        context.prec = 5
        narrowed = fingerprint_command_input({"price": price})

    assert narrowed == fingerprint_command_input({"price": price})


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_a_non_finite_decimal_is_refused(value: str):
    """sNaN is here because it signals on comparison: the refusal has to be
    reached before anything compares the value."""
    with pytest.raises(TypeError):
        fingerprint_command_input({"price": Decimal(value)})


def test_one_instant_in_two_offsets_is_one_input():
    """USE_TZ is on and TIME_ZONE is Europe/Prague, so a local-aware value and
    a UTC one for the same moment are an ordinary pair to hold.

    This also pins the branch order: datetime subclasses date, and a date-first
    branch never applies the UTC canonical form.
    """
    utc_noon = datetime(2026, 8, 22, 12, tzinfo=UTC)
    prague_afternoon = datetime(2026, 8, 22, 14, tzinfo=timezone(timedelta(hours=2)))

    assert utc_noon == prague_afternoon
    assert fingerprint_command_input({"when": utc_noon}) == (
        fingerprint_command_input({"when": prague_afternoon})
    )


def test_a_naive_datetime_is_refused():
    """astimezone() on a naive value reads the machine's timezone, so its
    canonical form would differ between processes."""
    naive = datetime(2026, 8, 22, 12)  # noqa: DTZ001 -- the value under test

    with pytest.raises(TypeError):
        fingerprint_command_input({"when": naive})


def test_the_tag_words_are_the_wire_form():
    """Renaming one moves every digest that carries that type, which is a
    FINGERPRINT_VERSION bump. Nothing else in this file would notice."""
    identifier = uuid.uuid7()

    assert _encode_command_value(datetime(2026, 8, 22, 12, tzinfo=UTC)) == (
        "datetime",
        "2026-08-22T12:00:00+00:00",
    )
    assert _encode_command_value(date(2026, 8, 22)) == ("date", "2026-08-22")
    assert _encode_command_value(identifier) == ("uuid", str(identifier))
    assert _encode_command_value(Decimal("1.10")) == ("decimal", "11E-1")
    assert _encode_command_value(TemporalValue.from_year(2026)) == (
        "temporal",
        "2026",
    )
    assert _encode_command_value(TemporalValue.unknown()) == ("temporal", None)


def test_a_value_and_its_own_text_are_not_the_same_input():
    """Without the word, a key issued for one replays the other."""
    identifier = uuid.uuid7()
    day = date(2026, 8, 22)
    pairs = [
        (Decimal("1.10"), "11E-1"),
        (identifier, str(identifier)),
        (day, day.isoformat()),
    ]

    for value, text in pairs:
        assert fingerprint_command_input({"field": value}) != (
            fingerprint_command_input({"field": text})
        )


def test_a_date_and_a_temporal_value_for_that_day_differ():
    """Both canonicalize to 2026-08-22, so only the word keeps them apart."""
    day = date(2026, 8, 22)

    assert fingerprint_command_input({"when": day}) != fingerprint_command_input(
        {"when": TemporalValue.from_day(day)}
    )


def test_an_unknown_temporal_value_and_an_unset_field_differ():
    """An unknown time encodes as None, which json writes as the null an unset
    field also writes."""
    assert fingerprint_command_input(
        {"when": TemporalValue.unknown()}
    ) != fingerprint_command_input({"when": None})


def test_a_decimal_and_an_int_of_the_same_value_differ():
    """Decimal(1) == 1, and they are still two different inputs: the digest
    identifies a value's type as well as its meaning."""
    assert fingerprint_command_input(
        {"count": Decimal(1)}
    ) != fingerprint_command_input({"count": 1})


def test_the_idempotency_migration_is_reversible():
    """0023 refuses reversal to protect the only copy of the user's history.

    These records are operational metadata, so the table stays droppable -- and
    a RunPython here would be the guard copied by analogy.
    """
    migration = MigrationLoader(None).disk_migrations[IDEMPOTENCY_MIGRATION]

    assert not any(
        isinstance(operation, migrations.RunPython)
        for operation in migration.operations
    )


def test_a_key_mismatch_is_a_command_conflict():
    #: A dispatcher catches one base for "another command was in the way" and
    #: may narrow to the leaves for two different messages.
    assert issubclass(IdempotencyKeyMismatch, CommandConflict)
