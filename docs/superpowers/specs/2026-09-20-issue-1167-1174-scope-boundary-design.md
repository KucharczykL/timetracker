# Where a scope miss is answered

A command resolves each row that its identifiers name. This document states
what a person gets when a resolve finds nothing, and where that rule is stated.

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

## The class

`RowNotHeld` states the first ending. It is in `games/events/dispatch.py`,
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
already succeeded. `ANSWERED_DIRECTLY` lists the class, thus
`tests/test_command_answers.py` fails for a boundary exception that nothing
classifies.

## Where the rule is stated

`Refusal` in `games/commands/scope.py` states it once. `raises` defaults to
`RowNotHeld` and `sentence` defaults to none, thus a resolver that states
neither answers 404. A resolver written later gets the rule without reading
this document.

`__post_init__` refuses the two pairs that cannot be true:

- a `RowNotHeld` that states a sentence, which nothing shows;
- a `CommandRejected` that states none, which reaches a person as the
  boundary's plain words.

`PlaythroughNotHeld` and `SessionNotHeld` become subclasses of `RowNotHeld`.
Each keeps its name, thus `_session_run` still takes `PlaythroughNotHeld` and
still states `RowUnreadable` for a session that names another library's run.

`tracked_game` states `CommandRejected` and says why. `PlayerGameNotTracked` is
not an answer: the write path takes it, tracks the game, and states the fact
again. A 404 there would end a request that the program repairs.

## What each resolver answers

| Resolver | Absent | Removed |
|---|---|---|
| `library_playthrough` | 404 | 409, the run's or the game's sentence |
| `library_device` | 404 | 409, "Restore it before choosing it." |
| `library_session` | 404 | the session commands' own rules |
| `library_record` | 404 | the record commands' own rules |
| `tracked_game` | 409 | — |

The run scope stays wide: this library's rows of every kind, removed or not.
Thus the bucket, a removed run and a removed game each keep the sentence that
says what to state instead.

The device scope becomes the same shape. A removed device answers 409 and its
sentence, where the route answered 404 before. The two rows now state one rule,
and a person who removed a device in another tab reads what to do about it. A
404 said less: on the record route it says "No such session" about a session
that does not exist yet.

## The routes

The route pre-checks go away. `POST /api/session/` and
`PATCH /api/session/{id}` state the identifiers and dispatch. The command
resolves under the stream-head lock, which alone proves a row is still there.

The playthrough routes need no change. Each reads its run with `owned_or_404`
before it dispatches, thus each answers 404 for a run another library holds
already.

## The retry

`idempotent_append` runs `build` after it reads the key. A second request under
a used key appends nothing and builds nothing, thus it resolves nothing.

This is what the pre-checks broke. They read the state now, ahead of a key that
states what already happened, and a device removed between the two requests
made the second answer 404. A client that reads 404 as "nothing happened"
retries under a fresh key and records a second session, which is the outcome
the header prevents.

With the resolve inside `build`, a retry under a used key answers the row that
the first request recorded, whatever became of the device since.

## What a 404 cannot say

`answered()` states `Http404` with the command's own noun, thus a POST that
names another library's run answers "No such session". Ninja shows that text
under `DEBUG` alone, so nobody reads it in production, but it is wrong where it
is read. The warning line is where the distinction lives.

A resolver could name its own row to the boundary. That is a wider change than
this rule needs, and nothing today reads the text.

## Beside it

`games/writes/historical_playtime.py` mints over a blank key with
`idempotency_key or ...`. A blank key is false, thus a caller that stated one
gets a second write on its retry rather than a refusal. The session twin states
`is None`, and this one does the same.
