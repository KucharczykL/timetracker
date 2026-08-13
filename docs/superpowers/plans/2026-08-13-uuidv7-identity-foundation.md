# UUIDv7 identity foundation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PostgreSQL-enforced UUIDv7 domain, reusable Django field, shared parsing/URL validation, and non-fatal application/database clock-skew warning without converting an existing model.

**Architecture:** PostgreSQL owns the invariant through a nullable `uuid_v7` domain over `uuid`. `UUIDv7Field` normally assigns `uuid.uuid7()` in Python and supplies PostgreSQL `uuidv7()` as the column fallback; shared parsing validates all untrusted inputs, and the existing physical-connection contract query observes database time without an additional round trip.

**Tech Stack:** Python 3.14 standard-library `uuid`, Django 6, PostgreSQL 18, psycopg 3, pytest/pytest-django, GNU Make.

## Global Constraints

- Complete `docs/superpowers/plans/2026-08-13-postgresql-only-cleanup.md` first and keep its commits separate from this feature.
- Use only the Python 3.14 standard library and PostgreSQL 18 UUID functions; add no UUID package dependency.
- The database type is the reusable `uuid_v7` domain. Do not substitute repeated per-column checks.
- The domain permits `NULL`; individual fields own nullability.
- The domain has no default; `UUIDv7Field` owns Python and database defaults and allows explicit overrides.
- Require both the RFC 9562 variant and version 7. Use `uuid_extract_version(VALUE) IS NOT DISTINCT FROM 7` so non-RFC variants cannot pass through SQL `NULL` check semantics.
- Do not use `IF NOT EXISTS`, `IF EXISTS`, or `CASCADE` in the domain migration.
- Do not convert any existing model key, relationship, row, URL, API response, or Django-owned table in issue #639.
- Do not add UUID timestamp extraction as application data. Explicit timestamps and sequence fields remain authoritative.
- Clock skew greater than one second warns once per episode and never changes connection acceptance, liveness, or readiness.
- Do not customize `inspectdb`; document `column::uuid` for clients that cannot resolve the domain base type.
- Keep the Makefile's default `PYTEST_WORKERS`. On Windows Codex desktop, run `make check`, `make check-fast`, and test targets through a managed hidden process and wait for its final log and exit status.
- Do not modify or stage the existing untracked `.pnpm-store/` directory.

## File Structure

- Create `games/migrations/0002_uuid_v7_domain.py`: reversible schema-level domain creation.
- Create `timetracker/uuidv7.py`: parser error, parser, Django validator, route converter, database-default expression, and `UUIDv7Field`.
- Modify `timetracker/urls.py`: register the `uuidv7` converter before building URL patterns.
- Create `tests/test_uuidv7_domain.py`: PostgreSQL catalog, constraint, and migration lifecycle tests.
- Create `tests/test_uuidv7.py`: parser, validation, URL, field metadata, unsaved-model, ORM, raw-SQL, index, and foreign-key tests.
- Modify `timetracker/postgres_contract.py`: add one-query database-time observation while preserving the existing static contract API.
- Modify `timetracker/database.py`: measure, deduplicate, and log non-fatal clock skew on physical default connections.
- Modify `tests/test_postgres_contract.py`: cover the five-column connection observation.
- Create `tests/test_database_clock.py`: pure measurement/state tests and connection-hook warning tests.
- Modify `README.md` and `docs/deployment.md`: record the field/domain convention, external casts, timestamp semantics, and clock warning.

---

### Task 1: Create and prove the PostgreSQL UUIDv7 domain

**Files:**
- Create: `games/migrations/0002_uuid_v7_domain.py`
- Create: `tests/test_uuidv7_domain.py`

**Interfaces:**
- Consumes: PostgreSQL 18 `uuid`, `uuidv7()`, and `uuid_extract_version(uuid)`.
- Produces: schema type `uuid_v7`; migration key `games.0002_uuid_v7_domain`.

- [ ] **Step 1: Write failing catalog and constraint tests**

Create `tests/test_uuidv7_domain.py` with these core cases:

