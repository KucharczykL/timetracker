# The PlayerGame and Playthrough replay-parity gate

Issue [#688](https://github.com/KucharczykL/timetracker/issues/688). The code is
in `tests/test_playergame_playthrough_gate.py`.

A projection must agree with the events it was written from. The gate replays
one stream that carries every registered type of both `CURRENT_STATE` families,
and compares the rows. It adds no event type, no column and no migration.

## The stream

Commands build the stream. Nothing appends an event by hand, because the gate is
a claim about the write path. Each column gets two different values, thus a
projector that writes a constant fails. The stream leaves one removed row in
each table. A second library gets a shorter stream: each assertion states that
its rows keep their values, and that their `xmin` does not move. A rewrite moves
`xmin` even when it writes the values the row already had.

## The three legs

1. **Empty-database replay.** The rows of the first library are destroyed,
   scoped by library: the `Playthrough` rows first, because `player_game` is
   `RESTRICT`, then the `PlayerGame` rows. A replay puts them back.
2. **Rebuild and swap.** A `REBUILD` swaps both tables and reports no row only
   live, none only rebuilt and none differing.
3. **Idempotency.** Each command runs again under its original key. The head
   does not move, and no event is appended.

Legs 1 and 3 compare full rows through `.values()`, thus a column added later is
in the comparison on the day it lands. Each clock-derived column comes from
`event.recorded_at`, thus no row differs legitimately.

## The coverage guard

The gate compares the event types its stream appended with the union of
`PlayerGames.handles` and `Playthroughs.handles`. A registered type that the
stream does not append fails the test and names itself. A second guard compares
the `PlaythroughKind` values the two legs wrote with the members of the
enumeration, less the members that no command can state.

## The conversion leg

Legs 1 and 2 run again on a converted stream. The conversion stamps
`recorded_at` from each legacy row's `created_at`, thus two undated rows made in
one instant tie on the first three sort fields. `RowNumber` follows the input
order of the plan, which a swap changes. The fourth field is the key, and it is
unique, thus a rebuild cannot give a run a different number. The gate states
that field.

## The benchmark

`seed_library` appends `PLAYERGAME_CREATED` and `PLAYTHROUGH_CREATED` for each
game, under one `correlation_id`. Its parameter counts games. `--seed N`
continues to count events and gives `N // 2` games to the seed, thus an odd `N`
seeds one event fewer. `--seed 0` seeds nothing and measures the commands alone.
`--seed 1` is refused, because it seeds no game and does not say so.

## The operator's run

`rebuild_projections` takes the scope group `--user`, `--library` or
`--all-libraries`, and one of them is necessary. `--all-libraries` refuses a
database that holds no library. `--fail-on-drift` exits non-zero when a check
found a differing row, and it needs `--check`: a rebuild removes drift instead
of reporting it. A check alone exits zero. The command checks every library in
the scope before it fails, and the failure names each library that drifted. A
replay through no table is refused, because zero tables compared prints as zero
rows differing. `make verify-replay-parity` runs all three flags. It is
read-only, and it is not in `make check`: it needs a stream in the database.

## Evidence

| run | measured | verdict |
|---|---|---|
| `bench` command latency | p50 5.2 ms, p95 6.0 ms, max 6.4 ms over 200 samples, against 100 ms | passed |
| `bench` rebuild seconds | 24.91 s instrumented, 24.74 s not, over 100,820 events, against 60.492 s | passed |
| `bench` work per event | 1.0 statement, 3.0 rows; 50,410 statements into each shadow table | passed, the slope holds |
| restored copy, libraries checked | 1, over 3,700 events, in 0.96 s | passed |
| restored copy, rows differing | 0 over 859 `PlayerGame` and 872 `Playthrough` rows | passed |

Measured on 2026-09-09, on the machine `docs/event-benchmarks.md` defines,
against that day's production dump, migrated before the parity run read it.

## Not in this gate

The `Session` family, whose own gate is #739. A drift outside these two
families becomes its own issue.
