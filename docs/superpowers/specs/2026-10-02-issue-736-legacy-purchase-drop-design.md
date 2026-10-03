# The legacy purchase is gone

Issue [#736](https://github.com/KucharczykL/timetracker/issues/736), P5c of the
[Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## The drop

The fourth squash drops `LegacyPurchase` and its through table, and
deletes the schedule row of the retired task `calculate_price_per_game`.

The currency task values purchases only. A purchase whose rate the
source does not have is skipped with a warning. A `DatabaseError`, or a
source that does not answer (`RateFetchFailed`), fails the run and
schedules one retry.

`RETIRED_FILTER_MODELS` keeps refusing `legacypurchase`.

## The conversion tooling

The conversion ran once, on the 2026-10-02 deploy. Its pass,
its verify commands and the legacy test fixture went with the fourth
squash (#1448), which refuses a database that still holds legacy
rows.

## The sample fixture

The fixture holds Platform, Game, Edition, Release, the event store and
ExchangeRate. The anonymizer keeps the copy that each purchase names,
because a refund ends that copy.

- Edition and Release have no `created_at`. They get new ids at
  `FIXED_EPOCH`, in key order.
- A reference to an entry gets the new id of the entry's aggregate, in
  the payload and in `LibraryEventReference`.
- A path rewrite goes into each item of a list. A join id gets a new id
  at the epoch. Any other bare id must name an aggregate of the library.
- The runs of a record are sorted again, and each rewritten payload is
  validated again. A reference, an id or a payload that fails stops the
  command with the key of the event or of the reference row.
- `--name-overrides` also changes the names of editions.
- The prune deletes the projection rows of the other libraries first,
  because their keys are `RESTRICT`.

The loader loads Edition and Release. It checks `game.parent`,
`edition.game`, `release.edition` and `release.platform`. It requests a
valuation run when the state is behind or a purchase is stale.

## Residuals

- #1450: a purge of a library that has an add-on fails. P6, the
  last member of the stack, fixes it.