```python
import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db

BEFORE_DOMAIN = ("games", "0001_squashed_0036_alter_playevent_days_to_finish")
WITH_DOMAIN = ("games", "0002_uuid_v7_domain")


def domain_base_type() -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT base.typname
            FROM pg_type AS domain
            LEFT JOIN pg_type AS base ON base.oid = domain.typbasetype
            WHERE domain.typname = 'uuid_v7'
            """
        )
        row = cursor.fetchone()
    return None if row is None else row[0]


def test_uuid_v7_domain_uses_uuid_as_its_base_type():
    assert domain_base_type() == "uuid"


def test_uuid_v7_domain_accepts_v7_and_null():
    value = uuid.uuid7()
    with connection.cursor() as cursor:
        cursor.execute("SELECT %s::uuid_v7, NULL::uuid_v7", [value])
        stored, nullable = cursor.fetchone()
    assert uuid.UUID(str(stored)) == value
    assert nullable is None


def test_postgresql_uuidv7_timestamp_tracks_the_database_clock():
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp(), uuid_extract_timestamp(uuidv7())")
        database_time, embedded_time = cursor.fetchone()
    assert abs(database_time - embedded_time) < timedelta(seconds=1)


@pytest.mark.parametrize(
    "value",
    [
        uuid.uuid1(),
        uuid.uuid4(),
        uuid.UUID(int=0),
        uuid.UUID(int=(1 << 128) - 1),
        uuid.UUID("00000000-0000-7000-0000-000000000000"),
    ],
)
def test_uuid_v7_domain_rejects_every_non_v7_or_non_rfc_value(value):
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT %s::uuid_v7", [value])
```

The last literal carries a v7-looking version nibble but a non-RFC variant; it is the regression for `uuid_extract_version()` returning `NULL`.

- [ ] **Step 2: Run the tests to verify the domain is absent**

Run through a managed hidden process on Windows:

```text
make test-fast ARGS="tests/test_uuidv7_domain.py -x -v"
```

Expected: FAIL because `uuid_v7` does not exist and the catalog query returns no base type.

- [ ] **Step 3: Add the reversible domain migration**

Create `games/migrations/0002_uuid_v7_domain.py`:

```python
from django.db import migrations

CREATE_UUID_V7_DOMAIN = """
CREATE DOMAIN uuid_v7 AS uuid
CHECK (
    VALUE IS NULL
    OR uuid_extract_version(VALUE) IS NOT DISTINCT FROM 7
)
""".strip()

DROP_UUID_V7_DOMAIN = "DROP DOMAIN uuid_v7"


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0001_squashed_0036_alter_playevent_days_to_finish"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_UUID_V7_DOMAIN,
            reverse_sql=DROP_UUID_V7_DOMAIN,
        ),
    ]
```

Do not append a semicolon requirement to the constants, and do not wrap the operation in `SeparateDatabaseAndState`.

- [ ] **Step 4: Add an actual backward/forward migration test**

Append this test, using `finally` so the worker database is restored even when an assertion fails:

```python
@pytest.mark.django_db(transaction=True)
def test_uuid_v7_domain_migration_reverses_and_reapplies():
    try:
        MigrationExecutor(connection).migrate([BEFORE_DOMAIN])
        assert domain_base_type() is None

        MigrationExecutor(connection).migrate([WITH_DOMAIN])
        assert domain_base_type() == "uuid"
    finally:
        MigrationExecutor(connection).migrate([WITH_DOMAIN])
```

- [ ] **Step 5: Run the focused migration and drift gates**

Run through managed hidden processes on Windows:

```text
make test-fast ARGS="tests/test_uuidv7_domain.py -x -v"
make check-migrations
```

Expected: all domain tests PASS and migration drift reports `No changes detected`.

- [ ] **Step 6: Commit the schema foundation**

```text
git add games/migrations/0002_uuid_v7_domain.py tests/test_uuidv7_domain.py
git commit -m "feat: add UUIDv7 database domain"
```

---

### Task 2: Add shared parsing, validation, and URL conversion

**Files:**
- Create: `timetracker/uuidv7.py`
- Modify: `timetracker/urls.py`
- Create: `tests/test_uuidv7.py`

**Interfaces:**
- Consumes: `uuid.UUID`, `uuid.RFC_4122`, Django `ValidationError`, and Django's canonical UUID route regex.
- Produces: `UUIDv7ParseError`; `parse_uuidv7(value: str | uuid.UUID) -> uuid.UUID`; `validate_uuidv7(value: str | uuid.UUID) -> None`; `UUIDv7Converter` registered as `uuidv7`.

- [ ] **Step 1: Write failing parser and validator tests**

Start `tests/test_uuidv7.py` with:

```python
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError

from timetracker.uuidv7 import parse_uuidv7, validate_uuidv7


def test_parse_uuidv7_normalizes_text_and_preserves_uuid_objects():
    value = uuid.uuid7()
    assert parse_uuidv7(str(value)) == value
    assert parse_uuidv7(value) is value


def test_python_uuidv7_timestamp_tracks_the_application_clock():
    before = datetime.now(UTC) - timedelta(milliseconds=2)
    value = uuid.uuid7()
    after = datetime.now(UTC) + timedelta(milliseconds=2)
    embedded = datetime.fromtimestamp(value.time / 1_000, UTC)
    assert before <= embedded <= after


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("not-a-uuid", "invalid_uuid"),
        (uuid.uuid1(), "invalid_uuid_version"),
        (uuid.uuid4(), "invalid_uuid_version"),
        (uuid.UUID(int=0), "invalid_uuid_version"),
        (uuid.UUID(int=(1 << 128) - 1), "invalid_uuid_version"),
        (
            uuid.UUID("00000000-0000-7000-0000-000000000000"),
            "invalid_uuid_version",
        ),
    ],
)
def test_validate_uuidv7_uses_stable_error_codes(value, code):
    with pytest.raises(ValidationError) as caught:
        validate_uuidv7(value)
    assert caught.value.code == code
```

