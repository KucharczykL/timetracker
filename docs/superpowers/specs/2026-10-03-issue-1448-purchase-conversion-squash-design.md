# Squash past the purchase conversion and remove its tooling (#1448)

## Problem

The deployment records `0019` to `0036` (2026-10-02 post-deploy dump,
`django_migrations`). `0031_purchase_conversion` runs the one-time
purchase conversion; `games/backfill/`, `make verify-purchase-conversion`,
its reconciliation, `make verify-purchase-statistics` with
`games/purchase_parity.py`, `seeded` in `games/valuations.py`, and the
`legacy_purchase` test fixture exist only for that pass and its
deploy-day rehearsal.

## Measured

- `make squash-migrations ARGS="games 0019 0036"`, after `0029`'s
  `copy_forward` and `0035`'s `remove_retired_schedule` take
  `elidable=True`, writes
  `0019_device_access_end_squashed_0036_defer_library_event_stream_matches_library`:
  58 operations to 34, no `RunPython`. The `RunSQL` in `0026` (legacy
  index renames) and `0036` (deferred stream key) are barriers and
  survive, so a fresh install creates `LegacyPurchase` and drops it, as
  the earlier squashes kept `Session`.
- With that file on disk, every test using the conversion tooling fails
  (121 of 190 in the six files): a fresh test database takes the
  squash, the replaced nodes leave the graph, and
  `legacy_purchase_model()` cannot render `0034`
  (`NodeNotFoundError`, `LegacyTableGone`); `test_purchase_migrations.py`
  migrates to replaced nodes by name. The tooling cannot outlive the
  squash, so it leaves in the same PR.
- `0031` imports `games.backfill.purchase` inside `convert`, not at
  module level. The deployment holds all eighteen and never runs it
  again. A database holding some but not all of them (a stale worktree
  database) takes the originals and reaches `convert`.
- A database holding none of the eighteen takes the squash. Every dump
  before 2026-10-02 is one (`.dumps/timetracker-2026-10-01.dump` records
  only `0001…` and `0007…`), and so is a dev database at `0018` after
  `make loadsample`. Three elided passes then lose data: eliding
  `0029`'s copy collapses it to `RemoveField rate` plus `AddField rate`
  `numeric(24, 12) NOT NULL` with no default (squash `exchangerate`
  operations), which refuses a table holding rates and drops an empty
  one's silently; the conversion's rows vanish when `DeleteModel
  LegacyPurchase` runs; `0032`'s preset rewrite never happens.

## Decisions

- One PR carries this and #1443. Not a stack: the remaining step needs a
  deploy between, and a branch held across a deploy only gathers
  rebases. The organizer ruled the same.
- The squash is the tool's output with `replaces`, through `make format` and `make lint-fix`, plus the guard. The
  eighteen originals stay until the deployment records the squash.
- `0031`'s `convert` raises `RuntimeError` instead of importing the
  pass. Only a partial history reaches it, and only a worktree database
  holds one, so the sentence says to drop and rebuild that database.
- The squash's first operation is a `RunPython`, `elidable=True`, that
  raises `RuntimeError` when `games_purchase` or `games_exchangerate`
  holds a row. At that point both tables are the `0018` ones; a fresh
  database holds none, so the guard passes, and the deployment has the
  squash recorded and never runs it. The sentence names both remedies:
  a deployment migrates with the image before the squash first; a dev
  database is dropped and rebuilt. It reads raw SQL on
  `schema_editor.connection`, so a test imports the squash by module,
  inserts an `ExchangeRate` into the live table and calls it; the next
  squash elides it.
- 0037 ships beside the squash, so a rollback to the previous image
  reads a column that no longer exists. The rollback is the pre-deploy
  dump, as for every wave deploy. A `db_default` step in between would
  keep the column for one deploy; chosen against, since the
  deployment's rollback has always been the dump.
- Removed: `games/backfill/` whole; `verify_purchase_conversion` and
  `verify_purchase_statistics` with their Makefile targets;
  `games/purchase_parity.py`; `seeded`; `tests/legacy_purchases.py` and
  its `tests/conftest.py` import; `tests/test_legacy_model.py`,
  `test_purchase_conversion.py`, `test_purchase_conversion_plan.py`,
  `test_purchase_stats_parity.py`, `test_verify_purchase_conversion.py`,
  `test_purchase_migrations.py`; the `seeded` tests in `test_purchase_valuation.py`; the
  `converted` fixture and its test in `test_purchase_preset_rewrite.py`.
  Each fails once the squash lands.
- Kept: `games/stats_parity.py` (`verify-reclassification-parity`);
  `refund_ends`, `identity_taken`, `release_on`,
  `purchase_creation_events`, the fingerprint helpers (each has a live
  caller); `PurchaseConversionState` (the valuation task's state); the
  pure tests of `0032`'s rewrite and `tests/test_exchange_rates.py`'s
  test of `0029`'s `decimal_rate`, which import the original files by
  module and leave with them.
- `docs/migration-squash.md` records the fourth squash and replaces
  "Passes waiting for a squash". CLAUDE.md's `LegacyPurchase` paragraph
  and the #723 paragraph take the Device and Session wording: the pass
  ran once, out of a migration since squashed; what it left behind is
  the events. The two command-table rows and the
  `verify-purchase-statistics` sentence in the #735 text go.

## Rehearsal

`make verify-baseline ARGS="--migrate"` on the 2026-10-02 post-deploy
dump: the copy carries over as startup `migrate` will, records the
squash beside the originals, and every catalog matches a fresh build.

## Follow-up issues to file

- Step two: after the deployment records the squash, remove the
  eighteen originals and `replaces`, the remaining `0032` rewrite tests
  and `tests/test_exchange_rates.py`'s `0029` test,
  run the cutover `DELETE` rehearsed with `--normalize`, and trim the
  wave doc's Conversion, Preflight and rehearsal, Review surface and
  Deployment sections.
