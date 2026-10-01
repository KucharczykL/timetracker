# P4: convert every legacy purchase — plan

Spec: [Convert every legacy purchase](../specs/2026-10-01-issue-723-purchase-conversion-design.md).
Branch `claude/issue-723-purchase-conversion`, stacked on #1417.
Inline, TDD. Every pytest run under
`flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS=…`.

Test DB note: a pass test that appends needs `transaction=True` only where it
goes through `dispatch`; the pass itself runs in `transaction.atomic()`, so
plain `django_db` works. The migration test needs `transaction=True`.

## Task 1 — extract `purchase_creation_events`

- `games/commands/purchase.py`: move `RecordPurchase.build`'s body into
  `purchase_creation_events(context, *, copy, kind, name, price, note,
  purchased, purchase_id=None) -> list[NewEvent]`; `build` calls it.
- Test (`tests/test_purchase_command.py`): the function with a
  `purchase_id` creates that key; with `None` mints one; it refuses what
  the command refuses (a bad price, a hidden copy). Existing tests stay
  green unchanged (fingerprint unaffected).

## Task 2 — extract `release_on`

- `games/catalog_release.py`: `release_on(library, game, platform:
  Platform) -> PlatformRelease` holds the `state()` body plus the
  shared-game refusal and the `write_and_mirror` call;
  `release_on_platform` resolves game and platform name and calls it.
- Existing `release_on_platform` tests stay green; one test for
  `release_on` reusing a live Release and making one.

## Task 3 — `seeded` valuation

- `games/valuations.py`: factor the row build in `value()` into
  `_valuation_row(...)`; add `seeded(facts, target, rate, amount, *,
  library, version, calculated_at)`: same rate-rule `ValueError` as
  `value()`; where no rate is needed, `amount` must equal
  `facts.amount` (else `ValueError`); `amount` quantized to cents.
- Tests in `tests/test_purchase_valuation.py`: rate row carries the given
  amount; no-rate row refuses a differing amount; a rate where none is
  needed is refused.

## Task 4 — the plan (pure)

`games/backfill/__init__.py`, `games/backfill/purchase_plan.py`:

- `LegacyRow(NamedTuple)`: `id, library_id, game_ids (tuple, key order),
  platform_id, platform_name, date_purchased, date_refunded, infinite,
  price (float), price_currency, converted_price, converted_currency,
  ownership_type, type, name, related_game_id, removed_at`.
- `Category(StrEnum)`: the ten review words plus `skipped_removed_game`.
- `PlannedCopy(NamedTuple)`: `row, game_id, purchase_id (UUID | None
  where no purchase), access, format, kind, name, amount (Decimal |
  None), currency, converted_share (Decimal | None), is_addon_game,
  is_attached (pass/upgrade), categories (tuple)`.
- `plan(row, *, minted: Callable[[], UUID]) -> list[PlannedCopy]` and
  `legacy_refusals(row) -> list[str]`.
- Helpers: `quantized_amount(float) -> Decimal` (`Decimal(repr(f))`,
  half up), `split_cents(total: Decimal, count) -> list[Decimal]`,
  `access_and_format(ownership, platform_name)`.
- Tests `tests/test_purchase_conversion_plan.py` (no DB): every table row
  of access/format; Gamepass vs other rental; Epic free vs Steam unknown
  vs non-owned no purchase vs non-owned priced; bundle 3 games of 10.00 →
  3.34/3.33/3.33 in key order, legacy key on first, minted on others;
  `du` → upgrade; dlc → kind game, blank name, `is_addon_game`; season
  pass attached; 2.9925 → 2.99 with `quantized`; currency upper-cased;
  converted share split by the same rule; refusals: no game, add-on
  games ≠ related, blank add-on name, NaN/inf price; upgrade
  (`type=game`, no related) is no refusal.

## Task 5 — legacy reader and schema guard

`games/backfill/purchase.py`:

