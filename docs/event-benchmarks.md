# Event benchmarks

The recorded output of `make bench`. It is a record of one machine on one day,
not a document to edit: to change a number here, run the tool again and paste
what it prints.

```
make bench                                   # 100,000 events, about 1.7 minutes
make bench ARGS="--seed 2000 --iterations 25" # the smoke size, about 4 seconds
make bench ARGS="--gate"                     # exit non-zero on a missed budget
make bench ARGS="--library <uuid>"           # check an existing library, read-only
```

`--seed` counts **events**, and the seed writes three a game — the pair
`TrackGame` appends since #679, then one finished session on the run — so
`--seed 100000` seeds 33,333 games. A count not divisible by three seeds one
or two events fewer.

`make bench` is deliberately **not** part of `make check`. CI runs on 4 vCPU,
where a timing gate turns a green machine red, and a command that runs for
minutes has no business in the gate.

## The machine

Nothing in the repository defined "the development machine" before this run.
This block is that definition, and every number below is only true of it.

```
Linux-6.18.45-x86_64-with-glibc2.42, 32 CPU(s), Python 3.14.2, PostgreSQL 18.6.
  shared_buffers 128MB, work_mem 4MB, DEBUG True.
```

The PostgreSQL cluster is the loopback-only one `make ensure-postgres`
provisions, at its stock settings. `DEBUG True` means Django keeps a query log,
which costs the run something and is reported rather than tuned away.

## The recorded run

`make bench`, 2026-09-05, the first recording with two projection tables. The
seed wrote one event a game then; #688 made it two, so the row counts below
describe a seed this repository no longer has. The run under **The #688
recording** replaces it.

```
About to create a scratch user, 100000 events and 100410 catalog rows, then remove them. Estimate: 1.6 minute(s).
Linux-6.18.45-x86_64-with-glibc2.42, 32 CPU(s), Python 3.14.2, PostgreSQL 18.6.
  shared_buffers 128MB, work_mem 4MB, DEBUG True.
  scratch user benchmark-01a0704e-f16c-7049-b796-54b1cdc47e7a
Seed: 100000 event(s) in 27.76s (3,602 event/s), 100410 catalog row(s) in 7.76s.
  The event/s figure is a bulk append, not a command.
Command: 200 sample(s), p50 4.3ms, p95 4.9ms, max 7.9ms.
Per command: 10.0 statement(s), 2.0 to projections (2.0 row(s)), 4.0 to the event store (5.0 row(s)), over 200 event(s).
    games_libraryevent: 200 statement(s), 400 row(s)
    games_libraryeventreference: 200 statement(s), 200 row(s)
    games_libraryeventstreamhead: 200 statement(s), 200 row(s)
    games_libraryidempotencyrecord: 200 statement(s), 200 row(s)
    games_playergame: 200 statement(s), 200 row(s)
    games_playthrough: 200 statement(s), 200 row(s)
Per replayed event: 1.0 statement(s), 1.0 to projections (3.0 row(s)), 0.0 to the event store (0.0 row(s)), over 100820 event(s).
    games_playergame: 2 statement(s), 200820 row(s)
    games_playergame__shadow: 100410 statement(s), 100410 row(s)
    games_playthrough: 2 statement(s), 820 row(s)
    games_playthrough__shadow: 410 statement(s), 410 row(s)
Rebuild: replayed 100820 event(s) through 2 table(s) in 18.03s over 1 attempt(s).
    attempt 1: replay 16.78s, diff 0.09s, swap 1.15s
    games_playergame: 100410 live, 100410 rebuilt, no difference
    games_playthrough: 410 live, 410 rebuilt, no difference
Teardown: 23.82s.
command p95: 0.005s against 0.100s -- passed
rebuild: 18.015s against 60.492s -- passed
```

The event count moved because #679 made `TrackGame` two events: the 200
commands the scenario dispatches append 400, and each states one `PlayerGame`
row and one `Playthrough` row. In the recording above the 100,000 seeded events
were appended directly and stated one row each, which is why the second table
holds 410 rows against the first table's 100,410. #688 gave the seed the same
pair, so both tables now hold half the seeded event count.

## The rebuild verdict

**Passed, with three quarters of the budget unspent.** The budget for 100,820
events is 60.492 s; the run took 18.015 s.

The previous recording took 60.223 s and passed by 23 milliseconds. Issue
**#930** named the reason: the handler was an `update_or_create`, which PostgreSQL
saw as `SAVEPOINT`, `SELECT ... FOR UPDATE`, `SAVEPOINT`, `INSERT`, `RELEASE`,
`RELEASE`. Five of those six statements searched a shadow table that a replay
starts empty. The handler is now one `INSERT ... ON CONFLICT (id) DO UPDATE`, and
the replay phase alone fell from 59.24 s to 15.31 s. The conflict target has
since become the `(id, library_id)` pair; the figures predate it.

The run was repeated with the statement counter switched off, as the previous
recording was:

