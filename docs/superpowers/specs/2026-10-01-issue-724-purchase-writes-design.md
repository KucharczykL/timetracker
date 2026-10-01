# Every purchase write on the projections

Issue: [#724](https://github.com/KucharczykL/timetracker/issues/724).
Member P5b of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md),
stacked on P5a ([reads](2026-10-01-issue-735-purchase-reads-design.md)).
P5b2 (the rest of #1266: selectable list, tray, review surface) and P5c
(#736: the legacy model dropped) follow. The wave doc on `main`
(bace11c6) records the rulings below; the stack takes it at its next
rebase.

## Decisions

The user ruled on 2026-10-01:

1. Game detail lists a held copy's live, unrefunded purchases under it.
   A copy with no such purchase shows no line.
2. A purchase's acts sit in the copy's ⋯ menu, one submenu per purchase.
   A purchase line has no menu of its own.
3. A refunded purchase is hidden on Game detail. A refunded `game`
   purchase ends its Owned copy, so that copy leaves anyway.
4. A purchase is added to an existing copy through "Add purchase…" in
   the copy's ⋯ menu. The "Add to library…" page states only the game's
   own purchase; the one-click add states none. The Library page's "Add
   purchase" action goes.

Decided here, with the reason:

- Add to library's purchase states the acquired day as its purchased
  day. One day field; Edit purchase corrects it.
- Paid always states an amount. An unknown price is its own choice,
  "Unknown", on Add purchase and Edit purchase, so a blank box never
  records a fact. Add to library offers Paid, Free and No purchase.
- The segment starts on Paid for the initial access, Owned. A later
  access change does not move it: following it needs script, and a
  Borrowed copy left on Paid is refused for its missing amount.
- No purchase detail page; `view_purchase` goes. Edit purchase is the
  purchase's page.
- Edit purchase does not move a purchase to another copy. The command
  can; no screen asks for it yet.
- Add Game's "Submit & Create Purchase" becomes "Submit & Add to
  library", to the game's Add to library page. The old add page's
  "Submit & Create Session" goes with it.
- The Library tab's Purchases column belongs to P5b2, with the list
  work.

## Forms

`games/purchase_forms.py` holds the purchase forms. `PriceFields` is
the shared part: `price` (a radio segment), `amount`, `currency`. It
answers a `StatedPrice`. Paid needs an amount and a currency; Free is
`0` in the stated currency, as `check_price` and the
`games_purchase_currency_where_amount` CHECK require; Unknown is
`UNKNOWN_PRICE`. The form reads amount and currency only under the
choice that uses them and ignores them otherwise, so a hidden row never
holds an error. The currency defaults to the user's
`DEFAULT_PURCHASE_CURRENCY`, the setting `PurchaseForm` reads today.

The segment, amount and currency render as one `FormFieldGroup`. Its
fieldset carries a named Tailwind group; the amount row shows under
Paid and the currency row under Paid and Free, through a new
`FormFieldPresentation.row_class`. With no CSS, every row shows and the
rule above still holds.

- `EntryAddForm` gains the price fields. No purchase records the entry
  through `record_entry`. Paid or Free dispatches one `RecordPurchase`
  with `copy=EntryStatement`, kind `game`, under the page's submission
  key. Both paths share that key, so a second press never makes a second
  copy; a press that changes path after a success meets the key's
  mismatch answer.
- `PurchaseAddForm`, route `add_purchase` at `library/<entry>/purchase/add`:
  kind, name, price, purchased (default the calendar's day), note.
  `RecordPurchase` with the copy's key, under a submission key.
- `PurchaseEditForm`, route `edit_purchase` at `purchase/<id>/edit`:
  kind, name, price, purchased, refund (Refunded or Not refunded, day,
  note), note. `restate_purchase` states each changed fact in one
  dispatch. Not refunded voids a standing refund and keeps where none
  stands. `refund_seen`, a hash of the refund's marker, day and note as
  `end_seen` is for an end, refuses a submitted refund block that
  differs from the page's while the refund changed since the page
  opened; an edit that leaves the refund block alone passes.

The purchase pages key their presses `purchase-add-<token>` and
`purchase-refund-now-<token>`: `page_key` and `one_click_key` take the
noun beside the act.

## Acts

- Refund now, route `refund_purchase_now` at `purchase/<id>/refund/now`:
  a POST with a submission key states the refund on the calendar's day
  through a new write, `refund_purchase(actor, purchase, statement, *,
  correlation_id, idempotency_key)`. It answers the `purchase.refunded`
  event's own sequence, read from `dispatched_events`, since a `game`
  refund appends the copy's end after it.
- Its Undo, route `undo_purchase_refund` at
  `purchase/<id>/refund/undo/<sequence>`, voids the refund only while
  that event is the purchase's latest refund-family event
  (`latest_refund_act`, new in `games/reads/purchases.py`); else it
  refuses with a sentence. The void takes the copy's end back where
  `refund_owns_the_end` holds, so a resume pressed between leaves the
  copy held.
- The one click keeps the command's refusals: a purchase or acquisition
  dated after today refuses with its sentence on the page.
- Remove: `remove_purchase` is `confirm_and_remove` over the write, its
  Undo `restore_purchase`. Both keep their names, keyed on the
  projection. `LegacyPurchase` stays in `REMOVABLE_MODELS`, with no
  route, until P5c.

## A copy's removal takes its purchases

The wave organizer ruled on 2026-10-01: a purchase has no life its copy
does not, and the refusal left a refunded copy with no reachable
remedy.

- `RemoveEntry` appends `purchase.removed` for each live purchase of the
  copy, then `libraryentry.removed`, in one dispatch.
- `RestoreEntry` appends `libraryentry.restored`, then
  `purchase.restored` for each removed purchase whose latest removal
  shares the idempotency key of the entry's latest removal. Dispatch
  stamps one key on every event it appends. `cascaded_purchase_ids` in
  `games/reads/purchases.py` reads them. A purchase removed on its own
  earlier stays removed. The restored events are built directly, since
  `RestorePurchase` refuses under the copy the same dispatch restores.
- `restore_entry` and the bulk inverse request a revaluation after an
  appended `purchase.restored`. `_revalue_after` moves to a module both
  writes import.
- The conversion's `_remove` keeps its two keys, `removed` and
  `removed_copy`, for key stability: its purchase is gone before the
  copy, so the copy's dispatch appends one event. A test holds that.
  A legacy-removed copy restored by hand leaves its purchase removed.
- `BlockingReferrer.on` takes `cascades=True` for `Purchase.entry`.
  `blocking_referrer` skips a cascading member; `foreign_referrer`
  still reads it, so another library's purchase naming the copy stays
  `RowUnreadable`. `PURCHASE_RECORDED` goes.
- The copy's confirmation names each purchase it takes, a refunded one
  marked so. The bulk `entry.remove` preview counts them through an
  annotation on `entry_resolution`. Its Undo runs `RestoreEntry`,
  so it brings them back.
- `RemovePurchase` alone leaves the copy.

## Routes

`games/views/returns.py`: `add_purchase`, `edit_purchase` and
`remove_purchase` are origin-aware; `refund_purchase_now`,
`undo_purchase_refund` and `restore_purchase` are in place.
`add_purchase_for_game`, `view_purchase`, `refund_purchase` and
`split_purchase` leave the table.

## Menus

`games/views/purchase_menu.py`:

- `purchase_items(purchase, origin, csrf_token)`: "Edit purchase…",
  "Refund" (unrefunded only, one click, "Dated today"), "Remove
  purchase…". The item names say purchase, since they share a menu
  with the copy's own Edit and Remove.
- `purchase_row_menu`: the Purchases list's row menu over those items,
  in the `menu_slot` column beside the column picker.
- `entry_row_menu` takes the copy's purchases. It adds "Add purchase…"
  and one `DropdownSubmenuItem` per live, unrefunded purchase, id
  `entry-menu-<entry>-purchase-<purchase>`, labelled as its line reads.

## Game detail

`copy_rows` reads each held copy's live, unrefunded purchases in one
query through `with_valuation`, ordered by purchased day, then
creation. Each copy row's `detail` lists them, one line each: "Bought"
or the kind and name, the purchased day, and `PurchaseAmount`. The
Library tab prefetches the same read for its menus.

## Retired

- Routes `add_purchase_for_game`, `view_purchase`, `split_purchase`,
  the legacy `refund_purchase`, and the legacy views behind
  `add_purchase` and `edit_purchase`.
- `PurchaseForm`, `ts/add_purchase.ts`, the per-game pricing controls,
  and `SelectionFields` with its element, props, export, generated type
  and e2e harness page.
- `render_pages` drops its `view_purchase` branch.
- The legacy route tests go. Tests that only host a shared widget on the
  legacy pages move to a surviving page: the date picker, touch target,
  platform create row, HTML validity and origin parity tests. The
  currency-default tests move to the new forms.
- The removal tests built on `LegacyPurchase` move to the projection.

## Verification

Focused tests per form, act and menu. The refund Undo test uses a
`game` purchase on an Owned copy. `test_a_live_purchase_keeps_its_copy`
becomes the cascade test; the registry test gets a cascading member
apart from Purchase; the bulk removal Undo test carries a purchase and
one removed alone before the batch. The replay gate removes and
restores a copy with a live purchase, and leaves one removed with its
purchase. `tests/test_game_display_order.py` builds its bundle through
`record_purchase`. E2e covers the Add to library segment
and the copy menu's Refund with Undo. `render_pages` diff at P5a and
P5b, each differing file attributed. Full `make check`.

## Follow-up issues to file

- Move a purchase to another copy from Edit purchase.
