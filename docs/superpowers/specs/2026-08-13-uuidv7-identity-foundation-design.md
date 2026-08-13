# UUIDv7 identity foundation

Date: 2026-08-13

Related issue: https://github.com/KucharczykL/timetracker/issues/639

## Outcome

Introduce the PostgreSQL and Django foundation for UUIDv7 identifiers without
converting any existing model. Timetracker gains one database-level UUIDv7
type, one reusable Django field, shared parsing and validation, a URL converter,
and a warning when the application and database clocks are too far apart. The
same delivery removes the active SQLite compatibility and test paths that
survived the completed PostgreSQL cutover.

The later identity-migration issues use this foundation to convert individual
primary keys, foreign keys, many-to-many tables, and URLs. Keeping those data
and routing migrations out of this issue makes the foundation independently
reviewable and gives every later issue one settled convention to adopt.

## Scope and identity policy

Timetracker domain and catalog records will use a single UUIDv7 identifier. The
design does not add a second public UUIDv4, an encoded UUIDv7 facade, or separate
private and public generators. If a future hosted deployment demonstrates a
real need for opaque public identifiers, that concern can be added deliberately
without making every record carry two identities today.

Django-owned system tables, including authentication and framework metadata,
keep their current integer keys. Issue #639 changes no existing model field,
database row, relationship, URL, or API response.

UUIDv7's embedded timestamp is diagnostic metadata. It does not replace
`created_at`, business dates, recorded event times, or explicit event sequence
fields. Sorting UUIDv7 values gives useful approximate creation order, but it is
not a guarantee of business order or strict global ordering.

## Chosen architecture

PostgreSQL owns the invariant through a reusable `uuid_v7` domain over its
built-in `uuid` type. Django exposes that type through `UUIDv7Field`. Normal ORM
construction uses Python's `uuid.uuid7()` so an instance has a real primary key
before it is saved. Each column also has PostgreSQL's `uuidv7()` as its database
default, covering direct SQL and inserts that omit the identifier.

This hybrid avoids the behavioral problems of a database-only default. Two
unsaved model instances have distinct keys, compare normally, can be hashed,
and can be referenced in logs or application state before either is saved. The
database default remains a fallback rather than the normal ORM generation path.

The rejected alternatives are:

- ordinary `uuid` columns with a repeated per-column check, which preserve the
  broadest introspection compatibility but duplicate the same identity rule;
- a plain `UUIDField` with conventions enforced only in Python, which does not
  protect direct SQL or future non-Django writers; and
- dual private/public IDs or a reversible UUIDv7 facade, which add storage,
  key-management, lookup, and migration complexity without a current consumer.

## PostgreSQL domain and migration

A foundational `games` migration creates the domain before any model migration
can refer to it:

```sql
CREATE DOMAIN uuid_v7 AS uuid
CHECK (
    VALUE IS NULL
    OR uuid_extract_version(VALUE) IS NOT DISTINCT FROM 7
);
```

The domain is deliberately nullable. Whether a value is required is a property
of each column, not the reusable type. The explicit `VALUE IS NULL` branch
preserves that nullable-domain policy. The `IS NOT DISTINCT FROM` comparison is
essential: `uuid_extract_version()` returns `NULL` for a UUID outside the RFC
9562 variant, and an ordinary `= 7` expression would therefore evaluate to
`NULL` and incorrectly pass a check constraint.

The domain contains no default. Generation is also a column-level policy, which
lets a future exceptional column use the constrained type without generating a
value automatically. `UUIDv7Field` supplies the defaults for ordinary identity
columns.

Django has no native domain migration operation, so creation uses a top-level,
reversible `RunSQL` operation. Its reverse SQL is:

```sql
DROP DOMAIN uuid_v7;
```

The reverse must not use `CASCADE`. If a dependent column still exists, reversal
should stop and identify the migration-order defect rather than silently remove
schema objects. Later model-conversion migrations depend on the domain migration
and must reverse their columns before the domain is dropped.