```
make bench ARGS="--gate --no-count-replay"

Rebuild: replayed 100820 event(s) through 2 table(s) in 17.48s over 1 attempt(s).
    attempt 1: replay 16.23s, diff 0.09s, swap 1.17s
    games_playergame: 100410 live, 100410 rebuilt, no difference
    games_playthrough: 410 live, 410 rebuilt, no difference
rebuild: 17.476s against 60.492s -- passed
```

Uninstrumented, the replay takes **17.48 s** — half a second under the
instrumented run, which is what run-to-run noise looks like at this scale. At 6
statements an event `connection.execute_wrapper` cost 600,000 Python calls and
was worth separating from the verdict; at 1 it costs 100,820 and no longer
shows.

Read the number the way the previous recording asked to be read: **the whole
CURRENT_STATE family costs a quarter of the 60-second rebuild budget, not all of
it.** #679 put a second projector in that family and the replay moved from
15.31 s to 16.78 s, which is the shape the budget was left room for. JOURNAL and
STATS are the two families the charter still expects, and nothing here promises
they cost as little — a family that reads before it writes pays for the read.

## Parity

`games_playergame: 100410 live, 100410 rebuilt, no difference` is the evidence
issue **#601** asks for: replaying every event from the log reproduces the live
projection row for row, column for column, with an empty `FULL OUTER JOIN` diff.
The `games_playthrough` line beside it says the same of the second table, whose
rows carry a foreign key to the first and four generated columns.

It holds across both write paths. The 100,000 seeded events were appended in
batches through `LockedStream.append`; the 820 that follow were written two at a
time through `dispatch`, with its idempotency record and its own transaction.
The replay cannot tell them apart, which is the point. Since #688 the seeded
batches append the same pair the commands do, so the two paths differ in
batching alone.

A non-empty diff is a hard failure: `benchmark_events` exits non-zero and prints
that the timings are real and the claim they support is not. A rebuild that is
fast and wrong is not a passing benchmark.

## Why the seed runs ANALYZE

`seed_library` ends with an `ANALYZE` of the tables it wrote. Without it the
command scenario measures the planner's ignorance instead of the write path. The
tables are named rather than left to a bare `ANALYZE`, which would rewrite
statistics for a whole database the benchmark never touched — `make bench` runs
against `DATABASE_URL`, which is a real one.

The duplicate check inside `TrackGame` —
`PlayerGame.objects.filter(library=..., game=...)` — has two indexes to choose
between. A benchmark library owns every projection row, so `library_id` matches
all 100,000 of them and `game_id` matches one. Told nothing, the planner chose
`library_id`:

```
Index Scan using games_playergame_library_id_e0dfda83
  Rows Removed by Filter: 100000
  Buffers: shared hit=1100
  Execution Time: 6.238 ms
```

After `ANALYZE` the same query reads 4 buffers in 0.009 ms, and the command p50
falls from 8.6 ms to 3.9 ms.

Which plan a run got used to depend on how long its seed took. Autovacuum wakes
once a minute; the previous recording's seed ran for 65 s, so an autoanalyze
fired inside it and the command was measured against statistics that described
the data. The cheaper handler seeds in 26 s, finishes inside one naptime, and first
recorded **8.6 ms** — a command latency twice the old one, produced entirely by
making the handler five statements cheaper. The seed now analyzes what it wrote, so
the number stops depending on that race.

## Cost per event

| Measurement | Value |
| --- | --- |
| Command p50 / p95 / max | 5.2 ms / 6.0 ms / 6.4 ms, against a 100 ms budget |
| Statements per command | 10 — 4 to the event store, 2 to the projections, the rest lookups and transaction control |
| Statements per replayed event | 1.00 |
| Rows per replayed event | 1 |
| Rebuild fixed cost | 16 statements, independent of the event count |

The per-event replay cost is a **slope, not an average**. Measured at three sizes,
the replay executes `1 × events + 16` statements exactly, so a 50-event rebuild
averages 1.4 statements per event and a 100,820-event rebuild averages 1.0. The
fixed cost is three statements higher than the one-table recording, because a
second table is created, diffed and swapped; two of them are that table's swap,
which is why a small rebuild's `games_playthrough` line reports 2 statements
against a shadow table's many.

#689 adds a third table, so this fixed cost grows again. A library with no
session writes no row into `games_playersession__shadow` and the shadow names
no statement at all, while the live table still takes its swap: two statements
more per rebuild, whatever the event count. No recording below was taken again
for it; `tests/test_event_benchmark.py` measures the shape directly, and the
per-event slope is unchanged because nothing here replays a session yet.

The command line counts a whole `dispatch`: the append, the reference rows, the
stream head, the idempotency record, and the synchronous handlers. Since #679 it
also counts the second event `TrackGame` appends and the second projection row
that event states — one statement more than the one-table recording, for one act
that now records two facts. It is the number the 100 ms budget judges, and it is
20× under it.

`project()` refuses a call that names less than the whole row, and pays for the
check per event. Measured directly: 19 ms for 100,410 calls, or 0.19 µs each. The
columns a model requires are resolved once and held per model, which is why a
rule enforced on every event does not appear in the rebuild time.

