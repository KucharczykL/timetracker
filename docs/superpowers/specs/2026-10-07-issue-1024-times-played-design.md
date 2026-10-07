# State how many times a game was played through

Issue: #1024. Part of #601, Playthrough wave
([wave](2026-09-04-playthrough-wave-design.md)). After #687, #1012 and #1034, whose
`with_implied_status` states the status in the act's own dispatch.

## Outcome

A person states "I played this game through 5 times" once, from Game
detail, and the library then holds five completed runs. No run is filled in
by hand.

## Decisions

The issue asks four questions. The user chose the answers to 1, 3's
affordance and 4 (2026-10-07); the rest follow from the run model.

1. **A count creates runs.** It records no number beside them. The runs are
   the one record: `Played N times`, `playthrough_count`, the statistics and
   the filters already count completed runs, and none of them learns a
   second source. A number beside the runs drifts the moment a person fills
   in one of those plays as a real run.
2. **A run made by a count states both acts and no day.** Start and
   completion are stated with an unknown day ("played before"); name, note
   and both act notes stay blank. All-time figures count it, because they
   read the completion marker. No year counts it, because a year reads the
   bound columns and an unknown day has none. No precision is invented.
3. **The count is a target total, and lowering removes dateless runs.**
   "Set times played" states N, the number of live ordinary runs whose
   completion is stated. The command and the seeded field read
   `completed_run_count`; Game detail's `Played N times` counts the same
   set off the rows it already loaded. Raising from k adds N − k.
   Lowering removes k − N *dateless* runs (below). The latest goes first,
   by `(created_at, id)` descending: the runs of one raise share
   `created_at`, the append's one `recorded_at`, and the build mints their
   ids in order. Where fewer
   dateless runs exist than the drop needs, the statement is refused whole,
   with a sentence saying the other runs are dated, named or hold play, and
   are removed from the table. A count never removes any other run.
4. **Such runs read as ordinary rows.** Game detail's Playthroughs table
   lists each one as `Playthrough N`, Started and Completed unknown. The
   numbering rule (known bounds NULLS LAST, then `created_at`, then `id`)
   puts them after every run with a known day; among undated runs they sort
   by creation. A person may later date or name any one; it then stops
   being dateless and a count no longer removes it.

### Dateless and bare

`games/reads/playthrough_count.py` states two predicates over a live
ordinary run of the game:

- **bare**: no act stated, blank name, blank note, and nothing names it;
- **dateless**: start and completion stated with no day, blank name, blank
  note, blank act notes, and nothing names it.

"Nothing names it" reads every `BLOCKING_REFERRERS` entry through
`rows_naming`, one `Exists` per entry annotated over the candidates, so a
lower costs a fixed number of queries under the lock. A row of this library,
live or removed, disqualifies the run: an act that takes a run away on its
own leaves alone any run a restorable row still names. `blocking_referrer`
reads live rows only and is the wrong rule here. A row of another library
naming a candidate raises `RowUnreadable`, as `RemovePlaythrough`'s
`_refuse_a_foreign_referrer` does: that is drift the ownership audit
reports, not a fact about the person's runs. `placeholder_run` is not
reused: it admits a noted run, which no dateless rule would take back.

### The placeholder

A tracked game holds one run from tracking. Raising fills one bare run
first, if the game holds exactly one live ordinary run and it is bare,
stating both acts on it, then creates the rest. A lowering that would
remove every live ordinary run keeps the oldest candidate and voids both its
acts instead, so the game keeps its one run, bare again. `RemovePlaythrough`'s
last-run refusal is therefore never reached.

### Two commands

`games/commands/playthrough_count.py` holds both. Each decides under the
dispatch lock, mints every id it names (a build cannot read rows the same
append writes), and appends only event types that exist:
`playthrough.created`, `.started`, `.completed`, `.removed`, `.restored`,
the two voids, and `playergame.status_changed`. No projector changes, so
replay parity holds by construction. One dispatch is atomic. Two
`CommandName` members join: `PLAYTHROUGH_STATE_COUNT`,
`PLAYTHROUGH_UNDO_COUNT`.

**`StatePlaythroughCount(game_id, count)`**, checked in this order:

1. untracked game: refused with its own sentence, through `library_row`
   and its own `Refusal`. `tracked_game`'s `PlayerGameNotTracked` says
   "reload", which leads nowhere: the item renders for a tracked game only,
   and no write path tracks and retries;
2. removed `PlayerGame`: refused, as `CreatePlaythrough` refuses;
3. `count` below 0: refused;
4. `count` equal to the current total: `Unchanged`;
5. a raise above `MAX_TIMES_PLAYED` (100): refused. A lower is never refused
   by the bound, so a library past 100 can still lower. A raise to 100 is
   at most 300 run events in one append; that cost is accepted;
