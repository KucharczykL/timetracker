# End access to many copies at once

Issue #1355, a member of the
[Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).
#1345 will declare the device act on the same module.

## The act

`entry.end` (`games/bulk_entry_end.py`) is the first act in the Library
tab's selection tray, because the row menu offers "I no longer have it"
first. The tray button reads **I no longer have them…**. The heading
reads **I no longer have these {count} copies**. The submit reads
**Save**. The toast is the runner's tally.

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
  `WayActStatement`. The wire form is JSON `{"when", "way", "note"}`
  (`AccessEndJson`). Null `when` is the unknown day, and decodes to
  `TemporalValue.unknown()`. Decode refuses a missing or unknown key, a
  way that is no text or is outside `ways`, and a day or note that it
  cannot read.
- `BulkAccessEndForm`, built from a `ways` tuple. Where `ways` holds
  `EndWay.UNSTATED`, that way leads and is selected. Where it does not
  (`DEVICE_WAYS`), a blank first choice leads, and the required field
  refuses it.
- `AccessEndQuestion(ways)`: its `choice()` is the act's `BulkChoice`,
  and its `decode` reads the settled value, so offer and run read one
  way set. The settled
  statement carries the day, so a confirmation posted twice replays one
  payload under one key.

## The Undo

The inverse dispatches `UndoEntryAccessEnd(entry_id, batch_id)`. Its
`build` calls `refuse_unless_this_batch_wrote_it`
(`games/commands/batch_undo.py`) under the stream lock, so no act can
land between the check and the void. The guard reads the row's events
of one endpoint family:

1. The batch wrote no statement of the family: refuse.
2. The batch's last statement is the latest: pass.
3. The latest is a void or a resume: pass. The void then answers
   `Unchanged`. This covers a second Undo press, a void by hand and a
   copy held again.
4. Any other latest act: refuse. This covers a correction and a later
   end.

Each command gives its two sentences as `UndoSentences`.
`UndoPlaythroughStart` and `UndoPlaythroughCompletion` call the same
guard. After the guard, each command voids as its Void command does:
`VoidEntryAccessEnd`'s rules refuse a removed copy, or a copy under a
removed game.

## Known consequence

An Owned copy can end in a batch, and its game purchase can be refunded
after that. The refund writes no end, because one stands. The batch's
Undo then leaves the copy held.