## What a batched replay would buy

One statement an event is a floor, not the floor: anything cheaper has to write
more than one row a statement. The measurement below is what a perfectly batched
replay could not beat — the same 100,410 rows, the same
`INSERT ... ON CONFLICT` into the same shadow table, in one transaction, with no
events read and no handlers called.

| Writing 100,410 shadow rows | Time |
| --- | --- |
| 500 rows a statement, 201 statements | 1.18 s |
| 1 row a statement, 100,410 statements | 10.47 s |
| The replay, which also reads and dispatches the events | 16.78 s |

Two gaps, and they are different problems. **9.29 s** separates the two write
shapes: that is round trips and one SQL compilation per call, bought by batching
alone. **6.31 s** separates the second from the real replay: reading
`LibraryEvent` rows, `RecordedEvent.from_row`, payload validation, and the
registry dispatch — per-event Python that batching does not touch. So the
ceiling on a batched replay is roughly 7 s against today's 16.78 s, and no
arrangement of statements goes below it. The two write-shape rows are the
`games_playergame` shadow table alone. In the recording above the 410
`games_playthrough` rows beside it were inside the replay figure and too few to
move it; since #688 that table holds half the seeded rows, so a re-measurement
of the ceiling has to write both.

**Batching would not change a single handler.** `ProjectionTarget` already owns
where a family writes — `LIVE_TARGET` returns the model, `ShadowTarget` returns
its temp twin — and `Projector.project` asks the target for the model before it
writes. A target that buffers rows and flushes them in chunks is a third
implementation of that one method's contract. Handlers do not have to return
rows, and `_created` reads the same either way.

Two conditions bound it, both already visible in the code:

- **A family that reads current state must see what an earlier family wrote.**
  JOURNAL and STATS run after CURRENT_STATE in the same transaction, so a
  buffering target has to flush before a read reaches the table it is holding
  rows out of.
- **Phase 3 diffs the shadow tables.** `diff_tables` runs a `FULL OUTER JOIN`
  against them, so the last flush has to land before the replay phase returns.

Neither is a new invariant. Both are reasons a buffering target is a piece of
work with a design rather than a patch. Issue **#932** carries it, with these
numbers, for when the budget grows tight again. #679's second projector shares
the CURRENT_STATE family and cost 6.9 s once #688's seed gave both tables their
50,410 rows, so the first family that reads before it writes is still the case
to watch.

## Seeding, which has no budget

`2,971 event/s` is a **bulk append measurement, not a command measurement**. It
comes from `LockedStream.append` writing 1,000 events per transaction, which no
user-facing path does. There is no bulk command to measure yet, so there is no
budget to compare it against; it is recorded because it sets how long seeding
takes, and seeding is a third of the run.

The seed ends with an `ANALYZE` of the seven tables it wrote, so the time above
includes it.

## The #688 recording

Recorded when the gate landed, against the seed that writes both creation
events. Paste what the tool prints; do not edit a number here.

`make bench ARGS="--gate"`, 2026-09-09:

```
About to create a scratch user, 100000 events and 50410 catalog rows, then remove them. Estimate: 1.6 minute(s).
Linux-6.18.49-x86_64-with-glibc2.42, 32 CPU(s), Python 3.14.2, PostgreSQL 18.6.
  shared_buffers 128MB, work_mem 4MB, DEBUG True.
  scratch user benchmark-01a08775-8e8b-750e-a5c0-c611df243f5e
Seed: 100000 event(s) in 33.65s (2,971 event/s), 50410 catalog row(s) in 4.56s.
  The event/s figure is a bulk append, not a command.
Command: 200 sample(s), p50 5.2ms, p95 6.0ms, max 6.4ms.
Per command: 10.0 statement(s), 2.0 to projections (2.0 row(s)), 4.0 to the event store (5.0 row(s)), over 200 event(s).
    games_libraryevent: 200 statement(s), 400 row(s)
    games_libraryeventreference: 200 statement(s), 200 row(s)
    games_libraryeventstreamhead: 200 statement(s), 200 row(s)
    games_libraryidempotencyrecord: 200 statement(s), 200 row(s)
    games_playergame: 200 statement(s), 200 row(s)
    games_playthrough: 200 statement(s), 200 row(s)
Per replayed event: 1.0 statement(s), 1.0 to projections (3.0 row(s)), 0.0 to the event store (0.0 row(s)), over 100820 event(s).
    games_playergame: 2 statement(s), 100820 row(s)
    games_playergame__shadow: 50410 statement(s), 50410 row(s)
    games_playthrough: 2 statement(s), 100820 row(s)
    games_playthrough__shadow: 50410 statement(s), 50410 row(s)
Rebuild: replayed 100820 event(s) through 2 table(s) in 24.91s over 1 attempt(s).
    attempt 1: replay 23.48s, diff 0.10s, swap 1.32s
    games_playergame: 50410 live, 50410 rebuilt, no difference
    games_playthrough: 50410 live, 50410 rebuilt, no difference
Teardown: 19.09s.
command p95: 0.006s against 0.100s -- passed
rebuild: 24.908s against 60.492s -- passed
```

