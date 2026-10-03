# Move a playthrough to another game

Issue [#1466](https://github.com/KucharczykL/timetracker/issues/1466).
Wave: [Access and Purchases](2026-09-28-access-and-purchases-wave-design.md).

## The gap

The conversion gave each DLC legacy row its own `dlc` Game. A run that
the library recorded on the parent game before that is the DLC's run.
No command moves a run between games. Edit playthrough refuses another
game, and the bulk session move refuses a run at another game.

## The command

`MovePlaythroughToGame(playthrough_id, game_id)` in
`games/commands/playthrough.py`. `game_id` is a catalog game, as in
`CreatePlaythrough`. The build runs these steps in this order:

1. Resolve the run with `library_playthrough`.
2. The run's game is the target: `Unchanged`. This comes before every
   refusal, as in `RemovePlaythrough`.
3. `refuse_unless_live`: a removed game or a removed run is refused.
4. The imported-history bucket is refused. The bucket holds one game's
   imported sessions and belongs to that game.
5. Resolve the target. The library's `PlayerGame` for `game_id` comes
   first, removed or not, because it is unique per library and game. A
   removed one is refused with the sentence that names the restore. A
   shared catalog game carries no stamp of its own, so only this read
   finds that removal. With no `PlayerGame`, `visible_row` over
   `Game.objects.alive()` resolves the catalog game, and a miss is
   `RowNotHeld`: the body names a row the library does not hold.
6. Read every record that names the run, live or removed, through
   `HistoricalPlaytimeRun`. A record that names another run as well is
   refused. Its sentence tells the person to take this playthrough off
   that record first. A record holds one game's runs, so the other runs
   are the old game's. The remedy for a live record is its edit. A
   removed record is restored first; the sentence says so.
7. Compose the events.

The events, in this order:

1. An untracked target is tracked with `playergame_created` alone.
   `tracking_events` splits into `tracking_event(game)` and the pair, so
   the move mints no placeholder only to remove it.
2. `library.playthrough.moved`, payload `{"player_game": ReferenceId}`.
   The id is bare for the reason `PlaythroughCreatedPayload` states.
3. `library.historicalplaytime.moved`, payload
   `{"player_game": ReferenceId}`, for each record that names the run
   alone. A removed record moves too, so a restore puts it on the right
   game.
4. The target's `placeholder_run`, if it has one, is removed with
   `playthrough_removed`. That read counts live referrers only, so a
   removed session or record may still name the placeholder. That is the
   shape `RemovePlaythrough` already has.
5. A source game left with no live ordinary run gets a new placeholder,
   `playthrough_created(source)`. Every tracked game holds one live
   ordinary run, and the person's intent is to leave the base game bare.

A record moves through its own event, not `historicalplaytime.restated`.
The restatement stamps `restated_at`, and `UndoSessionReclassification`
refuses a record with that stamp. The move states nothing new about the
record, so it must not block that Undo. The join rows keep their ids.

The wave organizer ruled both the record event and the target
placeholder removal on 2026-10-03. The issue body's "restated" was
loose wording.

Sessions name the run, not the game, so they follow with no event.
Numbering, the dormancy clock, playtime and every list are reads.

A record made from a session may name a sibling run of that session's
game. A move of either run then leaves the session and the record on
different games. Nothing reads that pair by game, so this is accepted.

A move renumbers the blank runs of both games. Numbering is derived,
so this is expected.

Statuses do not move. A status is stated, not counted; the move states
none.

## Batch Undo of a start or a completion

`games/bulk_playthrough_acts.py` puts back the status the batch changed.
It reads that status on `run.player_game_id`, the run's current game.
After a move, the batch's `playergame.status_changed` is on the old
game, so the Undo would put back nothing. A new read gives the
`PlayerGame` the run named when the batch wrote its event: the latest
`playthrough.created` or `playthrough.moved` of the run before that
event. `_word_before`, `_stated_since` and `_put_the_status_back` read
that game.

## Projectors

`Playthroughs._moved` amends `player_game_id`.
`HistoricalPlaytimes._moved` amends `player_game_id` alone.

The comment on `Playthroughs.handles` says every amended column carries
a default. `player_game_id` carries none, so the creation must name it,
and a move amends it later in the stream. `HistoricalPlaytimes._restated`
already amends the same column of a record. The upsert of a re-applied
creation would write the old game back, and no path re-applies one: a
replay starts from empty tables. The comment is restated to say so.

## The write path

`restate_run` takes `game_id`, a catalog game or `None`, which states
nothing. Where it differs from the run's game, `MovePlaythroughToGame`
dispatches first, under the same
`correlation_id` as the description and the endpoints, as
`restate_session` does. Each dispatch answers `Unchanged` for state the
run already holds, so a failed submit is finished by submitting again.

## The surfaces

Edit playthrough stops locking the game for an ordinary run. The
imported-history bucket keeps `locked_game`, because the command refuses
every move of it; the refusal sentence says the bucket stays with its
game. The view states the companion status on the game that the form
names and returns to that game's page by default. The Played box still
renders by the run's current game. A submit that moves a run and states
its first start can therefore omit the box the target would offer; the
person states that status on the game.

Edit playthrough opens only a run whose days fit the form
(`restatable_days`). `PATCH /api/playthrough/{id}` takes an optional
`game_id` as well, so a run with a month or year start can move too.

## Tests

- Command: the move; `Unchanged`; each refusal; an untracked target; a
  target placeholder removed; a target with a named run keeps it; a
  source placeholder minted; a sole record moved, live and removed; a
  shared record refused; `restated_at` stays null.
- Projection and events: payload validation and both handlers.
- Replay gate: the stream carries both new types; the
  sixty-two count in the partial-stream test becomes sixty-four.
- Form and view: a game change on Edit playthrough moves the run; the
  bucket's game stays locked. `test_a_locked_game_refuses_a_different_one`
  becomes the bucket's test.
- Batch Undo: a batch start, a move, then Undo puts the old game's
  status back.
- API: a PATCH with `game_id` moves the run; an unknown game is 404.

`make verify-purchase-statistics` counts completed runs per game. A
moved run is a difference it cannot explain, until #1448 removes that
tool. The anonymizer offsets each aggregate's dates by its current
game, so it needs no change.

CLAUDE.md's Playthrough paragraph names the new command.

## Follow-up issues to file

None. A bulk `playthrough.move` act and a move between libraries are out
of scope in the issue.
