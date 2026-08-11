# One-time SQLite-to-PostgreSQL production cutover

Date: 2026-08-11
Issue: https://github.com/KucharczykL/timetracker/issues/621
Parent phase: https://github.com/KucharczykL/timetracker/issues/600

## Status and purpose

Timetracker has one production SQLite database and one maintainer operating the
cutover. It does not need a supported, reusable SQLite migration product. This
design replaces the planned sequence of transfer-tool issues with one offline,
imperative migration rehearsed against a copy of the real production data.

The outcome is a verified PostgreSQL copy of that database, followed by the
small amount of SQLite compatibility cleanup that is safe only after the
cutover. The migration is not shipped as a management command, retained as a
user-facing upgrade path, or generalized for unknown installations.

## Operating constraints

- A planned maintenance window is acceptable. Timetracker is stopped before
  the final snapshot and remains unavailable until verification succeeds.
- The maintainer supplies a private copy of the production SQLite database for
  rehearsal. The snapshot includes the database and any `-wal`, `-shm`, or
  journal sidecars as one archive. Neither the archive nor data derived from it
  is committed.
- The final PostgreSQL database is created empty. The cutover script refuses a
  target that contained any tables when the run began.
- Before the application reopens for writes, rollback means discarding the
  PostgreSQL database and restarting the old release with the untouched SQLite
  snapshot.
- After PostgreSQL accepts new writes, the cutover is irreversible. Later
  defects are repaired forward; no reverse transfer or dual-write period is
  built.
- A failed or interrupted target is never resumed or cleaned in place. It is
  preserved for investigation or dropped, and the procedure restarts against
  another empty database.

## Scope

The cutover owns these outcomes:

1. Validate the supplied SQLite snapshot's integrity and exact migration
   lineage.
2. Prove the PostgreSQL target was empty before the script changed it.
3. Build the current schema through Timetracker's normal Django migrations.
4. Serialize all production model data through Django and load it into the
   PostgreSQL schema while preserving primary keys and relationships.
5. Recalculate and compare database-generated values.
6. Reset PostgreSQL sequences and produce exact reconciliation evidence.
7. Rehearse the complete procedure against the real production copy before the
   final offline execution.
8. Record the successful cutover without retaining private source data.

The cutover absorbs the outcomes previously assigned to issues #621 through
#626 and #810. PostgreSQL-only runtime cleanup and removal of the squashed
migration's `replaces` list remain post-cutover work, consolidated under one
small cleanup issue.

## Chosen approach

Use an ignored, reviewable Python script that orchestrates Django's existing
migration and serialization machinery. The script is an execution artifact,
not product code. It may be revised while rehearsing against the production
copy, but the final dress rehearsal and production cutover run the same script
unchanged.

An explicit table-by-table copier is the fallback only if rehearsal proves a
real Django serialization defect. It is not designed or implemented in
parallel. External tools such as `pgloader` and the SQLite command-line client
are excluded because they add dependencies and backend-specific coercion
without improving the evidence for this one database.

## Components

### Private cutover workspace

The ignored cutover workspace contains:

- the supplied SQLite snapshot archive and its extracted database/sidecars;
- the temporary cutover script;
- a serialized fixture derived from the snapshot; and
- verification reports from rehearsal and final execution.

The workspace is checked with `git check-ignore` before private data is placed
in it. The final repository status is inspected to prove that neither the
snapshot nor the serialized fixture is tracked.

### Source connection and migration validation

The supplied rehearsal archive
`timetracker-prod-copy-2026.08.11.19.14.zip` has SHA-256
`49b2952f71fec4df42a7bc3c1142c9554d7df0e53dd293cf9532126d318b1777` and
contains `db.sqlite3`, `db.sqlite3-wal`, and `db.sqlite3-shm`. Extraction keeps
those files together in the private workspace.

The script adds a command-scoped, non-default Django SQLite connection. Its
database name is a SQLite URI using `mode=ro`; it deliberately does not use
SQLite's `immutable=1`, because immutable mode may ignore committed data still
present in the WAL. No SQLite configuration is added to Timetracker's runtime
settings. The connection is closed after the run.

Validation uses Django's `MigrationLoader` and `MigrationRecorder` rather than
reimplementing migration-graph semantics. It:

