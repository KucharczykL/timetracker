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

`make bench ARGS="--gate"`, 2026-08-26:

```
About to create a scratch user, 100000 events and 100410 catalog rows, then remove them. Estimate: 1.6 minute(s).
Linux-6.18.45-x86_64-with-glibc2.42, 32 CPU(s), Python 3.14.2, PostgreSQL 18.6.
  shared_buffers 128MB, work_mem 4MB, DEBUG True.
  scratch user benchmark-01a03eb3-13e3-7741-a07a-28e3fc883303
Seed: 100000 event(s) in 26.57s (3,764 event/s), 100410 catalog row(s) in 7.11s.
  The event/s figure is a bulk append, not a command.
Command: 200 sample(s), p50 3.9ms, p95 4.5ms, max 7.9ms.
Per command: 9.0 statement(s), 1.0 to projections (1.0 row(s)), 4.0 to the event store (4.0 row(s)), over 200 event(s).
    games_libraryevent: 200 statement(s), 200 row(s)
    games_libraryeventreference: 200 statement(s), 200 row(s)
    games_libraryeventstreamhead: 200 statement(s), 200 row(s)
    games_libraryidempotencyrecord: 200 statement(s), 200 row(s)
    games_playergame: 200 statement(s), 200 row(s)
Per replayed event: 1.0 statement(s), 1.0 to projections (3.0 row(s)), 0.0 to the event store (0.0 row(s)), over 100410 event(s).
    games_playergame: 2 statement(s), 200820 row(s)
    games_playergame__shadow: 100410 statement(s), 100410 row(s)
Rebuild: replayed 100410 event(s) through 1 table(s) in 16.26s over 1 attempt(s).
    attempt 1: replay 15.31s, diff 0.07s, swap 0.87s
    games_playergame: 100410 live, 100410 rebuilt, no difference
Teardown: 50.42s.
command p95: 0.005s against 0.100s -- passed
rebuild: 16.258s against 60.246s -- passed
```

## The rebuild verdict

**Passed, with three quarters of the budget unspent.** The budget for 100,410
events is 60.246 s; the run took 16.258 s.

The previous recording took 60.223 s and passed by 23 milliseconds. Issue
**#930** named the reason: the handler was an `update_or_create`, which PostgreSQL
saw as `SAVEPOINT`, `SELECT ... FOR UPDATE`, `SAVEPOINT`, `INSERT`, `RELEASE`,
`RELEASE`. Five of those six statements searched a shadow table that a replay
starts empty. The handler is now one `INSERT ... ON CONFLICT (id) DO UPDATE`, and
the replay phase alone fell from 59.24 s to 15.31 s.

The run was repeated with the statement counter switched off, as the previous
recording was:

```
make bench ARGS="--gate --no-count-replay"

Rebuild: replayed 100410 event(s) through 1 table(s) in 16.59s over 1 attempt(s).
    attempt 1: replay 15.57s, diff 0.07s, swap 0.95s
    games_playergame: 100410 live, 100410 rebuilt, no difference
rebuild: 16.591s against 60.246s -- passed
```

Uninstrumented, the replay takes **16.59 s** — slower than the instrumented run,
which is what run-to-run noise looks like. At 6 statements an event
`connection.execute_wrapper` cost 600,000 Python calls and was worth separating
from the verdict; at 1 it costs 100,410 and no longer shows.

Read the number the way the previous recording asked to be read: **one projector
family costs a quarter of the 60-second rebuild budget, not all of it.** That is
the whole point of the change. JOURNAL and STATS are the two families the charter
still expects, and nothing here promises they cost as little — a family that
reads before it writes pays for the read. What the budget now has is room to
measure them in, rather than a deficit to argue about.

## Parity

`games_playergame: 100410 live, 100410 rebuilt, no difference` is the evidence
issue **#601** asks for: replaying every event from the log reproduces the live
projection row for row, column for column, with an empty `FULL OUTER JOIN` diff.

It holds across both write paths. The 100,000 seeded events were appended in
batches through `LockedStream.append`; the 410 that follow were written one at a
time through `dispatch`, with its idempotency record and its own transaction.
The replay cannot tell them apart, which is the point.

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
| Command p50 / p95 / max | 3.9 ms / 4.5 ms / 7.9 ms, against a 100 ms budget |
| Statements per command | 9 — 4 to the event store, 1 to the projection, the rest lookups and transaction control |
| Statements per replayed event | 1.00 |
| Rows per replayed event | 1 |
| Rebuild fixed cost | 13 statements, independent of the event count |

The per-event replay cost is a **slope, not an average**. Measured at three sizes,
the replay executes `1 × events + 13` statements exactly, so a 10-event rebuild
averages 2.3 statements per event and a 100,410-event rebuild averages 1.0. Two
of the 13 fixed statements are the swap itself, which is why a small rebuild's
`games_playergame` line reports 2 statements against a shadow table's many.

The command line counts a whole `dispatch`: the append, the reference rows, the
stream head, the idempotency record, and the synchronous handlers. It is the number
the 100 ms budget judges, and it is 22× under it.

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
| The replay, which also reads and dispatches the events | 15.31 s |

Two gaps, and they are different problems. **9.29 s** separates the two write
shapes: that is round trips and one SQL compilation per call, bought by batching
alone. **4.84 s** separates the second from the real replay: reading
`LibraryEvent` rows, `RecordedEvent.from_row`, payload validation, and the
registry dispatch — per-event Python that batching does not touch. So the
ceiling on a batched replay is roughly 6 s against today's 15.31 s, and no
arrangement of statements goes below it.

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
numbers, for when a second projector family makes the budget tight again.

## Seeding, which has no budget

`3,764 event/s` is a **bulk append measurement, not a command measurement**. It
comes from `LockedStream.append` writing 1,000 events per transaction, which no
user-facing path does. There is no bulk command to measure yet, so there is no
budget to compare it against; it is recorded because it sets how long seeding
takes, and seeding is a third of the run.

The seed ends with an `ANALYZE` of the six tables it wrote, so the time above
includes it.

## Teardown

`50.42s` deletes roughly 400,000 rows — the events, their reference rows, the
catalog, and the projections — through the same `purge_user_library` command an
operator would use. A raw-SQL cascade would be faster and would be a second
thing that can drift from `on_delete`, so the benchmark pays the time.
