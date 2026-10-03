# The fourth squash removes the purchase conversion (#1448)

## Scope

Migrations `0019` to `0036` carry the Access and Purchases wave. `0031`
ran the one-time purchase conversion. Its tooling existed for that pass
and its rehearsal.

## The squash

- `0019_device_access_end_squashed_0036_defer_library_event_stream_matches_library`
  replaces the eighteen files and keeps `replaces`. The originals stay
  until the deployment records the squash (#1472).
- `0029`'s rate copy, `0031`'s conversion and `0035`'s schedule removal
  are `elidable=True`. The squash holds none of them.
- The `RunSQL` in `0026` and `0036` are optimizer barriers. A fresh
  install creates `LegacyPurchase` and drops it.

## The guard

- The squash's first operation refuses a database whose
  `games_purchase` or `games_exchangerate` holds a row. At that point
  both tables have their `0018` shape.
- A fresh database holds no row, so it passes. The deployment records
  the squash and does not run it.
- A database at `0018` with data takes the squash. Without the guard,
  the squash drops its rates, its legacy purchases and their
  conversion. The error names the two remedies: a deployment migrates
  with the image before the squash first; a development database is
  dropped and rebuilt.
- The guard reads raw SQL on `schema_editor.connection`, so a test can
  call it against the live tables. It is `elidable=True`, so the next
  squash removes it.
- A database that holds some of the eighteen takes the originals.
  `0031` then refuses with the same remedy.

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
`0029` and `0032` by module. Those tests leave with the files.

## Rehearsal

`make verify-baseline ARGS="--migrate"` on the 2026-10-02 dump records
the squash, applies `0037`, and finds every catalog identical.
`make verify-dump` on the 2026-10-01 dump stops at the guard.