The migration does not use `IF NOT EXISTS`. An unexpected object with the same
name is a schema conflict that should fail visibly. The existing PostgreSQL 18
runtime contract guarantees that `uuidv7()` and `uuid_extract_version()` exist.

`tests/test_migration_portability.py` currently rejects every top-level
`RunSQL`. That check was introduced as a temporary static substitute before the
project had permanent PostgreSQL-backed migration verification. Delete the
obsolete portability module rather than weakening it one assertion at a time.
The permanent PostgreSQL test-database build already executes the complete
migration graph and therefore detects unsupported generated-column expressions
and SQL. The domain migration receives focused PostgreSQL forward, reverse, and
fresh-schema coverage.

## PostgreSQL-only cleanup

PostgreSQL 18 is Timetracker's sole runtime and test database. Active SQLite
compatibility is therefore removed as part of this delivery rather than carried
beside the new PostgreSQL-specific identifier type.

The cleanup includes:

- remove `DatabaseDateDifference.as_sqlite()` and SQLite-oriented descriptions
  from the expression layer while retaining the expression classes imported by
  the squashed migration;
- delete the SQLite branch in the xdist database-name fixture and express its
  assumptions positively in terms of the required PostgreSQL backend;
- remove the live-server SQLite locking regression module, the SQLite teardown
  regression, and the request-quiescence fixture introduced specifically to
  work around SQLite flush locking;
- delete the migration-portability test described above;
- replace stale SQLite explanations in active model, criteria, filter, E2E,
  database-configuration, and PostgreSQL-verification tests with current
  PostgreSQL behavior or remove them when the test itself has no surviving
  purpose; and
- remove or correct deployment comments whose SQLite rationale no longer
  matches the PostgreSQL deployment, without changing machine count or another
  operational policy merely as a side effect of comment cleanup.

The cleanup does not rewrite the changelog or completed design and migration
documents. Those references record project history; they are not executable
support. Incidental uses of Python's `strftime()` are also unrelated to a
database backend and remain.

SQLite removal and UUIDv7 behavior land in separate atomic commits. A sensible
implementation sequence is:

1. remove SQLite runtime expression compatibility and stale active-source
   assumptions;
2. remove SQLite-only test topology, locking regressions, and the obsolete
   migration portability audit; and
3. add the UUIDv7 domain, Django utilities, clock warning, documentation, and
   their focused tests in one or more independently passing feature commits.

If cleanup exposes a still-current behavior rather than a SQLite workaround,
that behavior is rewritten and tested in PostgreSQL terms instead of being
deleted blindly. Every cleanup commit must pass its relevant tests before the
UUIDv7 commits begin, so regressions and feature failures cannot hide each
other.

## Django field

`UUIDv7Field` is a small reusable subclass of `models.UUIDField`, kept with the
other project-wide identifier utilities rather than in a particular domain
model. Its contract is:

- PostgreSQL storage type is `uuid_v7`, including relational columns derived
  from a referenced UUIDv7 primary key.
- The Python default is `uuid.uuid7`, evaluated for every new model instance.
- The database default is a migration-serializable zero-argument `uuidv7()`
  expression.
- Callers may explicitly override either default when a migration or exceptional
  model needs different behavior.
- The version validator is part of the model field's validators, so Django
  forms and explicit `full_clean()` calls enforce it.
- Values read from the database are normalized to `uuid.UUID`, even if a
  database driver reports the user-defined domain differently from built-in
  `uuid`.
- Migration deconstruction preserves the custom field and its effective
  defaults; generated migrations do not flatten it to a generic `UUIDField`.
- Use against a non-PostgreSQL backend fails clearly. Supporting another
  database is not part of Timetracker's runtime contract.

Django does not call `full_clean()` from `save()`, so the field validator is a
developer-facing convenience rather than the final integrity boundary. The
domain rejects every non-v7 value regardless of the write path.

