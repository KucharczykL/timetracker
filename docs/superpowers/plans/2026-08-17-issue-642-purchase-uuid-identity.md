# ID-04: Convert Purchase and ownership identity to UUIDv7 — implementation plan

Design: [Purchase UUID identity design](../specs/2026-08-17-issue-642-purchase-uuid-identity-design.md).
Mechanically identical to the [catalog identity plan](2026-08-17-issue-640-catalog-uuid-identity.md) — this plan only calls out the one-model delta.

**Goal:** add a populated, unique, creation-ordered UUIDv7 column to
`Purchase` without changing any application behavior.

**Constraints:** same as `#640`'s plan.

## Task 1 — `uuid7_at` encoder (skip if already merged by `#640`/`#641`)

Follow whichever of those two lands first; do not reimplement independently
if either has already merged.

## Task 2 — model field

Files: `games/models.py`.

1. Add `uuid = UUIDv7Field(unique=True, editable=False)` to `Purchase`,
   after `library`, before `games`.
2. `make makemigrations`.

## Task 3 — split the migration and write the backfill

1. Split the generated `AddField` into the five-operation sequence.
2. Implement `backfill_purchase_uuid(apps, schema_editor)`: identical shape
   to `#640`'s per-model loop, ordered by `("created_at", "pk")`.
3. Implement `reconcile_purchase_identity(apps)`: the same six checks,
   scoped to `Purchase`.
4. Confirm no migration drift.

## Task 4 — tests

File: `tests/test_purchase_identity.py` (new), mirroring
`tests/test_catalog_identity.py`'s structure exactly (field contract,
form-field invisibility, forward/reverse `MigrationExecutor` tests).

`make test ARGS="tests/test_purchase_identity.py tests/test_uuidv7.py -x"`.

## Task 5 — regression sweep

```
make test ARGS="tests/test_api.py tests/test_filters.py tests/test_filter_execution.py tests/test_filter_presets.py tests/test_paths_return_200.py tests/test_rendered_pages.py tests/test_components.py tests/test_price_update.py"
```

## Task 6 — gate

`make check`; capture the printed `PUR identity backfilled ...` line as
migration evidence.

## Gotchas

- `Purchase.save()` has non-trivial conversion-request logic
  (`games/models.py:367-419`, locks `PurchaseConversionState` via
  `select_for_update`). Adding a field with a Python-side default
  (`uuid.uuid7`) doesn't touch this path, but run
  `tests/test_price_update.py` explicitly rather than assuming the
  regression sweep's other files cover it.
- Don't add an identity to the `Purchase.games` M2M through table — it's
  explicitly out of scope (see design doc Non-goals).
