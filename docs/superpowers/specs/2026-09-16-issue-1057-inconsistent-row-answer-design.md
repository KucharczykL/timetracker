# Answering an inconsistent row

Issue [#1057](https://github.com/KucharczykL/timetracker/issues/1057). The code
is in `games/events/dispatch.py`, `games/writes/answers.py`,
`games/commands/scope.py`, `games/commands/playersession.py` and
`games/commands/playthrough.py`. #905 gives the boundary that turns a refused
command into an answer; this issue gives that boundary a fourth answer.

## Two refusals behind one type

`CommandRejected` says that current state does not permit the action. Every
raise site today means one of two things by it.

The first is a rule the person can satisfy: a Duration-only session has no end
to state, a completion cannot precede a start. The person is shown a sentence
that names what to state instead, the answer is 409, and nothing is logged,
because nothing is wrong with the program.

The second is a fact about a row: a Timed session holding no start, a session
naming a run its library does not hold, a day zone this installation's tzdata
lost. The person can state nothing different. The row is the drift
`audit_library_ownership` reports, or a state a CHECK constraint forbids, or a
name the image no longer resolves. Nobody is alerted unless the raise site logs
by hand, and the answer is still 409, which tells every client to try again.

Four sites are of the second kind.

| Site                                                        | Today                  |
| ----------------------------------------------------------- | ---------------------- |
| `_timed_start`, Timed row with no start or no day zone      | 409, no log            |
| `_timed_start`, day zone tzdata no longer reads             | 409, no log            |
| `_session_run`, session naming a foreign run                | 409, `logger.error`    |
| `_refuse_a_foreign_referrer`, foreign row naming the run    | 409, `logger.error`    |

The two that log do so with a sentence of their own, `INCONSISTENT_SESSION` and
`INCONSISTENT_PLAYTHROUGH`, which promise that "the problem has been reported".
The two that do not log make no such promise, and would break it.

A database refusal is the model. `answered()` treats it as the defect it is:
`DEFECT_STATUS`, `logger.exception` with the constraint name, one sentence
saying nothing was saved. An inconsistent row is the same defect reached one
step earlier, before the schema had to say so.

## The type

```python
class RowInconsistent(CommandRejected):
    """A row the command read cannot be read as the schema promises."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
```

Named `<Subject><Predicate>`, as `ProjectionRowMissing`, `DeferredRowRefused`
and `PlayerGameNotTracked` are.

It lives in `games/events/dispatch.py` beside its parent, so the walk in
`tests/test_command_answers.py` that classifies every boundary exception sees it
and fails until `games/writes/answers.py` names it. That test is the forcing
function the issue asks for. The placement is load-bearing: the walk reads
`games/events/`, so a class in `games/commands/` is not seen.

It is a subclass, following `PlayerGameNotTracked`, because every reader that
handles a rejection today keeps handling one. It takes no `sentence`: a site
cannot write one, so four sites cannot drift into four sentences for one
meaning, and a person is never shown an id or an issue number by accident. The
argument is for the log, and names everything the log needs: the row's key, its
library, and for a foreign reference the referring model, field and library
keys. Nothing a by-hand log line said today is lost when that line goes.

## The answer

`answered()` gains a clause ahead of `except CommandRejected`, because Python
matches clauses in order and the parent would otherwise take it:

```python
except RowInconsistent as error:
    logger.exception("[answers]: a command refused an inconsistent %s.", subject)
    raise CommandFailed(
        REFUSED_BY_AN_INCONSISTENT_ROW.format(subject=subject), DEFECT_STATUS
    ) from error
```

`REFUSED_BY_AN_INCONSISTENT_ROW` sits beside `REFUSED_BY_DATABASE`:

> This {subject}'s record could not be read, so nothing was changed. The
> problem has been reported.

Worded about the reading, not the row: on the tzdata branch the row is right
and the installation is what changed, and a sentence saying the record is
inconsistent would send an administrator to the wrong place.

`logger.exception` carries the traceback, and the traceback carries the
argument and every chained cause, so the keys reach the log without a second
format string. `RowInconsistent` joins `ANSWERED_DIRECTLY`.

## The scope guard

`Refusal.raises` in `games/commands/scope.py` is typed `type[CommandRejected]`
and `raised()` passes `sentence=`. mypy accepts a subclass there without reading
its constructor, so `Refusal(raises=RowInconsistent)` would type-check and raise
`TypeError` at the first miss. A scope miss is never a defect, so `Refusal`
refuses the type in `__post_init__`, with a test. The refusal is a sentence at
construction rather than a `TypeError` at the one moment the row is absent.

## The sites

Each of the four raises `RowInconsistent(message)`. `_session_run` keeps `from
refusal`, so the scope miss it wraps stays in the traceback. The two by-hand
`logger.error` calls go, and so do `INCONSISTENT_SESSION` and
`INCONSISTENT_PLAYTHROUGH`: the boundary logs once and says the one sentence.

The tzdata branch is included on purpose. The fix is an image bump, not a
statement, and `calendar_day_zone` already logs the same fact at ERROR when the
calendar names such a zone. A refusal nobody is told about is the shape this
issue removes.

## Where the alert lives

The log line is written by `answered()`, not by the raise site. A dispatch
outside `answered()` therefore logs nothing and lets the exception rise as a
traceback, which is louder than a log line. Every write a person can reach goes
through `answered()`; no maintenance command dispatches a session or run
command today. A later caller that does must wrap its dispatch or accept the
traceback.

The line is the whole alert. A view that returns 500 is not an unhandled
exception: Django's request logger, `ADMINS` mail and any error tracker see
nothing, and the `games` logger writes to the console with `propagate=False`.
"The problem has been reported" means one ERROR record with a traceback exists
on stderr. `REFUSED_BY_DATABASE` promises the same and delivers the same.

## What the consumers see

`confirm_and_remove` renders its confirmation page at the refusal's own status,
so a removal refused by a foreign row answers 500, as one refused by the
database already does; its comment on that line predates the second 500 and is
reworded. The API's exception handler answers the status with the sentence in
`detail`. The HTMX middleware skips no 5xx, so the toast still shows. The
session views call `messages.error` and re-render or redirect, discarding the
status; that is the gap
[#958](https://github.com/KucharczykL/timetracker/issues/958) owns, and the one
literal `409` it names sits on the refund route, which dispatches a PlayerGame
fact, where no site raises `RowInconsistent`. Nothing here moves #958.

## The tests

At the boundary, in `tests/test_command_answers.py`: the status is
`DEFECT_STATUS`; the sentence carries no id from the argument; the last log
record is ERROR with `exc_info`, and the argument and its cause are in the
captured text; the sentence interpolates and leaves no brace; the type refuses
a `sentence` keyword.

In `tests/test_command_scope.py`: `Refusal(raises=RowInconsistent)` is refused
at construction.

At the sites, the assertions that read a sentence read the type instead:
`tests/test_playersession_command.py` for the two `_timed_start` branches and
the foreign run, `tests/test_playthrough_command.py` for the foreign referrer.
The assertions that read a log record at dispatch level move: the site no
longer logs, so each reads the argument for the keys the record carried, and
the boundary test reads the record.

## Out of scope

- The status a session view answers after `messages.error` (#958).
- A guard that finds a raise site whose message says a row is wrong but raises
  the parent. The two vocabularies overlap, and a test that greps messages
  would refuse honest sentences. The four sites are named here; a fifth is
  found by review.
- Administrator-assisted repair of the row the log names (#908).
- Routing the ERROR record anywhere but stderr.
