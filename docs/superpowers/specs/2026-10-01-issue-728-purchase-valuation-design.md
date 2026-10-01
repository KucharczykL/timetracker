# Purchase valuations in decimals

Issues: [#728](https://github.com/KucharczykL/timetracker/issues/728) and
[#729](https://github.com/KucharczykL/timetracker/issues/729). Member P3 of
the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## Exchange rates

`ExchangeRate.rate` is `Decimal(24, 12)`. Migration 0029 copies each float
through `repr()`, the shortest spelling that round-trips, rounded to twelve
places. The migration runs in both directions.

`exchange_rate(source, target, year)` in `games/exchange_rates.py` answers
the stored rate. Without one, it fetches the rate, parses the JSON with
`parse_float=Decimal`, quantizes to twelve places and stores it. It
answers `None` when the fetch fails or the API has no positive rate. The
legacy converter multiplies by `float(rate)`.

## PurchaseValuation

`PurchaseValuation` is a conventional model. The currency task is its only
writer. It holds one row per purchase and target currency:

- `purchase_id`: the key, not a foreign key.
- `amount`: `Decimal(26, 2)`. The task multiplies in a 60-digit context and
  rounds half up once.
- `source_amount`, `source_currency`, `rate_year`: the inputs.
- `rate`: null where the purchase needs no rate.
- `version`, `calculated_at`.

A purchase with an unknown amount has no row. A free purchase values at 0.
CHECKs hold the rate rule and the currency codes. The ownership audit
reports a valuation that names another library's purchase.

`rate_year` is the year of `purchased_lower`, else of `purchased_upper`,
else of `purchase_recorded_at` in the calendar zone. `valuation_year`
states this rule once, in SQL.

A valuation is **current** when all of these are true:

- Its target is the library's published target.
- Its inputs equal the purchase's.
- Its `rate` is null where the purchase needs none: same currency, or
  amount 0.
- Otherwise its `rate` equals the stored `ExchangeRate`.

A corrected rate makes its rows stale. `stale_purchases(library)` answers
the live purchases with an amount and no current valuation.

## The task

`convert_library_prices` values the legacy rows and the valuations for one
version. It publishes both under the state lock, in one transaction. The
publication replaces the library's valuations whole, so a library holds
one target. A changed snapshot or a newer version publishes nothing. A
missing rate fails the run for both sets.

## The request

`request_revaluation(library)` requests a version at the state row's own
target. Two signals call it:

1. The purchase writes, after a dispatch appends `created`,
   `price_changed`, `purchase_corrected` or `restored`. A crash between
   the two transactions loses the request.
2. The daily recovery, for a library at rest with stale purchases. This
   signal also covers a restored catalog parent and any appender outside
   the write path.

A failed request after a committed write is logged, not answered. The
recovery isolates each library and logs each one it requests.

## Reads and API

`with_valuation` annotates the current amount and currency. It reads the
target in the same statement. `PurchaseOut.valuation` is null or
`{amount, currency}`. The value is null without a current valuation.

## Handoffs

- P4 seeds valuations through `publish_valuations`, then requests one run.
- P5 reads valuations through `with_valuation`.
