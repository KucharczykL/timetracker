# Every purchase read on the projections

Issues: [#734](https://github.com/KucharczykL/timetracker/issues/734),
[#735](https://github.com/KucharczykL/timetracker/issues/735), the read
half of [#1266](https://github.com/KucharczykL/timetracker/issues/1266).
Member P5a of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## Filter

`PurchaseFilter` filters the `Purchase` projection. Its model key is
`purchase`. `price_state` is `paid`, `free` or `unknown`. `valuation`
reads the current valuation's amount. A float criterion compares as the
decimal the person typed.

`PurchaseQuerySet.annotated_for_filtering(library)` registers the price
and valuation aliases. Without a library, the aliases resolve and refuse
to compile. A later call that names a library is refused.

`AggregateSpec.correlated` names the path from a related row back to its
parent. The reducer sums a correlated subquery over the scoped queryset.
`games.E016` checks that each path ends at its parent.

## Migrations

Migration `0032` rewrites saved presets. A legacy price of 0 became an
unknown price, so a price criterion that matches 0 is refused. A refund
day's presence becomes the refund act. An upgrade rides its base copy,
so `du` states no format. A refused preset stays unchanged and loads
refused.

Migration `0033` removes every reverse accessor of the legacy model. It
changes no table.

## Statistics

Each figure states one filter. Its link carries the same filter. A
purchased or acquired day is in a year by containment. A completion is
in a year by overlap.

`games/reads/purchase_figures.py` reads purchases in one statement:

- `total_spent` sums the current valuations of unrefunded purchases.
- `total_spent_unpriced` counts unrefunded purchases with no amount.
- `total_spent_unvalued` counts unrefunded purchases with an amount and
  no valuation. The page shows it only when it is not 0.

`games/reads/copy_figures.py` reads copies in one statement. A copy is a
live entry on a `full` Edition. Unfinished, Dropped and Backlog decrease
count Owned copies. A pass or upgrade has no copy of its own.

## Parity gate

`legacy_figures(model, library, year)` computes the legacy figures. It
also runs on the historical model. It counts each legacy row once. Both
sides state their row sets as one `RowSets`.

A format-2 snapshot scope holds `figures`, `rows` and `amounts`.
`make verify-purchase-statistics` judges each row set. A key can leave,
join or repeat. Each `Reason` names the row sets it can move, and how.
A key is explained only by a reason that holds for it and can cause its
move. The gate fails on any unexplained row set, and on any figure
without an attribution. A ratio must equal its value recomputed from the
judged rows. Each key valued on both sides must match to the cent.

## Known differences

The legacy page counted a bundle once per abandoned game. A pass's
legacy ownership now reads as its base copy's.
