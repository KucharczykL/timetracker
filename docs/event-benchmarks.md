# Event benchmarks

The recorded output of `make bench`. It is a record of one machine on one day,
not a document to edit: to change a number here, run the tool again and paste
what it prints.

```
make bench                                   # 100,000 events, about 3 minutes
make bench ARGS="--seed 2000 --iterations 25" # the smoke size, about 4 seconds
make bench ARGS="--gate"                     # exit non-zero on a missed budget
make bench ARGS="--library <uuid>"           # check an existing library, read-only
```

`make bench` is deliberately **not** part of `make check`. CI runs on 4 vCPU,
where a timing gate turns a green machine red, and a three-minute command has no
business in the gate.

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
About to create a scratch user, 100000 events and 100410 catalog rows, then remove them. Estimate: 2.9 minute(s).
Linux-6.18.45-x86_64-with-glibc2.42, 32 CPU(s), Python 3.14.2, PostgreSQL 18.6.
  shared_buffers 128MB, work_mem 4MB, DEBUG True.
  scratch user benchmark-01a03e03-4455-724f-b092-e154c5a27917
Seed: 100000 event(s) in 65.34s (1,530 event/s), 100410 catalog row(s) in 7.01s.
  The event/s figure is a bulk append, not a command.
Command: 200 sample(s), p50 4.3ms, p95 4.9ms, max 5.1ms.
Per command: 14.0 statement(s), 1.0 to projections (1.0 row(s)), 4.0 to the event store (4.0 row(s)), over 200 event(s).
    games_libraryevent: 200 statement(s), 200 row(s)
    games_libraryeventreference: 200 statement(s), 200 row(s)
    games_libraryeventstreamhead: 200 statement(s), 200 row(s)
    games_libraryidempotencyrecord: 200 statement(s), 200 row(s)
    games_playergame: 200 statement(s), 200 row(s)
Per folded event: 6.0 statement(s), 1.0 to projections (3.0 row(s)), 0.0 to the event store (0.0 row(s)), over 100410 event(s).
    games_playergame: 2 statement(s), 200820 row(s)
    games_playergame__shadow: 100410 statement(s), 100410 row(s)
Rebuild: folded 100410 event(s) through 1 table(s) in 60.23s over 1 attempt(s).
    attempt 1: replay 59.24s, diff 0.07s, swap 0.91s
    games_playergame: 100410 live, 100410 rebuilt, no difference
Teardown: 52.47s.
command p95: 0.005s against 0.100s -- passed
rebuild: 60.223s against 60.246s -- passed
```

## The rebuild verdict

**Passed, by 23 milliseconds in 60 seconds.** The budget for 100,410 events is
60.246 s; the run took 60.223 s. A margin of 0.04% is a coin toss, not a result,
so the run was repeated with the statement counter switched off:

```
make bench ARGS="--gate --no-count-fold"

Rebuild: folded 100410 event(s) through 1 table(s) in 58.27s over 1 attempt(s).
    attempt 1: replay 57.28s, diff 0.07s, swap 0.91s
    games_playergame: 100410 live, 100410 rebuilt, no difference
rebuild: 58.262s against 60.246s -- passed
```

Uninstrumented, the fold takes **58.26 s against 60.25 s** — met by 3.3%. Both
numbers are recorded because the instrumented one is what `--gate` measures by
default, and it is deliberately conservative: `connection.execute_wrapper` runs
per statement, and at 6 statements per event that is 600,000 Python calls
charged to the time being judged.

Read either number the same way: **one projector family consumes the whole
60-second rebuild budget.** The second family will miss it. The charter says how
that is answered — "a phase may revise a number only with a recorded benchmark
and an explicit design review" — and this document is the recorded benchmark
that clause presumes. Issue **#930** is the standing lead on the cheaper fold:
during a replay the shadow table starts empty, so five of the fold's six
statements are a `SELECT ... FOR UPDATE` that cannot match, wrapped in savepoints
protecting an insert that was never in doubt.

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

## Cost per event

| Measurement | Value |
| --- | --- |
| Command p50 / p95 / max | 4.3 ms / 4.9 ms / 5.1 ms, against a 100 ms budget |
| Statements per command | 14 — 4 to the event store, 1 to the projection, the rest lookups and transaction control |
| Statements per folded event | 6.00 |
| Rows per folded event | 1 |
| Rebuild fixed cost | 13 statements, independent of the event count |

The per-event fold cost is a **slope, not an average**. Measured at two sizes,
the fold executes `6 × events + 13` statements, so a 15-event rebuild averages
6.9 statements per event and a 100,410-event rebuild averages 6.0. Two of the
13 fixed statements are the swap itself, which is why a small rebuild's
`games_playergame` line reports 2 statements against a shadow table's many.

The command line counts a whole `dispatch`: the append, the reference rows, the
stream head, the idempotency record, and the synchronous fold. It is the number
the 100 ms budget judges, and it is 20× under it.

## Seeding, which has no budget

`1,530 event/s` is a **bulk append measurement, not a command measurement**. It
comes from `LockedStream.append` writing 1,000 events per transaction, which no
user-facing path does. There is no bulk command to measure yet, so there is no
budget to compare it against; it is recorded because it sets how long seeding
takes, and seeding is a third of the run.

## Teardown

`52.47s` deletes roughly 400,000 rows — the events, their reference rows, the
catalog, and the projections — through the same `delete_user_library` command an
operator would use. A raw-SQL cascade would be faster and would be a second
thing that can drift from `on_delete`, so the benchmark pays the time.
