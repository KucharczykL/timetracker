import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from django.db import IntegrityError, migrations, transaction
from django.db.migrations.loader import MigrationLoader

from games.events.idempotency import fingerprint_command_input
from games.models import LibraryIdempotencyRecord
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
        pytest.param(
            datetime(2026, 8, 22, 11, tzinfo=UTC), id="datetime"
        ),
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
