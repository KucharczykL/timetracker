# Shadow projection rebuild and swap

Issue [#667](https://github.com/KucharczykL/timetracker/issues/667). The code is
in `games/events/rebuild.py`.

## The function and the command

`rebuild_projections(library, *, mode, wiring, apps)` rebuilds the projections
of one library from its events. The default mode is `CHECK`; `REBUILD` writes.
The function returns a `RebuildReport`.

`manage.py rebuild_projections <library-uuid> [--check]` prints the report. The
command exits with an error when a rebuild does not swap.

## The five phases

Each attempt has five phases:

1. Make an empty shadow table for each projection table.
2. Replay the events into the shadow tables. Keep the write guard on.
3. Compare the shadow rows with the live rows of this library.
4. In `REBUILD` mode, swap the rows under the stream lock.
5. Drop the shadow tables. This phase runs on all paths.

`CHECK` stops after phase 3. It reads the stream head again into the report.
The head can move, because `CHECK` takes no lock, so the diff is advisory.

## The rules

- A shadow table is a temp table:
  `CREATE TEMP TABLE "<table>__shadow" (LIKE "<table>" INCLUDING ALL)`.
  `INCLUDING ALL` copies the defaults, the checks, the generated columns and the
  indexes. It does not copy the foreign keys.
- A temp table is private to its connection, so two libraries can rebuild at
  once. All five phases use one connection.
- The write guard is an allowlist in `connection.execute_wrapper`. A statement in
  phase 2 writes a shadow table only; any other target raises
  `LiveWriteRefused`. Two limits stay: the guard reads the statement text, and it
  does not see a second connection.
- The diff is a `FULL OUTER JOIN` with whole-row
  `(live.*) IS DISTINCT FROM (shadow.*)`. This form is safe with NULL values.
  Keep the library scope in a subquery: in a `WHERE` clause it hides the rows
  only the shadow has.
- The swap does one `DELETE` and one `INSERT ... SELECT` for each table, in one
  transaction. Before the first write, `lock_stream` locks the stream and
  `require_sequence` compares the head with `folded_through`. The order of the
  tables is not important, because Django makes its foreign keys deferrable.
- An event that lands during the work makes `require_sequence` raise
  `StreamSequenceMismatch`. The full attempt then runs again with a new shadow.
  Do not use `run_in_transaction` here. It sorts errors by SQLSTATE and refuses
  this one.
- A shadow twin joins the registry of its live model and stays there, so each
  relation uses `related_name="+"` and `on_delete=DO_NOTHING`. The deletion
  collector reads hidden relations and skips `DO_NOTHING` only. A different rule
  makes a later delete of a live row read a temp table that is gone.
- A projection model subclasses `ProjectionModel`. Each row is a pure function of
  the events, so the model must not have an automatic primary key, a
  `db_default`, or a clock default.

This issue adds no migration and changes no schema.