- [ ] **Step 2: Run the parser tests to verify they fail**

Run through a managed hidden process on Windows:

```text
make test-fast ARGS="tests/test_uuidv7.py -x -v"
```

Expected: collection FAIL with `ModuleNotFoundError: timetracker.uuidv7`.

- [ ] **Step 3: Implement the parser, internal error, and Django adapter**

Create `timetracker/uuidv7.py` with this first responsibility:

```python
import uuid

from django.core.exceptions import ValidationError

INVALID_UUID_CODE = "invalid_uuid"
INVALID_UUID_VERSION_CODE = "invalid_uuid_version"


class UUIDv7ParseError(ValueError):
    """A malformed UUID or a UUID outside the required variant/version."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def parse_uuidv7(value: str | uuid.UUID) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = uuid.UUID(value)
        except (AttributeError, ValueError) as exc:
            raise UUIDv7ParseError(
                "Enter a valid UUID.", code=INVALID_UUID_CODE
            ) from exc
    else:
        raise UUIDv7ParseError("Enter a valid UUID.", code=INVALID_UUID_CODE)

    if parsed.variant != uuid.RFC_4122 or parsed.version != 7:
        raise UUIDv7ParseError(
            "UUID must use RFC 9562 version 7.",
            code=INVALID_UUID_VERSION_CODE,
        )
    return parsed


def _parse_for_django(value: str | uuid.UUID) -> uuid.UUID:
    try:
        return parse_uuidv7(value)
    except UUIDv7ParseError as exc:
        raise ValidationError(str(exc), code=exc.code, params={"value": value}) from exc


def validate_uuidv7(value: str | uuid.UUID) -> None:
    _parse_for_django(value)
```

- [ ] **Step 4: Add failing converter and project-registration tests**

Extend `tests/test_uuidv7.py` after importing `timetracker.urls` for its registration side effect:

```python
from django.http import HttpResponse
from django.test import Client, override_settings
from django.urls import NoReverseMatch, get_converters, path, reverse

from timetracker import urls as project_urls  # noqa: F401
from timetracker.uuidv7 import UUIDv7Converter


def uuidv7_probe(request, value):
    return HttpResponse(str(value), content_type="text/plain")


urlpatterns = [
    path("uuidv7/<uuidv7:value>/", uuidv7_probe, name="uuidv7-probe"),
]


def test_project_registers_uuidv7_converter():
    assert isinstance(get_converters()["uuidv7"], UUIDv7Converter)


@override_settings(ROOT_URLCONF=__name__)
def test_uuidv7_route_normalizes_valid_input_and_rejects_other_versions():
    value = uuid.uuid7()
    client = Client()
    accepted = client.get(f"/uuidv7/{value}/")
    rejected = client.get(f"/uuidv7/{uuid.uuid4()}/")
    uppercase = client.get(f"/uuidv7/{str(value).upper()}/")

    assert accepted.status_code == 200
    assert accepted.content == str(value).encode()
    assert rejected.status_code == 404
    assert uppercase.status_code == 404


@override_settings(ROOT_URLCONF=__name__)
def test_uuidv7_route_refuses_to_generate_a_non_v7_url():
    with pytest.raises(NoReverseMatch):
        reverse("uuidv7-probe", kwargs={"value": uuid.uuid4()})
```

Running the focused file now must fail during URL pattern construction because `uuidv7` is not registered.

- [ ] **Step 5: Implement and register the converter**

Append to `timetracker/uuidv7.py`:

```python
from django.urls.converters import UUIDConverter


class UUIDv7Converter:
    regex = UUIDConverter.regex

    def to_python(self, value: str) -> uuid.UUID:
        return parse_uuidv7(value)

    def to_url(self, value: str | uuid.UUID) -> str:
        return str(parse_uuidv7(value))
```

Modify `timetracker/urls.py` before `urlpatterns` is constructed:

```python
from django.urls import include, path, register_converter

from timetracker.uuidv7 import UUIDv7Converter

register_converter(UUIDv7Converter, "uuidv7")
```

Registration belongs in the root URLconf so every included application can use the converter without importing a model app.

- [ ] **Step 6: Run parsing and routing tests**

Run through a managed hidden process on Windows:

```text
make test-fast ARGS="tests/test_uuidv7.py -x -v"
```

Expected: parser, validation-code, actual route-resolution, canonical-case, and reverse-generation tests PASS.

