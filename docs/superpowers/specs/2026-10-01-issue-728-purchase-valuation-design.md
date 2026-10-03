# Purchase valuations in decimals

Issues: [#728](https://github.com/KucharczykL/timetracker/issues/728) and
[#729](https://github.com/KucharczykL/timetracker/issues/729). Member P3 of
the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## Exchange rates

`ExchangeRate.rate` is a positive `Decimal(24, 12)`. A one-time pass
copied each float through `repr()`, rounded to twelve places, and
dropped an unusable cached rate. The fourth squash elided it.

`exchange_rate` answers the stored rate, else fetches it with
`parse_float=Decimal`, quantizes and stores it. It answers `None` when the
fetch fails or answers no usable rate. The legacy converter multiplies by
`float(rate)`.

## PurchaseValuation

The currency task alone writes this conventional model, one row per
purchase:

- `purchase_id`: the key, not a foreign key.
- `amount`: `Decimal(26, 2)`, multiplied in 60 digits, rounded half up once.
- `source_amount`, `source_currency`, `rate_year`: the inputs.
- `rate`: null where the purchase needs no rate.
- `version`, `calculated_at`.

A purchase with an unknown amount has no row. A free purchase values at 0.
CHECKs hold the rate rule and the currency codes. The ownership audit
reports a valuation that names no purchase of its library.

`rate_year` is the year of `purchased_lower`, else of `purchased_upper`,
else of `purchase_recorded_at` in the calendar zone. `valuation_year`
states this rule once, in SQL.

A valuation is **current** when all of these are true:

- Its target is the library's published target.
- Its inputs equal the purchase's.
- Its `rate` is null where the purchase needs none: same currency, or
  amount 0.
- Otherwise its `rate` equals the stored `ExchangeRate`.

`stale_purchases(library)` answers the live purchases with an amount and
no current valuation.

## The task

`convert_library_prices` values the legacy rows and the valuations for one
version. It publishes both under the state lock, in one transaction. The
publication replaces the library's valuations whole, so a library holds
one target. A newer version publishes nothing. A changed snapshot
publishes nothing and requests the next version, because a removal
requests none.

A purchase without a rate (an unknown code, or a future year) is skipped
and logged as a warning. The rest publish. The skipped purchase stays
stale, so the recovery requests it every day; #1418 reports it. A legacy
row without a rate still fails the run. A defect fails the run without a
retry.

## The request

`request_revaluation(library)` requests a version at the state row's own
target. Two signals call it, and `load_sample_data` requests the same
way after its replay:

1. The purchase writes, after a dispatch appends `created`,
   `price_changed`, `purchase_corrected` or `restored`. A crash between
   the two transactions loses the request.
2. The daily recovery, for a library at rest with stale purchases. It
   also covers a restored parent, a zone change and other appenders.

A database failure after a committed write is logged, not answered. A
missing state row is a defect and raises. The recovery isolates each
library, skips a blank target with a warning, and logs each request.

## Reads and API

`with_valuation` annotates the current amount and the published target in
one statement. `PurchaseOut.valuation` is `{amount, currency}`, or null
without a current valuation.

## Handoffs

- P4 seeds valuations through `publish_valuations`, then requests one run.
- P5 reads valuations through `with_valuation`.