The same run without the statement counter:

```
make bench ARGS="--gate --no-count-replay"

Rebuild: replayed 100820 event(s) through 2 table(s) in 24.74s over 1 attempt(s).
    attempt 1: replay 23.27s, diff 0.10s, swap 1.37s
    games_playergame: 50410 live, 50410 rebuilt, no difference
    games_playthrough: 50410 live, 50410 rebuilt, no difference
rebuild: 24.738s against 60.492s -- passed
```

**Command p95 is 6.0 ms against the 100 ms budget.** Read it as a new baseline
rather than beside the 4.9 ms of the one-family seed: that seed left 100,000
`PlayerGame` rows, this one leaves 50,410, and `TrackGame`'s duplicate check
reads that table
([`games/events/benchmark_workload.py`](../games/events/benchmark_workload.py)).
Half the rows and a slower number is what a second projector costs a command,
not what a smaller table saves it.

**The rebuild took 24.91 s against the same 60.492 s allowance.** The event
count did not move — 100,820 either way — so the two recordings' rebuild
seconds compare directly: 18.03 s against 24.91 s, for a replay that now writes
two shadow rows an event instead of one. Uninstrumented it takes 24.74 s, which
is run-to-run noise at this scale.

**One statement an event still, over two tables.** The replay writes 50,410
statements into each shadow table for 100,820 events, so the slope holds at 1.00
and the per-event cost of the second projector is a row, not a statement.

## The #704 recording

Recorded when the session gates landed, against the seed that writes three
events a game: the tracking pair, then one finished hour on the run. Paste
what the tool prints; do not edit a number here.

`make bench ARGS="--gate"`, 2026-09-15:

```
About to create a scratch user, 100000 events and 33743 catalog rows, then remove them. Estimate: 1.3 minute(s).
Linux-6.18.49-x86_64-with-glibc2.42, 32 CPU(s), Python 3.14.2, PostgreSQL 18.6.
  shared_buffers 128MB, work_mem 4MB, DEBUG True.
  scratch user benchmark-01a0a61a-5c56-75f6-986c-4607093d7e6d
Seed: 99999 event(s) in 35.11s (2,848 event/s), 33743 catalog row(s) in 2.46s.
  The event/s figure is a bulk append, not a command.
Command: 200 sample(s), p50 4.5ms, p95 4.9ms, max 5.0ms.
Session command: 200 sample(s), p50 3.9ms, p95 4.2ms, max 8.9ms.
Read session_page: 200 sample(s), p50 2.4ms, p95 2.8ms, max 3.3ms.
Read game_playtime_sort: 200 sample(s), p50 126.8ms, p95 129.0ms, max 133.1ms.
Read stats_totals: 200 sample(s), p50 62.3ms, p95 64.9ms, max 76.0ms.
Read stats_by_platform: 200 sample(s), p50 23.6ms, p95 27.8ms, max 30.5ms.
Read stats_by_month: 200 sample(s), p50 41.5ms, p95 45.8ms, max 51.7ms.
Read stats_superlatives: 200 sample(s), p50 273.4ms, p95 286.7ms, max 355.1ms.
Per command: 10.0 statement(s), 2.0 to projections (2.0 row(s)), 4.0 to the event store (5.0 row(s)), over 200 event(s).
    games_libraryevent: 200 statement(s), 400 row(s)
    games_libraryeventreference: 200 statement(s), 200 row(s)
    games_libraryeventstreamhead: 200 statement(s), 200 row(s)
    games_libraryidempotencyrecord: 200 statement(s), 200 row(s)
    games_playergame: 200 statement(s), 200 row(s)
    games_playthrough: 200 statement(s), 200 row(s)
Per replayed event: 1.0 statement(s), 1.0 to projections (3.0 row(s)), 0.0 to the event store (0.0 row(s)), over 101029 event(s).
    games_librarycalendar: 2 statement(s), 0 row(s)
    games_playergame: 2 statement(s), 67486 row(s)
    games_playergame__shadow: 33743 statement(s), 33743 row(s)
    games_playersession: 2 statement(s), 67086 row(s)
    games_playersession__shadow: 33543 statement(s), 33543 row(s)
    games_playthrough: 2 statement(s), 67486 row(s)
    games_playthrough__shadow: 33743 statement(s), 33743 row(s)
Rebuild: replayed 101029 event(s) through 4 table(s) in 28.69s over 1 attempt(s).
    attempt 1: replay 27.35s, diff 0.09s, swap 1.23s
    games_librarycalendar: 0 live, 0 rebuilt, no difference
    games_playergame: 33743 live, 33743 rebuilt, no difference
    games_playersession: 33543 live, 33543 rebuilt, no difference
    games_playthrough: 33743 live, 33743 rebuilt, no difference
Teardown: 14.15s.
command p95: 0.005s against 0.100s -- passed
session command p95: 0.004s against 0.100s -- passed
read session_page p95: 0.003s against 0.020s -- not_gated
read game_playtime_sort p95: 0.129s against 0.020s -- not_gated
read stats_totals p95: 0.065s against 0.020s -- not_gated
read stats_by_platform p95: 0.028s against 0.020s -- not_gated
read stats_by_month p95: 0.046s against 0.020s -- not_gated
read stats_superlatives p95: 0.287s against 0.020s -- not_gated
rebuild: 28.671s against 60.617s -- passed
```