- [ ] **Step 7: Commit the untrusted-input boundary**

```text
git add timetracker/uuidv7.py timetracker/urls.py tests/test_uuidv7.py
git commit -m "feat: validate UUIDv7 inputs and routes"
```

---

### Task 3: Add the reusable Django field and prove ORM/database behavior

**Files:**
- Modify: `timetracker/uuidv7.py`
- Modify: `tests/test_uuidv7.py`

**Interfaces:**
- Consumes: `parse_uuidv7()` and `validate_uuidv7()` from Task 2; database type `uuid_v7` from Task 1.
- Produces: `PostgreSQLUUIDv7()` database expression and `UUIDv7Field(*args, **kwargs)` with overridable `default` and `db_default`.

- [ ] **Step 1: Write failing field metadata and unsaved-model tests**

Append to `tests/test_uuidv7.py`:

```python
from types import SimpleNamespace

from django.db import NotSupportedError, models
from django.test.utils import isolate_apps

from timetracker.uuidv7 import PostgreSQLUUIDv7, UUIDv7Field


def test_uuidv7_field_declares_stable_defaults_and_migration_path():
    field = UUIDv7Field(primary_key=True)
    _, path, args, kwargs = field.deconstruct()

    assert path == "timetracker.uuidv7.UUIDv7Field"
    assert args == []
    assert kwargs["primary_key"] is True
    assert kwargs["default"] is uuid.uuid7
    assert isinstance(kwargs["db_default"], PostgreSQLUUIDv7)


def test_uuidv7_field_allows_explicit_default_overrides():
    field = UUIDv7Field(default=None, db_default=None)
    assert field.default is None
    assert field.db_default is None


def test_uuidv7_field_rejects_an_unsupported_backend():
    with pytest.raises(NotSupportedError, match="PostgreSQL"):
        UUIDv7Field().db_type(SimpleNamespace(vendor="mysql"))


@isolate_apps("games")
def test_uuidv7_field_assigns_distinct_ids_before_save():
    class Probe(models.Model):
        id = UUIDv7Field(primary_key=True)

        class Meta:
            app_label = "games"

    first = Probe()
    second = Probe()

    assert first.pk.version == 7
    assert second.pk.version == 7
    assert first != second
    assert hash(first) != hash(second)
```

- [ ] **Step 2: Run the field tests to verify they fail**

Run through a managed hidden process on Windows:

```text
make test-fast ARGS="tests/test_uuidv7.py -k field -x -v"
```

Expected: collection FAIL because `PostgreSQLUUIDv7` and `UUIDv7Field` do not exist.

- [ ] **Step 3: Implement the database expression and custom field**

Append to `timetracker/uuidv7.py` and move all imports to the module header in normal project style:

```python
from django.db import NotSupportedError, models


class PostgreSQLUUIDv7(models.Func):
    function = "uuidv7"
    output_field = models.UUIDField()


class UUIDv7Field(models.UUIDField):
    default_validators = [validate_uuidv7]

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("default", uuid.uuid7)
        kwargs.setdefault("db_default", PostgreSQLUUIDv7())
        super().__init__(*args, **kwargs)

    def db_type(self, connection) -> str:
        if connection.vendor != "postgresql":
            raise NotSupportedError("UUIDv7Field requires PostgreSQL.")
        return "uuid_v7"

    def to_python(self, value):
        if value is None:
            return None
        return _parse_for_django(value)

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        return self.to_python(value)
```

`Field.rel_db_type()` already delegates to `db_type()`, so foreign keys targeting this field also use `uuid_v7`; do not duplicate that method.

- [ ] **Step 4: Add a temporary-model PostgreSQL integration test**

Append a transactional, isolated-app test. It must create and remove its tables explicitly and delete the child table first:

```python
from django.db import IntegrityError, connection, transaction


@pytest.mark.django_db(transaction=True)
@isolate_apps("games")
def test_uuidv7_field_round_trips_defaults_constraints_indexes_and_foreign_keys():
    class Probe(models.Model):
        id = UUIDv7Field(primary_key=True)
        label = models.CharField(max_length=32)
        optional = UUIDv7Field(null=True, default=None, db_default=None)

        class Meta:
            app_label = "games"
            db_table = "test_uuidv7_probe"

    class Child(models.Model):
        probe = models.ForeignKey(Probe, on_delete=models.CASCADE)

        class Meta:
            app_label = "games"
            db_table = "test_uuidv7_child"

    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(Probe)
        schema_editor.create_model(Child)

    try:
        python_created = Probe.objects.create(label="python")
        assert isinstance(python_created.pk, uuid.UUID)
        assert python_created.pk.version == 7
        assert python_created.optional is None

        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO "test_uuidv7_probe" ("label") VALUES (%s) RETURNING "id"',
                ["database"],
            )
            raw_id = uuid.UUID(str(cursor.fetchone()[0]))

        database_created = Probe.objects.get(pk=raw_id)
        assert isinstance(database_created.pk, uuid.UUID)
        assert database_created.pk.version == 7
        assert Child._meta.get_field("probe").db_type(connection) == "uuid_v7"
        assert Child.objects.create(probe=database_created).probe_id == raw_id

        ordered = list(Probe.objects.order_by("id").values_list("id", flat=True))
        assert ordered == sorted(ordered)

        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor, Probe._meta.db_table
            )
        assert any(item["primary_key"] for item in constraints.values())

        with pytest.raises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO "test_uuidv7_probe" ("id", "label") VALUES (%s, %s)',
                    [uuid.uuid4(), "invalid"],
                )
    finally:
        with connection.schema_editor() as schema_editor:
            schema_editor.delete_model(Child)
            schema_editor.delete_model(Probe)
```

