# Move a playthrough to another game

Issue [#1466](https://github.com/KucharczykL/timetracker/issues/1466).
Wave: [Access and Purchases](2026-09-28-access-and-purchases-wave-design.md).

## The command

`MovePlaythroughToGame(playthrough_id, game_id)` states the catalog
game of a run. The build checks, in this order:

1. The run is the library's run, else `PlaythroughNotHeld`.
2. The run is at that game already: `Unchanged`.
3. A removed run or game is refused.
4. The imported-history bucket is refused.
5. A removed `PlayerGame` of the target is refused. With none, the
   game must be visible to the library, else `RowNotHeld`.
6. A record that names the run and another run is refused, live or
   removed. A record holds the runs of one game.

The events are, in this order:

1. `playergame.created`, without a placeholder, for an untracked target.
2. `playthrough.moved`, which carries the new `player_game`.
3. `historicalplaytime.moved` for each record, removed too, that names
   the run alone.
4. `playthrough.removed` for the target's `placeholder_run`.
5. `playthrough.created` for a source game with no other live ordinary
   run.

Thus each tracked game keeps one live ordinary run. Sessions follow
with no event.

## The status at the target

The endpoints of a run imply a status on its new game:

- A completion implies Completed.
- Else a start implies Played on an Unplayed game.
- Else nothing.

`games/writes/implied_status.py` holds the rule and the status write,
which the endpoint acts share. The status takes the correlation id of
the move and its key with `-status`. A repeated move is `Unchanged` and
states nothing. The source keeps its status.

The move reads the endpoints from before the draft; the Edit page boxes
state the rest, and the Played box reads the status after the move.

A rejection or a collision refuses the status, not the move; a key
mismatch is a defect. The page toasts a refusal, the API logs it. A
failure after the move raises `MovedThenFailed`, carrying the move.

## The record event

A record moves through `historicalplaytime.moved`, not a restatement,
which stamps `restated_at` and blocks `UndoSessionReclassification`. The
join rows keep their ids.

## Projectors

Both handlers amend `player_game_id` alone; each creation handler names
it.

## Batch Undo

The Undo of `playthrough.start` and `playthrough.complete` puts back the
status that the batch changed, on the game that `run_game_at_batch`
reads. A removed game gets no status back. A stream with no game before
the batch reads the current game and logs a warning.

## The surfaces

`RunDraft.game_id` states the game; `None` states none. `restate_run`
refuses a reversed draft, then moves under the correlation id of the
draft. It answers a `MovedRun`, read from the events of the move.

Edit playthrough sends the game of the form and locks it for the bucket
only. One info toast tells the move, the tracking, each placeholder swap
and the status.

`PATCH /api/playthrough/{id}` takes `game_id` and refuses a present
null, so a run whose day the form cannot show can move.

## Accepted limits

- A record from a session can name a sibling run, so a move can part
  the session and the record.
- A removed session or record can name the placeholder a move removes.
