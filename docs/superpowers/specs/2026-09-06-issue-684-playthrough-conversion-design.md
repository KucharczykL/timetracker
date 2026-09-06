# Convert legacy PlayEvents into Playthrough facts

Issue [#684](https://github.com/KucharczykL/timetracker/issues/684). The model
is [the PlayerGame baseline
backfill](2026-08-27-issue-676-playergame-baseline-backfill-design.md).

The legacy `PlayEvent` table records which games a library played through, and
when. The conversion states every row in scope as Playthrough events. It writes
no legacy row. It changes no read path and no write path.

## The rule

Each legacy row in scope becomes one ordinary Playthrough that states both
acts. Each act takes its day from its column. Where the column is null, the act
is stated with no day.

A row with no dates is not an empty row. It is the record that a run happened
on days nobody wrote down. `start_recorded_at` beside a null `started` states
this. A null marker states an act that never happened, which is not what these
rows say.

## Events

`games/backfill/playthrough.py` appends, per row: `created`, `note_changed`
where the note is not blank, `started`, `completed`, and `removed` where the
row is removed. The day of an act is the `effective_time`. The `recorded_at` is
the row's `created_at`, or the row's `removed_at` for the removal.

Every aggregate id comes from `identity_at(recorded_at)`. The identity audit
holds each `games_playthrough` key to its `created_at` order, and the projector
writes `created_at` from `recorded_at`.

An endpoint with a day whose `(player_game, kind, day)` matches exactly one
#676 status event adopts that event's `correlation_id`. Each other event mints
a fresh id.

Idempotency keys are `backfill:684:playthrough:<fact>:<row>`, plus
`:default:<player_game>`. No `command_input` names an aggregate id, so a second
pass hashes the same fingerprint and replays.

## Scope and defaults

The walk pages the live `PlayerGame` rows of one library. It skips a game the
catalog marks removed. It takes that game's rows, live and removed alike.

A tracked game that holds no live run after its rows are converted receives one
`created` event, dated with its `tracked_at`.

## The gate

The migration `0045_playthrough_conversion_backfill` converts, then checks,
then commits. Any mismatch rolls the run back.

1. The live rows of a game and the runs that state an act say the same days and
   the same notes.
2. A removed row has a removed run.
3. A tracked game holds a live ordinary run.
4. The display order of the runs follows the legacy order of the rows.
5. A second pass appends no event.
6. The identity audit reports no violation for `games_playthrough`.

`load_sample_data` calls `convert_library()` beside `backfill_library()`.

## Rollback

The run appends events only. Reversal is the projection rebuild
[#667](2026-08-25-issue-667-shadow-rebuild-design.md) provides. The migration
reverses as `noop`.