- [ ] **Step 5: Add explicit model-validation and read-normalization cases**

Append these focused tests:

```python
@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("not-a-uuid", "invalid_uuid"),
        (uuid.uuid4(), "invalid_uuid_version"),
    ],
)
@isolate_apps("games")
def test_uuidv7_field_full_clean_uses_shared_validation_codes(value, code):
    class Probe(models.Model):
        id = UUIDv7Field(primary_key=True)

        class Meta:
            app_label = "games"

    with pytest.raises(ValidationError) as caught:
        Probe(id=value).full_clean()

    assert caught.value.error_dict["id"][0].code == code


@pytest.mark.django_db
def test_uuidv7_field_normalizes_a_driver_string():
    value = uuid.uuid7()
    normalized = UUIDv7Field().from_db_value(str(value), None, connection)
    assert normalized == value
    assert isinstance(normalized, uuid.UUID)
```

- [ ] **Step 6: Run the field and database integration tests**

Run through managed hidden processes on Windows:

```text
make test-fast ARGS="tests/test_uuidv7.py tests/test_uuidv7_domain.py -x -v"
make check-migrations
```

Expected: PASS; temporary tables are removed, raw omission invokes `uuidv7()`, wrong versions hit the domain, and no model migration is generated.

- [ ] **Step 7: Commit the reusable field**

```text
git add timetracker/uuidv7.py tests/test_uuidv7.py
git commit -m "feat: add reusable UUIDv7 model field"
```

---

### Task 4: Observe and warn about application/database clock skew

**Files:**
- Modify: `timetracker/postgres_contract.py`
- Modify: `timetracker/database.py`
- Modify: `tests/test_postgres_contract.py`
- Create: `tests/test_database_clock.py`
- Test: `tests/test_database_configuration.py`
- Test: `tests/test_health.py`

**Interfaces:**
- Consumes: the existing `PostgresContract`, `PostgresContractViolation`, and default `connection_created` receiver.
- Produces: `PostgresConnectionObservation(contract: PostgresContract, database_time_ms: int)`; `observe_valid_postgres_connection(connection) -> PostgresConnectionObservation`; `ClockSkewMeasurement`; `measure_clock_skew(database_time_ms: float, started_wall_ms: float, finished_wall_ms: float, round_trip_ms: float) -> ClockSkewMeasurement`; `ClockSkewWarningState.observe(is_skewed: bool) -> bool`.

- [ ] **Step 1: Write failing one-query observation tests**

Extend `tests/test_postgres_contract.py`:

```python
from timetracker.postgres_contract import (
    CONNECTION_OBSERVATION_QUERY,
    PostgresConnectionObservation,
    observe_valid_postgres_connection,
)


def test_observe_valid_postgres_connection_returns_contract_and_clock():
    version = 180004
    connection = RecordingConnection(
        (version, "UTF8", "b", "C.UTF-8", 1_786_647_600_123), []
    )

    assert observe_valid_postgres_connection(connection) == (
        PostgresConnectionObservation(
            contract=PostgresContract(version, "UTF8", "b", "C.UTF-8"),
            database_time_ms=1_786_647_600_123,
        )
    )
    assert connection.queries == [CONNECTION_OBSERVATION_QUERY]


def test_observe_valid_postgres_connection_rejects_a_non_integer_clock():
    connection = RecordingConnection((180004, "UTF8", "b", "C.UTF-8", "bad"), [])
    with pytest.raises(ValueError, match="database clock"):
        observe_valid_postgres_connection(connection)
```

- [ ] **Step 2: Run the observation tests to verify they fail**

Run through a managed hidden process on Windows:

```text
make test-fast ARGS="tests/test_postgres_contract.py -x -v"
```

Expected: collection FAIL because the observation API is absent.

- [ ] **Step 3: Add the combined contract-and-clock query without changing the static API**

In `timetracker/postgres_contract.py`, keep `CATALOG_QUERY` and `validate_postgres_collation_contract()` unchanged for `scripts/ensure_postgres.py`. Add:

