# Every purchase read on the projections

Issues: [#734](https://github.com/KucharczykL/timetracker/issues/734),
[#735](https://github.com/KucharczykL/timetracker/issues/735), the read
half of [#1266](https://github.com/KucharczykL/timetracker/issues/1266).
Member P5a of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## Filter

`PurchaseFilter` filters the `Purchase` projection. Its model key is
`purchase`. `price_state` is `paid`, `free` or `unknown`. `valuation`
reads the current valuation's amount.

`PurchaseQuerySet.annotated_for_filtering(library)` registers the
valuation aliases. Without a library, the aliases resolve and refuse to
compile. A second library is refused.

`AggregateSpec.correlated` names the path from a related row back to its
parent. The reducer then sums a correlated subquery over the scoped
queryset. `GameFilter.purchase_price_total` uses it.

Migration `0032` rewrites saved presets to the new fields. A preset it
cannot express stays unchanged and loads refused. Migration `0033` gives
the legacy model's relations no reverse accessor. It changes no table.

## Readers

The Purchases list, the Library page, the navbar, the removal previews
and the platform API read `library_purchases`. Game detail shows no
purchases.

## Statistics

Each figure states one filter. Its link carries the same filter, so a
figure and its link compile one predicate. A day is in a year by
containment.

`games/reads/purchase_figures.py` reads purchases in one statement:

- `total_spent` sums the current valuations of unrefunded purchases.
- `total_spent_unpriced` counts unrefunded purchases with no amount.
- `total_spent_unvalued` counts unrefunded purchases with an amount and
  no valuation. The page shows it only when it is not 0.

`games/reads/copy_figures.py` reads copies in one statement. A copy is a
live entry on a `full` Edition. Unfinished, Dropped and Backlog decrease
count Owned copies. The finished and played figures count copies of any
access. A pass or upgrade has no copy of its own. A DLC copy counts
through its own Game.

## Parity gate

`legacy_figures(model, library, year)` computes the legacy figures. It
takes the model, so it also runs on the historical model. It counts each
legacy row once.

A format-2 snapshot holds each figure's value and the legacy keys behind
it. `make verify-purchase-statistics` reads a snapshot, computes each
scope now, and judges each key. `games/purchase_parity.py` maps each
converted row to its legacy key and gives each moved key a `Reason`.
Each figure admits only its own reasons. A ratio is recomputed from its
judged row sets. `total_spent` must equal the legacy sum to the cent
over the keys valued on both sides. The gate fails on any moved key
without a reason.

## Known differences

The legacy page counted a bundle twice when it joined through two
games. The snapshot counts each row once. The new figures count copies,
so a bundle gives one copy per game, and a non-owned row at 0 gives a
copy and no purchase.
