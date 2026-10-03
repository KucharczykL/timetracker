# The fourth squash removes the purchase conversion (#1448, #1472)

## Scope

Migrations `0019` to `0036` carried the Access and Purchases wave.
`0031` ran the one-time purchase conversion. Its tooling existed for
that pass and its rehearsal.

## The squash

- `0019_device_access_end_squashed_0036_defer_library_event_stream_matches_library`
  holds the wave's schema. It has no `replaces`; the eighteen files are
  gone.
- It holds none of the four data passes: the rate copy, the
  conversion, the preset rewrite and the schedule removal.
- Its `RunSQL` operations are optimizer barriers. A fresh install
  creates `LegacyPurchase` and drops it.
- Prod is the only database. Its history records the squash. A
  development database is dropped and rebuilt.

## The guard

- The squash's first operation refuses a database that holds legacy
  purchases, stored rates, or a preset in the legacy purchase words.
  At that point the tables have their `0018` shape. A fresh database
  holds none of these and passes.
- Without the guard, legacy purchases drop unconverted, purchase
  presets stop loading, and stored rates fail a `NOT NULL` column.
- The second operation deletes the retired task's schedule row.
- Both read raw SQL on `schema_editor.connection`, so a test calls
  them against the live tables. Both are `elidable=True`, so the next
  squash removes them.

## Removed

`games/backfill/`; `verify_purchase_conversion` and
`verify_purchase_statistics` with their Make targets;
`games/purchase_parity.py`; `seeded` in `games/valuations.py`; the
`legacy_purchase` test fixture; every test that read the tooling or
imported a replaced file.

## Kept

`games/stats_parity.py`, `PurchaseConversionState`,
`purchase_creation_events` and `release_on`.

## Deployment

- Step one shipped the squash with `replaces` and `0037`. Startup
  recorded the squash beside the eighteen originals. The rollback was
  the pre-deploy dump, since `0037` removes a column the earlier image
  reads.
- Step two removes the originals and `replaces`. The cutover `DELETE`
  of the eighteen history rows runs after the step-two image is up.
  Before it, the earlier image still carries `replaces`; without the
  rows it tries the squash, the guard refuses, and the container does
  not start.

## Rehearsal

- Step one: `make verify-baseline ARGS="--migrate"` on the 2026-10-02
  dump found every catalog identical.
- Step two, on the post-deploy dump: `make verify-dump` applies
  nothing. `make verify-baseline ARGS="--normalize cutover.sql"`, with
  no `--migrate`, passes `migrate --check` after the `DELETE` and finds
  every catalog identical, history included.