```python
@dataclass(frozen=True)
class PostgresConnectionObservation:
    contract: PostgresContract
    database_time_ms: int


CONNECTION_OBSERVATION_QUERY = """
SELECT
    current_setting('server_version_num')::integer,
    pg_encoding_to_char(database.encoding),
    database.datlocprovider,
    database.datlocale,
    floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint
FROM pg_database AS database
WHERE database.datname = current_database()
""".strip()


def observe_valid_postgres_connection(
    connection: PostgresConnection,
) -> PostgresConnectionObservation:
    cursor = connection.cursor()
    cursor.execute(CONNECTION_OBSERVATION_QUERY)
    row = cursor.fetchone()
    if not isinstance(row, tuple) or len(row) != 5:
        raise PostgresContractViolation(
            "PostgreSQL connection observation returned an invalid row."
        )
    contract = _contract_from_values(row[:4])
    _validate_contract(contract)
    database_time_ms = row[4]
    if not isinstance(database_time_ms, int):
        raise PostgresContractViolation(
            "PostgreSQL connection observation returned an invalid database clock."
        )
    return PostgresConnectionObservation(contract, database_time_ms)
```

Refactor the current parsing and validation into these shared helpers before
adding the observation function:

```python
def _contract_from_values(values: Sequence[object]) -> PostgresContract:
    if len(values) != 4:
        raise PostgresContractViolation(
            "PostgreSQL collation contract query returned an invalid row."
        )
    server_version_num, encoding, locale_provider, locale = values
    if not isinstance(server_version_num, int):
        raise PostgresContractViolation(
            "PostgreSQL collation contract returned a non-integer server version."
        )
    if (
        not isinstance(encoding, str)
        or not isinstance(locale_provider, str)
        or not isinstance(locale, str)
    ):
        raise PostgresContractViolation(
            "PostgreSQL collation contract returned non-text database metadata."
        )
    return PostgresContract(server_version_num, encoding, locale_provider, locale)


def _validate_contract(contract: PostgresContract) -> None:
    actual_major = contract.server_version_num // 10_000
    if actual_major != REQUIRED_POSTGRES_MAJOR:
        raise PostgresContractViolation(
            "PostgreSQL collation contract requires major version 18, "
            f"got {actual_major} "
            f"(server_version_num={contract.server_version_num})."
        )
    if contract.encoding != REQUIRED_ENCODING:
        raise PostgresContractViolation(
            f"PostgreSQL collation contract requires encoding {REQUIRED_ENCODING}, "
            f"got {contract.encoding}."
        )
    if contract.locale_provider != REQUIRED_LOCALE_PROVIDER:
        provider = _PROVIDER_LABELS.get(
            contract.locale_provider, repr(contract.locale_provider)
        )
        raise PostgresContractViolation(
            f"PostgreSQL collation contract requires provider builtin, got {provider}."
        )
    if contract.locale != REQUIRED_BUILTIN_LOCALE:
        raise PostgresContractViolation(
            "PostgreSQL collation contract requires builtin locale "
            f"{REQUIRED_BUILTIN_LOCALE}, got {contract.locale}."
        )


def _read_contract(cursor: PostgresCursor) -> PostgresContract:
    cursor.execute(CATALOG_QUERY)
    row = cursor.fetchone()
    if not isinstance(row, tuple):
        raise PostgresContractViolation(
            "PostgreSQL collation contract query returned an invalid row."
        )
    return _contract_from_values(row)


def validate_postgres_collation_contract(
    connection: PostgresConnection,
) -> PostgresContract:
    contract = _read_contract(connection.cursor())
    _validate_contract(contract)
    return contract
```

Import `Sequence` beside `Protocol` from `typing`.

`validate_postgres_collation_contract()` must continue returning
`PostgresContract` and executing only `CATALOG_QUERY`; this avoids changing the
provisioning script's four-column interface.

- [ ] **Step 4: Write failing pure clock-measurement and episode-state tests**

Create `tests/test_database_clock.py`:

```python
from timetracker.database import (
    CLOCK_SKEW_TOLERANCE_MS,
    ClockSkewWarningState,
    measure_clock_skew,
)


def test_clock_measurement_accepts_database_time_inside_latency_interval():
    measured = measure_clock_skew(
        database_time_ms=1_500,
        started_wall_ms=1_000,
        finished_wall_ms=2_000,
        round_trip_ms=1_000,
    )
    assert measured.outside_tolerance is False
    assert measured.estimated_skew_ms == 0


def test_clock_measurement_detects_positive_and_negative_skew():
    positive = measure_clock_skew(3_001, 1_000, 2_000, 25)
    negative = measure_clock_skew(-1, 1_000, 2_000, 25)
    assert positive.outside_tolerance is True
    assert positive.estimated_skew_ms > CLOCK_SKEW_TOLERANCE_MS
    assert negative.outside_tolerance is True
    assert negative.estimated_skew_ms < -CLOCK_SKEW_TOLERANCE_MS


def test_clock_warning_state_warns_once_then_rearms_after_recovery():
    state = ClockSkewWarningState()
    assert state.observe(True) is True
    assert state.observe(True) is False
    assert state.observe(False) is False
    assert state.observe(True) is True
```

