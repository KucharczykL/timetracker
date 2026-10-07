# State how many times a game was played through

Issue: #1024. Part of the Playthrough wave
([wave](2026-09-04-playthrough-wave-design.md)).

## Rule

A person states a total from Game detail. The library then holds that many
live ordinary runs whose completion is stated. The runs are the only record.
No column keeps the number. `completed_run_count` reads the total.

## Runs a count makes

A run that a count makes states both acts with no day. Its
name, note and act notes are blank. All-time figures count it. A year does
not count it, because a year reads the bound columns.

`games/reads/playthrough_count.py` names two sets of live ordinary runs:

- **bare**: no act, blank text, and no row names the run;
- **dateless**: both acts, no day, blank text, and no row names the run.

A session or a record of this library names a run, removed or not. A live
row of another library raises `RowUnreadable`.

## `StatePlaythroughCount(game_id, count)`

The command refuses, in this order:

1. a game the library does not track;
2. a removed game;
3. a count below 0.

A count equal to the total answers `Unchanged`. A raise above
`MAX_TIMES_PLAYED` (100) is refused. A lower is never refused by that bound.

A raise fills the sole run when it is bare, creates the rest, and states
Completed through `with_implied_status`.

A lower removes dateless runs, newest first by `(created_at, id)`. It is
refused whole when too few dateless runs exist. When it takes every live
ordinary run, it keeps the oldest and voids both its acts. A lower states no
status.

The form's submission UUID is the correlation id. The key is
`count_statement_key`: `times-played-<submission>`. A repeat replays and
offers no Undo. A refusal renders the form with a new key.

## `UndoPlaythroughCount(game_id, statement_id, stated)`

The Undo reads the events of one statement and writes their inverse:

- creation: removal;
- start or completion on an older run: the void;
- removal: restore;
- void: the act again, with no day;
- status change: the word before, only while it is the latest status.

It refuses, in this order:

1. a game the library does not track, or a removed game;
2. an event without the count's key, or of another game: `RowNotHeld`;
3. a run with an event after the statement;
4. a total that is not `stated`;
5. a run to remove that a row names.

The key is `times-played-undo-<statement_id>-<stated>`, so a second press
replays. When a later status stays, the toast says so.

## Screen

Game detail's Played split button has "Set times played…". It opens
`games:state_times_played` in a form dialog: one field, "Times played
through", seeded with the total. A refusal shows on the field. A save shows
"Played N times." with Undo; an unchanged total shows "Already played N
times." without one.

Undo posts to `games:undo_times_played`, whose path carries the statement
and the total. Both routes are in `ORIGIN_AWARE`.
