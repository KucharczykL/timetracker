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

Use a tracked, reviewable Python script that orchestrates Django's existing
migration and serialization machinery. Tracking it gives every rehearsal an
exact implementation commit, lets normal review and tests cover it, and makes
"the same script" a Git-verifiable claim. The script is temporary product
support code: it remains in the repository through final cutover and is removed
by the post-cutover compatibility-cleanup issue.

An explicit table-by-table copier is the fallback only if rehearsal proves a
real Django serialization defect. It is not designed or implemented in
parallel. External tools such as `pgloader` and the SQLite command-line client
are excluded because they add dependencies and backend-specific coercion
without improving the evidence for this one database.

## Components

### Tracked and private artifacts

The repository temporarily tracks:

- the cutover script and its focused tests;
- the source migration/schema fingerprint constants; and
- a non-private verification-report schema or formatter.

The ignored cutover workspace contains only private or run-specific artifacts:

- the supplied SQLite snapshot archive and its extracted database/sidecars;
- a serialized fixture derived from the snapshot; and
- verification reports from rehearsal and final execution.

The workspace is checked with `git check-ignore` before private data is placed
in it. The final repository status is inspected to prove that the snapshot,
serialized fixture, and run reports are not tracked. The report records the Git
commit containing the script; the final cutover is accepted only when that
commit equals the successful dress-rehearsal commit.

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
reimplementing migration-graph semantics. Inspection of the supplied production
copy established an exact source contract: 128 migration rows in total, 91
`games` rows, and the historical `games.0055_alter_session_game` leaf. The
current squashed baseline is not recorded in the source, but Django correctly
recognizes it as effectively applied.

The script:

- runs SQLite `PRAGMA quick_check` and requires the result `ok`;
- calls Django's consistent-history check;
- compares the canonical sorted set of recorded `(app, migration)` pairs with a
  fingerprint derived from the supplied production copy;
- compares every source table and ordered column set with a checked-in schema
  fingerprint derived from that copy;
- requires Django to recognize the current squashed baseline as effectively
  applied; and
- rejects every missing, added, or changed migration/table/column with a
  structural diagnostic. This explicit fingerprint is required because
  Django's consistency check ignores unknown applied migrations.

The final frozen production snapshot must match the rehearsed migration and
schema fingerprints. A mismatch stops the cutover and requires an explicit
specification amendment; the script never guesses that a later snapshot is
compatible.

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
metadata and bundled exchange-rate rows. Before loading production data, the
script clears only target tables whose source-data disposition below is
"transfer". It never clears `django_migrations`, target-generated content
types, or target-generated permissions.

### Source-table disposition

The supplied source has 25 tables. Every one has an explicit disposition:

| Source table(s) | Disposition | Rationale |
| --- | --- | --- |
| `games_game`, `games_platform`, `games_device`, `games_purchase`, `games_purchase_games`, `games_session`, `games_exchangerate`, `games_playevent`, `games_gamestatuschange`, `games_filterpreset`, `games_sitesetting`, `games_userpreferences` | Transfer | Durable Timetracker domain, configuration, or user-preference data. |
| `auth_user` | Transfer | The production account and credentials remain valid. |
| `auth_group`, `auth_group_permissions`, `auth_user_groups`, `auth_user_user_permissions` | Require empty; do not transfer | All four are empty in the supplied copy. A nonempty final value is a contract change requiring review because permission primary keys are regenerated. |
| `django_content_type`, `auth_permission` | Regenerate on PostgreSQL | These describe the installed target code, not durable production identity. Source counts and IDs are deliberately not preserved. |
| `django_admin_log` | Intentionally discard | The admin application is no longer installed and its 138 historical operational rows are not required by Timetracker. |
| `django_session` | Intentionally discard | The 166 login sessions are ephemeral; users log in again after cutover. |
| `django_q_task`, `django_q_ormq` | Intentionally discard | Task results and queue state are operational history, not durable domain data. The supplied queue is empty. |
| `django_q_schedule` | Recreate from current code | Do not copy scheduler state or next-run timestamps. The supplied row is the recurring `games.tasks.convert_prices` schedule. Recreate it after verification with `manage.py schedule_convert_prices`. |
| `django_migrations` | Do not transfer | PostgreSQL records the migrations that built its own current schema. The SQLite rows are validation evidence only. |

The script asserts the source tables classified as "require empty" are still
empty. It reports counts for discarded tables, but it never serializes their
contents. Any source table absent from this disposition is a hard failure.

### Serialization and loading

The script serializes only the models classified as "transfer" from the SQLite
connection through Django using each model's base manager. It preserves
explicit primary keys, foreign keys, one-to-one relationships, and many-to-many
relationships. It does not use natural primary keys or silently omit rows
selected out by a custom default manager.

Database-generated fields are removed from the serialized objects based on
Django model metadata. In the current schema these are:

- `Session.duration_calculated`;
- `Session.duration_total`;
- `Purchase.price_per_game`; and
- `PlayEvent.days_to_finish`.

The PostgreSQL database therefore computes those values from their source
columns. Django's raw-save path suppresses ordinary model save signals, but its
many-to-many restore still emits `m2m_changed`. Before export, the script
requires each `Purchase.num_purchases` value to equal its `games` link count.
During load it disconnects only
`games.signals.update_num_purchases` from `Purchase.games.through`, restores
the M2M links without rewriting `num_purchases` or `updated_at`, and reconnects
the exact receiver in a `finally` block. A focused test proves the receiver is
restored after both successful and failed loads. The script resets every
PostgreSQL integer sequence for transferred models after the load.

