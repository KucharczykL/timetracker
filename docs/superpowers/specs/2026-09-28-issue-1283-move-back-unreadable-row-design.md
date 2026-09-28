# A broken session stream is a defect in the move back

Every session stream starts with `created`. A `moved` event with no `created`
or `moved` event before it is a broken stream: the row is wrong, not the
request. The Undo of bulk Edit
([#1310](2026-09-27-issue-1310-bulk-edit-moves-design.md)) answers that as a
defect, as `_earlier` in `games/bulk_session_edit.py` does for the described
facts. It never shows a sentence that the person cannot act on.

## The reads

`run_before` in `games/bulk_move.py` raises `RowUnreadable` when it finds no
run before the batch's `moved` event. The message names the session, its
library, the event type and the sequence. It also raises `RowUnreadable` when
the payload's run is missing or is not a key. Append validation refuses such
a payload. The check follows the rule that `_device_of` follows.

`run_before` still refuses a batch that did not move the session with
`NOT_MOVED_BY_THIS_BATCH`. Edit's Undo asks `moved_by` first, so only a direct
caller meets that refusal.

`_put_back_the_run` takes the session key. It raises `RowUnreadable` when the
library holds no run with the key from the stream. No command deletes a run
or changes its library, so a missing run is drift, as `_session_run` in
`games/commands/playersession.py` treats it. The message names the session,
the run, the library and the batch. The Undo ends on that row, and rows after
it stay where the batch put them.

## The forward move

`_remove_the_emptied_bucket` also calls `run_before`. The batch's own stream
tells which run the move left, also when another request moved the row after
the session was read. `_remove_the_emptied_bucket` wraps the call in
`answered("session")` and catches `CommandRejected` inside it, so a batch that
moved no such row still removes nothing. A broken stream becomes
`CommandFailed` at `DEFECT_STATUS` with an ERROR record, and the batch ends.

The row stays moved, and its bucket stays. The Undo of that batch ends on the
same row, which is the last row the batch moved. The stream cannot tell where
the row was, so no inverse can do better.

## Tests

- `run_before` on a hand-written row that one `move_session` moved raises
  `RowUnreadable`.
- `edit_back` on that row fails with `CommandFailed` at `DEFECT_STATUS`.
- `edit_one` moving a hand-written row out of a bucket fails the same way;
  the row is on the target and the bucket is not removed.
- A move back whose earlier run belongs to another library, set with
  `update()`, fails the same way.
- `test_a_row_moves` uses `a_bucket_session`, which records the stream.
