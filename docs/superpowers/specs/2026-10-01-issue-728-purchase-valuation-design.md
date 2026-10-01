# Purchase valuations in decimals

Issues: [#728](https://github.com/KucharczykL/timetracker/issues/728) and
[#729](https://github.com/KucharczykL/timetracker/issues/729). Member P3 of
the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md),
stacked on [A purchase is refunded](2026-10-01-issue-727-purchase-refund-design.md).
Charter: [Purchase](2026-08-09-timetracker-overhaul-design.md) ("Exchange-rate
conversion is replaceable derived state").

## Scope

P3 gives the `Purchase` projection its money in the reporting currency:

- `ExchangeRate.rate` becomes a decimal.
- `PurchaseValuation` is a new conventional model, one row per purchase and
  target currency. The currency task writes it.
- The per-library run state (`PurchaseConversionState`) stays and governs
  both caches: the legacy float cache that every screen reads until P5, and
  the valuations.
- A purchase write that moves a valuation requests a new version after
  its dispatch; the daily recovery finds every purchase whose valuation is
  missing or out of date, so a lost request costs a day, not a purchase.
- `GET /api/purchases/` answers each purchase's current valuation.

No screen reads a valuation. Two screen effects follow from one run state:
a purchase write raises the "Prices are being converted" toast, as a
legacy edit does today, and a run that fails on the new set (a missing
rate) fails the legacy cache too and raises the failure toast.
`POST /api/purchases/` can record a purchase today, and the rate API
answers no year before 2024 that the table does not already hold, so one
unvaluable purchase stalls the library's legacy cache, as one unvaluable
legacy row does today. P5 drops the legacy half, so the coupling is
accepted for the stack's span.

P5 switches every reader to valuations and drops the float cache,
`needs_price_update`, the legacy half of the task and the legacy `save()`
trigger. #728's body asks to remove `PurchaseConversionState`; the wave
keeps it (§PurchaseValuation), and the wave outranks the body.

## Exchange rates

`ExchangeRate.rate` is `DecimalField(max_digits=24, decimal_places=12)`.
A data migration adds the decimal column, copies each float through
`Decimal(repr(rate))` quantized to twelve places, drops the float column
and renames the new one. PostgreSQL's own float-to-numeric cast keeps 15
significant digits; `repr()` keeps the shortest exact spelling. The
reverse copies `float(rate)` back, so `tests/test_purchase_migrations.py`,
which migrates the chain back to `0025` and forward, runs it both ways.

`games/exchange_rates.py` holds the lookup and the fetch, moved out of
`games/tasks.py`: `exchange_rate(source, target, year) -> Decimal | None`.
The fetch parses the rate API's JSON with `parse_float=Decimal` and
quantizes to twelve places before it stores the row, and it answers the
stored value, so the first run and every later run read one number.
`get_or_create_rate` in `games/models.py` is unused and goes.

Three writers still hand the column a float: `games/fixtures/exchangerates.yaml`
(loaded on `post_migrate` into an empty table), `load_sample_data`'s rate
load, and the sample fixture. `DecimalField.to_python` expands each float
to 24 significant digits, and PostgreSQL rounds it to twelve places on
insert; every rate in both fixtures has twelve places or fewer, so the
stored value equals `repr()`'s. The next anonymizer run writes strings.

The legacy converter reads `round(price * float(rate), 0)`. Its whole-unit
output moves only where the twelve-place quantization crosses a `.5`
boundary.

## PurchaseValuation

| Column | Meaning |
|---|---|
| `id` | UUIDv7 |
| `library` | `UserLibrary`, `CASCADE`, so a purge takes it |
| `purchase_id` | the purchase key; no foreign key, since nothing outside the projections points at a projection row |
| `target_currency` | ISO code |
| `amount` | `Decimal(26, 2)`: the source amount times the rate, multiplied exactly (a local context of 60 digits) and quantized once with `ROUND_HALF_UP` to cents; the width holds `LARGEST_AMOUNT` times the largest rate the column admits |
| `source_amount`, `source_currency` | the purchase's amount and currency the row was computed from |
| `rate_year` | the year whose rate applies |
| `rate` | `Decimal(24, 12)`; null where no rate was read: same currency, or amount 0 |
| `version` | the run version that wrote it |
| `calculated_at` | the publication's instant |

Unique on `(purchase_id, target_currency)`. Publication keeps one target
per library, so the target column is part of the row's identity and the
rate's, never a second row to read. No row exists for an unknown amount.
A free purchase values at 0.

The identity audit lists the table and skips its ordering check: it has
no `created_at`, and every publication mints its rows again.

The rate's identity is `(source_currency, target_currency, rate_year)`.
`rate_year` is the first year the purchased day names: the year of
`purchased_lower`, else of `purchased_upper` (an open start, `../2015`).
An unknown purchased day takes the year of `purchase_recorded_at` in the
library's calendar zone (`calendar_day_zone`), because its price is known
and "no known price" would misreport it; `rate_year` says which year was
read, so nothing is hidden. `valuation_year(zone)` states the rule once as
a database expression (`ExtractYear(..., tzinfo=zone)`), and the task reads
it from the same query, never computing a year in Python.

A valuation is **current** when its row at the library's published target
holds the purchase's amount, currency and rate year, and its `rate` is
null where the purchase's own facts need none (currency equals the target,
or amount 0) and otherwise equals the stored `ExchangeRate` for that
identity. The null branch reads the purchase, never the absence of a rate
row, so a stray same-currency rate row makes nothing out of date. A
corrected rate makes its rows out of date (#493). A calendar zone change
can move a fallback year, and the recovery revalues it.
`stale_purchases(library)` in `games/reads/purchases.py` answers the
library's live purchases (`library_purchases()`, six removal marks) with
an amount and no current valuation.

## The task

`convert_library_prices(library_id, version)` values two sets per version:
the legacy rows, as today, and the live purchases with an amount, read
through `library_purchases()`. Both publish in one transaction under the
state lock, after the version, target and snapshot checks. The snapshot of
the new set is `(id, amount, currency, rate_year)` over that read.

Publication replaces the library's valuations whole: it removes every row
of the library and inserts the new set. So a library holds one target at a
time, and no reader can join a mixed set. The old set stays readable until
that transaction commits. A missing rate fails the run, keeps the old set,
and schedules one retry, as today.

## The request

`request_revaluation(library)` in `games/conversion.py` locks the state
row and requests a version at the row's own `requested_currency`, as the
legacy `save()` does. Reading the target before the lock could undo a
settings change committed in between.

Two signals call it.

1. **The write path.** After a dispatch in `games/writes/purchase.py`
   appends `purchase.created`, `.price_changed`, `.purchase_corrected` or
   `.restored`, the write requests, in its own transaction. A refusal or an
   `Unchanged` requests nothing. This signal is prompt and lossy: a crash
   between the two transactions drops it.
2. **The daily recovery.** `recover_library_price_conversions` enqueues a
   run where `requested > published`, as today. A library at rest
   (`requested == published`) whose `stale_purchases` is not empty is
   requested. This covers a lost request, a removal or restore of a
   catalog parent, which changes what is live without a purchase event,
   and every appender that bypasses the write path, P4's pass included.

`dispatch` gains nothing, and no lock is taken beside the stream head.
The recovery runs only where `schedule_convert_prices` has scheduled it;
the deploy checklist confirms the deployment's schedule row.

`_request_conversion_for_locked_state` refuses a blank target, so a test
that records a purchase seeds the state with a currency.

## Reads and API

`with_valuation(purchases)` in `games/reads/purchases.py` annotates
`valuation_amount` and `valuation_currency` from the current row at the
library's published target. The target is a subquery on the state row in
the same statement, so a publication between two reads cannot pair a row
with another target. An out-of-date row answers null: a PATCH that
changes the amount answers no valuation until the run publishes.
`PurchaseOut` answers `valuation`: null, or `{amount, currency}` with the
amount as a string. POST and PATCH answer it too.

## Fixture

The anonymizer dumps no valuation: it is derived. `load_sample_data`
makes one request after the replay, where the legacy cache is out of date,
a version is pending, or `stale_purchases` is not empty. The committed
fixture holds no purchase event until P4 regenerates it.

## Handoffs

- **P4** seeds valuations from `converted_price`, through the writer this
  member adds, with the legacy whole-unit rounding and inputs that make
  them current; it then requests one run, so the decimal refresh replaces
  them and the reconciliation prints both totals.
- **P5** reads valuations through `with_valuation` and its sums.

## Tests

- Rates: the migration copies through `repr()`; the fetch stores and
  answers a quantized decimal parsed without a float; the three float
  writers load.
- Valuation: same currency, free, unknown amount (no row), cross currency
  rounded half up, open start takes the upper year, unknown day takes the
  recorded year in the calendar zone, removed purchase not valued.
- Publication: whole replacement on a target change; a stale worker, a
  changed snapshot and a missing rate publish nothing and keep the old
  set; legacy and new sets publish together.
- Request: each of the four events requests at the locked row's target; a
  description of kind, name or note does not; a refusal does not.
- Recovery: a library at rest with a missing valuation, a changed amount,
  currency, rate year or stored rate is requested; a current library is
  not; a pending library is enqueued once.
- API: `valuation` null before publication, set after, null once the
  amount changes, another library's never read.
- Two libraries: one library's publication never touches the other's rows.
- Existing tests that change: `tests/test_library_conversion.py` patches
  `tasks._get_exchange_rate` at eight sites and the recovery's
  `async_task`; `tests/test_uuid_identity_audit.py`'s
  `EXPECTED_IDENTITY_TABLES` gains `games_purchasevaluation`;
  `tests/test_purchase_migrations.py` round-trips the new migration.

## Follow-up issues to file

None: P4 and P5 own the handoffs above, recorded on #723 and #724.
