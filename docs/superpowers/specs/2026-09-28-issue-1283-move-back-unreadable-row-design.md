# A broken session stream is a defect in the move back

Every session stream starts with `created`. A `moved` event with no `created`
or `moved` event before it is a broken stream: the row is wrong, not the
request. The Undo of bulk Edit
([#1310](2026-09-27-issue-1310-bulk-edit-moves-design.md)) answers that as a
defect, as it does for a broken stream of the described facts. It never shows
a sentence that the person cannot act on.

## The reads

`run_before` in `games/bulk_move.py` raises `RowUnreadable` when it finds no
run before the batch's `moved` event. The message names the session, its
library, the event type and the sequence. It also raises `RowUnreadable` when
the payload's run is missing or is not a key. Append validation refuses such a
payload, so this check is a backstop.

`run_before` still refuses a batch that did not move the session with
`NOT_MOVED_BY_THIS_BATCH`. Edit's Undo asks `moved_by` first, so only a direct
caller meets that refusal.

The move back raises `RowUnreadable` when the library holds no run with the
key from the stream. No command deletes a run or changes its library, so a
missing run is drift, as the session commands treat a session that names such
a run. The message names the session, the run, the library and the batch. The
Undo ends on that row, and rows after it stay where the batch put them.

## The forward move

The forward move also calls `run_before`, inside `answered("session")`, after
the move answers moved. The batch's own stream tells which run the move left.
A replayed chunk finds the row on the target already, and a row read before
the move can be stale, so the row cannot tell. A broken stream becomes
`CommandFailed` at `DEFECT_STATUS` with an ERROR record, and the batch ends.

The row stays moved, and its bucket stays. Remove the bucket by hand. The Undo
of that batch ends on the same row, which is the last row the batch moved. The
stream cannot tell where the row was, so no inverse can do better.

## Tests

- `run_before` on a hand-written row that one `move_session` moved raises
  `RowUnreadable`.
- `edit_back` on that row fails with `CommandFailed` at `DEFECT_STATUS`.
- `edit_one` moving a hand-written row out of a bucket fails the same way;
  the row is on the target and the bucket is not removed.
- A move back whose earlier run belongs to another library, set with
  `update()`, fails the same way.
- `run_before` on a stream whose run is missing or not a key raises
  `RowUnreadable`.
