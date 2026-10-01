# Every purchase write on the projections: plan

**Goal:** Move every purchase write onto the `Purchase` projection, show
each copy's purchases on Game detail, and retire the legacy purchase
routes.

**Spec:** `docs/superpowers/specs/2026-10-01-issue-724-purchase-writes-design.md`

**Global constraints:**
- No column on any table the 0031 pass reads or writes.
- Iterate with `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS=…`.
- Before each commit: `make format`, `make lint-fix`, `make format-check`,
  `make vale`, each read by exit code.
- Comments ≤ 7 words, no issue refs. Complete-word identifiers.
- Days from `calendar_today`/`request_calendar_today`; tests seed through
  `tests/calendar_days.py`.
- A view that dispatches carries no `@transaction.atomic`; a test POSTing
  through it is `transaction=True`.

---

### Task 1: Copy removal cascades to its purchases

**Files:**
- `games/reads/referrers.py`: `BlockingReferrer` gains `cascades: bool`;
  `on(..., cascades=False)`; `blocking_referrer` skips cascading
  members; `foreign_referrer` unchanged. Drop `PURCHASE_RECORDED`.
- `games/reads/purchases.py`: `live_purchase_ids(library, entry_id)` and
  `cascaded_purchase_ids(library, entry_id)` (removed purchases whose
  latest `purchase.removed` shares the key of the entry's latest
  `libraryentry.removed`; read `LibraryEvent`, scoped by library).
- `games/commands/libraryentry.py`: `RemoveEntry.build` prepends
  `purchase_removed(id)` per live purchase; `RestoreEntry.build` appends
  `purchase_restored(id)` per cascaded id after `libraryentry_restored`.
  Find the event constructors in `games/events/purchase.py`.
- `games/writes/purchase.py`: move `_revalue_after`/`_appended_types` to
  `games/writes/revaluation.py`; call from `restore_entry`
  (`games/writes/libraryentry.py`) and `restore_one_entry`
  (`games/bulk_removal.py`).
- `games/bulk_entries.py`: preview count of purchases per copy
  (annotation on `entry_resolution`, a column in `ENTRY_PREVIEW`).
- Remove confirmation in `games/views/library_entry.py`: `details` lists
  each live purchase (refunded marked).

**Tests:**
- `tests/test_purchase_command.py`: rewrite
  `test_a_live_purchase_keeps_its_copy` → removal takes the purchase;
  restore brings back only cascaded ones (one removed alone first stays
  removed); remove → restore → remove → restore round trip; refunded
  purchase cascades and returns, its copy end untouched.
- `tests/test_libraryentry_command.py`: a cascading throwaway member is
  skipped by `blocking_referrer`, still read by `foreign_referrer`.
- `tests/test_purchase_revaluation.py`: copy restore requests a run.
- `tests/test_bulk_entry_acts.py`: batch remove with a purchase, Undo
  brings it back; preview counts purchases.
- `tests/test_projection_replay_gate.py`: copy with live purchase removed
  and restored; one left removed with its purchase.
- `tests/test_purchase_conversion.py`: `removed_copy` dispatch appends
  exactly one event.

**Gotchas:** `RestorePurchase` refuses under a removed copy, so build
events directly. Unchanged-before-refusal order in both commands must
hold. Replay-gate `missing == 62` stays (no new event type).

### Task 2: Keyed refund write and its readers

**Files:**
- `games/writes/purchase.py`: `refund_purchase(actor, purchase,
  statement: ActStatement, *, correlation_id, idempotency_key) ->
  RefundedPurchase(sequence, copy_end)` over `RefundPurchase`; the
  sequence is the `purchase.refunded` event's, from `dispatched_events`.
- `games/reads/purchases.py`: `latest_refund_act(library, purchase_id)`.
- `games/entry_forms.py`: `page_key(noun, act, token)`,
  `one_click_key(noun, act, token)`; `SubmissionNoun = Literal["copy",
  "purchase"]`; acts gain `"refund"`. Update every caller (copy keys keep
  their spelling `copy-…`).

**Tests:** `tests/test_purchase_refund.py` (or a new
`tests/test_purchase_refund_write.py`): game refund on Owned copy
answers the refund's sequence, not the end's; repeat key replays;
`latest_refund_act` after refund, correction, void.

### Task 3: Price fields and the purchase forms

**Files:**
- `common/components/primitives.py`: `FormFieldPresentation.row_class`;
  `FormFieldGroup` gains a `class_` (or a named group) for the fieldset.
- `games/purchase_forms.py` (new): `PriceChoice` (paid/free/unknown/none),
  `PriceFields` mixin (`price`, `amount`, `currency`, `stated_price()`,
  `price_group()`, `price_presentations()`); currency default
  `resolve_str_for_user(user, "DEFAULT_PURCHASE_CURRENCY")`; keep the
  `x-mask` on currency (moves from `PurchaseForm`).
  `PurchaseAddForm` (kind, name, price, purchased, note, submission),
  `PurchaseEditForm` (kind, name, price, purchased, refund choice + day
  + note, note, `refund_seen`), `refund_seen(purchase)`.
