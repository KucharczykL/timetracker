# ID-02: Convert catalog identities to UUIDv7 — implementation plan

Design: [Catalog UUID identity design](../specs/2026-08-17-issue-640-catalog-uuid-identity-design.md).

**Goal:** add a populated, unique, creation-ordered UUIDv7 column to `Game`
and `Platform` without changing any application behavior.

**Constraints:** drive everything through Make targets (`make makemigrations`,
`make test`/`make test-fast`, `make check-migrations` if present, `make
check`); do not invoke `uv`, `pnpm`, or `manage.py` directly. Do not edit
`games/urls.py`, `games/api.py`, `games/forms.py`, `games/filters.py`,
`common/criteria.py`, `games/fixtures/sample.yaml.gz`, or any TypeScript.

## Task 1 — `uuid7_at` encoder

Files: `timetracker/uuidv7.py`, `tests/test_uuidv7.py`.

1. Write failing tests first: millisecond encoding, version-7 and RFC 4122
   variant bits, distinctness for repeated calls at the same instant,
   `sequence` ordering within one millisecond, rejection of a naive
   (tz-unaware) `datetime`, and a byte-layout pin.
2. Implement `uuid7_at(moment: datetime, *, sequence: int | None = None) ->
   uuid.UUID` beside `parse_uuidv7` in `timetracker/uuidv7.py`. Add a `type
   UnixMilliseconds = int` alias for the internal timestamp role (CLAUDE.md
   primitive-role convention).
3. `make test ARGS="tests/test_uuidv7.py -x"`.

## Task 2 — model fields

Files: `games/models.py`.

1. Add `uuid = UUIDv7Field(unique=True, editable=False)` to `Game` (after
   `library`, before `name`) and to `Platform` (same relative position).
2. `make makemigrations` to generate `games/migrations/0005_catalog_uuid_identity.py`.

## Task 3 — split the migration and write the backfill

Files: `games/migrations/0005_catalog_uuid_identity.py`.

1. Replace the generated single `AddField` per model with the five-operation
   sequence: nullable `AddField` ×2, `RunPython`, final `AlterField` ×2 (see
   design doc "Migration and reconciliation mechanics").
2. Implement `backfill_catalog_uuids(apps, schema_editor)`: for each of
   `Game` and `Platform`, iterate `.order_by("created_at",
   "pk").only("pk", "created_at")`, track `previous_ms` and a per-millisecond
   `sequence`, assign `uuid7_at(...)`, and `bulk_update(...,
   ["uuid"], batch_size=1000)`.
3. Implement `reconcile_catalog_identity(apps)` with a `require_match`-style
   helper raising `RuntimeError` (pattern from `require_match`, defined at
   `0004_user_library_ownership_cutover.py:267`),
   covering the six checks in the design doc, and print the
   `CAT identity backfilled ...` evidence line.
4. Confirm the migration reproduces current model state exactly (no drift
   between `games/models.py` and the migration graph).

## Task 4 — tests

Files: `tests/test_catalog_identity.py` (new).

1. Field-contract tests: ORM insert, raw-SQL insert, duplicate `uuid`
   rejection (`IntegrityError`), non-v7 UUID rejection (domain
   `CheckViolation`).
2. Invisibility tests: `uuid` absent from `Game`/`Platform` `ModelForm` field
   sets and from the generated Ninja OpenAPI schema.
3. `MigrationExecutor` forward test `0004 → 0005` (pattern from
   `tests/test_library_cutover_migration.py`): fixtures with several
   `created_at` values sharing one millisecond and one row out of
   primary-key order; assert full population, distinctness, version 7,
   `uuid_extract_timestamp` equal to `created_at` truncated to milliseconds,
   and `order_by("uuid")` reproducing `order_by("created_at", "pk")`.
4. `MigrationExecutor` reverse test `0005 → 0004`: both columns dropped,
   every other column value intact.
5. `make test ARGS="tests/test_catalog_identity.py tests/test_uuidv7.py -x"`.

## Task 5 — regression sweep

Run the surfaces most likely to catch a boundary escape, expecting zero
changes needed:

```
make test ARGS="tests/test_api.py tests/test_filters.py tests/test_filter_execution.py tests/test_filter_presets.py tests/test_paths_return_200.py tests/test_rendered_pages.py tests/test_components.py tests/test_library_api_isolation.py tests/test_library_commands.py"
```

A failure here is a boundary violation (the new column leaked into a form,
schema, filter, or template), not a test to update.

## Task 6 — gate

1. `make check` to completion.
2. Capture the printed `CAT identity backfilled ...` reconciliation line from
   the migration run as the issue's migration evidence.

## Test list (for quick reference)

- `tests/test_uuidv7.py`: `uuid7_at` millisecond/version/variant/sequence
  encoding, byte-layout pin.
- `tests/test_catalog_identity.py`: field contract (ORM + raw SQL insert,
  duplicate/version rejection), form/schema invisibility, forward migration
  backfill + reconciliation, reverse migration.
- Untouched regression surface listed in Task 5.

## Gotchas

- `uuid7_at` is imported into a migration from application code — a
  deliberate, documented exception (see design doc). Don't let a future lint
  pass "fix" this into an inlined copy without checking the design doc first.
- The reconciliation check must run *before* the final `AlterField` installs
  the unique constraint, so a bad backfill fails with a readable count
  instead of an opaque `IntegrityError` on index creation.
- `games/sorting.py:189`'s `F("pk").asc()` tiebreak is why ordering must be
  preserved now — this is not defensive-programming; a real future issue
  (#646) depends on it.
- Don't regenerate `games/fixtures/sample.yaml.gz`. It's out of scope and the
  new column doesn't need to appear there yet.
