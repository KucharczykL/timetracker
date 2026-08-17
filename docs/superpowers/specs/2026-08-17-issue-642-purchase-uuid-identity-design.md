# ID-04: Convert Purchase and ownership identity to UUIDv7 — design specification

Status: draft for approval. Parent phase: #600. Depends on `#639`; shares
mechanics with `#640` — see the
[catalog identity design](2026-08-17-issue-640-catalog-uuid-identity-design.md)
and the [wave plan](2026-08-17-uuid-identity-cutover-wave-plan.md). Does not
depend on `#640`, `#641` merging first.

## Context

`Purchase` is the one model in the "Purchase and ownership" bucket — the
M2M through table for `Purchase.games` is not a domain identity in its own
right and gets no `uuid` of its own (see Non-goals). This is the smallest of
the four Wave B issues: one model, and `Purchase` already has a non-null
`created_at`, so it is a direct, unmodified application of `#640`'s pattern
with no model-specific wrinkle comparable to `#641`'s `GameStatusChange`
case.

## Goals

Same as `#640`: a populated, unique, creation-ordered `uuid` column on
`Purchase`, landed as one additive, reversible migration with reconciliation
evidence.

## Non-goals

Same list as `#640`, plus explicitly:

- The `Purchase.games` M2M through table gets no identity of its own. It is
  a pure link table; ID-09/#847 (the M2M FK-rewrite slice) repoints its two
  FK columns (`purchase_id`, `game_id`) directly at `Purchase.uuid` and
  `Game.uuid` without the through table needing an identity of its own.
- `Purchase.related_game` and `Purchase.platform` stay integer foreign keys
  in this issue — repointing them is ID-09/#847.
- No change to `PurchaseConversionState` — it already shares `UserLibrary`'s
  UUID primary key and needs no conversion (see `#640`'s design, "Model
  inventory").

## Data model after this issue

`Purchase` gains exactly one field:

```python
uuid = UUIDv7Field(unique=True, editable=False)
```

Declared immediately after `library` and before `games` — the same relative
position `#640` uses for `Game`/`Platform` (right after the ownership FK,
before the first domain field).

No `ModelSchema` in `games/api.py` touches `Purchase` (confirmed by
inspection — there is no `PurchaseOut`/`PurchaseIn` class at all; purchase
data reaches templates/JS through server-rendered components, not a Ninja
schema), so the "no API leak" argument holds without `#641`'s
`AutoPlayEventIn` caveat. `PurchaseForm` (`games/forms.py`) enumerates
fields explicitly, same as every other form in this sequence.

## Backfill

Identical mechanism to `#640`: `created_at` (`auto_now_add=True`,
`games/models.py:309`) drives `uuid7_at`, ordered by `("created_at", "pk")`
with the same within-millisecond sequence counter.

## Migration and reconciliation mechanics

Same five-operation shape as `#640`, single model: nullable `AddField`,
`RunPython` backfill+reconciliation, final `AlterField`. Migration depends
on whichever of `#639`'s successors is latest at implementation time.

Reconciliation checks: the same list as `#640` (row/distinct count, no
`uuid` shared with any other converted model, version-7, timestamp equality,
order preservation), scoped to `Purchase` alone.

```
PUR identity backfilled purchase_rows=<n> purchase_distinct=<n> max_timestamp_delta_ms=0 order_preserved=true
```

## Rollback and reversibility

Identical to `#640`: drop the column, total reversal, window closes once
ID-09/#847 repoints `Purchase`'s relations.

## Deployment assumption

Same as `#640`.

## Verification

New file `tests/test_purchase_identity.py`, structured exactly like
`tests/test_catalog_identity.py`: field-contract tests, `uuid` absence from
`PurchaseForm`, `MigrationExecutor` forward test (same-millisecond and
out-of-order fixtures) and reverse test.

Regression surface expected unchanged: `tests/test_api.py`,
`tests/test_filters.py`, `tests/test_filter_execution.py`,
`tests/test_filter_presets.py`, `tests/test_paths_return_200.py`,
`tests/test_rendered_pages.py`, `tests/test_components.py`,
`tests/test_price_update.py` (conversion signals — `Purchase.save()`'s
conversion-request logic in `games/models.py:367-419` is untouched by this
issue but is the most save()-path-sensitive code in the model, worth an
explicit regression pass).

The gate is the full `make check`.

## Explicit handoffs

Same shape as `#640`'s: `#645`/ID-10 reuses this issue's reconciliation
checks; ID-09/#847 repoints `Purchase.games`, `Purchase.related_game`,
`Purchase.platform`; ID-13/#849 removes the integer identity once verified.
