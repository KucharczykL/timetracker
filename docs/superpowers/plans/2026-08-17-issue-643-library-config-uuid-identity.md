# ID-05: Convert library configuration identities to UUIDv7 — implementation plan

Design: [Library configuration UUID identity design](../specs/2026-08-17-issue-643-library-config-uuid-identity-design.md).
Mechanically identical to the [catalog identity plan](2026-08-17-issue-640-catalog-uuid-identity.md) — this plan only calls out the two-model delta.

**Goal:** add a populated, unique, creation-ordered UUIDv7 column to
`Device` and `FilterPreset` without changing any application behavior.

**Constraints:** same as `#640`'s plan.

## Task 1 — `uuid7_at` encoder (skip if already merged by `#640`/`#641`/`#642`)

Follow whichever of those lands first; do not reimplement independently if
any has already merged.

## Task 2 — model fields

Files: `games/models.py`.

1. Add `uuid = UUIDv7Field(unique=True, editable=False)` to `Device` (after
   `library`, before the `PC`/`CONSOLE`/... choice constants) and to
   `FilterPreset` (after `library`, before `name`).
2. `make makemigrations`.

## Task 3 — split the migration and write the backfill

1. Split the generated `AddField` ×2 into the five-operation sequence.
2. Implement `backfill_library_config_uuids(apps, schema_editor)`: identical
   shape to `#640`'s per-model loop for both `Device` and `FilterPreset`,
   ordered by `("created_at", "pk")`.
3. Implement `reconcile_library_config_identity(apps)`: the same six
   checks, scoped to both models, including the cross-model uniqueness
   check between `Device` and `FilterPreset` (and against every
   previously-converted model).
4. Confirm no migration drift.

## Task 4 — tests

File: `tests/test_library_config_identity.py` (new), mirroring
`tests/test_catalog_identity.py`'s structure: field contract for both
models, `uuid` absence from `DeviceForm` and from the hand-written
`DeviceOut`/`PresetOption`/`PresetIn` schemas, forward `MigrationExecutor`
test (include an empty-table case for `FilterPreset`), reverse test.

`make test ARGS="tests/test_library_config_identity.py tests/test_uuidv7.py -x"`.

## Task 5 — regression sweep

```
make test ARGS="tests/test_api.py tests/test_filters.py tests/test_filter_execution.py tests/test_filter_presets.py tests/test_paths_return_200.py tests/test_rendered_pages.py tests/test_components.py tests/test_search_select.py"
```

## Task 6 — gate

`make check`; capture the printed `LIB identity backfilled ...` line as
migration evidence.

## Gotchas

- `FilterPreset` is managed entirely through `/api/presets` (no Django
  form) — don't go looking for a `FilterPresetForm` that doesn't exist; the
  invisibility test targets `PresetIn`/`PresetOption` instead.
- Production has zero `FilterPreset` rows today — the migration must still
  handle the empty-table case correctly (test it explicitly), not just rely
  on "there's nothing to break."
