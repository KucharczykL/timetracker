# PostgreSQL Post-Cutover Cleanup Design

**Issue:** #628

**Status:** Approved design

**Scope:** Timetracker repository only

## Goal

Finish the SQLite-to-PostgreSQL migration by making PostgreSQL the sole current
database model of the application. Remove the one-time transfer machinery and
the compatibility code that existed only to keep SQLite working, while
preserving application behavior and leaving the live schema unchanged.

This is cleanup after the successful #621 production cutover. It is not another
data migration.

## Ownership and sequencing

#628 owns only Timetracker application, migration, test, and documentation
cleanup. It does not modify `docker-compose-templates`, implement PostgreSQL
backups, or wait for the backup work.

The operational backup work remains independently owned by homelab issue #158.
That work can cover Timetracker immediately through the shared-cluster
`pg_dumpall`; the later Timetracker-native archive in #597 is not a prerequisite
for this cleanup. Removing Timetracker from the shared SQLite backup allowlist
also belongs to #158, not to this repository.

## Cleanup boundary

Remove or rewrite every SQLite reference that describes how the application
works now. This includes current setup and deployment guidance, configuration
examples and errors, architecture and developer guidance, runtime comments and
docstrings, test names and comments, CI/test-topology logic, and the permanent
migration baseline.

Do not rewrite history. Clearly historical snapshots may retain SQLite
references: CHANGELOG entries, completed issue/PR history, and old plans or
specifications that accurately record earlier work. Git history is not edited.

The one-time cutover design and implementation plan are a deliberate exception:
delete both even though they are historical. The final #621 evidence is the
permanent cutover record, and retaining more than 1,400 lines of one-use
instructions in the product repository would add noise rather than recovery
value.

When a retained historical document reads as current guidance, either make its
historical status unambiguous or remove the misleading passage. Classification
is based on what the text claims, not which directory contains it.

## One-time artifact removal

Delete the following together:

- `scripts/one_time_sqlite_postgres_cutover.py`;
- `scripts/sqlite_postgres_source_contract.json`;
- `tests/test_one_time_sqlite_postgres_cutover.py`;
- `docs/superpowers/specs/2026-08-11-one-time-sqlite-postgresql-cutover-design.md`;
- `docs/superpowers/plans/2026-08-12-one-time-sqlite-postgresql-cutover.md`.

No generic transfer command, reusable transfer framework, or replacement source
contract is introduced. The original SQLite database and final cutover evidence
are operational records outside the application code.

## Native PostgreSQL generated expressions

`games.expressions.DatabaseDurationSum` and
`games.expressions.DatabaseDateDifference` exist to translate generated-field
expressions differently for SQLite. PostgreSQL accepts the ordinary operations
directly:

- `Session.duration_total` adds an interval calculated from timestamps to
  `duration_manual` and remains a `DurationField`;
- `PlayEvent.days_to_finish` subtracts two dates and remains an `IntegerField`.

Express both using ordinary serializable Django expressions with explicit output
fields where Django needs type information. Use the same expressions in
`games/models.py` and the squashed baseline, then delete `games/expressions.py`.
The implementation must confirm the generated PostgreSQL SQL and values through
behavioral tests and migration-drift checks; it must not retain vendor dispatch
for a database the project no longer supports.

## Permanent migration baseline

Edit `games/migrations/0001_squashed_0036_alter_playevent_days_to_finish.py`
in place:

- serialize the native PostgreSQL generated expressions;
- remove its import of `games.expressions`;
- remove the entire `replaces` list;
- keep it as the sole initial migration.

Do not add a new migration. The production database already records both the 36
retired migration names and
`0001_squashed_0036_alter_playevent_days_to_finish` as applied. Once `replaces`
is removed, Django still sees the surviving baseline row and has no migration to
run. Fresh databases apply the edited baseline normally.

