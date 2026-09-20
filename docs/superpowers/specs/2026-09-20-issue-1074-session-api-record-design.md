# Record a session through the API

The session API reads the projection and writes through the session commands.
It has no endpoint that records a session, because the legacy router had none.
`POST /api/session/` states one. Part of the
[session delivery wave](2026-09-12-session-wave-design.md), over the
[PlayerSession aggregate](2026-09-13-issue-689-playersession-aggregate-design.md)
and the [cutover](2026-09-15-issue-702-session-cutover-design.md).

## The body

The body names the run, and it states one whole timing statement. Both keys are
necessary. `device_id`, `note` and `emulated` are optional, and each holds the
default that `CreateSession` holds.

The run is stated, never derived from a game. A command that reads a preference
records a fact that nobody stated, and the same rule makes the timing
necessary: a body with no timing is refused, and a caller that records a
running session states its own clock.

The timing is the union that `PATCH /api/session/{id}` already takes. The three
shapes are Timed, Duration-only and Corrected, and the keys of each shape tell
them apart. One definition serves both routes, thus the two cannot state
different grammars for one statement. Strict validation refuses an unknown key
in the body and in the timing, thus a stale spelling cannot pass unread.

The day zone is not a key. The library states it, and the route reads it with
`calendar_day_zone`, as the correction route does.

## The two identifiers

The route resolves the run and the device before it dispatches. Each resolution
answers 404 for an identifier that this library does not hold.

The run scope is this library's rows of every kind, removed or not. That scope
is the scope of `library_playthrough`, the resolver that the command uses. Thus
404 says one thing only: this library holds no such run. Every other refusal
stays with the command, which alone can say what to state instead — the
imported-history bucket, a removed run, a removed game, a statement that ends
before it starts, a zone that one tzdata set does not read. Each of those is
the command's sentence at 409.

The device resolution is the helper that the two `PATCH` routes use. Its scope
is narrower than the run's, because `for_library` calls `alive()`: a removed
device is absent to the API, and the command's sentence about a removed device
is unreachable from here. The two identifiers are asymmetric, and this route
keeps the asymmetry that the routes beside it have.

The command resolves both identifiers again under the lock. The route's
resolution is an answer for a person, not a guard: only the lock can prove that
a row is still there.

## The retry

`record_session` takes no key today: it lets the private dispatch make one, and
thus two identical requests record two sessions. It accepts a keyword-only key,
as `reclassify_session` does, and it gives that key to the dispatch. The route
reads the `Idempotency-Key` header, and it makes a key when the header is
absent. No caller of `record_session` changes, because the keyword has a
default.

A second request that carries the key of the first appends nothing. Its result
holds the sequence range of the first append, thus the route answers the row
that the first request recorded. A key that already belongs to a different body
is the mapped conflict, and it answers a sentence at 409.

The route measures the header before it dispatches. `validate_idempotency_key`
raises a plain `ValueError` for a blank key and for a key of more than 255
characters, and no answer maps that error, thus a person would read a defect.
The route refuses such a header at 422 instead. It removes the spaces at the
two ends before it measures, because a key of spaces alone passes both that
check and the constraint on the column, and it names no request.

## The answer

The route answers 201 and the projection row, as `SessionOut`. The row states
the identity, the mode, the day that the library's calendar counts, and the
duration. Thus a client knows what it recorded, and it makes no second request.
`POST /api/playthrough/` answers 204 for the reason that the run's identity was
not necessary to it; this route has a caller that needs it.

The read that makes the answer is `readable_sessions`, which refuses a session
under four removal marks. One of them, the mark on the catalog game, no session
command reads. Thus a person who stops tracking the game in a second window,
between the append and the read, receives a defect and not the row. The
correction route holds the same window, and this route holds it for the same
reason: a read that is wider than the list would answer a row that no list
shows.

The route queues a message, as every write route beside it does. The middleware
empties the queue on this response and states it in the trigger header, thus
the message reaches the browser that recorded the session and no page after it.
Every caller is such a browser: the API authenticates with the session cookie,
and it demands the CSRF token with it.

## What else changes

Two documents state that this endpoint does not exist: the API list in
`CLAUDE.md`, and the cutover design. Each names the issue, and each states the
route instead.

A test that records through this route opens no transaction of its own, because
the dispatch opens one and refuses to nest. It seeds the library's calendar,
for the reason that a statement with no calendar is refused.

No gate reads the set of API routes, thus a new one needs no registration. The
answer of a schema with 201 is the first in this project; the presets route
answers 201 with no body.

## What stays

`PATCH /api/session/{id}` answers 409 for a run that another library holds,
because its move resolves the run in the command alone. One rule for every
route is a change to `library_playthrough` and to the callers that catch its
refusal by class. That change is its own issue.
