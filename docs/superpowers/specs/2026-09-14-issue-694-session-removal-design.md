# Remove and restore a session

A library takes a session out of its lists, and puts it back. Both acts are
commands, because `PlayerSession.removed_at` is the projector's column. Part
of the [session delivery wave](2026-09-12-session-wave-design.md), over the
[PlayerSession aggregate](2026-09-13-issue-689-playersession-aggregate-design.md).
The model is [remove and restore a Playthrough](2026-09-06-issue-1011-playthrough-removal-design.md).

## The events

`library.playersession.removed` and `library.playersession.restored`. The
aggregate id is the session's. Both payloads are empty: the type is the fact,
thus no key can disagree with it. `recorded_at` carries the time. Neither
carries an `effective_time`, because a removal is an act about the row.

The projector amends `removed_at` to `recorded_at`, or to `None`. The
creation handler does not name the column, thus a re-applied creation keeps a
later removal.

## The commands

`RemoveSession(session_id)` and `RestoreSession(session_id)`.

Both resolve the row with `library_session()`, a library-scoped resolve over
the plain manager. `_live_session` is `library_session()`, then `_live_run()`, then the
session's own mark check. Neither command uses `_live_session`: a repeated removal must answer
`Unchanged`, and a restore names a removed row.

The order in `build`, under the lock:

1. the row already holds the state, thus answer `Unchanged`;
2. the run's `PlayerGame` is removed, thus refuse;
3. the run is removed, thus refuse.

The no-op comes first. A command that asks for state that already holds is
never refused for a reason that cannot apply to it. The way back is game, then
run, then session, and each refusal names the next step.

`_refuse_under_a_removed_parent()` holds both sentences. They say "before
changing its sessions", not "before recording this", because a removal records
nothing.

Every other session command resolves through `_live_session`, thus a removed
session refuses an end, a correction, a description, and a move.

## The registry entry

`BLOCKING_REFERRERS` holds one entry: `PlayerSession.playthrough`. A run that a
live session names cannot be removed. The sentence names a move, one session
at a time, to a run at the same game or any other.

`alive()` reads the run's mark and the tracked game's, not the catalog game's.

## The order in `RemovePlaythrough`

1. the run is already removed, thus answer `Unchanged`;
2. the run's `PlayerGame` is removed, thus refuse;
3. the run is the last live ordinary run of its game, thus refuse;
4. a registered referrer names the run, thus refuse.

The last-run rule runs before the referrers. A sole run with sessions is
refused either way, and only "remove the game itself" is a remedy that works
for it. Moving every session elsewhere leaves it the last run. The referrer
sentence answers only a run with a live ordinary sibling.

This accepts a gap: until #714's bulk move exists, such a run needs its
sessions moved one at a time. `make preflight-sessions` counts the legacy
data: 62 of 2,807 sessions sit at a game
with more than one live ordinary run.

## What does not change

No schema, no migration. `REMOVABLE_MODELS` stays without the projection.
`MoveSessionToPlaythrough` refuses a removed session; the remedy is to restore
it first. No read changes: the reads use `alive()`.