- runs SQLite `PRAGMA quick_check` and requires the result `ok`;
- calls Django's consistent-history check;
- requires all historical `games` migrations `0001` through `0036` to be
  applied;
- accepts the squashed baseline marker as optional, because Django may record
  it after recognizing that every migration it replaces is applied;
- requires every other migrated installed app to be at the exact leaf state
  expected by the code used for the cutover; and
- rejects every unknown, partial, missing, or newer migration record. This
  explicit comparison is required because Django's consistency check ignores
  unknown applied migrations.

The script records cryptographic checksums for the source archive and the
extracted database plus durable `-wal` or journal members before and after the
run and requires them to remain unchanged. The transient `-shm` file is listed
but is not an identity or immutability artifact: SQLite may update or recreate
its shared-memory index while reading the unchanged database and WAL. SQLite
reads the database and its WAL as one consistent read-only snapshot.

### Empty PostgreSQL target and schema creation

The operator creates a new PostgreSQL database with the required Timetracker
PostgreSQL major, encoding, locale provider, and locale. `DATABASE_URL` points
to that database.

Before running migrations, the script uses PostgreSQL introspection to require
that the database contains no tables in the application schema. This check is
the destructive-operation guard: the script does not truncate or load any
database that was not empty when it began.

The script then calls Timetracker's normal Django `migrate` command. This gives
the target the schema corresponding to the running code and preserves its
`django_migrations` records. Migration hooks create deterministic framework
and application seed rows. Before loading production data, the script clears
all registered managed-model tables while leaving `django_migrations` intact.
This removes generated content types, permissions, and bundled exchange rates
that would otherwise collide with the corresponding source rows.

### Serialization and loading

The script serializes every concrete managed model from the SQLite connection
through Django using each model's base manager. It preserves explicit primary
keys, foreign keys, one-to-one relationships, and many-to-many relationships.
It does not use natural primary keys or silently omit models selected by a
custom default manager.

Database-generated fields are removed from the serialized objects based on
Django model metadata. In the current schema these are:

- `Session.duration_calculated`;
- `Session.duration_total`;
- `Purchase.price_per_game`; and
- `PlayEvent.days_to_finish`.

The PostgreSQL database therefore computes those values from their source
columns. Fixture loading uses Django's raw-save path, so existing Timetracker
signals do not create status-history rows or recalculate aggregates once per
loaded object. The script resets every PostgreSQL integer sequence after the
load.

The ordinary Django serialized format is the first and only implementation
attempt. If it cannot round-trip a production value, the rehearsal report must
identify the exact model, primary key, field, and representation before the
design is amended to use a narrower explicit copy path.

## Data flow

The complete rehearsal and final data flow is:

1. Hash the SQLite archive, extract its database and sidecars together, hash
   the database and durable WAL/journal members, and open the database
   read-only.
2. Validate SQLite integrity and the exact pinned migration lineage.
3. Connect to PostgreSQL and enforce the initially-empty target guard.
4. Run current Django migrations on PostgreSQL.
5. Serialize all source models and relationships.
6. Remove generated fields from the serialized records.
7. Clear migration-created model rows from PostgreSQL without clearing
   `django_migrations`.
8. Load the serialized records through Django.
9. Reset integer sequences.
10. Run reconciliation and application smoke checks.
11. Write the verification report and re-hash the unchanged archive, database,
    and durable WAL/journal members.

No step changes the source archive, extracted database, or durable WAL/journal
contents. SQLite may maintain the extracted transient `-shm` index while
reading. No step publishes the serialized fixture or private field values.

## Reconciliation

A run succeeds only when all of these checks pass:

- the SQLite archive, database, and durable WAL/journal checksums are unchanged;
- SQLite `quick_check` reports no corruption;
- source and target migration histories match their required states;
- every concrete model has identical row counts and primary-key sets;
- every many-to-many relationship has identical link counts and endpoint sets;
- canonical per-model digests match after excluding generated fields;
- canonical values are normalized through Django types before hashing, covering
  text, notes, JSON, decimals, booleans, nulls, foreign keys, dates,
  timezone-aware timestamps, and durations;
- each generated value matches the SQLite value by model and primary key after
  PostgreSQL recalculation;
- PostgreSQL reports no foreign-key or constraint violations;
- each integer sequence's next value is greater than the table's maximum
  primary key;
