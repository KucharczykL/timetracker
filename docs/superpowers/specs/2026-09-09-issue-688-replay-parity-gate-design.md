# The PlayerGame and Playthrough replay-parity gate

Both families are proven at once, because one command creates a row in each.
The gate builds a stream, empties the projections, replays, and demands the
same rows back. It adds no event type, no column and no migration.

## What is already proven

Every event type of both families already has a projection test of its own,
and `tests/test_playthrough_projection.py` already replays a tracked game to
an empty database and rebuilds it. Those tests each hold one slice: one event
type, on one row, in a stream that holds little else.

Two more hold more than a slice:
`tests/test_playthrough_conversion.py:438` replays a converted library and
diffs both tables, and `tests/test_playthrough_numbering.py:179` holds the
display number across a real swap, over four runs of one append that tie on
every sort field but the key.

Three things no test holds today:

1. one stream that carries **every** event type of both families, replayed as
   a whole;
2. that stream replayed into the live tables, rather than into a shadow. The
   conversion test above diffs in `CHECK` mode, which fills a shadow table and
   leaves the live rows alone;
3. a benchmark whose seeded library holds runs. `seed_library` appends bare
   `PLAYERGAME_CREATED`, so its rebuild scenario replays one family and swaps
   one table.

The gate is those three, plus the operator's way to run the first against a
restored copy.

## The gate module

`tests/test_playergame_playthrough_gate.py`. One module, three legs over one
built stream, and a guard that keeps the stream complete.

### The stream

Built through commands only. Nothing appends an event by hand, because the
gate is a claim about what the write path produces.

| act | command |
|---|---|
| track two games | `TrackGame` |
| state a status | `SetPlayerGameStatus` |
| state mastery | `SetPlayerGameMastered` |
| state the exclusion | `SetPlayerGameExcludedFromUnfinished` |
| remove a tracked game and bring it back | `RemovePlayerGame`, `RestorePlayerGame` |
| state a start and a completion | `StartPlaythrough`, `CompletePlaythrough` |
| correct both endpoints | `CorrectPlaythroughStart`, `CorrectPlaythroughCompletion` |
| name a run and note it | `DescribePlaythrough` |
| add a second run, remove it, bring it back | `CreatePlaythrough`, `RemovePlaythrough`, `RestorePlaythrough` |

A second library gets a shorter stream of its own. No assertion of the first
library reads it, and every assertion states that its rows did not move.

### The three legs

1. **Empty-database replay.** The rows of the first library are destroyed,
   scoped by `library`: the `Playthrough` rows first, because `player_game` is
   `RESTRICT`, then the `PlayerGame` rows. The second library's rows stay,
   which is the stronger claim — a replay must not disturb a neighbour, and an
   unscoped destruction could not tell the difference. `replay` answers the
   head's sequence, and both tables hold what they held.
2. **Rebuild and swap.** `rebuild_projections(REBUILD)` swaps, and reports
   `games_playergame` and `games_playthrough` each with no row only live, none
   only rebuilt and none differing.
3. **Idempotency.** Every command of the stream is dispatched a second time
   under its original key. The head does not move, no event is appended, both
   tables are unchanged, and the library holds one
   `LibraryIdempotencyRecord` per key.

Legs 1 and 3 compare whole rows, through `.values()` ordered by key, over both
tables, so a column added later is in the comparison the day it lands. Every
clock-derived column — `tracked_at`, `created_at`, `removed_at`,
`start_recorded_at`, `completion_recorded_at` — is written from
`event.recorded_at`, so nothing in either row legitimately differs between the
write path and the replay. Leg 2 asserts on the `FULL OUTER JOIN` diff
`RebuildReport` carries, which is the rebuild's own comparison rather than
this one.

There is no fourth leg for the display number.
`tests/test_playthrough_numbering.py:179` already holds it across a real
`REBUILD`, and it holds the case that can fail: four runs appended together,
tied on `started_lower`, `completed_lower` and `created_at`, separated only by
the key. A stream built through commands cannot reproduce that tie, because
each dispatch is its own append with its own `recorded_at`. The conversion
below can, and that is where the number is read.

### The coverage guard

