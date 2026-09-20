# Where a scope miss is answered

A command resolves each row that its identifiers name. This document states
what a person gets when such a resolve finds nothing.

It replaces the rule in
[Record a session through the API](2026-09-20-issue-1074-session-api-record-design.md),
which put the scope check at the route.

## Two endings

A row that this library does not hold is **absent**. The answer is 404 and
nothing more, thus one library learns nothing about another library's rows.

A row that this library holds, but cannot use, is **refused**. A person can
act on it: restore the game, restore the run, choose a different device. The
answer is 409 and one sentence that names the remedy.

The rule governs an identifier in a **body**. The row in a route's **path** is
the route's own subject, and each route states its read scope for it, with
`owned_or_404`.

## The class

`RowNotHeld` states the absent ending, in `games/events/dispatch.py`, beside
`CommandRejected` and `RowUnreadable`. It is a sibling of both, not a
subclass, because the boundary answers it differently: a handler written for
a rejection must not take it.

It carries no sentence. The boundary owns the answer, and a sentence that
nothing shows becomes wrong with nobody to see it. Its argument names the row
and the library.

`answered()` holds a clause for it: one warning line, then `Http404`. The
warning carries no traceback, because the program is correct and the
identifier is not. An invisible 404 is how a client comes to retry a request
that already succeeded.

## Where the rule is stated

`Refusal` in `games/commands/scope.py` states it once. `raises` defaults to
`RowNotHeld` and `sentence` to none, thus a resolver that states neither
answers 404. `__post_init__` refuses the two pairs that cannot be true: an
absence that states a sentence nothing shows, and a rejection that states
none.

| Resolver | Absent | Removed |
|---|---|---|
| `library_playthrough` | 404 | 409, the run's or the game's sentence |
| `library_device` | 404 | 409, "Restore it before choosing it." |
| `library_device_row` | 404 | resolves; the caller states the rule |
| `library_session` | 404 | resolves; the session commands state the rules |
| `library_record` | 404 | resolves; the record commands state the rules |
| `tracked_game` | 409, and the write path takes it | — |

`tracked_game` is the one exception. `PlayerGameNotTracked` is no answer: the
write path takes it, tracks the game, and states the fact again, thus a 404
would end a request that the program repairs.

The run scope stays wide: this library's rows of every kind, removed or not.
Thus a command that names a run in a body reaches the bucket's sentence, a
removed run's sentence and a removed game's sentence.

## The retry

`idempotent_append` runs `build` after it reads the key. A second request
under a used key appends nothing and builds nothing, thus it resolves no run
and no device.

A route that resolves them itself reads the state now, ahead of a key that
states what already happened. A device removed between two requests made the
second answer 404, and a client that reads 404 as "nothing happened" retries
under a fresh key and records a second session.

## The batch runner

Each leg of the bulk runner re-resolves its rows before it runs them, so no
resolve inside can miss. The loop states that, and takes `Http404` beside
`CommandFailed`: the same end, the same report, and one ERROR line naming the
row.

## Left for later

Two rows state the wrong ending, before this rule and after it.

A record and a reclassification each resolve the device their own row names.
A library that does not hold it has drift, thus `RowUnreadable` is the
ending, as it is for a session's run (#1180).

`clone_session` resolves a run outside `build`, outside the lock and outside
`games/commands/`, where `test_command_scope_guard.py` walks (#1181).