## Parsing, validation, and URLs

One parser supplies the common version rule. `parse_uuidv7(value)` accepts a
string or an existing `uuid.UUID`, returns a normalized `uuid.UUID`, and
distinguishes malformed UUID syntax from a syntactically valid UUID of another
version. It requires the RFC 9562 variant as well as version 7 so application
validation matches PostgreSQL's `uuid_extract_version()` semantics.

`validate_uuidv7(value)` adapts that behavior to Django's validator contract.
It raises `ValidationError` with stable codes for malformed input and the wrong
version. Those codes, rather than incidental exception text, are the supported
surface for forms and tests.

A `UUIDv7Converter` is registered under the route converter name `uuidv7`.
Future URL migrations use it as follows:

```python
path("projects/<uuidv7:project_id>/", views.project_detail)
```

The converter follows Django's built-in UUID URL convention: canonical,
lowercase, hyphenated text. `to_python()` returns a `uuid.UUID`; malformed or
non-v7 input raises `ValueError`, so URL resolution returns 404 without running
a view or issuing a model lookup. `to_url()` applies the same version check so
the application cannot accidentally generate a URL containing another UUID
version.

General parsing may normalize UUID text accepted by Python, but public URLs have
one canonical representation. The foundation does not add serializers, custom
managers, base-model mixins, identifier aliases, or timestamp-extraction APIs.

## Write and read flows

For an ordinary Django-created record:

1. Model construction evaluates `uuid.uuid7()`.
2. The model has its final identifier while still unsaved.
3. Django includes that value in the `INSERT`.
4. PostgreSQL coerces it to `uuid_v7` and checks its version.

For a direct database insert that omits the identifier, the column's
`DEFAULT uuidv7()` supplies it and the domain checks the result. An explicitly
provided UUIDv1, UUIDv4, nil UUID, or max UUID fails the domain check.

For reads, Django callers always receive `uuid.UUID`. Lookups accept ordinary
UUID parameters; PostgreSQL's domain-to-base coercion supplies the normal UUID
comparison and indexing behavior. Integration tests, rather than an assumption
about Psycopg's treatment of domain OIDs, prove round trips, lookups, ordering,
indexes, and foreign keys.

Python and PostgreSQL generation are intentionally independent. Both encode Unix
time in milliseconds according to UUIDv7, but they need not use the same random
bits or monotonicity strategy within a millisecond. The application guarantees
valid UUIDv7 values and useful approximate temporal locality, not one merged,
strictly increasing sequence across generators.

## Clock alignment warning

Python-generated IDs use the application host's clock; database-generated IDs
use the PostgreSQL host's clock. A large disagreement would make their combined
ordering misleading, so the existing default-connection validation performs a
lightweight runtime sanity check.

The PostgreSQL catalog query already executed for every new physical default
connection will also return `clock_timestamp()` as Unix milliseconds. The
application records its own wall-clock time immediately before and after the
query. PostgreSQL time is considered in tolerance when it falls inside that
local interval extended by one second at each end. This interval comparison
accounts for query and network latency instead of pretending a single local
sample is exact.

Out-of-tolerance time logs a warning containing the signed midpoint estimate,
round-trip duration, and threshold. It does not raise
`ImproperlyConfigured`, reject the connection, or alter an HTTP health result.
Warnings are emitted once per skew episode in each process and are enabled
again after a later connection observes recovery, preventing log floods when
connections are short lived.

No separate time-health endpoint is added:

- `/health` remains database-free liveness and does not run the check.
- `/health/ready` remains a database-availability probe. Opening its connection
  may run the check, but time skew alone still returns 200.

This warning is an early operational signal, not continuous monitoring and not
a replacement for NTP or infrastructure clock alerts.

## Introspection and external tools

