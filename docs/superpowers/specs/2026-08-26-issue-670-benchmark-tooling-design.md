# Command, replay, and projector benchmarks

Issue [#670](https://github.com/KucharczykL/timetracker/issues/670). The code is
in the three `games/events/benchmark*.py` modules and in
`games/management/commands/benchmark_events.py`. Run it with `make bench`. The
recorded results are in [Event benchmarks](../../event-benchmarks.md).

The tool uses the real write path: `TrackGame`,
`library.playergame.created`, and the `CURRENT_STATE` projector. There is no
synthetic workload.

## The three scenarios

The command runs them in this sequence.

| Scenario | What it calls | Budget |
|---|---|---|
| `command` | `dispatch(TrackGame(...))`, `iterations` times | 100 ms at p95 |
| `amplification` | the same dispatch, under the statement counter | none |
| `rebuild` | `rebuild_projections(REBUILD)`, under the counter | 60 s for 100,000 events |

The two command scenarios run after the seeding. `TrackGame` refuses a second
track of one game, and its refusal reads the projection. Thus each dispatch needs
its own untracked catalog row, and a full library is the correct condition.

`--warmup` samples are additional to `--iterations`. The tool discards them. A
percentile is a nearest rank on the sorted samples. The tool reports p50, p95
and the maximum, not the mean.

The rebuild runs last. The stream then holds events from `LockedStream.append`
and events from `dispatch`. One diff shows parity for the two write paths.

## Seeding and teardown

`--seed N` makes a scratch user, a catalog of `Game` rows, and `N` events in
batches of 1,000. Each batch is one transaction and one `append()` call. The
command prints a time estimate first.

The teardown calls `delete_user_library`. A second copy of the cascade in SQL
can disagree with `on_delete`. `--keep` holds the library and prints the command
that removes it.

`--library <uuid>` measures a library that exists. That mode uses `CHECK`, seeds
nothing, and writes no permanent row. `--seed` and `--library` together are an
error.

## The verdicts

A budget gives `PASSED`, `MISSED` or `NOT_GATED`. The rebuild budget scales on
`folded_through`. Below 2,000 folded events, or below 20 samples, the tool
reports the measurement but no verdict. Linear scaling is verified from 2,000
events up.

`--gate` exits non-zero on `MISSED`. A rebuild diff that is not empty exits
non-zero always. A rebuild that is quick and wrong is not a measurement.

## Cost per event

A `connection.execute_wrapper` counts each statement and each affected row, per
table. Statements that name no table go in the total only. A savepoint or a
lock names no table, so a count per table alone hides the cost.

`write_targets` in `games/events/rebuild.py` parses the targets, and the
shadow-write guard uses the same function. A statement against
`<table>__shadow` counts as a statement against `<table>`.

`--no-count-fold` removes the counter from the rebuild. Use it when a verdict lands
inside the cost of the instrument.

## Limits

The tool measures one process: no concurrency and no query path. There is no
bulk scenario, because no bulk command exists. In its place the tool reports the
append rate of the seeding, which has no budget.

`replay()` opens a server-side cursor. A transaction-pooling pooler closes it. A
cursor error gives a message that names issue #917.
