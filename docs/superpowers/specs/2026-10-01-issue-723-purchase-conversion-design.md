# Convert every legacy purchase

Issues: [#723](https://github.com/KucharczykL/timetracker/issues/723),
[#730](https://github.com/KucharczykL/timetracker/issues/730),
[#731](https://github.com/KucharczykL/timetracker/issues/731),
[#732](https://github.com/KucharczykL/timetracker/issues/732),
[#733](https://github.com/KucharczykL/timetracker/issues/733). Member P4 of
the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## The pass

Migration `0031` runs the pass once; `make verify-purchase-conversion`
runs it for one library. `legacy_rows(model)` reads the legacy rows
through the historical model, because P5 removes the live class. Every
write goes through live code.

The pass returns at once when every live copy holds its keys. It
refuses when a live model declares a column the database lacks, so P5
adds no column to a table the pass touches.

## Plan

`purchase_plan.plan` makes one copy per (legacy row, game). It holds no
database access. It refuses a row that no rule states, a DLC that is also
a digital upgrade included.

- Access and format follow the wave's table.
- An amount is `Decimal(repr(price))`, rounded half up to cents once.
- A bundle splits its cents; the remainder goes to the first games in key
  order. The first game keeps the legacy key.
- An owned row at 0 is free on `Epic Games Store`, else unknown. A
  non-owned row at 0 makes a copy and no purchase.
- A DLC row buys its own Game, kind `dlc`, under the base game.
- A pass or an upgrade with a purchase goes on the base game's live,
  owned, unended copy, on the row's platform first. Else it gets its own
  copy, in the `own_copy_fallback` list.

## Acts

The pass appends each command's `build` through `idempotent_append`,
one key per act and copy (`conversion:723:<act>:<legacy id>:<game id>`)
and one per excluded game. The command input holds legacy facts only, so
a repeat matches its fingerprint; a legacy row changed since is a defect.
One `recorded_at` serves the pass. `source_metadata` names the origin,
the legacy rows and the review categories.

Passes and upgrades run after the other rows, each row in a savepoint.
The pass lists every refusal and defect, then rolls back everything. A
copy of a removed game is skipped with a warning.

A refunded owned `game` purchase ends its copy through `RefundPurchase`,
so the refund owns the end. Any other refunded copy of the row's own ends
through `EndEntryAccess`, way `refunded`. A copy shared with the base game
does not end.

A live `infinite` row excludes its game from both backlog figures. A
DLC row excludes the DLC's own Game, not the base, as the legacy figures
did.

## Valuations

Where the library publishes a target, the pass seeds one valuation per
new purchase through `seeded` and keeps every standing one. A purchase in
the target currency values at its amount. Another currency takes the
legacy converted share and the stored rate. A purchase without a stored
rate or a converted share in the target is listed as unvalued. Where the library requests a target,
`request_revaluation` then requests one run.

## Checks

The pass checks replay parity. The command prints the refusals, the
review lists and the reconciliation; a currency total or refund count
that does not reconcile fails it. `--snapshot` writes the legacy
statistics for P5.
