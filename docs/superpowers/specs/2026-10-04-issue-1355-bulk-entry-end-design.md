# End access to many copies at once

Issue #1355, a member of the
[Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).
#1345 declares the device act on the same module.

## The act

`entry.end` (`games/bulk_entry_end.py`) is the first act in the Library
tab's selection tray, because the row menu offers "I no longer have it"
first. The tray button reads **I no longer have them…**. The heading
reads **I no longer have these {count} copies**. The submit reads
**Save**. The done toast is the runner's tally sentence.

The confirmation asks one statement for every row: **What happened**,
**When** and **Note**, as on the per-copy page. What happened starts at
`Not said`. When starts at the library's calendar today. The preview
adds an **Ended** column: the standing end's day, `Unknown` for an end
on no day, `–` for a held copy.

The scope is every live selected copy. There is no held-only base.
`EndEntryAccess` refuses an ended copy with its own sentence, and the
log names it. The `caution` counts the selected copies that hold an end
marker, and says that they will be left as they are.

## The shared statement

`games/bulk_access_end.py` imports no act module. It holds:

- `encode_access_end` and `decode_access_end(raw, ways)` over
  `WayActStatement`. The wire form is JSON `{"when", "way", "note"}`.
  Null `when` is the unknown day. Decode refuses a missing key, a way
  outside `ways`, and a day or note that it cannot read.
- `BulkAccessEndForm`, built from a `ways` tuple. Where `ways` holds
  `EndWay.UNSTATED`, that way leads and is selected. Where it does not
  (`DEVICE_WAYS`), a blank first choice leads, and the required field
  refuses it.
- `access_end_choice(ways)`, the act's `BulkChoice`. The settled
  statement carries the day, so a confirmation posted twice replays one
  payload under one key.

## The Undo

`refuse_unless_this_batch_wrote_it` (`games/bulk_endpoint_undo.py`)
reads a row's events of one endpoint family, in append order:

1. The latest is a void: pass. The void command then answers
   `Unchanged`. This covers a second Undo press and a void by hand.
2. The batch stated no event of the family: refuse.
3. The latest is not the batch's last statement: refuse. This covers a
   resume, a correction and a later end.

Each act gives its two sentences as `UndoSentences`. The guard raises
`CommandRejected`, so the caller wraps it in `answered`. The
playthrough start and completion acts call the same guard.

The inverse voids through `void_entry_access_end`. A removed copy is
refused by `VoidEntryAccessEnd`.

## Known consequence

An Owned copy can end in a batch, and its game purchase can be refunded
after that. The refund writes no end, because one stands. The batch's
Undo then leaves the copy held. The one-click Undo does the same.