**A second command, at the same budget.** `CreateSession` with a Duration-only
statement runs at 4.2 ms p95, under `TrackGame`'s 5.0 ms: one projection row
instead of two, and a run resolve in place of a duplicate check.

**Six reads, measured on the scratch library and judged on a real one.** The
scratch seed is a shape no library has -- one session on every one of 33,543
games, twelve times the production row count -- so its read numbers are
recorded here as `not_gated` and the 20 ms verdict is given under `--library`,
against a restored dump, which is where the budget was set. `session_page`
runs at 2.6 ms here; the five aggregates run between 23 ms and 287 ms over
33,543 rows, and are what the budget watches on production shape.

**The rebuild took 28.67 s against the 60.6 s allowance**, over three tables
and 101,029 events. The replay writes one statement an event still, into three
shadow tables, so the third projector costs a row, not a statement.

### The production-shape recording

The same tool against the 2026-09-12 production dump, restored with
`make restore-dump` and migrated through the conversion: one library, 2,807
sessions on 718 tracked games. This is the run the read budget is judged on.

`make bench ARGS="--library 01a009fd-5800-7642-900d-1384c2b99ee7 --gate"`,
2026-09-15:

```
Linux-6.18.49-x86_64-with-glibc2.42, 32 CPU(s), Python 3.14.2, PostgreSQL 18.6.
  shared_buffers 128MB, work_mem 4MB, DEBUG True.
Read session_page: 200 sample(s), p50 3.2ms, p95 3.6ms, max 4.5ms.
Read game_playtime_sort: 200 sample(s), p50 6.6ms, p95 8.1ms, max 9.0ms.
Read stats_totals: 200 sample(s), p50 4.8ms, p95 6.4ms, max 10.1ms.
Read stats_by_platform: 200 sample(s), p50 2.3ms, p95 3.0ms, max 3.6ms.
Read stats_by_month: 200 sample(s), p50 3.5ms, p95 4.2ms, max 5.2ms.
Read stats_superlatives: 200 sample(s), p50 10.1ms, p95 12.6ms, max 14.4ms.
Per replayed event: 1.0 statement(s), 1.0 to projections (1.4 row(s)), 0.0 to the event store (0.0 row(s)), over 7057 event(s).
    games_librarycalendar__shadow: 1 statement(s), 1 row(s)
    games_playergame__shadow: 2359 statement(s), 2359 row(s)
    games_playersession__shadow: 2810 statement(s), 5474 row(s)
    games_playthrough__shadow: 1888 statement(s), 1888 row(s)
Rebuild: replayed 7057 event(s) through 4 table(s) in 2.18s over 1 attempt(s).
    attempt 1: replay 2.15s, diff 0.01s, swap -
    games_librarycalendar: 1 live, 1 rebuilt, no difference
    games_playergame: 859 live, 859 rebuilt, no difference
    games_playersession: 2807 live, 2807 rebuilt, no difference
    games_playthrough: 873 live, 873 rebuilt, no difference
read session_page p95: 0.004s against 0.020s -- passed
read game_playtime_sort p95: 0.008s against 0.020s -- passed
read stats_totals p95: 0.006s against 0.020s -- passed
read stats_by_platform p95: 0.003s against 0.020s -- passed
read stats_by_month p95: 0.004s against 0.020s -- passed
read stats_superlatives p95: 0.013s against 0.020s -- passed
rebuild: 2.157s against 4.234s -- passed
```

**Every read passes at 20 ms.** `stats_superlatives` first measured 20.4 ms at
p95, over by 0.4 ms; its three aggregating readers walked from the Game
through four joins and were rewritten to group on the session table and fetch
the one game after, which halved each. The other five never came near.

## The #1099 recording

Recorded when the historical-playtime gates landed. The seed is #704's;
after the session command the run dispatches `IMPORT_SHAPE_RECORDS`, six
hundred `RecordHistoricalPlaytime` commands, one seeded run each, ten hours
at year precision, and analyzes the two record tables before the reads.
Paste what the tool prints; do not edit a number here.

`make bench ARGS="--gate"`, 2026-09-19:

