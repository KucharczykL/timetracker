# Record a session through the API

`POST /api/session/` records one session. Part of the
[session delivery wave](2026-09-12-session-wave-design.md), over the
[PlayerSession aggregate](2026-09-13-issue-689-playersession-aggregate-design.md)
and the [cutover](2026-09-15-issue-702-session-cutover-design.md).

## The body

The body names the run, and states one whole timing statement. Both are
necessary. `device_id`, `note` and `emulated` are optional, and each holds the
default that `CreateSession` holds.

The run is stated, never derived from a game: a command that reads a preference
records a fact that nobody stated.

The timing is the union that `PATCH /api/session/{id}` takes. One definition
serves the two routes, thus they cannot state different grammars. Strict
validation refuses an unknown key in the body and in the timing.

The day zone is not a key. The library states it, and the route reads it with
`calendar_day_zone`.

`duration_seconds` is bounded by what a `timedelta` holds, because the
conversion runs before the dispatch, where no answer maps an `OverflowError`.
The sign is not bounded: the command has a sentence for it.

## The two identifiers

The route states them and dispatches. The command resolves both, under the
stream head's lock, which alone proves a row is still there.

A row this library does not hold answers 404, and a row it holds but cannot
use answers 409 and one sentence. The rule is stated once, for every command:
[Where a scope miss is answered](2026-09-20-issue-1167-1174-scope-boundary-design.md).

## The retry

`record_session` accepts a keyword-only key for the dispatch, which makes one
when the caller states none. The route reads the `Idempotency-Key` header.

A second request under the key of the first appends nothing. Its result holds
the first append's range, thus the route answers the row the first request
recorded. A key that belongs to a different body answers 409.

The route measures the header before it dispatches, because
`validate_idempotency_key` raises a plain `ValueError` that no answer maps. It
refuses a blank key, and a key of more than 255 characters, at 422. It strips
the two ends first: a key of spaces alone passes both that check and the
column's constraint. Nothing else reads the state ahead of the key: a resolve
that did would answer the second request about a row the first never saw.

## The answer

The route answers 201 and the projection row, as `SessionOut`, thus a client
knows what it recorded and makes no second request.

The read is `readable_sessions`, which refuses a session under four removal
marks. A row the marks refuse answers 404: a repeat under the key of a session
since removed, and the window where the game stops being tracked between the
append and the read. The read comes first, because a message queued ahead of it
would state the opposite of the answer.

## What stays

`PATCH /api/session/{id}` states its `playthrough_id` the same way, and answers
the same 404. The two routes read one rule.
