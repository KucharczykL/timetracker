# ID-03: Convert Session and play-history identities to UUIDv7 — implementation plan

Design: [Session and play-history UUID identity design](../specs/2026-08-17-issue-641-session-playhistory-uuid-identity-design.md).
Shares mechanics with the [catalog identity plan](2026-08-17-issue-640-catalog-uuid-identity.md) — read that first if `#640` hasn't landed yet.

**Goal:** add a populated, unique, creation-ordered UUIDv7 column to
`Session`, `PlayEvent`, and `GameStatusChange` without changing any
application behavior.

**Constraints:** same as `#640`'s plan — drive everything through Make
targets; do not edit `games/urls.py`, `games/filters.py`,
`common/criteria.py`, `games/fixtures/sample.yaml.gz`, or TypeScript.

## Task 1 — `uuid7_at` encoder (skip if `#640` already merged)

If `#640` has already landed, `timetracker/uuidv7.py` already has
`uuid7_at`; skip to Task 2. Otherwise follow `#640`'s Task 1 exactly.

## Task 2 — model fields

Files: `games/models.py`.

1. Add `uuid = UUIDv7Field(unique=True, editable=False)` as the first field
   declared on `Session` (before `game`), `PlayEvent` (before `game`), and
   `GameStatusChange` (before `game`).
2. `make makemigrations` to generate the migration (name depends on merge
   order — expected `..._session_playhistory_uuid_identity.py`).

## Task 3 — split the migration and write the backfill

1. Split the generated single `AddField` ×3 into the five-operation
   sequence per model, as in `#640`.
2. Implement `backfill_playhistory_uuids(apps, schema_editor)`:
   - `Session`, `PlayEvent`: iterate `.order_by("created_at",
     "pk").only("pk", "created_at")`, same sequenced-assignment loop as
     `#640`.
   - `GameStatusChange`: iterate `.order_by("timestamp",
     "pk").only("pk", "timestamp")`. For rows with `timestamp is None`,
     call `uuid7_at(timezone.now())` (no `sequence`, since these are the
     tail of the ordering and don't need cross-row ordering guarantees
     against each other). For rows with a `timestamp`, use the same
     sequenced encoder as the other two models.
3. Implement `reconcile_playhistory_identity(apps)`: the same six checks as
   `#640` for `Session`/`PlayEvent`; for `GameStatusChange`, scope the
   timestamp-equality check to non-null rows and separately assert the
   null-timestamp row count matches what was observed going in (printed,
   not silently dropped).
4. Confirm no migration drift.

## Task 4 — tests

File: `tests/test_session_playhistory_identity.py` (new).

1. Field-contract tests for all three models.
2. Invisibility tests: `uuid` absent from `SessionForm`, `PlayEventForm`,
   `GameStatusChangeForm` Meta.fields, and from `AutoPlayEventIn`'s
   generated Ninja schema specifically (this is the one `ModelSchema` case
   in the whole identity-cutover sequence — don't skip it).
3. `MigrationExecutor` forward tests: `Session`/`PlayEvent` mirroring
   `#640`'s same-millisecond/out-of-order fixtures; `GameStatusChange` with
   a mixed populated/`NULL` `timestamp` fixture, asserting null rows sort
   after populated ones in `uuid` order.
4. Reverse migration test.
5. `make test ARGS="tests/test_session_playhistory_identity.py tests/test_uuidv7.py -x"`.

## Task 5 — regression sweep

```
make test ARGS="tests/test_api.py tests/test_filters.py tests/test_filter_execution.py tests/test_filter_presets.py tests/test_paths_return_200.py tests/test_rendered_pages.py tests/test_components.py tests/test_signals.py"
```

## Task 6 — gate

`make check`; capture the printed `SES identity backfilled ...` line as
migration evidence.

## Gotchas

- `GameStatusChange` has no `created_at` — don't copy-paste the `#640`
  backfill loop unmodified onto it; it needs the `timestamp`-with-NULLS-LAST
  ordering described in the design doc.
- `AutoPlayEventIn` is a real `ModelSchema` — this is the one place in the
  whole cutover sequence where "no `ModelSchema` touches this model" isn't
  true by default; it's still safe because its `Meta.fields` is explicit,
  but write the test that proves it rather than assuming it from `#640`'s
  precedent.
- If implementing before `#640` merges: don't invent a different shape for
  `uuid7_at` — copy `#640`'s design exactly so whichever PR merges second
  can trivially rebase out the duplicate.
