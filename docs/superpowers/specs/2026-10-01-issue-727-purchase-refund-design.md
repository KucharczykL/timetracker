# A purchase is refunded

Issue: [#727](https://github.com/KucharczykL/timetracker/issues/727).
Member P2 of the
[Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md),
stacked on [The Purchase aggregate](2026-10-01-issue-725-purchase-aggregate-design.md).

## Purpose

A refund is a stated endpoint on a purchase. A refund of a game also
ends the access to the owned copy, in the same dispatch. No screen states a
refund until P5; the API does.

## Storage

Migration 0028 adds the stated endpoint `PURCHASE_REFUND`
(`PURCHASE_REFUND_COLUMNS` beside `PURCHASE_DAY_COLUMNS`, in `ENDPOINTS`)
to `Purchase`: `refunded`, `refunded_lower`, `refunded_upper`,
`refund_recorded_at`, `refund_note`. It has no way, so no `CHECK`
holds the columns together, as on a playthrough's endpoints.

## Events

`library.purchase.refunded`, `.refund_corrected` and `.refund_voided`,
built by `endpoint_events`. The statement and correction carry
`EndpointPayload`; the void carries the empty
`PurchaseRefundVoidedPayload`. The day is the envelope's `effective_time`. The `Purchases` projector writes them
through `project_stated`, `project_corrected` and `project_voided`.

## Commands

`RefundPurchase`, `CorrectPurchaseRefund` and `VoidPurchaseRefund` in
`games/commands/purchase.py` call `state_endpoint`, `correct_endpoint`
and `void_endpoint`. The statement and the correction refuse a removed
purchase and a copy that a read hides, as `DescribePurchase` does. The
void refuses only a removed purchase, copy or game, as
`VoidEntryAccessEnd` does, so a later removed Release never blocks an
Undo.

The **coupled end** is a `libraryentry.access_ended` event with way
`refunded` and a blank note, dated by the refund. `RefundPurchase`
appends it when the purchase is of kind `game` and its copy is Owned
and states no end. A pass or an upgrade names the base game's copy, so
its refund leaves the copy held. Every other refund appends nothing on
the copy.

The refund **owns** the copy's end when two things hold: the copy's
latest end-family event (`latest_end_act`) is an end statement or a
correction, and the dispatch that appended it also appended a
`refunded` or `refund_corrected` event of this purchase. `coupled_end`
in `games/reads/purchases.py` matches the two events on
`LibraryEvent.idempotency_key`. This needs one key for each dispatch.
`idempotent_append` holds it. `make anonymize-sample` rewrites each key
to `sample:{first sequence}` of its dispatch, so it holds it too. A
future direct appender must hold it. Ownership is read from the stream,
never from the present kind or access of the rows.

- `CorrectPurchaseRefund` also appends `access_end_corrected` (way
  `refunded`, the new day, a blank note) where the refund owns the end
  and the day changes. A note-only correction appends nothing on the
  copy, and the refund keeps the end.
- `VoidPurchaseRefund` also appends `access_end_voided` where the refund
  owns the end.
- An end, a correction or a resume stated by hand is not the refund's.
  After one, the copy keeps what the person stated, and a refund void
  can leave an end of way `refunded` without a refund.

Day order, through `certainly_reversed`:

- A refund or its correction certainly before the purchase day is
  refused.
- A refund or its correction certainly before the copy's acquired day is
  refused where the command appends an end event for the copy. The
  command never appends the refund and skips the end.
- `DescribePurchase` refuses a purchase-day correction certainly after
  a standing refund.

`DescribePurchase` refuses a move to another copy while a refund
stands, so a coupled end always lies on `purchase.entry`.
`RemovePurchase` leaves the copy's end where it is.

## Writes and API

`restate_purchase` dispatches the description and the refund act that
`endpoint_move` chooses, under one correlation. A void goes first. A
refund statement goes first, as an entry's end does, unless its new day
is certainly before the purchase day that the row holds, or the body
states `kind` or moves the purchase to another copy; then the
description goes first. The coupling then reads the stated kind and the
target copy. Before any dispatch, the
write refuses a reversed order of the stated days, the purchase day,
and the acquired day where an end is due. On a move it reads the target
copy through `library_entries`; a copy that read does not find is left
to the command's 404. A void always dispatches.

`PATCH /api/purchases/{id}` takes `refund`: `{refunded, note}` states or
corrects the refund, `null` voids it, an absent key states nothing.
`PurchaseOut` answers the five refund columns.

## Verification

The replay gate's stream carries the three refund events and the
coupled end, correction and void. Each new command has a fingerprint
test. `tests/test_anonymize_sample.py` holds one key for each dispatch.

## Limits

- Two purchases of one copy: a void of the first refund takes back the
  end even when the second purchase is refunded too, because the second
  refund appended nothing on the copy.
- A refund that appended nothing still blocks a move to another copy.
- P4 converts a refunded Owned copy unended and lets `RefundPurchase`
  state the end. An end that P4 stated first is not the refund's.
- P5 adds the row menu's one-click Refund and its sequence-keyed Undo.