- `legacy_rows(model, library_id=None) -> list[LegacyRow]`: values via
  the model and its `games.through`, platform name via `platform__name`;
  no live-class import. Order (date_purchased, id).
- `_require_the_schema_this_pass_was_written_for()`: port from
  `git show 5ddb30d5:games/backfill/device.py`, over the models the pass
  touches (spec list).
- `unconverted(rows)`: rows whose (legacy id, game) key holds no
  idempotency record; the pass returns at once on none.
- Tests: reader over the live model returns rows with games in key order
  and platform names; the guard refuses with a fake missing column
  (monkeypatch introspection).

## Task 6 — the pass, catalog step

- `_dlc_game(row, base, library) -> Game`: lookup (library, parent,
  name, kind DLC, live) else `Game(library, name, sort_name=name)`,
  `state_addon`, `save()`, `state_catalog_graph` default Edition + default
  Release on base's default Release platform, `mirror_legacy_columns`.
- `_release_for(copy, game, library) -> Release`: Demo → Edition "Demo"
  prerelease (lookup by name, live) + Release on platform under it
  (through `state_catalog_graph` with the existing Edition row);
  else default Release when platform null or equal; else `release_on`.
- Tests (`tests/test_purchase_conversion.py`): DLC Game kind/parent/
  sort_name/tracked after the pass, second run finds it; Demo Edition
  prerelease; mismatched platform makes one private Release, a second row
  on it reuses it.

## Task 7 — the pass, acts

- `PurchaseConversionRefused(Exception)` with the listed refusals.
- `PurchaseConversion(NamedTuple)`: `libraries, appended (count),
  skipped, refusals`.
- `_Appender`: library, actor, correlation id, recorded_at; `append(key,
  command_input, build, metadata) -> tuple[LibraryEvent, ...]`, reading
  events back by stream + sequence range on a `ReplayedAppend`; counts
  appended.
- `convert_purchases(rows, *, recorded_at=None, commit=True)`:
  group by library; per library phases A (game + dlc) and B (attached),
  each row in `transaction.atomic()` savepoint with catch list from the
  spec; exclusions; valuations; replay check. `commit=False` raises a
  private rollback exception at the end and answers the result (preflight).
- Base copy pick for attached rows: query `LibraryEntry` live, Owned,
  `access_end_recorded_at__isnull=True`, `player_game__game=base`, order
  (platform match desc, acquired_lower, id).
- Own-copy removal: `RemoveEntry` only for a copy this row's `created`
  made, after `RemovePurchase`, when `blocking_referrer` finds none.
- Tests:
  - single game row: one entry (owned digital, acquired = day) and one
    purchase under the legacy key, amount/currency, metadata origin;
  - refunded game row: `refund_owns_the_end` true; `VoidPurchaseRefund`
    (via `tests/purchases` style append) clears the copy end;
  - refunded non-owned priced row: copy ended way refunded, no coupling;
  - non-owned zero: entry, no purchase;
  - bundle: n purchases, cents sum to total, first keeps legacy key;
  - pass with refunded + live base copies picks the live one; pass with
    no base copy gets its own; upgrade gets its own owned copy kind upgrade;
  - infinite on game and on dlc row: both flags on base and DLC Game;
    mixed game tagged;
  - removed legacy row: purchase and own copy removed;
  - removed game: skipped and reported, nothing appended for it;
  - hand-recorded copy: second entry made, tagged;
  - second run appends nothing (LibraryEvent count equal), seeds nothing;
  - two libraries: converting one leaves the other untouched;
  - a refusal (e.g. price above `LARGEST_AMOUNT`, add-on base not main)
    is listed with the row; nothing written; two refusals both listed;
  - replay check passes (`rebuild_projections` CHECK clean).

## Task 8 — valuations in the pass

