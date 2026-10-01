# P3 plan: Purchase valuations in decimals

Spec: [2026-10-01-issue-728-purchase-valuation-design.md](../specs/2026-10-01-issue-728-purchase-valuation-design.md).
Branch `claude/issue-728-purchase-valuation`, stacked on #1408. Inline, TDD.
Every pytest run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS=…`.

## Task 1 — decimal rates

Files: `games/models.py` (`ExchangeRate.rate`, drop `get_or_create_rate`),
`games/migrations/0029_exchangerate_decimal_rate.py`, new
`games/exchange_rates.py`, `games/tasks.py`.

- Migration: `AddField rate_decimal` (nullable) → `RunPython(copy_forward,
  copy_backward)` → `RemoveField rate` → `RenameField` → `AlterField` to
  non-null. Forward: `Decimal(repr(row.rate)).quantize(Decimal("1e-12"))`;
  backward: `float(row.rate)`. Write by hand; check `makemigrations --check`
  agrees afterward.
- `RATE_PLACES = Decimal("1e-12")` beside the model, or derive from the
  field's `decimal_places`.
- `exchange_rate(source, target, year) -> Decimal | None`: stored row, else
  fetch (`response.json(parse_float=Decimal)` — `requests` passes kwargs to
  `json.loads`), quantize, `create`, answer the quantized value. Keep the
  log lines.
- Legacy converter: `round(purchase.price * float(rate), 0)`.
- `tasks._get_exchange_rate` goes; tests patch `exchange_rates.exchange_rate`
  through the name the task imports (`tasks.exchange_rate`), eight sites.

Tests: `tests/test_exchange_rates.py` — migration copy helpers on a float
with many digits; fetch stores a quantized decimal with a mocked response
whose JSON text has 18 digits; the answer equals the stored row; missing
currency answers None; request error answers None. Existing:
`tests/test_purchase_migrations.py` round trip passes.

## Task 2 — PurchaseValuation model

Files: `games/models.py`, migration `0030_purchasevaluation.py`,
`tests/test_uuid_identity_audit.py` (`EXPECTED_IDENTITY_TABLES`).

- Fields per the spec table. `id = UUIDv7Field(primary_key=True,
  editable=False)` as `UserLibrary` does. `source_currency`,
  `target_currency` `CharField(max_length=3)`. `rate_year
  PositiveSmallIntegerField`. `version PositiveBigIntegerField`.
- `UniqueConstraint(fields=("purchase_id", "target_currency"),
  name="games_purchasevaluation_one_per_target")`; index on `library`
  comes with the FK.
- Gotcha: the nullable-string test and `CHECK`s — add `CHECK amount >= 0`,
  `source_amount >= 0`; no nullable strings.

## Task 3 — the valuation rule (reads)

File `games/reads/purchases.py` (or new `games/reads/valuations.py`, decide
by size; `purchases.py` already imports the read scope).

- `valuation_year(zone: ZoneInfo) -> Func`: `Coalesce(ExtractYear(
  "purchased_lower"), ExtractYear("purchased_upper"),
  ExtractYear("purchase_recorded_at", tzinfo=zone))`.
- `valued_purchases(library)`: `library_purchases(library)
  .filter(amount__isnull=False).annotate(rate_year=valuation_year(
  calendar_day_zone(library)))`, ordered by `id`. The task and the stale
  read share it.
- `current_valuation(library)`: `PurchaseValuation` filtered on
  `purchase_id=OuterRef("pk")`, `library`, `target_currency=Subquery(state
  published_currency)`, `source_amount=OuterRef("amount")`,
  `source_currency=OuterRef("currency")`, `rate_year=OuterRef("rate_year")`,
  and the rate rule: `Q(rate__isnull=True) & (Q(source_currency=target) |
  Q(source_amount=0))` or `rate = Subquery(ExchangeRate by identity)`.
  Write the identity subquery with `OuterRef` on the valuation's own
  columns.
- `stale_purchases(library)`: `valued_purchases(library).filter(~Exists(
  current_valuation(library)))`.
- `with_valuation(purchases, library)`: annotate `rate_year`, then
  `valuation_amount`/`valuation_currency` from `current_valuation`.

Tests `tests/test_purchase_valuation.py`: year rule (lower, open start →
upper, unknown → recorded year in the calendar zone, New Year's Eve case
with a zone east of UTC); stale for each changed input (amount, currency,
year, stored rate corrected); current with null rate for same currency
and for free, even beside a stray same-currency rate row; removed purchase
not in `valued_purchases`; another library's valuation never current.

## Task 4 — the task values and publishes both sets

Files `games/tasks.py`, new `games/valuations.py` (the writer).

- `games/valuations.py`: `ValuationInput(purchase_id, amount, currency,
  rate_year)`, `value(input, target, rate) -> PurchaseValuation` (unsaved;
  `localcontext(prec=60)`, `quantize(Decimal("0.01"), ROUND_HALF_UP)`),
  `publish_valuations(library, valuations)` — `delete` the library's rows,
  `bulk_create`. Caller holds the transaction and the state lock.
- In `convert_library_prices`: after the legacy snapshot, read
  `valued_purchases(library).values_list("id", "amount", "currency",
  "rate_year")` as the new snapshot; compute rows (rate via
  `exchange_rate`, skip the lookup where same currency or 0); inside the
  publish transaction compare both snapshots, then legacy `bulk_update`
  and `publish_valuations`, then the state.
- `calculated_at = now()` once per publication; `version = requested_version`.

Tests (extend `tests/test_purchase_valuation.py`, reuse the
`test_library_conversion.py` fixtures/helpers where importable): cross
currency half up; same currency and free publish without a rate; unknown
amount no row; target change replaces whole (no old-target row left);
changed purchase snapshot publishes nothing; stale worker publishes
nothing; missing rate keeps the old set and the legacy cache; two
libraries isolated.

## Task 5 — the requests

Files `games/conversion.py`, `games/writes/purchase.py`, `games/tasks.py`
(recovery), `games/management/commands/load_sample_data.py`.

- `request_revaluation(library) -> int`: `atomic`, `select_for_update`,
  `_request_conversion_for_locked_state(state, state.requested_currency)`.
- `VALUATION_EVENTS = frozenset({created, price_changed,
  purchase_corrected, restored})` event types in `games/writes/purchase.py`.
  After `record_purchase`, `restate_purchase`, `restore_purchase`: when the
  outcome is APPENDED and `dispatched_events` holds one of them →
  `request_revaluation(actor.library)`. `record_purchase` already reads the
  events; `restate_purchase` reads them in `_copy_end_of` — read once, pass
  the types to both.
- Recovery: after the existing loop, for each state at rest
  (`requested_version == published_version`) whose library has
  `stale_purchases(...).exists()` → `request_revaluation`. Iterate libraries
  with `keyset_pages` or a plain list (few libraries); no `.iterator()`.
- `load_sample_data`: move the request after the replay; one call when the
  legacy mismatch, a pending version, or stale purchases hold.

Tests: each of the four events bumps `requested_version` once; a
description of kind/name/note does not; a refusal does not; the request
keeps a target another transaction committed; recovery requests a stale
library at rest, ignores a current one, enqueues a pending one once.
Recovery tests patch `conversion.async_task` too.

## Task 6 — API

File `games/api.py`.

- `ValuationOut(Schema)`: `amount: str`, `currency: str`.
- `PurchaseOut.valuation: ValuationOut | None` via a resolver reading the
  two annotations (`resolve_valuation`).
- `readable_purchases` → wrap with `with_valuation` at the routes (list,
  get, `_written_purchase`).

Tests in `tests/test_purchases_api.py`: null before publication; set after
(string amount); null after a PATCH changes the amount; another library's
row never read.

## Task 7 — docs sweep, gate, PR

Delete this plan; spec timeless; CLAUDE.md (ExchangeRate line, Purchase
entry, background tasks paragraph, API bullet); wave doc section and
sibling comments (#723: P4 seeding handoff; #724: P5 readers);
`make check` once; draft PR via `gh stack submit`.

## Gotchas

- `make makemigrations` names: pass `ARGS="games --name …"`; hand-written
  RunPython migration first, then check the autodetector is clean.
- `Decimal` vs `float` in tests comparing `converted_price` — the legacy
  cache stays float.
- `ExtractYear(tzinfo=…)` needs `USE_TZ`; `purchased_lower` is a
  `DateField`, so no tzinfo there.
- `bulk_create` then `bulk_update` inside one atomic block; the unique
  constraint holds because the delete runs first in the same transaction.
- `_request_conversion_for_locked_state` refuses a blank currency: seed the
  state with one in new tests.
- Never `localdate()`; the year rule reads the calendar zone only.
