# Answering an inconsistent row

Issue [#1057](https://github.com/KucharczykL/timetracker/issues/1057). The code
is in `games/events/dispatch.py`, `games/writes/answers.py`,
`games/commands/playersession.py` and `games/commands/playthrough.py`. #905
gives the boundary that turns a refused command into an answer; this issue gives
that boundary a fourth answer.

## Two refusals behind one type

`CommandRejected` says that current state does not permit the action. Every
raise site today means one of two things by it.

The first is a rule the person can satisfy: a Duration-only session has no end
to state, a completion cannot precede a start. The person is shown a sentence
that names what to state instead, the answer is 409, and nothing is logged,
because nothing is wrong with the program.

The second is a fact about a row: a Timed session holding no start, a session
naming a run its library does not hold. The person can state nothing different.
The row is the drift `audit_library_ownership` reports, or a state a CHECK
constraint forbids, or a zone name this installation's tzdata lost. Nobody is
alerted unless the raise site logs by hand, and the answer is still 409, which
tells every client to try again.

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
class InconsistentRow(CommandRejected):
    """A row the command read is wrong, so nothing can be stated about it."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
```

It lives in `games/events/dispatch.py` beside its parent, so the walk in
`tests/test_command_answers.py` that classifies every boundary exception sees it
and fails until `games/writes/answers.py` names it. That test is the forcing
function the issue asks for.

It is a subclass, following `PlayerGameNotTracked`, because every reader that
handles a rejection today keeps handling one. It takes no `sentence`: a site
cannot write one, so four sites cannot drift into four sentences for one
meaning, and a person is never shown an id or an issue number by accident. The
argument is for the log, and may name anything.

## The answer

`answered()` gains a clause ahead of `except CommandRejected`, because Python
matches clauses in order and the parent would otherwise take it:

```python
except InconsistentRow as error:
    logger.exception("[answers]: a command refused an inconsistent %s.", subject)
    raise CommandFailed(
        REFUSED_BY_AN_INCONSISTENT_ROW.format(subject=subject), DEFECT_STATUS
    ) from error
```

`REFUSED_BY_AN_INCONSISTENT_ROW` sits beside `REFUSED_BY_DATABASE`:

> This {subject}'s record is inconsistent, so nothing was changed. The problem
> has been reported.

`logger.exception` carries the traceback, and the traceback carries the
argument, so the ids and library keys the four sites already write reach the
log without a second format string. `InconsistentRow` joins
`ANSWERED_DIRECTLY`.

## The sites

Each of the four raises `InconsistentRow(message)`. `_session_run` keeps `from
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

## What the consumers see

`confirm_and_remove` renders its confirmation page at the refusal's own status,
so a removal refused by a foreign row answers 500, as one refused by the
database already does. The API's exception handler answers the status with the
sentence in `detail`. The session views call `messages.error` and re-render or
redirect, discarding the status; that is the gap
[#958](https://github.com/KucharczykL/timetracker/issues/958) owns, and the one
literal `409` it names sits on the PlayerGame path, where no site raises
`InconsistentRow`. Nothing here moves #958.

## The tests

At the boundary, in `tests/test_command_answers.py`: the status is
`DEFECT_STATUS`; the sentence carries no id from the argument; the last log
record is ERROR with `exc_info`; the sentence interpolates and leaves no brace;
the type refuses a `sentence` keyword.

At the sites, the assertions that read a sentence read the type instead:
`tests/test_playersession_command.py` for the two `_timed_start` branches and
the foreign run, `tests/test_playthrough_command.py` for the foreign referrer.
The assertions that read a log record at dispatch level go, because the site
no longer logs; the boundary test reads the record.

## Out of scope

- The status a session view answers after `messages.error` (#958).
- A guard that finds a raise site whose message says a row is wrong but raises
  the parent. The two vocabularies overlap, and a test that greps messages
  would refuse honest sentences. The four sites are named here; a fifth is
  found by review.
- Administrator-assisted repair of the row the log names (#908).
