# P2: a purchase is refunded — plan

Spec: `docs/superpowers/specs/2026-10-01-issue-727-purchase-refund-design.md`.
Branch `claude/issue-727-purchase-refund`, stacked on P1 (#1403) with
`gh stack`. Iterate with focused `make test ARGS=…` under the shared lock.

## 1. Columns, endpoint, migration

- `games/models.py`: `PURCHASE_REFUND_COLUMNS = EndpointColumns(name="refund",
  model_label="games.Purchase", when="refunded", lower="refunded_lower",
  upper="refunded_upper", marker="refund_recorded_at", note="refund_note")`;
  declare the fields on `Purchase` the way `PURCHASE_DAY_COLUMNS` /
  `ENTRY_ACCESS_END_COLUMNS` are declared (`games/endpoint_fields.py`
  helper); `*endpoint_constraints(...)` for symmetry (returns `()`).
- `make makemigrations ARGS="games --name purchase_refund"` → `0028`.
- `games/events/purchase.py`: `PurchaseRefundVoidedPayload` (empty,
  `STRICT_SCHEMA`), `PURCHASE_REFUND_EVENTS = endpoint_events("purchase",
  stated="library.purchase.refunded", corrected=".refund_corrected",
  voided=".refund_voided", payload=EndpointPayload, voided_payload=…)`
  and aliases `PURCHASE_REFUNDED` etc.
- `games/endpoints.py`: `PURCHASE_REFUND = Endpoint.over(...)`, add to
  `ENDPOINTS` (E014 and `tests/test_endpoint_primitive.py` pick it up).
- Projector `Purchases`: three handlers via `project_stated`,
  `project_corrected`, `project_voided`.

Tests: `tests/test_purchase_storage.py` (columns, generated bounds),
`tests/test_purchase_migrations.py` if it pins the leaf.

## 2. Reader `coupled_end`

`games/reads/purchases.py`: `coupled_end(library, purchase) -> LibraryEvent | None`
— `latest_end_act(library, purchase.entry_id)`; None unless its type is
the end's `stated`/`corrected`; then `exists()` an event with
`library`, `aggregate_id=purchase.pk`, `event_type in (refunded,
refund_corrected)`, `idempotency_key=end.idempotency_key`. Query through
`(library, aggregate_id)` index. Returns the end event (P5's Undo reads it).

## 3. Commands (`games/commands/purchase.py`)

- `CommandName`: `PURCHASE_REFUND`, `PURCHASE_CORRECT_REFUND`,
  `PURCHASE_VOID_REFUND` in `games/events/dispatch.py`.
- Sentences: `REFUND_BEFORE_PURCHASE`, `REFUND_BEFORE_ACQUISITION`
  ("…Correct the copy's acquired day first…"), `PURCHASE_AFTER_REFUND`,
  `MOVE_A_REFUNDED_PURCHASE` ("Take the refund back before moving it to
  another copy."); `_refund_sentences(purchase_id) -> EndpointSentences`.
- `_end_is_due(purchase) -> bool`: `kind == "game"`, entry access
  `owned`, `stated(entry, ENTRY_ACCESS_END) is None`.
- `RefundPurchase(purchase_id, statement: ActStatement)`: `check_note`;
  `state_endpoint(..., before_event=…)` where before_event refuses a live
  act and the two day orders (acquired only if end due). If the result is
  events and the end is due, append `ENTRY_ACCESS_END_EVENTS.stated.new(
  aggregate_id=entry.pk, effective_time=when, payload={"way": "refunded",
  "note": ""})`. Unchanged passes through.
- `CorrectPurchaseRefund`: `correct_endpoint`; owned = `coupled_end(...)`
  read before building; day order (acquired only if owned and day
  changes); append `access_end_corrected` (way refunded, blank note) when
  owned and `when != purchase.refunded`.
- `VoidPurchaseRefund`: `void_endpoint(before_event=_refuse_under_a_removed_copy
  + removed purchase)`; append `access_end_voided` (payload `{}`) when owned.
- `DescribePurchase`: refuse `entry_id` move while `stated(purchase,
  PURCHASE_REFUND)`; refuse `purchased` correction certainly after a
  standing refund (inside `_day_correction`'s before_event).
- `context.library` for the reader: check `CommandContext` field name.

Tests in `tests/test_purchase_command.py` (new `tests/test_purchase_refund.py`
if the file passes ~1500 lines):
- refund appends refunded + coupled end (game, owned, unended);
- no end for season_pass/upgrade, borrowed copy, already-ended copy;
- repeat same statement → Unchanged; different → refused already stated;
- refund before purchase day refused; before acquired refused only when due
  (passes on borrowed copy);
- correction moves the end when owned; note-only correction appends no end
  and ownership survives (later void takes end back);
- correction after hand correction of the end appends no end;
- void takes end back when owned; leaves hand end, resumed copy, hand
  re-end; void with nothing → Unchanged;
- void under a removed Release passes; refund under one refused;
- refunded→voided→refunded couples afresh;
- kind changed to season_pass after coupled refund: void still takes end;
- move refused while refunded; purchase-day correction after refund refused;
- remove refunded purchase leaves the end;
- two-library: another library's purchase key → 404.

## 4. Writes (`games/writes/purchase.py`)

`restate_purchase(..., refund: ActStatement | None | Keep = KEEP)`:
- `_refuse_a_reversed_draft(purchase, purchased, refund, kind, entry)`
  before dispatch: final purchase day vs final refund day; final refund
  vs target copy's acquired day where an end would be due (target via
  `library_entries(library).filter(pk=entry_id).first()`; None → skip).
- order: void first; else refund first unless (refund day certainly before
  `purchase.purchased`) or `kind`/`entry_id` stated → description first.
- returns whether anything appended; one correlation.
- `refund_purchase`, `correct_purchase_refund`, `void_purchase_refund`
  thin helpers only if a caller needs them (API does not — skip).

Tests: `tests/test_purchase_writes.py` or the command file: ordering
cases from spec (both days forward, both back, kind+refund, move+refund,
void+move), refused body appends nothing.

## 5. API (`games/api.py`)

- `PurchaseRefundIn {refunded: StatedTemporal = None, note: str = ""}`,
  `extra="forbid"`, `.statement() -> ActStatement`.
- `PurchaseUpdate.refund: PurchaseRefundIn | None = None` +
  `refund_statement() -> ActStatement | None | Keep`.
- `PurchaseOut`: `refunded`, `refunded_lower`, `refunded_upper`,
  `refund_recorded_at`, `refund_note`.

Tests `tests/test_purchases_api.py`: PATCH refund object 200 + columns +
entry ended; null voids; absent keeps; refund before purchase 409;
unknown key in refund 422.

## 6. Anonymizer

`games/management/commands/anonymize_sample.py`: map each original key
to `f"sample:{first sequence}"` (events sorted by sequence; dict old→new).
Test: events of one dispatch share one key, two dispatches differ.
Regenerating the fixture is not needed (keys only).

## 7. Pinned lists

- `tests/test_projection_replay_gate.py`: stream gains refund, correction
  (owned → coupled correction), void; `missing` count +3 (59 → 62? read).
- `tests/test_endpoint_fingerprints.py`: three digests.
- grep tests for `PURCHASE_DAY`/`purchase_corrected`/`CommandName` lists
  (`test_command_answers`, isolation, rebuild tuples, PINNED_DEFAULTS).

## 8. Docs

CLAUDE.md Purchase entry (refund, coupled end, PATCH no longer one
dispatch), endpoint paragraph (five stated endpoints → list), API bullet;
P1 spec "A PATCH is one dispatch" → describe + refund; wave doc P2 notes;
comment on #728/#723/#724 siblings as needed.

## Gotchas

- `state_endpoint` answers Unchanged before `before_event` — keep coupling
  outside the helper, after it returns events.
- `EndpointPayload` note is plain `str`; anonymizer blanks top-level note.
- Events appended in one dispatch for two aggregates: purchase first,
  entry end second (P5's Undo keys on the sequence the press appended).
- Replay gate's emptying runs under `purging_library()`.