- representative aggregate checks match, including session and manual
  playtime, per-Game playtime, purchase totals and counts, status-history
  counts, users, filter presets, and settings; and
- curated ORM queries and important application pages succeed against the
  migrated target.

The report contains the source archive/member checksums, code revision,
database versions, model and relationship counts, digests, generated-value
results, aggregate results, smoke-check results, timestamps, and overall
status. It contains no notes, names, credentials, settings values, or other
private field contents.

## Error handling

The script exits nonzero on every validation, migration, serialization, load,
or reconciliation failure. Independent reconciliation checks continue where
safe so one run reports all useful mismatches instead of only the first.

The script does not repair data, infer missing values, resume partial work,
merge into a target, or roll a target back. Error output names the failing
stage and the affected model, relationship, or generated field without printing
private values. The PostgreSQL database is then either retained for inspection
or dropped explicitly by the operator.

## Rehearsal and final cutover

The supplied production copy is the primary migration fixture. Before final
cutover:

1. Run the script against the copy and a disposable empty PostgreSQL database.
2. Resolve every evidence-backed serialization or reconciliation discrepancy.
3. Point the script at a deliberately nonempty disposable target and prove it
   refuses to proceed without changing that target.
4. Run a clean dress rehearsal against another empty PostgreSQL database
   without modifying the script.
5. Require successful reports from both clean runs to have identical source
   checksums, model/relationship counts, data digests, generated-value results,
   and aggregate results. Operational timestamps and target identifiers may
   differ.
6. Run the repository's full `make check` gate with its normal Windows worker
   configuration and run the curated application smoke checks.

The final cutover procedure is:

1. Stop Timetracker and its background worker.
2. After SQLite writers have stopped, archive `db.sqlite3` together with any
   `-wal`, `-shm`, or journal sidecars and record the archive, database, and
   durable WAL/journal checksums.
3. Create a new empty PostgreSQL database satisfying the runtime contract.
4. Run the dress-rehearsed script unchanged.
5. Review and retain the successful non-private verification report.
6. Start Timetracker against PostgreSQL without reopening public writes and run
   login, list, detail, session, purchase, settings, filter, and statistics
   smoke checks.
7. Reopen the application for writes and record the irreversible cutover time.
8. Retain the final SQLite snapshot and old deployable release as offline
   rollback artifacts until the maintainer deliberately archives them.

Rollback is permitted only before step 7. After step 7, PostgreSQL is the sole
source of truth and any defect is fixed forward.

## Issue consolidation

After this specification is approved:

- rewrite #621 to own the private script, rehearsal, final cutover, and
  reconciliation evidence described here;
- close #622, #623, #624, #625, #626, and #810 as not planned and superseded by
  #621;
- audit #627 against the current PostgreSQL-only configuration and close it as
  already satisfied if no runtime switch remains;
- after the successful cutover, rescope #628 as the single compatibility
  cleanup issue; and
- absorb #809 into #628 so the same post-cutover cleanup removes the squashed
  migration's `replaces` list and remaining SQLite-only runtime/expression
  compatibility.

The issue edits are administrative consequences of the approved design. They
do not happen before the specification review is complete.

## Explicit non-goals

- A public `check_sqlite_transfer` or `migrate_sqlite_to_postgres` command.
- Support for unknown SQLite installations or multiple source versions.
- An automatic bridge release or two-hop upgrade path.
- Online migration, dual writes, change capture, or zero-downtime cutover.
- A merge into a populated PostgreSQL database.
- Dry-run, resume, retry, repair, or reverse-transfer machinery.
- A permanent machine-readable migration-report format.
- Retaining the temporary script, serialized fixture, or production snapshot as
  shipped product assets.
- Combining this database cutover with later ownership, UUID, catalog, or event
  migration work.

## Acceptance

The cutover is complete when:

- the real production copy passes two unchanged-script rehearsals against
  separately created empty PostgreSQL targets;
- the nonempty-target safety check is demonstrated without changing that
  target;
- every reconciliation requirement passes with no unexplained mismatch;
- the full repository verification gate and migrated-target smoke checks pass;
- the final frozen production snapshot passes the same script and checks;
- the application reopens on PostgreSQL and the cutover time is recorded;
- private artifacts remain ignored and untracked; and
- the superseded issues are consolidated as described above.