The native expressions are intended to generate the same PostgreSQL column
definitions already deployed. Before editing them, capture PostgreSQL's current
generated expressions for both columns with `pg_get_expr`; after the edit,
compare those definitions with a fresh database built from the baseline. The
implementation must stop and reconsider this design if that comparison or
`makemigrations --check` shows a real schema change. It must not silently create
a column rebuild under this cleanup issue.

## Test cleanup

Tests should protect behavior, not memorialize a removed database transition.

Keep or strengthen tests that demonstrate:

- calculated, manual, and total session durations remain correct;
- play-event day differences remain correct;
- filtering and aggregation over generated values still work;
- concurrent request or teardown behavior still works where it represents a
  real application invariant;
- models and the permanent migration baseline have no drift.

Delete tests whose only purpose is to:

- assert that the configured engine is PostgreSQL;
- reject a SQLite `DATABASE_URL`;
- scan migration source for SQLite-only SQL names;
- exercise the removed one-time transfer tool;
- pin a SQLite workaround rather than observable application behavior.

Remove SQLite-only branches and skips from `timetracker/pytest_topology.py` and
other current test infrastructure. For the live-server quiescence helper in
`e2e/conftest.py`, first test whether PostgreSQL still needs the behavior. Delete
it if not; if it still prevents a genuine request/teardown race, retain it with
an accurate backend-neutral name and explanation.

The initial source audit includes SQLite references in `common/criteria.py`, the
E2E suite, `games/models.py`, `tests/test_database_configuration.py`,
`tests/test_filter_presets.py`, `tests/test_live_server_db_concurrency.py`,
`tests/test_migration_portability.py`, `tests/test_postgresql_reverification.py`,
`tests/test_sentinel_removal.py`, and `timetracker/pytest_topology.py`. This is an
audit input, not a mandate to delete every matching line: each reference is
classified by the current-versus-historical rule and by whether it protects real
behavior.

The audit also covers hidden tracked configuration. The existing Gitea and
GitHub staging workflows cannot boot the PostgreSQL-only application because
they provision no PostgreSQL database or `DATABASE_URL`; one still seeds a
SQLite volume and the other retains a nonfunctional manual escape hatch. Remove
both workflows and their Fly-specific configuration and guidance. Designing a
new PostgreSQL staging lifecycle is separate work, not part of this cleanup.

## Documentation and code-language audit

After the known removals, search the full tracked repository case-insensitively
for `sqlite`. Review every result rather than accepting a zero-result check as
the goal.

- Current claims are removed or rewritten for PostgreSQL.
- Historical records remain when their time boundary is clear.
- Comments attached to live code describe the live PostgreSQL behavior.
- User-facing configuration and errors do not suggest SQLite is supported.
- Test names and docstrings do not explain present behavior through obsolete
  SQLite limitations.

Historical CHANGELOG entries remain unchanged. Old plans and specifications
unrelated to the one-time cutover are not mechanically rewritten merely because
they mention SQLite.

## Verification

Implementation verification consists of:

1. focused generated-field behavior tests for duration totals and date
   differences on PostgreSQL;
2. parity between the pre-change and fresh-baseline `pg_get_expr` definitions
   for both generated columns;
3. `manage.py makemigrations --check --dry-run` with no drift;
4. building a fresh PostgreSQL test database from the edited baseline;
5. `manage.py migrate --check` against a production copy or an equivalent
   read-only production context, proving no pending migration;
6. the normal full `make check` gate with the Makefile's configured parallel
   pytest workers;
7. a classified repository-wide SQLite-reference audit under the rule above.

No production write or special deployment procedure is part of #628. Because
there is no schema migration, the merged image follows the normal deployment
path. If any verification step reveals schema drift, pending production work, or
changed generated values, implementation stops rather than treating the result
as harmless cleanup.

## Result

After #628, Timetracker has one current database story: PostgreSQL. Fresh
installations build from one PostgreSQL-native baseline, production sees no
pending migration, runtime and tests carry no SQLite compatibility machinery,
and historical records remain historical rather than being rewritten.
