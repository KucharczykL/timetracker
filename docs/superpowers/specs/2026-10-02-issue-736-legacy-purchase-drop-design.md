# The legacy purchase is gone

Issue [#736](https://github.com/KucharczykL/timetracker/issues/736), P5c of the
[Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## The drop

Migration `0035_delete_legacypurchase` deletes `LegacyPurchase` and its
through table. It also deletes the schedule row of the retired task
`calculate_price_per_game`. The reverse creates the tables again, empty.

The currency task values purchases only. A purchase whose rate the
source does not have is skipped with a warning. A `DatabaseError`, or a
source that does not answer (`RateFetchFailed`), fails the run and
schedules one retry.

`RETIRED_FILTER_MODELS` keeps refusing `legacypurchase`.

## The conversion tooling

Migration 0031 runs the conversion in the deploying image. Thus the pass,
`verify_purchase_conversion` and the reconciliation stay until the
squash (#1448).

They read the model from migration state `0034_conversion_review_hidden`
through `legacy_purchase_model()` (`games/backfill/legacy_model.py`).
The historical model takes keys, not instances, and has no signals. `require_legacy_table` raises `LegacyTableGone` when the
table or the migration state is absent. The command then refuses with
one sentence.

Tests make legacy rows with the `legacy_purchase` fixture. It creates
both tables inside the test's transaction, and the rollback removes them.
It refuses a `transaction=True` test, because a flush cannot empty a
table that no model declares.

Each module and fixture that #1448 removes has the comment
`conversion-tooling`.

## The deploy-day rehearsal

Use the dump of that day. Set `DATABASE_URL` to the URL that the restore
prints, for each step after the first.

1. `make restore-dump`.
2. `make migrate ARGS="games 0030_purchasevaluation"`.
3. `make verify-purchase-conversion ARGS="--user X --snapshot S"`.
4. The same command with `--confirm X`.
5. `make migrate ARGS="games 0034_conversion_review_hidden"`. It appends
   no event.
6. `make migrate`.
7. `make verify-purchase-statistics ARGS="--user X --snapshot S"`.
8. `make verify-replay-parity`, `make verify-dump`,
   `make verify-baseline ARGS="--migrate"`.

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