- `games/entry_forms.py`: `EntryAddForm` gains price fields with choices
  paid/free/none, initial paid; `purchase_draft()` or none.

**Tests:** `tests/test_purchase_forms.py` (new): each choice's
`StatedPrice`; hidden-row values ignored; Paid without amount refused;
Free states 0 in the currency; default currency from the setting;
`refund_seen` refuses only a changed refund block; Not refunded with no
refund keeps. Move `tests/test_purchase_defaults.py` and the purchase
cases of `tests/test_user_preference_consumers.py` onto these forms.

### Task 4: Purchase views, routes and returns

**Files:**
- `games/views/purchase.py`: drop legacy add/edit/view/refund/split,
  `_pricing_controls`, `_create_separate_purchases`. New `add_purchase`
  (entry), `edit_purchase`, `remove_purchase`, `restore_purchase`,
  `refund_purchase_now`, `undo_purchase_refund`. Reuse `_form_page`,
  `_one_click`, `_one_click_key` from `library_entry.py` (move the
  shared ones to a small module, e.g. `games/views/copy_pages.py`).
- `games/views/library_entry.py`: `_add` writes `record_purchase` with
  `copy=EntryStatement` when the price choice is not none.
- `games/urls.py`, `games/views/returns.py`: routes and buckets per the
  spec.
- `games/views/game.py`: Add Game button → "Submit & Add to library" to
  `add_library_entry`.
- `games/views/library.py`: drop the "Add purchase" action.
- `games/management/commands/render_pages.py`: drop `view_purchase`.

**Tests:** `tests/test_purchase_pages.py` (new, `transaction=True`):
add on a copy, edit each fact, Not refunded voids, stale refund
refused, remove + Undo, refund now + Undo, Undo overtaken refused, a
key-less press answers 400, a foreign library's purchase 404.
`tests/test_library_entry_pages.py` (existing name, check): Add to
library with Paid/Free/None. Update `tests/test_rendered_pages.py`
(Add Game button), `tests/test_render_pages.py`,
`tests/test_returns_classification.py` expectations,
`tests/test_action_origin_parity.py`, `tests/test_html_validity.py`,
`tests/test_removal_confirmation.py`, `tests/test_restore_routes.py`,
`tests/test_removal_purchases.py`, `tests/test_origin_partials.py`.
Delete `tests/test_purchase_separate_orders.py`; rewrite
`tests/test_game_display_order.py`'s bundle over `record_purchase`.

### Task 5: Menus and Game detail

**Files:**
- `games/views/purchase_menu.py` (new): `purchase_line_words(purchase)`,
  `purchase_items`, `purchase_row_menu`.
- `games/views/entry_menu.py`: `entry_row_menu(entry, origin, csrf,
  *, purchases, size)`: "Add purchase…" and one submenu per purchase.
- `games/views/library_cards.py`: `copy_rows` reads purchases per copy
  (one query, `with_valuation`, unrefunded, live) and renders lines in
  `SummaryRow.detail`.
- `games/views/library_list.py`: prefetch the same purchases for the
  menus.
- `games/views/purchase.py`: Purchases list row menu in `menu_slot`.

**Tests:** `tests/test_library_cards.py` (or the existing Game detail
library tests): lines, hidden refunded, no line without purchase,
foreign currency valuation; menu items and ids; Purchases list menu.
Query-count pin for Game detail if one exists.

### Task 6: Retire the legacy client code

**Files:** delete `ts/add_purchase.ts`, `ts/elements/selection-fields.ts`
(+ test), `SelectionFields` builder/props/export, regenerate
`ts/generated/props.ts` (`make gen-element-types`), drop
`PurchaseForm` from `games/forms.py`, fix `ts/elements/search-select.ts`
comment.

**Tests:** move e2e hosted on legacy pages to surviving pages:
`e2e/test_date_picker_e2e.py`, `e2e/test_touch_targets_e2e.py`,
`e2e/test_search_select_create_e2e.py`, `e2e/test_settings_page_e2e.py`,
`e2e/test_purchase_e2e.py`, `tests/test_date_picker.py`,
`tests/test_library_form_isolation.py`. New e2e: Add to library price
segment shows/hides rows; copy menu Refund with Undo.

### Task 7: render_pages diff, docs sweep, gate

- `make render-pages` at P5a and P5b on one database, attribute every
  difference.
- Docs sweep per the skill: delete this plan, trim the spec to 200–500
  words, CLAUDE.md (LegacyPurchase writes, Purchase writes, Alpine
  masks, cascade on LibraryEntry), comment the open siblings.
- File the follow-up issue; full `make check`; `gh stack submit`.
