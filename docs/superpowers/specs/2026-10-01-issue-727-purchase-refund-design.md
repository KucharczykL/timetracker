# A purchase is refunded

Issue: [#727](https://github.com/KucharczykL/timetracker/issues/727).
Member P2 of the
[Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md),
stacked on [The Purchase aggregate](2026-10-01-issue-725-purchase-aggregate-design.md).

## Storage and events

`PURCHASE_REFUND` is a stated endpoint on `Purchase`: `refunded`, its
two bounds, `refund_recorded_at` and `refund_note`. It has no way.
Its events are `library.purchase.refunded`, `.refund_corrected` and
`.refund_voided`.

## Commands

`RefundPurchase`, `CorrectPurchaseRefund` and `VoidPurchaseRefund`
refuse a removed purchase. The statement and the correction also refuse
a copy that a read hides. The void refuses only a removed copy or game.

`RefundPurchase` also ends the copy, way `refunded`, blank note, on the
refund's day. It does this only for kind `game`, on an Owned copy that
states no end. A pass or an upgrade leaves the copy held.

The refund **owns** the copy's end while the latest end-family event of
the copy is a statement or a correction, and its dispatch also appended
a refund statement or correction of this purchase. `coupled_end` in
`games/reads/purchases.py` matches the two on `idempotency_key`. Each
dispatch has one key. `make anonymize-sample` keeps one key for each
dispatch.

- A correction that changes the day also corrects an owned end.
- A void also voids an owned end.
- After an end, a correction or a resume by hand, the copy keeps what
  the person stated.

Day order:

- A refund before the purchase day is refused.
- A refund before the acquired day is refused where an end is appended.
- A purchase day after a standing refund is refused.
- A refunded purchase does not move to another copy.

`RemovePurchase` leaves the copy's end.

## Writes and API

`restate_purchase` takes `refund`: `KEEP` states nothing, `None` voids.
It refuses a reversed final day order before any dispatch. Then it
dispatches in this order:

- A first refund goes after the description, because it reads the
  stated kind and copy.
- A correction goes first, unless its day is before the held purchase
  day.
- A void goes first.

`PATCH /api/purchases/{id}` takes `refund`: `{refunded, note}` or null.
`PurchaseOut` answers the five refund columns.

## Limits

- Two purchases of one copy: a void of the first refund takes back the
  end, even when the second purchase is refunded too.
- P4 writes the refund and the copy's end in one append under one key.
  An end that P4 states first is not the refund's.
- P5 adds the one-click Refund and its Undo.
