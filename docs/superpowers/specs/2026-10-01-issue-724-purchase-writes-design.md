# Every purchase write on the projections

Issue: [#724](https://github.com/KucharczykL/timetracker/issues/724).
Member P5b of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## Forms

`PriceFields` (`games/price_fields.py`) states a price with a segment:
Paid, Free, Unknown, or No purchase. Paid needs an amount and a
currency. Free is `0` in a currency. Unknown is `UNKNOWN_PRICE`. The form
reads amount and currency only under the choice that uses them, so a
hidden row holds no error. The currency defaults to
`DEFAULT_PURCHASE_CURRENCY`.

The rows show and hide through a named Tailwind group:
`FormFieldGroup.class_` names it, `FormFieldPresentation.row_class`
reads it. The class strings are literal, so Tailwind finds them. Without
CSS, every row shows and the rules still hold.

- Add to library offers Paid, Free and No purchase, and starts on Paid.
  Paid or Free records the copy through `RecordPurchase` with an
  `EntryStatement`, kind `game`, on the acquired day. Both paths share the
  page key.
- Add purchase (`games/purchase_forms.py`) states one purchase of a held
  copy. Edit purchase restates each changed fact in one dispatch, with
  no submission key. Not refunded voids a standing refund. A refund
  block left as the page showed it states nothing. A changed block is
  refused when the refund moved since the page opened.

## Acts

- Refund is one click, dated the calendar's day, keyed
  `purchase-refund-now-<token>`. `refund_purchase` answers the sequence of
  `purchase.refunded`, because a `game` refund appends the copy's end
  after it.
- Its Undo voids the refund only while that event is the purchase's
  latest refund act. `UndoPurchaseRefund` checks this
  under the stream lock.
- A refund toast says what the act did to the copy.
- Remove confirms and offers Undo. The fallback is Game detail.

## A copy's removal takes its purchases

- `RemoveEntry` appends `purchase.removed` for each unremoved purchase,
  then `libraryentry.removed`, in one dispatch.
- `RestoreEntry` appends `libraryentry.restored`, then
  `purchase.restored` for each purchase whose latest removal has the
  idempotency key of the copy's latest removal (`cascaded_purchase_ids`).
  A purchase removed alone stays removed.
- `CASCADING_REFERRERS` holds `Purchase.entry`. `blocking_referrer`
  does not read it; `foreign_referrer` does.
- A copy restore requests a revaluation.

## Screens

- Game detail lists each held copy's live, unrefunded purchases under it,
  with the valuation.
- The copy's menu has "Add purchase…" and one submenu for each such
  purchase: "Edit purchase…", "Refund", "Remove purchase…". The Purchases
  list rows have the same items.
- Add Game's second submit opens Add to library. The "Submit & Create
  Session" button is gone.
- The legacy add, edit, view, refund and split routes, `PurchaseForm`,
  `ts/add_purchase.ts` and `SelectionFields` are gone.

## Follow-up issues

- #1437: move a purchase to another copy from Edit purchase.
