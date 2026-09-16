# Answering an unreadable row

Issue [#1057](https://github.com/KucharczykL/timetracker/issues/1057). The
code is in `games/events/dispatch.py` and `games/writes/answers.py`.

## Two kinds of refusal

A command refuses in one of two ways.

A rule refuses a statement. The person can state something different. The
command raises `CommandRejected` with a sentence. The boundary answers 409. It
logs a WARNING only when the rejection states no sentence.

A row refuses a command. The person can state nothing different. The row is
one the ownership audit reports, or one a CHECK constraint forbids, or one that
names a zone this installation's tzdata does not read. The command raises
`RowUnreadable`. The boundary answers 500, says one sentence and logs one ERROR
record with the traceback.

A database refusal is the same defect, reached one step later. The two answers
have the same shape.

## The type

`RowUnreadable` is a sibling of `CommandRejected` in
`games/events/dispatch.py`, not a subclass. It takes a message and no
sentence. Nothing that handles a rule may take it: no `except
CommandRejected`, no `pytest.raises(CommandRejected)`. `Refusal.raises` is
typed `type[CommandRejected]`, so mypy refuses a scope miss that names it.

The message is for the log. It names the row, the library, and for a foreign
reference the referring model, the field and the library keys. The record is
the only log, so the message names everything.

The type is declared in the dispatch module. The test that classifies every
boundary exception reads that module, and fails until `games/writes/answers.py`
names the type. A class in `games/commands/` is not seen.

## The answer

`answered()` has a clause for `RowUnreadable`. The clause writes one ERROR
record whose message carries the argument and whose `exc_info` carries the
traceback, then raises `CommandFailed` with `REFUSED_BY_AN_UNREADABLE_ROW` at
`DEFECT_STATUS`.

The sentence is worded about the reading, not the row:

> This {subject}'s record could not be read, so nothing was changed. The
> problem has been reported.

On the retired-zone branch the row is right and the installation changed. A
sentence that calls the record inconsistent tells the person the wrong thing.

The `games` record is the alert. Django's request logger writes a second line
for the 500 response, with no traceback. This project's logging attaches no
`mail_admins` handler, and the `games` logger does not propagate.

## The sites

Four sites raise `RowUnreadable`:

- `_timed_start`, a Timed row with no start or no day zone.
- `_timed_start`, a day zone tzdata does not read.
- `_session_run`, a session naming a run of another library.
- `_refuse_a_foreign_referrer`, a row of another library naming the run.

`_session_run` wraps a scope miss. It catches `PlaythroughNotHeld`, the class
`library_playthrough` refuses with, and not `CommandRejected`. A rule added to
that resolve later keeps its sentence.

No site logs by hand. The boundary logs once. A dispatch outside `answered()`
logs nothing and lets the traceback rise.

## What the consumers see

`confirm_and_remove` renders its page at the refusal's status. The API answers
the status with the sentence in `detail`. The HTMX middleware sends the toast
on every status that is not a redirect. The session views call
`messages.error` and discard the status;
[#958](https://github.com/KucharczykL/timetracker/issues/958) owns that gap.
Repair of the row the log names is
[#908](https://github.com/KucharczykL/timetracker/issues/908).

Two tests drive a foreign session through the real stack: the removal
confirmation answers 500 with the sentence and one `games` record, and
`DELETE /api/playthrough/{id}` answers 500 with the sentence in `detail`.