- [ ] **Step 5: Implement interval measurement and thread-safe episode state**

Add to `timetracker/database.py`:

```python
import logging
import time
from dataclasses import dataclass
from threading import Lock

CLOCK_SKEW_TOLERANCE_MS = 1_000
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClockSkewMeasurement:
    estimated_skew_ms: float
    round_trip_ms: float
    outside_tolerance: bool


def measure_clock_skew(
    database_time_ms: float,
    started_wall_ms: float,
    finished_wall_ms: float,
    round_trip_ms: float,
) -> ClockSkewMeasurement:
    lower = min(started_wall_ms, finished_wall_ms) - CLOCK_SKEW_TOLERANCE_MS
    upper = max(started_wall_ms, finished_wall_ms) + CLOCK_SKEW_TOLERANCE_MS
    midpoint = (started_wall_ms + finished_wall_ms) / 2
    return ClockSkewMeasurement(
        estimated_skew_ms=database_time_ms - midpoint,
        round_trip_ms=round_trip_ms,
        outside_tolerance=not lower <= database_time_ms <= upper,
    )


class ClockSkewWarningState:
    def __init__(self) -> None:
        self._active = False
        self._lock = Lock()

    def observe(self, is_skewed: bool) -> bool:
        with self._lock:
            if not is_skewed:
                self._active = False
                return False
            if self._active:
                return False
            self._active = True
            return True


_clock_skew_warnings = ClockSkewWarningState()
```

- [ ] **Step 6: Write the failing connection-hook warning test**

Add to `tests/test_database_clock.py`:

```python
from unittest.mock import Mock

from timetracker import database
from timetracker.database import validate_default_connection
from timetracker.postgres_contract import (
    PostgresConnectionObservation,
    PostgresContract,
)


class DefaultConnection:
    alias = "default"


def test_default_connection_warns_for_skew_without_rejecting_it(monkeypatch):
    observation = PostgresConnectionObservation(
        PostgresContract(180004, "UTF8", "b", "C.UTF-8"),
        3_001,
    )
    warning = Mock()
    wall_samples_ns = iter([1_000_000_000, 2_000_000_000])
    monotonic_samples_ns = iter([10_000_000_000, 10_025_000_000])

    monkeypatch.setattr(
        database, "observe_valid_postgres_connection", lambda connection: observation
    )
    monkeypatch.setattr(database.time, "time_ns", lambda: next(wall_samples_ns))
    monkeypatch.setattr(
        database.time, "monotonic_ns", lambda: next(monotonic_samples_ns)
    )
    monkeypatch.setattr(database.logger, "warning", warning)
    monkeypatch.setattr(database, "_clock_skew_warnings", ClockSkewWarningState())

    assert (
        validate_default_connection(sender=None, connection=DefaultConnection()) is None
    )
    warning.assert_called_once()
    assert "estimated_skew_ms" in warning.call_args.args[0]
```

The pure `ClockSkewWarningState` test in Step 4 covers duplicate suppression,
recovery, and rearming without coupling four observations to clock mocks.

- [ ] **Step 7: Wire the combined observation into the existing receiver**

In `validate_default_connection()`:

```python
started_wall_ms = time.time_ns() / 1_000_000
started_monotonic_ns = time.monotonic_ns()
try:
    observation = observe_valid_postgres_connection(connection)
except PostgresContractViolation as exc:
    raise ImproperlyConfigured(
        f"PostgreSQL database contract violation: {exc}"
    ) from exc
finished_wall_ms = time.time_ns() / 1_000_000
round_trip_ms = (time.monotonic_ns() - started_monotonic_ns) / 1_000_000

measurement = measure_clock_skew(
    observation.database_time_ms,
    started_wall_ms,
    finished_wall_ms,
    round_trip_ms,
)
if _clock_skew_warnings.observe(measurement.outside_tolerance):
    logger.warning(
        "PostgreSQL clock skew exceeds tolerance: "
        "estimated_skew_ms=%+.1f round_trip_ms=%.1f tolerance_ms=%d",
        measurement.estimated_skew_ms,
        measurement.round_trip_ms,
        CLOCK_SKEW_TOLERANCE_MS,
    )
```

Keep the non-default alias early return. Do not touch `common/middleware.py`: `/health` remains database-free, and `/health/ready` continues returning 200 whenever `SELECT 1` succeeds.

