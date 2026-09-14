# Convert legacy Sessions into PlayerSession facts

Migration `0004_playersession_conversion` states each legacy `Session` row as
`PlayerSession` events. Each session names a run. A game gets one
imported-history bucket when no single run claims a session's day. The
migration gates the result and rolls back on a mismatch. The reverse is
`noop`. The code is in `games/backfill/playersession.py`. `load_sample_data`
runs the same pass after it replays the fixture.

This branch is member 1 of the wave stack (#700, #1047, #702, #704). Land it
only with `gh stack merge`. Do not merge it alone.

## One row, one statement

`classify_timing` gives one of six verdicts. Three are modes:

| Verdict | Statement |
|---|---|
| `timed` | `TimedTiming(start, day_zone, start_zone, end, end_zone)` |
| `duration_only` | `DurationOnlyTiming(day, duration_manual)` |
| `corrected` | `CorrectedTiming(start, end, duration_total, day_zone, zones)` |

A Corrected statement takes `duration_total`: the legacy total adds the manual
part to the elapsed time, and the mode replaces it.

A `running` row is a Timed statement with no end when the row is removed. A
live running row refuses. `negative_elapsed`, `negative_manual` and a NULL
`duration_manual` refuse. The NULL check runs before the verdict, because
`classify_timing` reads NULL as zero.

`day_zone` is the library user's `DISPLAY_TIME_ZONE`. A Duration-only day is
`timestamp_start` read in that zone. Endpoint zones convert as recorded; NULL
and blank become `None`. The device converts as named, removed or not; another
library's refuses. The note is stripped. The pass calls the command module's
`normalized_timing`, `timing_payload` and `check_note`, so each value refusal
the command states, the conversion states.

## Events and identity

- `library.playersession.created`: aggregate id is the legacy `Session.id`;
  `recorded_at` is the row's `created_at`.
- `library.playersession.removed`: `recorded_at` is the row's `removed_at`.

Keys are `backfill:700:playersession:{created,removed}:<session>` and
`backfill:700:playthrough:{bucket,bucket_name}:<player_game>`. A `BUCKET`
row's `command_input` names no run: the bucket is the pass's choice, not the
row's statement, so the fingerprint holds whichever bucket stands.

`source_metadata.legacy` keeps the instants, both zones, the three durations
in microseconds, `created_at`, the verdict, the assignment and the claimer
count. It is what survives #772.

## Assignment and the bucket

Per game, the live ordinary runs become `RunInterval`s. The day is the start
read in the display zone. `assign_run` answers `SOLE_RUN`, `CONTAINED` or
`BUCKET`. The bucket is one `imported_history` run per game, named "Imported
history — needs sorting", minted at the migration's instant on the first
`BUCKET` row, after a query for a live one. `MoveSessionToPlaythrough` is the
only way out.

The walk pages the library's games, as the census does. A row on an untracked
game, a removed tracking row, a removed game or a shared game refuses the
migration by name. The module's reads, the census and the parity read name
their columns with `.only()`. The replay (check 7) does not: it reads every
column of the projection tables, so a later migration that adds one to them
must run after this one has already run.

## The gate

`reconcile()` runs `ANALYZE` on the filled tables first: the planner does not
know uncommitted rows. Then, per library:

1. Row to row, live and removed apart: mode, run, instants, zones, day,
   `day_zone`, `effective_duration == duration_total`, device, note,
   emulated, `created_at`, mark.
2. Census: the pass's counts equal `preflight_library()`'s secondary column.
3. Bucket: at most one per game, holding exactly the `BUCKET` rows, present
   only where a row needs one.
4. Playtime: `differing(playtime_figures(library, display_zone(library)))` is
   empty.
5. Counts: legacy rows in scope equal projection rows, live and removed.
7. Replay: `rebuild_projections(mode=CHECK)` shows no difference.

After every library, check 6: identity ordering on `games_playersession` and
`games_playthrough`, once over both tables.

The migration prints one machine-readable line to stderr and names the first
three mismatches in the exception, with the rest counted. A second pass
appends nothing and mints nothing. `games/backfill/reporting.py` prints the
same report for the migration and for `load_sample_data`.

## Out of scope

Screens, write paths, run pickers, the dormancy clock, the zone a library
counts days in (#1047), the fixture's session rows (#772), and reads of the
projection.