The ordinary Django serialized format is the first and only implementation
attempt. If it cannot round-trip a production value, the rehearsal report must
identify the exact model, primary key, field, and representation before the
design is amended to use a narrower explicit copy path.

## Data flow

The complete rehearsal and final data flow is:

1. Hash the SQLite archive, extract its database and sidecars together, hash
   the database and durable WAL/journal members, and open the database
   read-only.
2. Validate SQLite integrity plus the exact pinned migration, table, and column
   fingerprints.
3. Connect to PostgreSQL and enforce the initially-empty target guard.
4. Run current Django migrations on PostgreSQL.
5. Assert the complete source-table disposition and the required-empty tables.
6. Validate stored Purchase counts against M2M links.
7. Serialize only the explicitly transferred models and relationships and
   remove generated fields from their records.
8. Clear only migration-created rows in the target tables receiving source
   data.
9. Disconnect the Purchase M2M receiver, load the serialized records through
   Django, and reconnect the receiver in `finally`.
10. Reset integer sequences for transferred models.
11. Recreate the current price-conversion schedule from code.
12. Run reconciliation and application smoke checks.
13. Write the verification report and re-hash the unchanged archive, database,
    and durable WAL/journal members.

No step changes the source archive, extracted database, or durable WAL/journal
contents. SQLite may maintain the extracted transient `-shm` index while
reading. No step publishes the serialized fixture or private field values.

## Reconciliation

A run succeeds only when all of these checks pass:

- the SQLite archive, database, and durable WAL/journal checksums are unchanged;
- SQLite `quick_check` reports no corruption;
- source migration and schema fingerprints match the supplied production copy,
  and target migration history matches the current code;
- every transferred model has identical row counts and primary-key sets;
- every transferred many-to-many relationship has identical link counts and
  endpoint sets;
- canonical per-model digests match after excluding generated fields;
- canonical values are normalized through Django types before hashing, covering
  text, notes, JSON, decimals, booleans, nulls, foreign keys, dates,
  timezone-aware timestamps, and durations;
- each generated value matches the SQLite value by model and primary key after
  PostgreSQL recalculation;
- PostgreSQL reports no foreign-key or constraint violations;
- each integer sequence's next value is greater than the table's maximum
  primary key;
- discarded and required-empty source tables match their stated dispositions,
  target content types and permissions match a fresh migration, and exactly the
  intended price-conversion schedule exists after recreation;
- representative aggregate checks match, including session and manual
  playtime, per-Game playtime, purchase totals and counts, status-history
  counts, users, filter presets, and settings; and
- curated ORM queries and important application pages succeed against the
  migrated target.

The report contains the source archive/member checksums, Git commit containing
the cutover script, database versions, migration/schema fingerprints,
transferred and discarded table counts, model and relationship counts,
digests, generated-value results, aggregate results, schedule recreation,
smoke-check results, timestamps, and overall status. It contains no notes,
names, credentials, settings values, or other private field contents.

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
   from the same Git commit without modifying the script.
5. Require successful reports from both clean runs to have identical source
   checksums, model/relationship counts, data digests, generated-value results,
   and aggregate results. Operational timestamps and target identifiers may
   differ.
6. Run the repository's full `make check` gate with its normal Windows worker
   configuration, the cutover-script focused tests, and the curated application
   smoke checks.

The final cutover procedure is:

1. Stop Timetracker and its background worker.
2. After SQLite writers have stopped, archive `db.sqlite3` together with any
   `-wal`, `-shm`, or journal sidecars and record the archive, database, and
   durable WAL/journal checksums.
3. Create a new empty PostgreSQL database satisfying the runtime contract.
4. Check out the dress-rehearsed Git commit and run its tracked script
   unchanged.
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
  cleanup issue, including removal of the tracked cutover script and its
  focused tests; and
- absorb #809 into #628 so the same post-cutover cleanup removes the squashed
  migration's `replaces` list and remaining SQLite-only runtime/expression
  compatibility.

The issue edits are administrative consequences of the approved design. They
do not happen before the specification review is complete.

## Explicit non-goals

- A public `check_sqlite_transfer` or `migrate_sqlite_to_postgres` command.
- Support for any SQLite migration/schema fingerprint other than the supplied
  and rehearsed production database.
- An automatic bridge release or two-hop upgrade path.
- Online migration, dual writes, change capture, or zero-downtime cutover.
- A merge into a populated PostgreSQL database.
- Dry-run, resume, retry, repair, or reverse-transfer machinery.
- A permanent machine-readable migration-report format.
- Retaining the serialized fixture, production snapshot, or private reports as
  tracked assets.
- Keeping the tracked cutover script after the post-cutover compatibility
  cleanup issue removes it.
- Combining this database cutover with later ownership, UUID, catalog, or event
  migration work.

## Acceptance

The cutover is complete when:

- the tracked script and focused tests pass normal repository review;
- the real production copy passes two same-commit rehearsals against separately
  created empty PostgreSQL targets;
- the nonempty-target safety check is demonstrated without changing that
  target;
- every reconciliation requirement passes with no unexplained mismatch;
- the full repository verification gate and migrated-target smoke checks pass;
- the final frozen production snapshot passes the same script and checks;
- the application reopens on PostgreSQL and the cutover time is recorded;
- private artifacts remain ignored and untracked;
- the cutover report identifies the exact rehearsed Git commit; and
- the superseded issues are consolidated as described above.