The domain is a real PostgreSQL user-defined type with its own type OID. Normal
Django ORM operation does not reverse-engineer that OID: the custom model field
already states the storage type and normalization behavior. Native PostgreSQL
tools, including `psql`, `pg_dump`, and `pg_restore`, understand domains and
their dependencies.

Django's stock PostgreSQL `inspectdb` mapping recognizes built-in `uuid`, not
the project's domain OID. Generic schema generators, BI clients, and ETL tools
may likewise report `uuid_v7` as `USER-DEFINED` rather than as UUID. Customizing
Django's database backend or individual external products is outside this
issue. Document that a client which cannot follow the domain's base type can
select or expose the value as `column::uuid`.

This is accepted because Timetracker does not use `inspectdb` or such generic
integration tooling today. The centralized database invariant is worth the
small mapping cost. PostgreSQL catalog tests will nevertheless verify that
`uuid_v7` has built-in `uuid` as its base type, and Django/Psycopg integration
tests will prove the application's actual path.

## Error behavior

Failures are deliberately reported at the closest useful boundary:

- malformed or wrong-version URL input does not resolve and becomes 404;
- form and explicit model validation raise `ValidationError` with a stable
  code;
- a write bypassing application validation fails with PostgreSQL's domain check
  violation, surfaced by Django as a database integrity error;
- an unsupported PostgreSQL version or incompatible schema fails through the
  existing database contract or migration rather than degrading silently; and
- clock skew produces an operational warning only.

The application does not catch a domain violation and translate it into a
public validation response globally. Normal untrusted request paths should use
the parser, converter, or form validation; the constraint remains the backstop
for programming errors and external writers.

## Verification

Focused unit tests cover:

- parsing UUIDv7 objects and strings;
- rejection of malformed, non-RFC-variant, v1, v4, nil, and max UUID values;
- stable Django validation codes;
- URL conversion in both directions and rejection before view execution;
- immediate, distinct IDs and normal equality/hash behavior for unsaved model
  instances using the field;
- field defaults, override behavior, and migration deconstruction; and
- synchronized clocks, positive and negative skew, latency contained by the
  measurement interval, warning suppression, and recovery.

PostgreSQL-backed tests cover:

- forward creation and reverse removal of the domain;
- the catalog base type and version constraint;
- a fresh migration from an empty database;
- ORM creation and retrieval as `uuid.UUID`;
- raw insertion using the database default;
- rejection of non-v7 and non-RFC-variant values and acceptance of `NULL` on
  nullable columns;
- UUID lookup, equality, ordering, indexing, and foreign-key behavior; and
- timestamp agreement between each generator and its own clock within a test
  tolerance, without asserting strict cross-generator order.

The normal migration-drift and full project checks remain required. A dedicated
automated `pg_dump`/`pg_restore` round trip is not added here: these are native
domain-aware PostgreSQL operations already owned by the project's backup and
restore verification. The new schema object is included in the next normal
backup/restore exercise.

## Documentation and acceptance

Developer documentation records the `UUIDv7Field` convention, the domain and
cast behavior seen by external tools, and the distinction between UUID time and
authoritative application timestamps. Later identity issues can then limit
their designs to model-specific data and URL migration concerns.

Issue #639 is complete when:

- the reversible `uuid_v7` domain migration works on a fresh PostgreSQL 18
  database;
- the reusable field exposes Python and database UUIDv7 defaults while giving
  unsaved models immediate identifiers;
- parsing, Django validation, and URL conversion consistently reject every
  other UUID version;
- direct database writes cannot bypass the version invariant;
- database values round-trip as `uuid.UUID` through the ORM;
- clock disagreement greater than the defined tolerance warns without changing
  liveness or readiness; and
- no existing model, relationship, row, URL, or Django-owned key is converted;
- no active SQLite database rendering, test topology, locking workaround, or
  portability audit remains; and
- SQLite cleanup and UUIDv7 behavior are separated into atomic, independently
  verified commits.