```
About to create a scratch user, 100000 events, 33743 catalog rows and 600 historical playtime records, then remove them. Estimate: 1.3 minute(s).
Linux-6.18.49-x86_64-with-glibc2.42, 32 CPU(s), Python 3.14.2, PostgreSQL 18.6.
  shared_buffers 128MB, work_mem 4MB, DEBUG True.
  scratch user benchmark-01a0b912-4dfa-77e2-b73b-4033f6f2dbaf
Seed: 99999 event(s) in 37.95s (2,635 event/s), 33743 catalog row(s) in 2.37s.
  The event/s figure is a bulk append, not a command.
Command: 200 sample(s), p50 4.4ms, p95 4.8ms, max 5.3ms.
Session command: 200 sample(s), p50 3.9ms, p95 4.3ms, max 4.6ms.
Record command: 600 sample(s), p50 4.5ms, p95 5.0ms, max 6.1ms.
Read session_page: 200 sample(s), p50 2.4ms, p95 2.6ms, max 2.8ms.
Read game_playtime_sort: 200 sample(s), p50 159.1ms, p95 161.3ms, max 162.3ms.
Read stats_totals: 200 sample(s), p50 70.5ms, p95 81.7ms, max 101.5ms.
Read stats_by_platform: 200 sample(s), p50 26.3ms, p95 30.9ms, max 37.7ms.
Read stats_by_month: 200 sample(s), p50 45.6ms, p95 49.2ms, max 58.6ms.
Read stats_superlatives: 200 sample(s), p50 94.7ms, p95 104.0ms, max 112.0ms.
Per command: 10.0 statement(s), 2.0 to projections (2.0 row(s)), 4.0 to the event store (5.0 row(s)), over 200 event(s).
    games_libraryevent: 200 statement(s), 400 row(s)
    games_libraryeventreference: 200 statement(s), 200 row(s)
    games_libraryeventstreamhead: 200 statement(s), 200 row(s)
    games_libraryidempotencyrecord: 200 statement(s), 200 row(s)
    games_playergame: 200 statement(s), 200 row(s)
    games_playthrough: 200 statement(s), 200 row(s)
Per replayed event: 1.0 statement(s), 1.0 to projections (3.0 row(s)), 0.0 to the event store (0.0 row(s)), over 101639 event(s).
    games_historicalplaytime: 2 statement(s), 1220 row(s)
    games_historicalplaytime__shadow: 610 statement(s), 610 row(s)
    games_historicalplaytimerun: 2 statement(s), 1220 row(s)
    games_historicalplaytimerun__shadow: 1220 statement(s), 610 row(s)
    games_librarycalendar: 2 statement(s), 0 row(s)
    games_playergame: 2 statement(s), 67486 row(s)
    games_playergame__shadow: 33743 statement(s), 33743 row(s)
    games_playersession: 2 statement(s), 67086 row(s)
    games_playersession__shadow: 33543 statement(s), 33543 row(s)
    games_playthrough: 2 statement(s), 67486 row(s)
    games_playthrough__shadow: 33743 statement(s), 33743 row(s)
Rebuild: replayed 101639 event(s) through 6 table(s) in 29.97s over 1 attempt(s).
    attempt 1: replay 28.10s, diff 0.10s, swap 1.74s
    games_historicalplaytime: 610 live, 610 rebuilt, no difference
    games_historicalplaytimerun: 610 live, 610 rebuilt, no difference
    games_librarycalendar: 0 live, 0 rebuilt, no difference
    games_playergame: 33743 live, 33743 rebuilt, no difference
    games_playersession: 33543 live, 33543 rebuilt, no difference
    games_playthrough: 33743 live, 33743 rebuilt, no difference
Teardown: 15.00s.
command p95: 0.005s against 0.100s -- passed
session command p95: 0.004s against 0.100s -- passed
record command p95: 0.005s against 0.100s -- passed
read session_page p95: 0.003s against 0.020s -- not_gated
read game_playtime_sort p95: 0.161s against 0.020s -- not_gated
read stats_totals p95: 0.082s against 0.020s -- not_gated
read stats_by_platform p95: 0.031s against 0.020s -- not_gated
read stats_by_month p95: 0.049s against 0.020s -- not_gated
read stats_superlatives p95: 0.104s against 0.020s -- not_gated
rebuild: 29.939s against 60.983s -- passed
```

**A third command, at the same budget.** `RecordHistoricalPlaytime` runs at
5.0 ms p95 over 600 samples, beside `TrackGame`'s 4.8 ms and
`CreateSession`'s 4.3 ms: one record row and one join row, and a run
resolve. The 600 records land on 600 of the 33,543 seeded runs.

**The reads with 610 records present.** Against the #704 recording,
`game_playtime_sort` moved from 129 ms to 161 ms, `stats_totals` from 65 ms
to 82 ms, `stats_by_month` from 46 ms to 49 ms and `stats_by_platform` from
28 ms to 31 ms: every playtime figure sums a second source now. Recorded and
not gated, as before; the verdict is given on production shape below.

**The rebuild took 29.94 s against the 60.98 s allowance**, over six tables
and 101,639 events. The replay still writes one statement an event; the join
table's two rows a record are one statement each.

### The production-shape recording

The 2026-09-19 production dump, restored with `make restore-dump`, migrated
from 0007 through 0011, and converted by `make verify-reclassification-parity`
ahead of the run: one library, 2,819 sessions and 93 records on 861 tracked
games. This is the run the read budget is judged on.

`make bench ARGS="--library 01a009fd-5800-7642-900d-1384c2b99ee7 --gate"`,
2026-09-19:

