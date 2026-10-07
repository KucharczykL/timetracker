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

`games/reads/playthrough_count.py` names two sets:

- **bare**: no act, blank text, and no row names the run;
- **dateless**: both acts with no day, blank text, and no row names the run.

A row of this library names a run when it is a session or a record that
points to the run. A removed row also names it. A live row of another
library raises `RowUnreadable`.

## `StatePlaythroughCount(game_id, count)`

The command refuses, in this order:

1. a game the library does not track;
2. a removed game;
3. a count below 0.

A count equal to the total answers `Unchanged`. A raise above
`MAX_TIMES_PLAYED` (100) is refused. A lower is never refused by that bound.

A raise fills the sole run when it is bare. Then it creates the remaining
runs. It states Completed through `with_implied_status`.

A lower removes dateless runs, newest first by `(created_at, id)`. It is
refused whole when too few dateless runs exist. When it takes every live
ordinary run, it keeps the oldest and voids both its acts. A lower states no
status.

The form's submission UUID is the correlation id and the key
(`times-played-<submission>`). A repeat replays the first dispatch.

## `UndoPlaythroughCount(game_id, statement, stated)`

The Undo reads the events of one statement and writes their inverse:

- creation: removal;
- start or completion on an older run: the void;
- removal: restore;
- void: the act again, with no day;
- status change: the word before, only while it is the latest status.

It refuses, in this order:

1. a removed game;
2. a run with an event after the statement;
3. a total that is not `stated`;
4. a run to remove that a row names.

A statement of another library or game is `RowNotHeld`. The key is
`times-played-undo-<statement>`, so a second press replays.

## Screen

The Played split button on Game detail has "Set times played…" for a
tracked game. It opens `games:state_times_played` in a form dialog. The one
field is "Times played through", seeded with the total. A refusal shows on
the field. A save shows "Played N times." with Undo. An unchanged total shows
"Already played N times." with no Undo.

Undo posts to `games:undo_times_played`, whose path carries the statement and
the total. Both routes are in `ORIGIN_AWARE`.

## Verification

The rules, the routes and the dialog each have tests. Both commands are in
the replay gate and the fingerprint table.