Update both monkeypatch targets in `tests/test_database_configuration.py` from
`timetracker.database.validate_postgres_collation_contract` to
`timetracker.database.observe_valid_postgres_connection`. The contract-violation
test continues raising `PostgresContractViolation("wrong")`, and the non-default
test continues failing if the observation function is unexpectedly called.

- [ ] **Step 8: Run contract, clock, connection, and health tests**

Run through a managed hidden process on Windows:

```text
make test-fast ARGS="tests/test_postgres_contract.py tests/test_database_clock.py tests/test_database_configuration.py tests/test_health.py -x -v"
```

Expected: PASS. Contract violations still raise, time skew only warns, repeated skew is suppressed until recovery, `/health` stays database-free, and `/health/ready` remains an availability probe.

- [ ] **Step 9: Commit clock observation separately**

```text
git add timetracker/postgres_contract.py timetracker/database.py tests/test_postgres_contract.py tests/test_database_clock.py tests/test_database_configuration.py tests/test_health.py
git commit -m "feat: warn about PostgreSQL clock skew"
```

If `tests/test_database_configuration.py` and `tests/test_health.py` require no edits, omit them from `git add`; never create noise-only changes.

---

### Task 5: Document the convention and run complete acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/deployment.md`
- Test: all files created or modified in Tasks 1-4

**Interfaces:**
- Consumes: the implemented `uuid_v7`, `UUIDv7Field`, `<uuidv7:identifier>`, and clock-warning behavior.
- Produces: developer and operator guidance; no new runtime interface.

- [ ] **Step 1: Add the developer identity convention**

Add a concise `## Identifier convention` subsection under `# Development` in `README.md`:

```markdown
## Identifier convention

New Timetracker domain/catalog identities use `timetracker.uuidv7.UUIDv7Field`.
It assigns Python's `uuid.uuid7()` before save and maps to PostgreSQL's
`uuid_v7` domain, whose column fallback is `uuidv7()`. Use the `<uuidv7:identifier>`
route converter for untrusted URL identifiers. Django-owned framework tables
retain their existing key types.

UUID order is approximately chronological. The embedded time is diagnostic
metadata and never replaces an explicit creation time, business date, or event
sequence.
```

- [ ] **Step 2: Document domain tooling and clock operations**

Append `## UUIDv7 storage and clocks` to `docs/deployment.md`:

```markdown
## UUIDv7 storage and clocks

Timetracker identity columns use the PostgreSQL `uuid_v7` domain over the
built-in `uuid` type. Native PostgreSQL backup and restore tools preserve the
domain and its dependencies. A generic schema or analytics client that reports
the column as `USER-DEFINED` can expose it as built-in UUID with
`identifier::uuid`; Timetracker does not customize Django `inspectdb` mappings.

Python-created identifiers use the application host clock and database-default
identifiers use the PostgreSQL host clock. On each new physical application
connection, Timetracker warns when database time falls more than one second
outside the latency-adjusted application interval. The warning does not change
`/health` or `/health/ready`; keep both hosts synchronized through normal NTP
and infrastructure monitoring.
```

- [ ] **Step 3: Run focused acceptance and inspect generated migration state**

Run through managed hidden processes on Windows:

```text
make test-fast ARGS="tests/test_uuidv7.py tests/test_uuidv7_domain.py tests/test_postgres_contract.py tests/test_database_clock.py tests/test_database_configuration.py tests/test_health.py -x -v"
make check-migrations
```

Expected: PASS and no migration drift beyond the committed domain migration.

- [ ] **Step 4: Run static gates and confirm scope boundaries**

Run:

```text
make lint
make format-check
make typecheck
git diff HEAD~4 -- games/models.py games/migrations timetracker common tests README.md docs/deployment.md
```

Expected: static gates PASS. Inspection shows one new schema domain but no existing model-field, relationship, row, application URL pattern, API payload, or Django system-table conversion.

- [ ] **Step 5: Run the full repository gate**

Run `make check` through a managed hidden process on Windows and wait for its final log and exit status.

Expected: lint, formatting, mypy, TypeScript, generated assets, migration drift, Vitest, PostgreSQL pytest, and E2E all pass with the Makefile's default worker count.

- [ ] **Step 6: Commit documentation**

```text
git add README.md docs/deployment.md
git commit -m "docs: explain UUIDv7 storage and clocks"
```

- [ ] **Step 7: Review the final atomic history**

Run:

```text
git log --oneline --decorate -8
git status --short
```

Expected: cleanup commits precede and remain separate from `add UUIDv7 database domain`, `validate UUIDv7 inputs and routes`, `add reusable UUIDv7 model field`, `warn about PostgreSQL clock skew`, and the documentation commit. The only unrelated status entry may be the pre-existing untracked `.pnpm-store/`, which remains unstaged.
