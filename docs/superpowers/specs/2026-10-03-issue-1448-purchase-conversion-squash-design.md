# The fourth squash removes the purchase conversion (#1448)

## Scope

Migrations `0019` to `0036` carry the Access and Purchases wave. `0031`
ran the one-time purchase conversion. Its tooling existed for that pass
and its rehearsal.

## The squash

- `0019_device_access_end_squashed_0036_defer_library_event_stream_matches_library`
  replaces the eighteen files and keeps `replaces`. The originals stay
  until the deployment records the squash (#1472).
- Four data passes are `elidable=True` and the squash holds none:
  `0029`'s rate copy, `0031`'s conversion, `0032`'s preset rewrite and
  `0035`'s schedule removal.
- The `RunSQL` in `0026` and `0036` are optimizer barriers. A fresh
  install creates `LegacyPurchase` and drops it.

## The guard

- The squash's first operation refuses a database that holds legacy
  purchases, stored rates, or a preset in the legacy purchase words. At
  that point the tables have their `0018` shape.
- Only a database that has applied none of the eighteen takes the
  squash. A fresh one holds no such row and passes. The deployment
  records the squash and does not run it.
- Without the guard, legacy purchases drop unconverted, purchase
  presets stop loading, and stored rates fail a `NOT NULL` column with
  no remedy. The error names the table and two remedies: a deployment
  migrates with the image before the squash first; a development
  database is dropped and rebuilt. Rates are a cache, so deleting them
  also works.
- The second operation deletes the retired task's schedule row.
- Both read raw SQL on `schema_editor.connection`, so a test calls them
  against the live tables. Both are `elidable=True`, so the next squash
  removes them.
- A database that has applied some of the eighteen takes the
  originals. `0031` refuses it while legacy purchases exist, with the
  same remedies.

## Rollback

`0037` ships with the squash. The image before it reads a column that
`0037` removes. The rollback is the pre-deploy dump.

## Removed

`games/backfill/`; `verify_purchase_conversion` and
`verify_purchase_statistics` with their Make targets;
`games/purchase_parity.py`; `seeded` in `games/valuations.py`; the
`legacy_purchase` test fixture and every test that used it.

## Kept

`games/stats_parity.py`, `PurchaseConversionState`,
`purchase_creation_events`, `release_on`, and the tests that import
`0029`, `0031` and `0032` by module. Those tests leave with the files.

## Rehearsal

`make verify-baseline ARGS="--migrate"` on the 2026-10-02 dump records
the squash, applies `0037`, and finds every catalog identical.
`make verify-dump` on the 2026-10-01 dump stops at the guard.
