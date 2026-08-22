from typing import Any

import pytest
from django.db import IntegrityError, migrations, transaction
from django.db.migrations.loader import MigrationLoader

from games.models import LibraryIdempotencyRecord

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
