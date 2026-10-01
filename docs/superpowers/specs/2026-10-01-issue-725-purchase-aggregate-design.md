# The Purchase aggregate

Issues: [#725](https://github.com/KucharczykL/timetracker/issues/725),
[#726](https://github.com/KucharczykL/timetracker/issues/726),
[#828](https://github.com/KucharczykL/timetracker/issues/828). Member P1 of
the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## Purpose

A purchase is one transaction for one item. It names one copy, a
`LibraryEntry`. The `Purchases` projector writes the `Purchase` row from
the `library.purchase` stream. No screen reads the row until P5.

## The legacy row

`LegacyPurchase` is the old row, on table `games_legacypurchase`. P5
deletes it. Its `verbose_name` is "purchase", so the screens keep their
words. The filter key is `legacypurchase`, because the filter machinery
finds a filter by model name. Migration 0026 renames the model, its
through table and every index of the two tables. A table rename keeps
the index names, and the old names collide with the new table's names.

## Storage

| Column | Rule |
|---|---|
| `entry` | `LibraryEntry`, `RESTRICT`, required; one copy may have many purchases |
| `kind` | `game`, `season_pass`, `battle_pass` or `upgrade` |
| `name` | the product name, at most 255 characters, blank by default |
| `amount` | `Decimal(12, 2)`; null is unknown; zero is free |
| `currency` | three upper-case letters; blank exactly where `amount` is null |
| `purchased` and its bounds, marker and note | the opening endpoint `PURCHASE_DAY` |
| `note` | free text |
| `created_at` | the creation event's `recorded_at` |
| `removed_at` | the projector's mark; null is live |

CHECK constraints hold the kind, the sign and the currency rule.
`alive()` reads the marks of the purchase, the entry and the tracked game.

## Events

Nine events: `created`, `kind_changed`, `name_changed`, `note_changed`,
`price_changed`, `entry_changed`, `purchase_corrected`, `removed`,
`restored`. A price is one object: an amount as text with two places and
no sign (`"12.50"`), and a currency. An unknown price is null. A float
never enters a payload. A name is no longer than its column. `entry` is a reference of kind
`libraryentry`.

## Commands

Every command but `RecordPurchase` resolves through
`library_purchase_row`. A key that the library does not hold is `RowNotHeld`. A purchase that names the entry of
another library is `RowUnreadable`.

- `RecordPurchase` names one `copy`: a held entry's key, or an
  `EntryStatement`. A new entry is created in the same dispatch, after the tracking events if
  the game is not tracked.
- `DescribePurchase` writes one event for each changed fact. Its
  `purchased` corrects the opening endpoint. A new entry must belong to
  the same game. No other command corrects the day.
- `RemovePurchase` and `RestorePurchase` move the mark. Both answer
  `Unchanged` for the state that the row holds. Removal refuses under a
  removed copy or tracked game. Restore refuses under a copy that a read
  hides, a removed Release included.

`check_price` refuses a non-number, a signed amount, an amount above
`LARGEST_AMOUNT` and a third decimal place. It requires a currency
exactly where an amount is stated. `LARGEST_AMOUNT` comes from the
column. A command does not round an amount. A name, a note or a day
note that holds a NUL byte or a lone surrogate is refused.

A command refuses a copy that a removed Release hides, because no read
shows a purchase on it. A live purchase prevents the removal of its
entry.

## API

`/api/purchases/` has `GET /`, `GET /{id}`, `POST /` and `PATCH /{id}`.
A body refuses an unknown key. `PATCH` states `amount` with `currency`,
and `purchased` with `purchase_note`; else it answers 422. A `PATCH`
dispatches `DescribePurchase`, and the refund act where it states one.
A price that
`check_price` refuses answers 409.

## Limits

- P2 adds refunds. A refunded purchase does not move to another entry.
- P3 adds valuation. P4 converts the legacy rows.