```
Linux-6.18.49-x86_64-with-glibc2.42, 32 CPU(s), Python 3.14.2, PostgreSQL 18.6.
  shared_buffers 128MB, work_mem 4MB, DEBUG True.
Read session_page: 200 sample(s), p50 3.5ms, p95 3.8ms, max 4.0ms.
Read game_playtime_sort: 200 sample(s), p50 14.8ms, p95 15.9ms, max 16.8ms.
Read stats_totals: 200 sample(s), p50 6.4ms, p95 6.9ms, max 9.1ms.
Read stats_by_platform: 200 sample(s), p50 3.1ms, p95 3.3ms, max 3.6ms.
Read stats_by_month: 200 sample(s), p50 5.2ms, p95 6.2ms, max 19.3ms.
Read stats_superlatives: 200 sample(s), p50 12.8ms, p95 14.0ms, max 15.9ms.
Per replayed event: 1.0 statement(s), 1.0 to projections (1.4 row(s)), 0.0 to the event store (0.0 row(s)), over 7277 event(s).
    games_historicalplaytime__shadow: 93 statement(s), 93 row(s)
    games_historicalplaytimerun__shadow: 186 statement(s), 93 row(s)
    games_librarycalendar__shadow: 1 statement(s), 1 row(s)
    games_playergame__shadow: 2365 statement(s), 2365 row(s)
    games_playersession__shadow: 2925 statement(s), 5592 row(s)
    games_playthrough__shadow: 1894 statement(s), 1894 row(s)
Rebuild: replayed 7277 event(s) through 6 table(s) in 2.34s over 1 attempt(s).
    attempt 1: replay 2.31s, diff 0.01s, swap -
    games_historicalplaytime: 93 live, 93 rebuilt, no difference
    games_historicalplaytimerun: 93 live, 93 rebuilt, no difference
    games_librarycalendar: 1 live, 1 rebuilt, no difference
    games_playergame: 861 live, 861 rebuilt, no difference
    games_playersession: 2819 live, 2819 rebuilt, no difference
    games_playthrough: 875 live, 875 rebuilt, no difference
read session_page p95: 0.004s against 0.020s -- passed
read game_playtime_sort p95: 0.016s against 0.020s -- passed
read stats_totals p95: 0.007s against 0.020s -- passed
read stats_by_platform p95: 0.003s against 0.020s -- passed
read stats_by_month p95: 0.006s against 0.020s -- passed
read stats_superlatives p95: 0.014s against 0.020s -- passed
rebuild: 2.320s against 4.366s -- passed
```

**Every read passes at 20 ms.** Five moved under a millisecond from the #704
recording. `game_playtime_sort` moved from 8.1 ms to 15.9 ms: on this dump
before the conversion it measured 8.9 ms, so the 93 records cost 7 ms, and
they cost it a game rather than a record -- the record leg's correlated
subquery joins through the tracked row and builds a hash for each of the 861
games where the session leg walks an index. #1131 owns bringing the record
leg to the session leg's cost.

**The first run of this recording missed.** It measured `game_playtime_sort`
at 49.1 ms, three times the budget, because it ran straight after the
conversion and before autovacuum had analyzed the two tables the conversion
filled: the planner worked from empty statistics. The parity command
analyzes those tables now, for the reason the seed does, and the analyzed run
is the one pasted above.

## The #713 recording

Recorded when the bulk runner landed. The seed is #704's; after the record
command the run writes `BATCH_SHAPE_SESSIONS` written-down sessions at the
review threshold, converts each through the act's own `run` under one
correlation id -- the runner's loop, not its view -- and analyzes the two
record tables before the reads. `--bulk` states another size. Paste what the
tool prints; do not edit a number here.

Taken at `6c1e6ae9`. `41d9e970` changed how the scenario picks its rows,
which is setup outside the sample window; the timed loop is the same.

`make bench`, 2026-09-20:

