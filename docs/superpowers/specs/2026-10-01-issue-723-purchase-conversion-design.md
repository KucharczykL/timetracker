# Convert every legacy purchase

Issues: [#723](https://github.com/KucharczykL/timetracker/issues/723),
[#730](https://github.com/KucharczykL/timetracker/issues/730),
[#731](https://github.com/KucharczykL/timetracker/issues/731),
[#732](https://github.com/KucharczykL/timetracker/issues/732),
[#733](https://github.com/KucharczykL/timetracker/issues/733). Member P4 of
the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## The pass

Migration `0031` runs the pass once. `make verify-purchase-conversion`
runs it for one library. The legacy rows stay; P5 removes them.

`legacy_rows(model)` reads the legacy rows. The migration gives it the
historical model, because P5 removes the live class. Everything the pass
writes goes through live code.

The pass returns at once when every live copy has its creation key. Before
it writes, it refuses when a live model declares a column the database
does not hold. P5 adds no column to a table the pass touches.

## Plan

`purchase_plan.plan` makes one copy per (legacy row, game). It holds no
database access.

- Access and format follow the wave's table. `Xbox Gamepass` rentals are
  subscriptions.
- An amount is `Decimal(repr(price))`, rounded half up to cents once.
- A bundle splits its cents; the remainder goes to the first games in key
  order. The first game keeps the legacy key.
- An owned row at 0 is free on `Epic Games Store`, else unknown. A
  non-owned row at 0 makes a copy and no purchase.
- A DLC row buys its own Game, kind `dlc`, under the base game.
- A pass or an upgrade goes on the base game's live, owned, unended copy,
  else on its own copy.

## Acts

The pass calls each command's `build` and appends through
`idempotent_append`. One key per act:
`conversion:723:<act>:<legacy id>:<game id>`. The command input holds
legacy facts only, so a second run appends nothing. One `recorded_at`
serves the whole pass. `source_metadata` names the origin, the legacy rows
and the review categories.

Order per library: game and DLC rows, then passes and upgrades, then
exclusions, then valuations. Each row runs in its own savepoint. The pass
lists every refusal, then rolls back everything. A copy of a removed game
is skipped.

A refunded owned `game` copy ends through `RefundPurchase`, so the refund
owns the end. Another refunded copy ends through `EndEntryAccess`, way
`refunded`.

## Valuations

Where the library publishes a target, the pass seeds one valuation per
purchase through `seeded`. A purchase in the target currency values at
its amount. Another currency takes the legacy converted share and the
stored rate. Then `request_revaluation` requests one run.

## Checks

The pass analyzes the tables and checks replay parity. The command prints
the refusals, the review lists, the reconciliation and the backlog counts.
A currency total or a refund count that does not reconcile fails it.
`--snapshot` writes the legacy statistics for P5.