6. too few dateless runs for a lower: refused.

A raise states Completed through #1034's helper that appends the implied
status last in the act's own dispatch (`with_implied_status`, over
`status_implied_over`): Completed wherever the game is not Completed. This
issue lands after #1034 and calls its code; nothing here imports
`games/writes/implied_status.py`. A lower states no
status; nothing walks a status back. The count is absolute, so a repeated
press answers `Unchanged`; the form's submission key absorbs a repeat that
races the first. The form's submission UUID (a uuid7) is the dispatch's
`correlation_id` as well as its key, as the bulk runner's token is: a
replayed dispatch answers the first one's events, and the Undo link names
an id those events carry.

**`UndoPlaythroughCount(game_id, statement, stated)`** takes back one
statement, named by its correlation id; `stated` is the total it left. It reads the statement's events
(`batch_events`) and inverts each:

- `playthrough.created` → `playthrough.removed`;
- `.started`/`.completed` on a run the statement did not create → the void;
- `.removed` → `.restored`;
- a void → the act again, with no day and no note;
- `playergame.status_changed` → the word before (`status_change`), only
  while it is still the latest status event; otherwise the status stays.

In this order:

1. a removed `PlayerGame` refuses, as `RestorePlaythrough` refuses under
   one;
2. any touched run states another event after the statement's last one on
   it (dated, named, corrected, removed by hand): refused whole;
3. the current total differs from `stated`: refused whole. A later
   statement on other runs moved the total, and restoring a delta would
   leave a number nobody stated;
4. a run it would remove is disqualified by the "nothing names it" rule:
   refused whole, a foreign row as `RowUnreadable`.

The Undo is keyed `times-played-undo:<statement>`, so a second press
replays the first dispatch's answer rather than meeting its own events as a
change.

Each refusal says the playthroughs changed since and are edited by hand.
The status goes back only where the statement's status event is still the
latest. The build assembles every inverse itself rather than calling the
per-row endpoint helpers, whose single-row `Unchanged` has no meaning for
the whole. This is an exact inverse: a raise's own runs go, the bare run
returns, and a lower's runs come back under their own ids.

### Screen and routes

The `Played [N times ▾]` split button gains "Set times played…" beside
"Add playthrough…", for a tracked game only. It opens
`games:state_times_played` (`game/<uuid>/times-played`, GET form, POST
write) through `form_dialog_link`: one number field, "Times played
through", seeded with `completed_run_count`, help text "Adds or removes
playthroughs with no days stated." A refusal renders on the field. A save
redirects to Game detail with the toast "Played 5 times." and Undo; an
`Unchanged` answer says "Already played 5 times." with no Undo.

The toast posts with no body, so Undo's route carries the statement in its
path: `games:undo_times_played`,
`game/<uuid>/times-played/undo/<uuid:statement>/<int:stated>`, POST only, through
`restore_and_return`. Both routes join `ORIGIN_AWARE` in
`games/views/returns.py`.

## Verification

- State: raise from a bare run, raise beside dated runs, raise with a
  noted sole run (not filled), lower, lower to 0 (bare run back), lower
  beside an undated unfinished run, too few dateless runs, a dateless run
  named by a removed session is never removed, `Unchanged`, bounds (raise
  above 100 refused, lower from 120 to 110 allowed), untracked and removed
  game, Completed stated on a raise only.
- Undo: of a raise (runs removed, bare run back, status back); of a lower
  (same ids restored); refused after a raise-made run was dated; refused
  after a later statement touched the same runs; second press `Unchanged`;
  status left where stated since.
- Undo: a double-submitted statement's Undo works; a lower, then a raise
  on other runs, then the lower's Undo is refused; Undo under a removed
  game is refused.
- Edit: renaming a count-made run takes it out of a lower's reach; saving
  its edit form with blank days leaves it dateless.
- Replay: both commands join `build_stream` in
  `tests/test_projection_replay_gate.py`, so the rebuild, swap and
  repeat-under-key gates cover them.
- Fingerprints: both commands join `COMMANDS`/`RECORDED` in
  `tests/test_endpoint_fingerprints.py`, after #1034's bump to 6.
- View: GET seeds the total; POST redirects with an Undo toast; Undo
  restores the total; refusal on the field; the item renders for a tracked
  game only; both routes classified.
- e2e: the menu item inside `<drop-down>` opens a dialog, not a
  navigation; save; read the new rows; press Undo.

## Follow-up issues to file

None.
