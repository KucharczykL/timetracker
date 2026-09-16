# Answering an inconsistent row

Issue [#1057](https://github.com/KucharczykL/timetracker/issues/1057). The
code is in `games/events/dispatch.py`, `games/writes/answers.py` and
`games/commands/scope.py`.

## Two kinds of refusal

A command refuses in one of two ways.

A rule refuses a statement. The person can state something different. The
command raises `CommandRejected` with a sentence. The boundary answers 409 and
logs nothing.

A row refuses a command. The person can state nothing different. The row is
one the ownership audit reports, or one a CHECK constraint forbids, or one that
names a zone this installation's tzdata does not read. The command raises
`RowInconsistent`. The boundary answers 500, says one sentence and logs an
ERROR record with the traceback.

A database refusal is the same defect, reached one step later. The two answers
have the same shape.

## The type

`RowInconsistent` is a subclass of `CommandRejected` in
`games/events/dispatch.py`. It takes a message and no sentence. The message is
for the log. It names the row, the library, and for a foreign reference the
referring model, the field and the library keys. The traceback is the only
log, so the message names everything.

The type is declared beside its parent. The test that classifies every
boundary exception reads that module, and fails until `games/writes/answers.py`
names the type. A class in `games/commands/` is not seen.

## The answer

`answered()` has a clause for `RowInconsistent` before the clause for
`CommandRejected`. Python matches clauses in order; the parent would take the
subclass. The clause calls `logger.exception` and raises `CommandFailed` with
`REFUSED_BY_AN_INCONSISTENT_ROW` at `DEFECT_STATUS`.

The sentence is worded about the reading, not the row:

> This {subject}'s record could not be read, so nothing was changed. The
> problem has been reported.

On the retired-zone branch the row is right and the installation changed. A
sentence that calls the record inconsistent sends an administrator to the wrong
place.

The ERROR record is the whole alert. A view that returns 500 is not an
unhandled exception. Django's request logger and `ADMINS` mail see nothing.
The `games` logger writes to the console and does not propagate.

## The scope guard

`Refusal.raises` is typed `type[CommandRejected]`, and `raised()` passes a
sentence. mypy accepts a subclass there without reading its constructor. A
scope miss is never a defect, so `Refusal.__post_init__` refuses
`RowInconsistent` and its subclasses with a `TypeError` at construction.

## The sites

Four sites raise `RowInconsistent`:

- `_timed_start`, a Timed row with no start or no day zone.
- `_timed_start`, a day zone tzdata does not read.
- `_session_run`, a session naming a run of another library.
- `_refuse_a_foreign_referrer`, a row of another library naming the run.

No site logs by hand. The boundary logs once. A dispatch outside `answered()`
logs nothing and lets the traceback rise.

## What the consumers see

`confirm_and_remove` renders its page at the refusal's status. The API answers
the status with the sentence in `detail`. The HTMX middleware sends the toast
on every status. The session views call `messages.error` and discard the
status; [#958](https://github.com/KucharczykL/timetracker/issues/958) owns
that gap. Repair of the row the log names is
[#908](https://github.com/KucharczykL/timetracker/issues/908).