```
About to create a scratch user, 100000 events, 33743 catalog rows, 600 historical playtime records and a batch of 600 conversions, then remove them. Estimate: 1.4 minute(s).
Linux-6.18.49-x86_64-with-glibc2.42, 32 CPU(s), Python 3.14.2, PostgreSQL 18.6.
  shared_buffers 128MB, work_mem 4MB, DEBUG True.
  scratch user benchmark-01a0bdb3-cbac-703e-ad50-68790177af0a
Seed: 99999 event(s) in 37.01s (2,702 event/s), 33743 catalog row(s) in 2.32s.
  The event/s figure is a bulk append, not a command.
Command: 200 sample(s), p50 4.7ms, p95 6.4ms, max 8.3ms.
Session command: 200 sample(s), p50 3.9ms, p95 4.3ms, max 7.7ms.
Record command: 600 sample(s), p50 4.5ms, p95 5.3ms, max 9.5ms.
Bulk command: 600 sample(s), p50 6.3ms, p95 7.2ms, max 10.9ms.
Read session_page: 200 sample(s), p50 2.5ms, p95 2.6ms, max 2.8ms.
Read game_playtime_sort: 200 sample(s), p50 177.7ms, p95 180.3ms, max 183.3ms.
Read stats_totals: 200 sample(s), p50 60.9ms, p95 69.2ms, max 75.0ms.
Read stats_by_platform: 200 sample(s), p50 24.1ms, p95 25.3ms, max 29.6ms.
Read stats_by_month: 200 sample(s), p50 43.8ms, p95 47.8ms, max 55.7ms.
Read stats_superlatives: 200 sample(s), p50 87.6ms, p95 94.5ms, max 108.7ms.
Per command: 10.0 statement(s), 2.0 to projections (2.0 row(s)), 4.0 to the event store (5.0 row(s)), over 200 event(s).
    games_libraryevent: 200 statement(s), 400 row(s)
    games_libraryeventreference: 200 statement(s), 200 row(s)
    games_libraryeventstreamhead: 200 statement(s), 200 row(s)
    games_libraryidempotencyrecord: 200 statement(s), 200 row(s)
    games_playergame: 200 statement(s), 200 row(s)
    games_playthrough: 200 statement(s), 200 row(s)
Per replayed event: 1.0 statement(s), 1.0 to projections (3.0 row(s)), 0.0 to the event store (0.0 row(s)), over 103469 event(s).
    games_historicalplaytime: 2 statement(s), 2440 row(s)
    games_historicalplaytime__shadow: 1220 statement(s), 1220 row(s)
    games_historicalplaytimerun: 2 statement(s), 2440 row(s)
    games_historicalplaytimerun__shadow: 2440 statement(s), 1220 row(s)
    games_librarycalendar: 2 statement(s), 0 row(s)
    games_playergame: 2 statement(s), 67486 row(s)
    games_playergame__shadow: 33743 statement(s), 33743 row(s)
    games_playersession: 2 statement(s), 68306 row(s)
    games_playersession__shadow: 34763 statement(s), 34763 row(s)
    games_playthrough: 2 statement(s), 67486 row(s)
    games_playthrough__shadow: 33743 statement(s), 33743 row(s)
Rebuild: replayed 103469 event(s) through 6 table(s) in 30.43s over 1 attempt(s).
    attempt 1: replay 28.52s, diff 0.09s, swap 1.80s
    games_historicalplaytime: 1220 live, 1220 rebuilt, no difference
    games_historicalplaytimerun: 1220 live, 1220 rebuilt, no difference
    games_librarycalendar: 0 live, 0 rebuilt, no difference
    games_playergame: 33743 live, 33743 rebuilt, no difference
    games_playersession: 34153 live, 34153 rebuilt, no difference
    games_playthrough: 33743 live, 33743 rebuilt, no difference
Teardown: 14.73s.
command p95: 0.006s against 0.100s -- passed
session command p95: 0.004s against 0.100s -- passed
record command p95: 0.005s against 0.100s -- passed
bulk command p95: 0.007s against 0.100s -- passed
read session_page p95: 0.003s against 0.020s -- not_gated
read game_playtime_sort p95: 0.180s against 0.020s -- not_gated
read stats_totals p95: 0.069s against 0.020s -- not_gated
read stats_by_platform p95: 0.025s against 0.020s -- not_gated
read stats_by_month p95: 0.048s against 0.020s -- not_gated
read stats_superlatives p95: 0.095s against 0.020s -- not_gated
rebuild: 30.404s against 62.081s -- passed
```

**The most expensive command the bench times.** The reclassification runs at
7.2 ms p95 over 600 samples, beside `TrackGame`'s 6.4 ms,
`RecordHistoricalPlaytime`'s 5.3 ms and `CreateSession`'s 4.3 ms. One row is
two events -- the created record and the reclassified session -- so the gap is
the second append and the second projector, not a slower resolve.

**What a chunk holds.** A chunk is given three seconds and spends it one row
at a time, so at 7.2 ms it reaches about four hundred rows before it renders a
waypoint. A library with more than that walks two requests, which is the case
the correlation id has to survive.

**The batch crosses the gating floor on a small seed.** At `seed=25` the
600 rows take the run to roughly 2,400 events, the rebuild budget starts
being judged, and a scratch rebuild misses it at 1.561 s against 1.465 s.
Nothing under test is slow: the run above passes at 30.4 s against 62.1 s.
The floor assumes the seed's mix, and this one writes two projections a row.
`--bulk` keeps the tests that drive the command small; #1160 owns the floor.

**The reads with 600 more converted rows.** Every read moved with the seed
rather than with the batch: `game_playtime_sort` 161 ms to 180 ms,
`stats_superlatives` 104 ms to 95 ms, `stats_totals` 82 ms to 69 ms. The
scratch seed's reads are measured and never gated, for the reason
`read_budget` states.

## Teardown

`19.09s` deletes roughly 350,000 rows — the events, their reference rows, the
catalog, and both projections — through the same `purge_user_library` command an
operator would use. A raw-SQL cascade would be faster and would be a second
thing that can drift from `on_delete`, so the benchmark pays the time.
