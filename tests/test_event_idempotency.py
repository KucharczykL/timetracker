import contextlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from django.db import IntegrityError, migrations, transaction
from django.db.migrations.loader import MigrationLoader

from games.events.append import NewEvent
from games.events.idempotency import (
    FINGERPRINT_VERSION,
    IdempotencyKeyMismatch,
    ReplayedAppend,
    fingerprint_command_input,
    idempotent_append,
)
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
        pytest.param({"idempotency_key": ""}, id="empty-key"),
        pytest.param({"request_fingerprint": ""}, id="empty-fingerprint"),
        pytest.param({"fingerprint_version": 0}, id="version-below-one"),
    ],
)
def test_rejected_records(owned_library, overrides: dict[str, Any]):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_record(owned_library, **overrides)


def make_new_event(**overrides: Any) -> NewEvent:
    fields: dict[str, Any] = {
        "event_type": "library.probe.recorded",
        "aggregate_type": "probe",
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


def test_a_rolled_back_command_leaves_its_key_usable(owned_library):
    with contextlib.suppress(RuntimeError), transaction.atomic():
        run_command(owned_library)
        raise RuntimeError("the command failed after appending")

    assert not LibraryEvent.objects.exists()
    assert not LibraryIdempotencyRecord.objects.exists()

    with transaction.atomic():
        result = run_command(owned_library)

    assert (result.first_sequence, result.last_sequence) == (1, 1)


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
    """datetime subclasses date, so a date-first branch would collapse them."""
    day = date(2026, 8, 22)
    moment = datetime(2026, 8, 22, tzinfo=UTC)

    assert fingerprint_command_input({"when": day}) != fingerprint_command_input(
        {"when": moment}
    )


def test_an_unsupported_value_is_refused():
    with pytest.raises(TypeError):
        fingerprint_command_input({"platforms": {"pc", "switch"}})


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
