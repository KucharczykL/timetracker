# Issue #848: session and play-history UUID primary keys

Design:
[Session and play-history UUID primary-key design](../specs/2026-08-20-issue-848-session-playhistory-uuid-primary-key-design.md).

## Goal

Promote the UUIDv7 identities already present on `Session`, `PlayEvent`, and
`GameStatusChange` to their primary keys. Remove the three legacy integer IDs
without aliases, redirects, or changes to unrelated identity contracts.

## Global constraints

- Base the work on GitHub `main` commit `2e91c87` or newer and use branch
  `claude/issue-848-planning` in an isolated worktree.
- Use migration `0014_session_playhistory_uuid_primary_key.py` with
  `SeparateDatabaseAndState`. State operations must remove integer `id` and
  UUID `uuid`, then add `id = UUIDv7Field(primary_key=True, editable=False,
  serialize=False)`. Do not use `RenameField` or ordinary `AlterField` for the
  promotion.
- Custom PostgreSQL DDL must drop each integer key, rename `uuid` to `id`, add
  the UUID primary key, remove the redundant unique constraint, and reconcile
  row counts for all three tables. Preserve unrelated indexes and outbound
  foreign keys. Do not add relation-detachment or through-table conversion.
- Reverse only when all three tables are empty. Populated reverse must fail
  before any mutation and direct the operator to a pre-migration backup.
- `Session`, `PlayEvent`, and `GameStatusChange` expose only UUIDv7 `id`
  primary keys. Remove exactly their entries from
  `RESIDUAL_INTEGER_PRIMARY_KEYS`; leave the rest of the identity inventory
  unchanged.
- The nine affected HTML routes and every Session/PlayEvent Ninja path
  parameter use strict UUIDv7 validation. Ninja response IDs use `UUIDv7`.
  Device values remain integers. Legacy integers and UUIDv4 values do not
  resolve. No redirects or alias storage are introduced.
- Session cloning explicitly assigns a fresh UUIDv7 primary key. All
  library-scoped lookups continue through `owned_or_404`.
- Fixture records for Session and PlayEvent move `fields.uuid` to `pk` and
  remove `fields.uuid`; relationships are unchanged and gzip output remains
  deterministic. GameStatusChange has no committed sample rows.
- Purchase, Device, FilterPreset, slug canonicalization, filters, saved
  presets, statistics, custom elements, TypeScript, and unrelated anonymizer
  behavior remain out of scope.
- Follow test-driven development for behavior changes. Verify against real
  PostgreSQL with `make migrate`; do not substitute `sqlmigrate`.

### Task 1: Record the approved design and execution plan

Create
`docs/superpowers/specs/2026-08-20-issue-848-session-playhistory-uuid-primary-key-design.md`
and finish this plan document. Capture the migration rationale, runtime
identity contract, fixture strategy, rollback policy, scope boundaries, and
test/verification sequence. Use the issue #646 catalog promotion documents as
the established pattern, while explicitly documenting why this wave needs no
relation detachment or through-table conversion.

### Task 2: Implement and test the database/model promotion

Write focused migration and identity tests first and observe the expected
failures. Add migration `0014_session_playhistory_uuid_primary_key.py`, update
the three models to UUIDv7 primary keys, and remove exactly their audit
exceptions. Prove existing UUIDs and relationships survive, legacy columns are
absent, UUIDv7 database defaults and constraints are correct, unrelated indexes
and outbound foreign keys survive and remain enforced, empty reverse works,
populated reverse is mutation-free and fails with backup guidance, and a
single `MigrationExecutor` can reverse and reapply. Cover duplicate and
wrong-version rejection for the promoted identities.

### Task 3: Convert runtime routes, APIs, and cloning

Write route, view, API, isolation, and clone tests first and observe the
expected failures. Convert PlayEvent edit/delete; Session clone/edit/finish/
reset/delete; and GameStatusChange edit/delete routes to the registered
`uuidv7` converter. Type view parameters as `UUID`, remove the delete-session
integer sentinel, update `PlayEventOut.id` and `SessionOut.id` plus all
PlayEvent/Session Ninja path parameters to `UUIDv7`, and assign a fresh UUIDv7
primary key when cloning. Verify valid reverse/resolve behavior, integer and
UUIDv4 rejection, UUID-string response IDs, strict GET/PATCH/DELETE API
handling, and representative cross-library 404s in HTML and API paths.

### Task 4: Promote fixtures and update cutover documentation

Mechanically transform `games/fixtures/sample.yaml.gz` so Session and
PlayEvent records store their former UUID under `pk` and omit `fields.uuid`.
Preserve relationships and deterministic gzip metadata. Add or update tests
for fixture shape, deterministic generation, sample loading, and anonymize/
load round trips. Confirm no production changes are needed in
`load_sample_data` or `anonymize_sample`. Update the UUID cutover wave plan with
the delivered ID-12 behavior, rollback policy, route ownership, and lessons
from #646. Comment on #647 that the nine bare UUID route conversions were
necessarily completed by #848 while slug-plus-UUID canonicalization remains
with #647.

### Task 5: Integrate and verify the complete change

Run focused migration, route, API, identity, and fixture tests. Run
`make migrate` against PostgreSQL, `make audit-uuid-identity`,
`make check-migrations`, and full `make check` with the Makefile's unchanged
default `PYTEST_WORKERS`. Resolve only failures caused by this branch and
review the complete diff for conformance to the design and scope boundaries.
