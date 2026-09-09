# The PlayerGame and Playthrough replay-parity gate

Both families are proven at once, because one command creates a row in each.
The gate builds a stream, empties the projections, replays, and demands the
same rows back. It adds no event type, no column and no migration.

## What is already proven

Every event type of both families already has a projection test of its own,
and `tests/test_playthrough_projection.py` already replays a tracked game to
an empty database and rebuilds it. Those tests each hold one slice: one event
type, on one row, in a stream that holds little else.

Three things no test holds today:

1. one stream that carries **every** event type of both families, replayed as
   a whole;
2. the stream the #684 conversion writes, replayed as a whole;
3. a benchmark whose seeded library holds runs. `seed_library` appends bare
   `PLAYERGAME_CREATED`, so its rebuild scenario replays one family and swaps
   one table.

The gate is those three, plus the operator's way to run the first against a
restored copy.

## The gate module

`tests/test_playergame_playthrough_gate.py`. One module, four legs over one
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

### The four legs

Each compares whole rows, through `.values()` ordered by key, over both
tables. A column added later is therefore in the comparison the day it lands.

1. **Empty-database replay.** The `Playthrough` rows are destroyed first,
   because `player_game` is `RESTRICT`, then the `PlayerGame` rows. `replay`
   answers the head's sequence, and both tables hold what they held.
2. **Rebuild and swap.** `rebuild_projections(REBUILD)` swaps, and reports
   `games_playergame` and `games_playthrough` each with no row only live, none
   only rebuilt and none differing.
3. **Idempotency.** Every command of the stream is dispatched a second time
   under its original key. The head does not move, no event is appended, both
   tables are unchanged, and the library holds one
   `LibraryIdempotencyRecord` per key.
4. **Display numbers.** `numbered_for` answers a number per run id. The map is
   read before the rebuild and after it, and the two are equal.
   `tests/test_playthrough_numbering.py` holds this for one game's runs; here
   it is read across the whole library, after a swap that reinserted every row.

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

The gate builds legacy rows, runs the conversion, and puts the resulting
stream through legs 1 and 2 above. `tests/test_playthrough_conversion.py`
holds what the conversion writes; this holds that what it wrote replays.

## The benchmark

`seed_library` appends two events per game — `PLAYERGAME_CREATED` and
`PLAYTHROUGH_CREATED`, under one `correlation_id`, in the order and shape
`TrackGame` writes since #679. The seeded aggregate identity of the run is
minted with the event, as the command mints it.

`--seed N` keeps counting **events**, not games, so the run stays comparable
with the recording in [Event benchmarks](../../event-benchmarks.md): the same
100,000 seeded events, over half as many games, across both tables. The seed
writes `N // 2` pairs and refuses an `N` below two.

| reads | before | after |
|---|---|---|
| `--seed 100000` | 100,000 games, 100,000 events | 50,000 games, 100,000 events |
| seeded projection rows | 100,000 in one table | 50,000 in each of two |
| catalog rows | one per event | one per pair |
| `_SEEDED_TABLES` | five tables | six, with `Playthrough` |

`SeedReport` keeps `events` as the appended count, so `events_per_second`
means what it meant. It gains `games`, because the two numbers are no longer
the same and the estimate the command prints before a run reads the catalog
one.

No budget constant moves on argument. `COMMAND_BUDGET_SECONDS` gates
`TrackGame`, which has appended both events since #679, so its measurement
already covers both families. `rebuild_budget` scales its limit by the events
replayed, and that count is unchanged, so the recorded 60.492 s allowance for
100,820 events is the allowance again — against a replay that now writes two
tables rather than one. `make bench ARGS="--gate"` is re-run with and without
`--no-count-replay`, as the recording was, and both numbers go under Evidence
below and into `docs/event-benchmarks.md`, whose parity section states the
seeded rows land in one table. A missed budget is a finding, not a licence to
raise the limit.

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
goes. Nothing outside tests calls the command: two test helpers pass the
positional argument today, in `tests/test_projection_rebuild.py` and
`tests/test_reference_reconciliation.py`, and both state `--library` instead.
The CLAUDE.md command table gains the new target beside `make bench`.

`--check` already replays, diffs and writes nothing. Over several libraries it
reports each in turn and exits non-zero if any drifted, so a run over a
restored copy needs no UUID looked up by hand.

`make verify-replay-parity` runs `--all-libraries --check`. It is read-only,
and it is not in `make check`: it needs a database with a stream in it.

## Verification

The gate is the full `make check`, over:

- the four legs above, on the command-built stream;
- legs 1 and 2 on the conversion-built stream;
- the coverage guard, and a proof that it fails: a stream missing one
  registered event type is refused, and the refusal names that type;
- the second library's rows unchanged by every replay, rebuild and swap;
- `seed_library` writing one `PlayerGame` and one `Playthrough` per seeded
  game, both under one `correlation_id`;
- the seeded library rebuilding with both tables swapped and no row differing;
- each scope flag of `rebuild_projections`, its mutual exclusion, an unknown
  user, an unknown library, a library id that is no UUID, and
  `--all-libraries` over two libraries where one drifted.

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
| `bench` command latency | | |
| `bench` rebuild seconds | | |
| `bench` work per event | | |
| restored copy, libraries checked | | |
| restored copy, rows differing | | |

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
