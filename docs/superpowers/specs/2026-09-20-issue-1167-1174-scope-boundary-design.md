# Where a scope miss is answered

A command resolves each row that its identifiers name. This document states
what a person gets when such a resolve finds nothing, and where that rule is
stated.

It replaces the rule in
[Record a session through the API](2026-09-20-issue-1074-session-api-record-design.md),
which puts the scope check at the route.

## Two endings

A resolve has two endings, and they state different facts.

A row that this library does not hold is **absent**. The identifier names
nothing here. The answer is 404 and nothing more, thus one library learns
nothing about another library's rows.

A row that this library holds, but cannot use, is **refused**. The row is
there, and a person can act on it: restore the game, restore the run, choose a
different device. The answer is 409 and one sentence that names the remedy.

## What the rule governs

The rule governs an identifier in a **body**: the row a command resolves while
it builds.

It does not govern the row in a route's **path**. That row is the route's own
subject, and each route states its read scope for it, with `owned_or_404`. The
two are different questions. `PATCH /api/playthrough/{id}` answers 404 for the
imported-history bucket because `_writable_runs` states that this route edits
ordinary runs alone, which is a statement about the route. `POST /api/session/`
answers the bucket's own sentence, because there the bucket is a run the
library holds and the command can say what to record instead.

## The class

`RowNotHeld` states the absent ending. It is in `games/events/dispatch.py`,
beside `CommandRejected` and `RowUnreadable`, and it is a sibling of both. It
is not a subclass, because the boundary answers it differently: a handler
written for a rejection must not take it.

It carries no sentence. The boundary owns the answer, and a sentence that
nothing shows becomes wrong with nobody to see it. Its argument names the row,
the identifier and the library, because the log is the only record of one.

`answered()` holds a clause for it: one warning line, then `Http404`. The
warning carries no traceback, because the program is correct and a client sent
an identifier this library does not hold. A 404 that nothing records is
invisible, and an invisible 404 is how a client comes to retry a request that
already succeeded.

`ANSWERED_DIRECTLY` lists the class, thus
`test_every_boundary_exception_is_classified` fails for a boundary exception
that nothing classifies. A second test states that `RowNotHeld` is no
`CommandRejected`, beside the one that states the same of `RowUnreadable`: the
guard walks `games/events/`, and the two subclasses below live in
`games/commands/`, which it does not walk.

## Where the rule is stated

`Refusal` in `games/commands/scope.py` states it once. `raises` defaults to
`RowNotHeld` and `sentence` defaults to none, thus a resolver that states
neither answers 404. A resolver written later gets the rule without reading
this document.

`__post_init__` refuses the two pairs that cannot be true:

- a `RowNotHeld` that states a sentence, which nothing shows;
- a `CommandRejected` that states none, which reaches a person as the
  boundary's plain words.

`raised()` reads the class before it builds the exception. `RowNotHeld` takes
the message alone, because it holds no sentence keyword; `CommandRejected`
takes both. Its return type, and `raises`, name the two classes.

Four sentences go away, because nothing shows them any more: "That playthrough
is not available.", "That device is not available.", "That session is not
available." and "That record is not available."

`PlaythroughNotHeld` and `SessionNotHeld` become subclasses of `RowNotHeld`.
Each keeps its name, because two commands resolve a row that another row
already names, and state `RowUnreadable` where the library does not hold it:
`_session_run` for a session's run, and `_refuse_beside_a_live_session` for a
record's session. Both read the drift that `audit_library_ownership` reports,
and both keep working.

`tracked_game` states `CommandRejected` and says why. `PlayerGameNotTracked` is
not an answer: the write path takes it, tracks the game, and states the fact
again. A 404 there would end a request that the program repairs.

## What each resolver answers

| Resolver | Absent | Removed |
|---|---|---|
| `library_playthrough` | 404 | 409, the run's or the game's sentence |
| `library_device` | 404 | 409, "Restore it before choosing it." |
| `library_device_row` | 404 | resolves; the caller states the rule |
| `library_session` | 404 | resolves; the session commands state the rules |
| `library_record` | 404 | resolves; the record commands state the rules |
| `tracked_game` | 409, and the write path takes it | — |

The run scope stays wide: this library's rows of every kind, removed or not.
Thus a command that names a run in a body still reaches the bucket's sentence,
a removed run's sentence and a removed game's sentence.

The device scope becomes the same shape. A removed device answers 409 and its
sentence, where the route answered 404 before. The two rows now state one rule,
and a person who removed a device in another tab reads what to do about it. The
404 said less: on the record route it says "No such session" about a session
that does not exist yet.

## The routes

Three routes hold the device pre-check, and one holds the run pre-check. All
four go away:

- `POST /api/session/`, both checks;
- `PATCH /api/session/{id}`, the device;
- `PATCH /api/session/{id}/device`, the device.

Each route then states the identifiers and dispatches. The command resolves
under the stream-head lock, which alone proves a row is still there.

The playthrough routes need no change. Each reads the run its path names with
`owned_or_404`, which is that route's own scope, not this rule.

## The retry

`idempotent_append` runs `build` after it reads the key. A second request under
a used key appends nothing and builds nothing, thus it resolves no run and no
device.

This is what the pre-checks broke. They read the state now, ahead of a key that
states what already happened, and a device removed between the two requests
made the second answer 404. A client that reads 404 as "nothing happened"
retries under a fresh key and records a second session, which is the outcome
the header prevents.

With both resolves inside `build`, a device removed after the first request
changes no answer to the second.

The route still reads the recorded row after the dispatch, and that read keeps
its own rule: a session removed since the first request answers 404, because
`readable_sessions` refuses it. The retry answers what the library holds now,
and the change is about the device alone.

## The batch conversion

`_convert_each` converts each reviewed session in turn. It takes
`CommandFailed` and reads the status: a conflict becomes a sentence on the
page, and anything else stops the run and reports. An `Http404` is neither,
thus it would leave the loop with rows already recorded and no message.

The rows come from `library_sessions` moments before, so this library holds
each of them and `library_session` cannot miss. The loop states that, and takes
`Http404` beside `CommandFailed` to say what happens if it ever does: the same
stop, and the same report.

## What a 404 cannot say

`answered()` states `Http404` with the command's own noun, thus a POST that
names another library's run answers "No such session". Ninja shows that text
under `DEBUG` alone, and the web pages never show it, because the project
ships no `404.html` and Django's built-in page prints fixed words. The warning
line is where the distinction lives.

A resolver could name its own row to the boundary. That is a wider change than
this rule needs, and nothing today reads the text.

## Beside it

`games/writes/historical_playtime.py` mints over a blank key with
`idempotency_key or ...`. A blank key is false, thus a caller that stated one
gets a second write on its retry rather than a refusal. The session twin states
`is None`, and this one does the same.

## Left for later

Two rows that this rule touches state the wrong ending, before and after it.
Each gets an issue of its own.

A record and a reclassification each resolve the device their row already
names, with `library_device_row`. A library that does not hold that device has
drift, which `audit_library_ownership` reports, thus `RowUnreadable` is the
ending, as it is for a session's run. Today it is a rejection; under this rule
it becomes a 404. Neither says what happened.

`clone_session` reads the game's latest ordinary run with
`latest_ordinary_run`, inside `answered` but ahead of the dispatch. The resolve
is library-scoped and states a rejection, and it sits outside `build`, outside
the lock and outside `games/commands/`, where `test_command_scope_guard.py`
walks. It mints a key every call, so no replay reaches it today.
