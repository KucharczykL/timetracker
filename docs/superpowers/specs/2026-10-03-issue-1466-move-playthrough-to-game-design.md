# Move a playthrough to another game

Issue [#1466](https://github.com/KucharczykL/timetracker/issues/1466).
Wave: [Access and Purchases](2026-09-28-access-and-purchases-wave-design.md).

## The command

`MovePlaythroughToGame(playthrough_id, game_id)` states the game of a
run. `game_id` is a catalog game. The build does these checks in this
order:

1. The run is the library's run, else `PlaythroughNotHeld`.
2. The run is at that game already: `Unchanged`.
3. A removed run or a removed game is refused.
4. The imported-history bucket is refused. It stays with its game.
5. The library's `PlayerGame` for the target is read first. A removed
   one is refused. With no `PlayerGame`, the catalog game must be
   visible to the library, else `RowNotHeld`.
6. A record that names the run and another run is refused, live or
   removed. A record holds the runs of one game.

The events are, in this order:

1. `playergame.created` for an untracked target. `tracking_event` makes
   it without a placeholder run.
2. `playthrough.moved`, which carries the new `player_game`.
3. `historicalplaytime.moved` for each record that names the run alone,
   removed records too.
4. `playthrough.removed` for the target's `placeholder_run`.
5. `playthrough.created` for a source game with no other live ordinary
   run.

Thus each tracked game keeps one live ordinary run.

Sessions name the run, so they follow with no event. Numbering,
playtime and the dormancy clock are reads.

## The status at the target

A run keeps its endpoints when it moves. The endpoints imply a status
on the target, as they do when an act states them. Thus `restate_run`
states that status after the move (issue
[#1476](https://github.com/KucharczykL/timetracker/issues/1476)):

- A stated completion implies Completed.
- Else a stated start implies Played, where the target is Unplayed.
- Else the move implies no status.

`games/writes/implied_status.py` holds this rule and the status write.
The endpoint acts use the same rule and the same write. The status has
the correlation id of the move. Its idempotency key is the key of the
move with `-status`.

The move reads the endpoints that the run held before the draft. An
endpoint that the same draft states gets no status from the move. The
Edit page states it through its boxes, as on any edit. The Played box
asks the status again after the move, so it does not replace a
Completed that the move stated. A PATCH that moves the run and states
an endpoint states no status for that endpoint.

A second post of the same move is `Unchanged`. Thus the status is not
stated again.

The source keeps its status. The move does not unstate an act there.

A status is `StatusStated`, `StatusRefused` or none. A refused status
does not refuse the move. Only a conflict that a person caused is a
refusal: a rejection or a collision. A key mismatch is a defect,
because the key of the status derives from the key of the move.

`MovedRun.status` carries the answer. The toast names a stated status.
A refused status is a second toast that tells the person to set the
status on the page of the game. The API logs a refused status as a
warning and answers 204.

A failure after the move raises `MovedThenFailed`, which carries the
`MovedRun`. The Edit page then names the move before the failure.

## The record event

A record moves through `historicalplaytime.moved`, not
`historicalplaytime.restated`. The restatement stamps `restated_at`, and
`UndoSessionReclassification` refuses a restated record. The move states
nothing about the record. The join rows keep their ids.

## Projectors

Both handlers amend `player_game_id` alone. `player_game_id` has no
default, so each creation handler names it. A re-applied creation puts
the old game back. A replay starts from empty tables, so this does not
occur.

## Batch Undo

The Undo of `playthrough.start` and `playthrough.complete` puts back the
status that the batch changed. `run_game_at_batch` reads the game that
the run had when the batch wrote. The Undo reads and states the status
on that game. A removed game gets no status back. A stream with no game
before the batch reads the current game and logs a warning.

## The surfaces

`RunDraft.game_id` states the game; `None` states none. `restate_run`
refuses a reversed draft first. Then it dispatches the move, under the
correlation id of the description and the endpoints. It answers a
`MovedRun`, read from the events of the move.

Edit playthrough sends the game of the form. It locks the game for the
bucket only. The companion status and the return page use the game of
the form. The Played box follows the current game of the run. One info
toast tells the move, the tracking, and each placeholder swap.

`PATCH /api/playthrough/{id}` takes `game_id` and refuses a present
null. Thus a run that the form cannot show, with a month or a year as
its day, can move.

## Accepted limits

- A record from a session can name a sibling run. After a move, the
  session and the record are on different games.
- `placeholder_run` reads live referrers only. A removed session or a
  removed record can name the placeholder that the move removes.