- After acts, where appended > 0: lock state; skip if `published_version`
  0 or blank target; inputs from `valuation_inputs(library)` keyed by
  purchase id; per purchase: rate needed → stored `ExchangeRate` and the
  plan's `converted_share` with matching legacy `converted_currency`,
  else skip; else `seeded(amount=facts.amount)`. `publish_valuations`.
  Then `request_revaluation(library)` unless `requested_currency` blank.
- Tests: same-currency row seeds its own amount; foreign row seeds the
  converted share with the stored rate and reads current
  (`stale_purchases` empty for it); no stored rate → no row; unpublished
  library → no rows, no request; request bumps `requested_version` once;
  second run leaves rows untouched.

## Task 9 — reconciliation, review lists, snapshot

`games/backfill/purchase_reconciliation.py`:

- `Reconciliation` dataclass and `reconcile(library, rows)`: the spec's
  list; `failures()` → unexplained differences.
- `review_lists(library)`: events with origin conversion grouped by
  category → legacy ids/aggregate ids; plus preflight-only lists.
- `legacy_statistics(library) -> dict` and `snapshot_value(value)`
  encoder; scopes: all-time + `played_years` ∪ legacy purchase/refund
  years.
- Tests: totals equal after a pass with quantization delta reported;
  refund counts match; snapshot encodes queryset, model, timedelta, date,
  Decimal, named tuple, mapping, None; JSON round-trips; scopes include a
  purchase-only year.

## Task 10 — command and Make target

- `verify_purchase_conversion`: `--user` (required), `--confirm`,
  `--snapshot PATH`. Preflight: `convert_purchases(...,
  commit=False)`, print refusals, review lists, reconciliation, mixed
  infinite backlog counts (legacy `compute_stats` before vs a read of the
  converted flags—print unfinished/dropped counts before and after inside
  the rolled-back transaction). Confirm: commit; nonzero exit on
  refusals or reconciliation failures.
- Makefile target `verify-purchase-conversion` beside
  `verify-reclassification-parity`; CLAUDE.md command table row.
- Tests (`tests/test_verify_purchase_conversion.py`): preflight writes
  no event; confirm writes; mismatched `--confirm` refused; snapshot file
  shape; a refusal makes exit nonzero with the row named.

## Task 11 — migration 0031

- `games/migrations/0031_purchase_conversion.py`: depends on
  `("games", "0030_purchasevaluation")` and django_q's
  `0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more`;
  `convert(apps, schema_editor)` reads `apps.get_model("games",
  "LegacyPurchase")` through `legacy_rows`, runs `convert_purchases`.
- Test (`tests/test_purchase_migrations.py`): migrate to 0030, insert
  legacy rows with SQL/historical model (plus game, release, tracked
  game via live code), migrate to 0031, assert purchases; migrate back to
  leaf in `finally`.

## Task 12 — dump rehearsal

- Restore the 2026-10-01 dump, migrate 0030, run preflight with
  `--snapshot`, confirm, `make migrate` (0031 appends nothing),
  `make verify-replay-parity`, `make audit-uuid-identity`. Paste the
  reconciliation into the PR.

## Gotchas

- `state_addon` raises outside an atomic block; the pass is inside one.
- `state_catalog_graph` and `write_and_mirror` are `@transaction.atomic`:
  savepoints, fine.
- `mirror_legacy_columns` raises `LEGACY_IDENTITY_TAKEN` on a flat
  collision: a refusal.
- `idempotent_append` returns `ReplayedAppend` without events: read back.
- `capture_reference` vs `uuid` copy: `purchase_creation_events` takes
  the same `copy` union as the command.
- `RecordPlayerGameFacts` skips held facts: a second run is `Unchanged`
  anyway, but keys answer first.
- `django.db.Error` inside a savepoint: catch after the `atomic()` block
  exits so the savepoint rolls back.
- `games` logger has `propagate=False`: use the `capture_games_logger`
  fixture for log assertions.
- Test libraries publish nothing (`published_version` 0): set the state
  in valuation tests.
