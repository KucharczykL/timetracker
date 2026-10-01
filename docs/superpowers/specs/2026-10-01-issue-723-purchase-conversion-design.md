# Convert every legacy purchase

Issues: [#723](https://github.com/KucharczykL/timetracker/issues/723),
[#730](https://github.com/KucharczykL/timetracker/issues/730),
[#731](https://github.com/KucharczykL/timetracker/issues/731),
[#732](https://github.com/KucharczykL/timetracker/issues/732),
[#733](https://github.com/KucharczykL/timetracker/issues/733).
Member P4 of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md)
(its [Conversion](2026-09-28-access-and-purchases-wave-design.md#the-conversion)
section is the contract). Builds on P1 (#725), P2 (#727), P3 (#728),
M3 (#1352), M7 (#1353), M8 (#1334).

## Outcome

One pass states every `LegacyPurchase` row as the events, catalog rows and
valuations the new model holds. It runs once, out of migration `0031`, and
by hand through `make verify-purchase-conversion`. The legacy rows stay
untouched; every reader keeps reading them until P5.

## What the data says

Read on the 2026-10-01 dump, migrated to `0030`. One library, 808 live
legacy rows, none removed, no `LibraryEntry`, no `Purchase`.

| Fact | Count |
|---|---|
| Ownership: Digital / Physical / Rented / Demo / Pirated / Borrowed / Upgrade | 678 / 48 / 36 / 34 / 7 / 4 / 1 |
| Type: game / dlc / season_pass / battle_pass | 767 / 35 / 4 / 2 |
| Bundles of 2, 4, 6, 8 games | 1, 2, 2, 2 rows: 7 rows, 38 games |
| Refunded: game / dlc, all Digital; refund before purchase | 220 / 1; 0 |
| Purchase platform null (Digital / Pirated) | 4 / 4 |
| Purchase platform not the game's Release platform (Digital / Rented) | 10 / 4 |
| Owned at price 0 on Epic Games Store (a shared platform) | 19 |
| Rented on Xbox Gamepass (a shared platform) | 6 |
| `infinite` rows: game / dlc | 26 / 7 |
| Prices with a third decimal | 2 (2.9925 EUR, 1.0725 EUR) |
| Currencies in mixed or lower case | 3 |
| Games all private; one Edition and one Release each | 864 |
| Purchased games untracked; naming a removed game | 0; 0 |
| `ExchangeRate` rows; conversion state | 75; published 9, CZK, at rest |

Every add-on names its base as its only game and as `related_game`.
Each of the six passes has one or two `game` purchases of its base; one
base purchase of the 2025-04-20 battle pass is refunded. The upgrade's
game has no other purchase.

## Where the pass runs

P4 and P5 deploy in one image. When `0031` runs in production, P5's code
is live and the live `LegacyPurchase` class is gone. So:

- The pass reads legacy rows through a reader that takes the model:
  `legacy_rows(model, library_id=None) -> list[LegacyRow]`. The migration
  hands it the historical model from `apps`; the P4 command hands it the
  live one. Everything the pass writes goes through live code: commands,
  projectors, the catalog writers, the valuation writer.
- The pass returns at once where no legacy row lacks its creation event,
  so a fresh database never runs today's code against an older schema.
- Before it writes, the pass refuses where a live model it touches
  declares a column the database does not hold yet, as #1274's pass did.
  P5 therefore adds no column to a table the pass reads or writes
  (projections, the event tables, `Game`, `Edition`, `Release`,
  `Platform`, `PurchaseConversionState`, `PurchaseValuation`,
  `ExchangeRate`), or its rehearsal fails.
- The rehearsal, the `--snapshot` and the reconciliation run on P4's
  commit, on the day's dump, before the deploy. The deploy rehearsal on
  P5's commit (`make verify-dump`) runs `0031` under P5's code.

`0031` is `RunPython(convert, noop, elidable=True)` with no schema change.
It imports live command code, as `0015` (#1274) and `0004` (#700) did,
because the event store lives only in the live classes. A squash elides it
once the deployment records it ([Squashing](../../migration-squash.md)).
It depends on `django_q`'s last migration, so the revaluation request
enqueues on commit.

## Modules

- `games/backfill/purchase_plan.py`: pure. `LegacyRow` and the plan: one
  `PlannedCopy` per (legacy row, game) with access, format, kind, name,
  amount, currency, days, the purchase key, whether a purchase is made,
  the review categories. No database access.
- `games/backfill/purchase.py`: `legacy_rows`, and the pass:
  `convert_purchases(rows, *, recorded_at=None) -> PurchaseConversion`.
- `games/backfill/purchase_reconciliation.py`: the reconciliation, the
  review lists and the legacy statistics snapshot.
- `games/management/commands/verify_purchase_conversion.py`,
  `make verify-purchase-conversion`.
- `games/migrations/0031_purchase_conversion.py`.

Two extractions keep one rule in one place:

- `purchase_creation_events(context, *, copy, kind, name, price, note,
  purchased, purchase_id=None)` in `games/commands/purchase.py` holds
  `RecordPurchase.build`'s body, every check included; the command calls
  it with no key. No command gains a field, so `FINGERPRINT_VERSION` stays
  3.
- `release_on(library, game, platform)` in `games/catalog_release.py`
  holds `release_on_platform`'s body for a `Platform` row; the named
  variant resolves the name and calls it.

## Events through the commands' own code

A migration's transaction cannot host `dispatch`, because
`run_in_transaction` refuses to nest. A command's `build` can run there.
So the pass calls each act's builder with `CommandContext(library,
actor)` and appends the result through `idempotent_append` with:

- one idempotency key per act: `conversion:723:<act>:<legacy id>:<game
  id>`, and `conversion:723:excluded:<game id>` for the one act per game.
  P2's one key per dispatch holds.
- a `command_input` of legacy-derived values only (act, legacy id, game
  id, the planned facts), never a minted key, so a second run replays its
  keys instead of mismatching.
- one `recorded_at` for the whole pass (the instant it starts). Every
  converted row's `created_at` ties, so the UUID order audit
  (`(created_at, pk)`) breaks the tie by key. This holds because no
  `Purchase` exists before the pass.
- one correlation id per library.
- `source_metadata = {"origin": "conversion", "issue": 723,
  "legacy_purchases": ["<id>", ...], "review": [<categories>]}`: one id
  for a row's acts, every `infinite` row of the game for its exclusion.
  P5's review surface finds the events by `origin`.

| Act | Builder |
|---|---|
| `created` | `purchase_creation_events(..., copy=EntryStatement(...) or the base copy's key, purchase_id=key)` |
| `entry` (a copy and no purchase) | `RecordEntry(...).build` |
| `refunded` | `RefundPurchase(...).build`: `purchase.refunded`, then the copy's `access_ended` directly after it where the copy is Owned and held, P2's shape |
| `ended` (a refunded non-Owned copy) | `EndEntryAccess(copy, WayActStatement(day, REFUNDED)).build` |
| `removed` | `RemovePurchase(...).build`; then `RemoveEntry(...).build` on the row's own copy where no live purchase names it |
| `excluded` | `RecordPlayerGameFacts(game, excluded_from_unfinished=True, excluded_from_dropped=True).build` |

`actor` is the library's user. A replayed key answers its range; the pass
reads the events in that range back for the keys later acts need. A second
run therefore appends nothing and still reaches the same rows.

## Refusals

Each legacy row's catalog writes and acts run in one savepoint. A
refusal (`CommandRejected`, `RowUnreadable`, `GraphRefused`,
`AddonRefused`, `RowRefused`, a `ValidationError`) is caught, the
savepoint rolled back, and the row, its game and the sentence recorded.
A `CommandConflict` or a `django.db.Error` is caught the same way and
recorded as a defect, with its class and message. After the last row, any refusal
raises `PurchaseConversionRefused` naming every one, and the whole
transaction rolls back. So the preflight prints every refusal in one run,
and a refusal never first appears in a deploy.

Checks no command makes run first, as refusals of the same list: a row
naming no game, a row of `type` other than `game` whose games are not
exactly its `related_game`, a blank add-on name, a price that is not
finite. The upgrade is `type` `game` with no `related_game`; its base is
its own game.

Two user states are not refusals:

- A row whose only games the library removed (the catalog mark or the
  tracked game's) is hidden today; the pass skips it, and its
  exclusion, and reports it as `skipped_removed_game`.
- A library whose conversion state names no target currency seeds no
  valuation and requests no run.

## Order inside one library

Each row runs its catalog writes, then its
acts, in its own savepoint.

1. **Catalog**, per row. Not events; idempotent by lookup.
   - A `dlc` row: a private `Game(library, name, sort_name=name)` of the
     row's name (a blank `sort_name` leads every game order), then
     `state_addon(kind=DLC, parent=base)`, then `save()`, then
     `state_catalog_graph` for a default Edition and a default Release on
     the base's default Release platform, then `mirror_legacy_columns`. A
     second run finds it by (library, parent, name, kind).
   - A `Demo` row's Release: the live Edition named "Demo", kind
     `prerelease`, of its game (made where none), and the Release on the
     row's platform under it.
   - Any other row's Release: the game's default Release when the row
     states no platform or the default's platform (8 rows state none),
     else `release_on(library, game, platform)` (14 made on the dump).
2. **Game and DLC rows**, ordered by (purchase day, legacy key, game key):
   `created` or `entry`; then `refunded` or `ended`; then `removed`.
3. **Passes and the upgrade**, in the same order and with the same acts.
   They come after step 2, so every refund has ended its copy and every
   removed row's copy is gone before a pass picks a base copy.
4. **Exclusions**, once per game.
5. **Valuations**, then `request_revaluation(library)` once; only where
   this run appended.
6. **Replay check**: `ANALYZE` the tables the pass wrote, then
   `rebuild_projections(library, mode=CHECK)` over the live projection
   classes; a difference refuses.

## Planning rules

Access and format follow the wave's table. "Owned" is Physical, Digital
and Digital Upgrade. Gamepass and Epic are recognised by the platform's
exact name, `Xbox Gamepass` and `Epic Games Store`; these are the only
inferences.

| Rule | Result |
|---|---|
| Amount | `Decimal(repr(price))` quantized to cents, half up, once |
| Currency | upper-cased |
| Bundle of n games | total cents divmod n; each game the quotient; the remainder one cent each to games in key order; days, refund and words copied |
| Bundle's purchase keys | the first game in key order keeps the legacy UUIDv7; each other game a UUIDv7 minted at the pass |
| Owned at amount 0 | free (0) on Epic Games Store, else unknown (null amount, blank currency) |
| Non-Owned at amount 0 | a copy and no purchase |
| Non-Owned with an amount | a copy and a purchase |
| Kind | `du` → `upgrade`; `season_pass`, `battle_pass` kept; `game` and `dlc` → `game` |
| Name | the legacy name, except a DLC row's, which names its Game and leaves the purchase's blank |
| Copy of a `dlc` row | the DLC Game's Release, access and format by the table |
| Copy of a pass or the upgrade | among the base game's live Owned copies whose access end is unstated: the one on the row's platform's Release first, then earliest acquired, then key; none: its own copy by the table |
| Acquired and purchased | the purchase day, exact; notes blank |
| A refunded `game` row's Owned copy | created unended; `RefundPurchase` ends it |
| A refunded non-Owned copy | `EndEntryAccess`, way `refunded`, the refund day |
| `infinite` | both exclusions on each game the row links, and on a DLC row's own Game too |

Review categories, one list per planned copy: `unknown_price`,
`epic_free`, `rental`, `created_release`, `demo_edition`,
`mixed_infinite` (a game with an `infinite` row beside a normal one),
`addon_game`, `quantized`, `bundle_split`, `hand_recorded_copy` (a game
that already holds a copy no conversion stated; the pass adds a second
one, since no rule tells one copy stated twice from two copies).

## Valuations

The pass seeds one row per purchase with an amount, through
`publish_valuations(library, rows)` under the conversion state's lock,
inside the pass's transaction. Each row's inputs come from
`valuation_inputs(library)`, so they read current. A row is built by
`seeded(facts, target, rate, amount, ...)` in `games/valuations.py`, a
sibling of `value()` with the same rate rule; `value()` computes `amount ×
rate`, and a whole-unit seed cannot come from it.

- No rate needed (same currency as the published target, or 0): `amount`
  is the purchase's own amount, `rate` null. P3's `rate_where_needed`
  CHECK requires that.
- A rate needed and stored: `amount` is the legacy `converted_price`
  split by the bundle rule, `rate` the stored rate.
- No row: a rate needed and none stored, a null `converted_price`, a
  legacy `converted_currency` other than the published target, or a
  library that has published nothing (`published_version` 0 or a blank
  target, which the `currency_codes` CHECK refuses). The daily recovery
  values those.

`version` is the published version, `calculated_at` the pass instant.
`request_revaluation` then replaces the whole-unit values with decimal
ones. A run that appended nothing seeds and requests nothing, so a
rehearsal's `migrate` never puts whole-unit values back.

## Make verify-purchase-conversion

`--user NAME` is the preflight. It runs the pass for that library inside
a transaction it rolls back, then prints every refusal, the review lists,
the reconciliation, and the backlog counts the infinite games move.
`--confirm NAME` (equal to `--user`) runs the same pass and commits. A
library the pass converted already appends nothing.

The reconciliation, read from legacy rows beside the projections:

- planned copies, copies and purchases made, rows skipped, by category;
- legacy totals per currency against purchase totals, and each
  quantization delta;
- refunded legacy rows against refunded purchases and refund-ended copies;
- copies by access and format;
- tracked games before and after (the DLC Games are new);
- valuation sums against legacy `converted_price` sums;
- mixed infinite games with their unfinished and dropped counts.

An unexplained difference fails the command: a total that does not
reconcile to its quantization deltas, or a refund count that differs.

`--snapshot PATH` writes the legacy statistics for P5, which judges its
new readers against it. Shape:

```json
{
  "format": 1,
  "library": "<uuid>",
  "taken_at": "<ISO instant>",
  "scopes": {"all-time": {"<StatsData key>": "<value>"}, "2024": {}}
}
```

Scopes are all-time and every year a session, a record or a legacy
purchase day names. A value encodes recursively: a queryset as its keys
in order, a model as its key, a `timedelta` as whole seconds, a `date` as
ISO text, a `Decimal` as text, a named tuple or a mapping as an object, a
list element-wise; `None`, booleans, numbers and text as themselves. A
queryset of legacy rows differs by design after the split: bundle keys
are new.

## Callers that change

- `load_sample_data` does not run the pass. Within P4 every reader still
  reads legacy rows, so the fixture loads as before. P5, which drops the
  legacy table, owns the fixture: a pass at load or a fixture regenerated
  in the stack. Its loader tests (`tests/test_library_commands.py`, the
  anonymizer round trip) hold legacy rows a pass would refuse: a row
  naming no game, games with no Release.
- P5 deletes the command, the reconciliation and the live call of
  `legacy_rows`; the migration's historical read stays until a squash
  elides `0031`. `docs/migration-squash.md` records that `games/backfill/`
  returns with it.
- `RecordPurchase.build` and `release_on_platform` call the extracted
  functions.
- CLAUDE.md (commands table, the Purchase note) and
  `docs/migration-squash.md` (the elided passes).
- The fixture PR after the cutover: the anonymizer empties
  `source_metadata` and mints new aggregate ids, so the regenerated
  fixture holds no review tags and no legacy keys.

## Rehearsal and deployment

On P4's commit, with the day's dump:

1. `make restore-dump`; it prints the scratch `DATABASE_URL`, which every
   step below passes.
2. `make migrate ARGS="games 0030"`.
3. `make verify-purchase-conversion ARGS="--user NAME --snapshot PATH"`.
4. `make verify-purchase-conversion ARGS="--user NAME --confirm NAME"`.
5. `make migrate`: `0031` appends nothing.
6. `make verify-replay-parity`, `make audit-uuid-identity`.

On P5's commit: `make verify-dump` and `make verify-baseline
ARGS="--migrate"`. The container's startup `migrate` runs `0031`. The
pre-deploy dump is the rollback; the pass has no reverse.

## Verification

- Planning: unit tests per table row, the bundle remainder, the zero rule,
  Gamepass and Epic, the key rule, the categories.
- The pass: two libraries (only the named one converts); a second run
  appends nothing and seeds nothing; a converted refund's copy end is the
  refund's own (`refund_owns_the_end`) and `VoidPurchaseRefund` takes it
  back; a pass skips a refunded base copy; every refusal is listed and
  nothing is written; the schema guard refuses; the replay check passes.
- The migration test runs `0031` over seeded legacy rows.
- The command: the preflight writes nothing, confirm writes, the snapshot
  shape.
- The 2026-10-01 dump: the reconciliation pasted into the PR.

## Follow-up issues to file

None found yet.