The gate collects the event types its stream appended, and compares them with
the union of `PlayerGames.handles` and `Playthroughs.handles`. A registered
event type the stream never appended fails the test, and names itself.

Fifteen types today: six PlayerGame, nine Playthrough. The guard is what keeps
the gate honest when #700 and #701 give `Session` its reference to a run, and
whenever a family gains a type after that.

## The conversion leg

The stream a live library builds is not the stream production holds. #684
converts legacy `PlayEvent` rows, and its events carry backdated effective
times and a `correlation_id` shared with the status event #676 recorded.

`tests/test_playthrough_conversion.py:438` already replays a converted library
and diffs both tables. It diffs in `CHECK` mode, which fills a shadow table,
reads the live rows and writes none. Two things it does not do, and the gate
does:

1. **legs 1 and 2 on the converted stream** — the live rows destroyed and
   replayed back into the tables they came from, then a real `REBUILD` that
   swaps;
2. **the display number over converted rows.** The conversion stamps
   `recorded_at` from each legacy row's `created_at`
   (`games/backfill/playthrough.py:225`), so two undated legacy rows created in
   one instant convert into two runs that tie on `started_lower`,
   `completed_lower` and `created_at` alike. The gate builds that pair, reads
   `numbered_for` before the rebuild and after it, and demands the same number
   per run id.

## The benchmark

`seed_library` appends two events per game — `PLAYERGAME_CREATED` and
`PLAYTHROUGH_CREATED`, under one `correlation_id`, in the order and shape
`TrackGame` writes since #679. The seeded aggregate identity of the run is
minted with the event, as the command mints it.

**Two knobs, one argument.** `seed_library` takes `games` rather than
`events`, because a pair per game makes the two numbers different and a
parameter that names one while meaning the other reads wrong at every call
site. `--seed N` on the command keeps counting **events**, as its help text
says, and passes `N // 2` games down. An odd `N` therefore seeds one event
fewer, which the help text states. No count is refused: the existing tests
seed zero games and one game, and both stay legal.

That division keeps the event count of the recording in
[Event benchmarks](../../event-benchmarks.md) — the same 100,000 seeded
events, over half as many games, filling both tables.

| reads | before | after |
|---|---|---|
| `--seed 100000` | 100,000 games, 100,000 events | 50,000 games, 100,000 events |
| seeded projection rows | 100,000 in one table | 50,000 in each of two |
| catalog rows | one per event | one per pair |
| `games_libraryeventreference` rows | one per event | one per pair, because a run's `player_game` is a bare `ReferenceId` |
| `_SEEDED_TABLES` | six tables | seven, with `Playthrough` |

`SeedReport` keeps `events` as the appended count, so `events_per_second`
means what it meant, and gains `games`. That new field changes the JSON the
command prints, so `REPORT_SCHEMA` goes to 2 and the two tests that pin it are
rewritten. The estimate printed before a run is computed from the arguments,
not from a report, so it reads the events the argument names and the games it
divides into.

**Two budgets, one comparable.** `rebuild_budget` scales its limit by the
events replayed, and that count is unchanged, so the recorded 60.492 s
allowance for 100,820 events is the allowance again — against a replay that
now writes two tables rather than one. `COMMAND_BUDGET_SECONDS` gates
`TrackGame`, which has appended both events since #679, so both families are
already inside its measurement; but the seeded `PlayerGame` rows halve, and
that table is what `TrackGame`'s duplicate check reads
(`games/events/benchmark_workload.py:172`). The latency number is therefore
measured against a table half the size, and it is recorded as a new baseline
rather than compared with 0.005 s. The check is one indexed lookup and the
recorded margin is twentyfold, so a missed budget here would be a finding
about the command, not about the seed.

`make bench ARGS="--gate"` is re-run with and without `--no-count-replay`, as
the recording was, and both numbers go under Evidence below.
`docs/event-benchmarks.md` is rewritten where the reshape makes it false: the
pasted report and its per-table row counts, the paragraph explaining why the
second table holds 410 rows, the Parity paragraph, and the batched-replay
ceiling analysis, whose "too few to move it" no longer describes 50,000 rows.
A missed budget is a finding, not a licence to raise the limit.

## The operator's run

`rebuild_projections` takes one positional library UUID today. It gains the
scope group `preflight_playthroughs` and `audit_library_ownership` already
carry:

