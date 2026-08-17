# ID-05: Convert library configuration identities to UUIDv7 — design specification

Status: draft for approval. Parent phase: #600. Depends on `#639`; shares
mechanics with `#640` — see the
[catalog identity design](2026-08-17-issue-640-catalog-uuid-identity-design.md)
and the [wave plan](2026-08-17-uuid-identity-cutover-wave-plan.md). Does not
depend on `#640`, `#641`, `#642` merging first.

## Context

"Library configuration" is `Device` and `FilterPreset` — the two remaining
models with their own integer primary key that don't fit the catalog,
play-history, or purchase buckets. `UserLibraryPreferences` and
`PurchaseConversionState` are explicitly not part of this (or any) issue:
both already use `UserLibrary`'s UUID as a shared one-to-one primary key
(`library = OneToOneField(UserLibrary, primary_key=True, ...)`,
`games/models.py:766` and `:811`) and have no integer identity to convert.

Both `Device` and `FilterPreset` follow `#640`'s pattern with no
model-specific wrinkle — no nullable timestamp case like `#641`'s
`GameStatusChange`, no zero-`ModelSchema`-exception like `#641`'s
`AutoPlayEventIn`.

## Goals

Same as `#640`: a populated, unique, creation-ordered `uuid` column on
`Device` and `FilterPreset`, landed as one additive, reversible migration
with reconciliation evidence.

## Non-goals

Same list as `#640`, plus explicitly: `UserLibraryPreferences.default_device`
stays an integer foreign key to `Device.id` in this issue — repointing it is
part of ID-08/#846 (bundled with `Session.device`, since both target
`Device`).

## Data model after this issue

`Device` and `FilterPreset` each gain exactly one field:

```python
uuid = UUIDv7Field(unique=True, editable=False)
```

`Device` has no `library`-adjacent field to place it after in the same way
`#640` does — `library` *is* `Device`'s first field
(`games/models.py:529`) — so `uuid` goes immediately after `library`, before
the `PC`/`CONSOLE`/... choice constants. `FilterPreset` places it the same
way, after `library` (`games/models.py:706`), before `name`.

Neither model has a `ModelSchema` in `games/api.py`: `DeviceOut`
(`games/api.py:337`), `PresetOption`/`PresetIn` (`:601`/`:609`) are all
hand-written `Schema` classes with explicit fields, not derived from the
model. `DeviceForm` (`games/forms.py:852`, `fields = ("name", "type")`) is
the only `ModelForm` involved; `FilterPreset` has no form at all — it is
managed entirely through the `/api/presets` Ninja endpoints (see
`CLAUDE.md`'s "Filter presets have no classic views" note), whose request/
response schemas are the hand-written `PresetIn`/`PresetOption` above.

## Backfill

Identical mechanism to `#640`: both `Device.created_at` and
`FilterPreset.created_at` are non-null `auto_now_add=True`
(`games/models.py:549` and `:715`). Ordering source `("created_at", "pk")`,
same sequence counter for within-millisecond ties.

## Migration and reconciliation mechanics

Same five-operation shape as `#640`, two models: nullable `AddField` ×2,
`RunPython` backfill+reconciliation, final `AlterField` ×2. Migration
depends on whichever of `#639`'s successors is latest at implementation
time.

Reconciliation checks: the same list as `#640` (row/distinct count, no
`uuid` shared with any other converted model — including the specific case
of a `Device` and a `FilterPreset` sharing a value, which the cross-check
must catch same as it catches `Game`/`Platform` collisions in `#640` —
version-7, timestamp equality, order preservation), scoped to both models.

```
LIB identity backfilled device_rows=<n> device_distinct=<n> filterpreset_rows=<m> filterpreset_distinct=<m> max_timestamp_delta_ms=0 order_preserved=true
```

## Rollback and reversibility

Identical to `#640`: drop both columns, total reversal. The window for
`Device` closes once ID-08/#846 repoints `Session.device` and
`UserLibraryPreferences.default_device`. `FilterPreset` has no incoming
foreign keys anywhere in the schema (it is only ever looked up by its own
pk from the API layer), so its reversal window in practice stays open
through the rest of the cutover — noted for completeness, not relied upon.

## Deployment assumption

Same as `#640`. `FilterPreset` specifically: this repository's production
database has zero saved presets (confirmed directly), so there is no
existing-row backfill risk to rehearse for that model regardless of the
general row-count assumption.

## Verification

New file `tests/test_library_config_identity.py`, mirroring
`tests/test_catalog_identity.py`'s structure: field-contract tests for both
models, `uuid` absence from `DeviceForm`'s field set and from
`DeviceOut`/`PresetOption`/`PresetIn` (confirming the hand-written schemas
stay hand-written and don't accidentally start deriving from the model),
`MigrationExecutor` forward test (same-millisecond and out-of-order
fixtures for both models, plus a genuinely-empty-table case for
`FilterPreset` given the zero-rows-in-production fact above) and reverse
test.

Regression surface expected unchanged: `tests/test_api.py`,
`tests/test_filters.py`, `tests/test_filter_execution.py`,
`tests/test_filter_presets.py`, `tests/test_paths_return_200.py`,
`tests/test_rendered_pages.py`, `tests/test_components.py`,
`tests/test_search_select.py` (Device selector).

The gate is the full `make check`.

## Explicit handoffs

Same shape as `#640`'s: `#645`/ID-10 reuses this issue's reconciliation
checks; ID-08/#846 repoints `Session.device` and
`UserLibraryPreferences.default_device`; ID-14/#850 removes the integer
identities once verified.
