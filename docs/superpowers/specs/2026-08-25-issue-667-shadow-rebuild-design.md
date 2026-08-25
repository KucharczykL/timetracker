# Shadow projection rebuild and swap

Issue [#667](https://github.com/KucharczykL/timetracker/issues/667). The code is
in `games/events/rebuild.py`.

## The function and the command

`rebuild_projections(library, *, mode, wiring, apps)` builds the projections of
one library again from the events of that library. The default mode is `CHECK`.
`REBUILD` is the mode that writes. The function returns a `RebuildReport`.

`manage.py rebuild_projections <library-uuid> [--check]` prints the report. The
command exits with an error when a rebuild does not swap.

## The five phases

Each attempt has five phases:

1. Make an empty shadow table for each projection table.
2. Replay the events into the shadow tables. Keep the write guard on.
3. Compare the shadow rows with the live rows of this library.
4. In `REBUILD` mode, swap the rows under the stream lock.
5. Drop the shadow tables. This phase runs on all paths.

`CHECK` mode stops after phase 3. It reads the stream head again and puts the
head into the report. The head can move, because `CHECK` takes no lock. If the
head moved, the diff is advisory.

## The rules

- A shadow table is a temp table:
  `CREATE TEMP TABLE "<table>__shadow" (LIKE "<table>" INCLUDING ALL)`.
  `INCLUDING ALL` copies the defaults, the checks, the generated columns and the
  indexes. It does not copy the foreign keys.
- A temp table is private to its connection. Thus two libraries can rebuild at
  the same time. All five phases use one connection.
- The write guard is an allowlist in `connection.execute_wrapper`. A statement in
  phase 2 can write a shadow table only. For any other target, the guard raises
  `LiveWriteRefused`. Two limits stay: the guard reads the statement text, and it
  does not see a second connection.
- The diff is a `FULL OUTER JOIN` with whole-row
  `(live.*) IS DISTINCT FROM (shadow.*)`. This form is safe with NULL values.
  Keep the library scope in a subquery. In a `WHERE` clause, the scope hides the
  rows that only the shadow has.
- The swap does one `DELETE` and one `INSERT ... SELECT` for each table, in one
  transaction. Before the first write, `lock_stream` locks the stream and
  `require_sequence` compares the head with `folded_through`. The order of the
  tables is not important, because Django makes its foreign keys deferrable.
- An event that lands during the work makes `require_sequence` raise
  `StreamSequenceMismatch`. The full attempt then runs again with a new shadow.
  Do not use `run_in_transaction` here. It sorts errors by SQLSTATE and refuses
  this one.
- A projection model is a subclass of `ProjectionModel`. Each row must be a pure
  function of the events. Thus a projection model must not have an automatic
  primary key, a `db_default`, or a clock default.

This issue adds no migration and changes no schema.