| flag | scope |
|---|---|
| `--user USERNAME` | the library that user owns |
| `--library UUID` | one library |
| `--all-libraries` | every library, in key order |

The group is required, as it is in both precedents, so the positional argument
goes. Nothing outside tests calls the command. Four call sites state
`--library` instead: the helpers in `tests/test_projection_rebuild.py:1138`
and `tests/test_reference_reconciliation.py:695`, the direct
`call_command` at `tests/test_projection_rebuild.py:1478`, and the
malformed-id case at `:1267`. Two documents print the positional form and are
corrected with it: `docs/event-retention.md:140` and the #667 specification.
The CLAUDE.md command table gains the new target beside `make bench`.

**A drift must fail the run, and today it does not.** `--check` replays, diffs
and writes nothing, then prints a warning and exits zero.
`docs/event-retention.md:141` states that rule and its reason: a rebuild
removes drift, so a check that found some has found work rather than a fault.
An operator rehearsing a deployment wants the opposite, so the command gains
`--fail-on-drift`, which exits non-zero when any library reported a differing,
only-live or only-rebuilt row. The default exit stays as documented, and
`docs/event-retention.md` gains the flag beside the rule rather than losing
it.

`make verify-replay-parity` runs `--all-libraries --check --fail-on-drift`. It
is read-only, and it is not in `make check`, alongside `bench`,
`audit-uuid-identity` and `preflight-playthroughs`: it needs a database with a
stream in it.

## Verification

The gate is the full `make check`, over:

- the three legs above, on the command-built stream;
- legs 1 and 2 on the conversion-built stream, and the display number over its
  tied pair, read across a real `REBUILD`. Not leg 3:
  `tests/test_playthrough_conversion.py:395` already holds that a second pass
  appends nothing;
- the coverage guard, and a proof that it fails: a stream missing one
  registered event type is refused, and the refusal names that type;
- the second library's rows unchanged by every replay, rebuild and swap;
- `seed_library` writing one `PlayerGame` and one `Playthrough` per seeded
  game, the run naming its own tracked game rather than another's;
- an odd `--seed` seeding one event fewer, and a seed of zero games still
  writing no head;
- the seeded library rebuilding with both tables swapped and no row differing;
- each scope flag of `rebuild_projections`, its mutual exclusion, an unknown
  user, an unknown library, a library id that is no UUID, and
  `--all-libraries` over two libraries where one drifted;
- `--fail-on-drift` exiting non-zero on that drift, and `--check` without it
  still exiting zero.

Two runs happen outside `make check` and are recorded here:

1. `make bench ARGS="--gate"`, for the budgets above;
2. `make verify-dump`, then `make verify-replay-parity`, against a restored
   production copy. Production stands behind the #676 backfill, so the restore
   is migrated first and the parity run reads the state the deployment will
   leave.

## Evidence

Recorded before the issue closes.

| run | measured | verdict |
|---|---|---|
| `bench` command latency | p50 5.2 ms, p95 6.0 ms, max 6.4 ms over 200 samples, against 100 ms | passed |
| `bench` rebuild seconds | 24.91 s instrumented, 24.74 s not, over 100,820 events, against 60.492 s | passed |
| `bench` work per event | 1.0 statement, 3.0 rows; 50,410 statements into each shadow table | passed, the slope holds |
| restored copy, libraries checked | 1, over 3,700 events, in 0.96 s | passed |
| restored copy, rows differing | 0 over 859 `PlayerGame` and 872 `Playthrough` rows | passed |

Measured on 2026-09-09, on the machine `docs/event-benchmarks.md` defines. The
restored copy is that day's production dump, migrated by `make verify-dump`
before the parity run read it.

## Reversibility

Nothing to reverse. The gate writes no migration and changes no stored row.
The benchmark seed writes to a scratch library the run removes, and the scope
flags change a command's arguments.

## Out of scope

- Legacy `PlayEvent` and `GameStatusChange` storage, which #771 removes after
  this gate is green.
- The `Session` family. Its own gate is #739, and its reference to a run
  arrives with #700 and #701.
- A drift this gate finds outside these two families. It becomes its own
  issue rather than a fix here.
