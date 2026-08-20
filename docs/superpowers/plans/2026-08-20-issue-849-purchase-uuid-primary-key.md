# Issue #849: Purchase UUID Primary-Key Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the existing `Purchase.uuid` values to the sole UUIDv7 primary key, remove the legacy integer identity, convert `games_purchase_games.purchase_id` to UUIDv7, and update Purchase-facing routes and sample data without compatibility aliases.

**Architecture:** Migration `0015_purchase_uuid_primary_key` uses `SeparateDatabaseAndState`. PostgreSQL DDL first rewrites the auto-created through-table column, then promotes `games_purchase.uuid`, and finally recreates the through-table FK and indexes using Django's generated names. Runtime routes and fixtures switch atomically to the promoted identity.

**Tech Stack:** Django 6, PostgreSQL 18, pytest/pytest-django, deterministic gzip/YAML fixtures.

**Spec:** `docs/superpowers/specs/2026-08-20-issue-849-purchase-uuid-primary-key-design.md`

## Global Constraints

- Base work on GitHub `main` commit `6e407177` or newer, on branch `claude/issue-849-planning` in an isolated worktree.
- Preserve existing Purchase UUIDs exactly; do not mint replacements, retain integer aliases, or add redirects.
- Use `SeparateDatabaseAndState` with state `RemoveField(id)`, `RemoveField(uuid)`, `AddField(id = UUIDv7Field(primary_key=True, editable=False, serialize=False))`. Never use `RenameField` for migration state.
- Convert `games_purchase_games.purchase_id` before dropping `games_purchase.id`. Run `SET CONSTRAINTS ALL IMMEDIATE` before its first `ALTER TABLE` after the backfill.
- Explicitly restore the through-table foreign key, `purchase_id` index, and `(purchase_id, game_id)` unique constraint through Django's schema editor.
- Populated reverse is unsupported and must fail before schema mutation with backup guidance. Empty reverse must restore the preceding structural shape.
- Keep every Purchase lookup library-scoped through `owned_or_404`; UUID possession never grants access.
- Purchase has no identity-bearing Ninja API endpoint. Filters, saved presets, statistics, currency conversion, split/refund semantics, and slug canonicalization remain out of scope.
- Follow test-driven development for behavior changes. Verify migrations against real PostgreSQL; `sqlmigrate` is not evidence for Python-owned DDL.
- Run `make check` with the Makefile's unchanged default `PYTEST_WORKERS`.

---

### Task 1: Record the approved design

**Files:**
- Create: `docs/superpowers/specs/2026-08-20-issue-849-purchase-uuid-primary-key-design.md`
- Modify: `docs/superpowers/plans/2026-08-20-issue-849-purchase-uuid-primary-key.md`

- [x] Document the identity contract, forced through-table ordering, constraint recreation, reverse locking/refusal, seven Purchase routes, fixture representation, exclusions, and exact verification sequence.
- [x] Cross-check the result against issue #849 and all three comments, the #848 promotion design, the #646 catalog promotion design, the UUID cutover wave plan, and the overhaul charter.
- [x] Commit with `git commit -m "docs: plan purchase UUID primary key cutover"`.

### Task 2: Implement the Purchase and through-table promotion

**Files:**
- Create: `games/migrations/0015_purchase_uuid_primary_key.py`
- Create: `tests/test_purchase_uuid_primary_key.py`
- Modify: `games/models.py`
- Modify: `games/identity_audit.py`
- Modify: `tests/test_uuid_identity_audit.py`
- Modify: `tests/test_purchase_fk_uuid.py`
- Modify: `tests/test_purchase_identity.py`

**Interfaces:**
- `Purchase.id: UUIDv7Field` is the sole primary key; `Purchase.uuid` no longer exists.
- `games_purchase_games.purchase_id` is a non-null `uuid_v7` FK to `games_purchase.id`, indexed independently and jointly unique with `game_id`.

- [ ] Write focused failing tests for the final model contract, UUID/row/value/link preservation, physical PK/domain/default, through FK/index/uniqueness, duplicate and UUIDv4 rejection, empty reverse, populated reverse before mutation, reverse locking, and one-executor reverse/reapply.
- [ ] Run the focused tests and record the expected failures caused by the missing migration/model contract.
- [ ] Implement migration state and forward DDL in this order: add/backfill/reconcile `purchase_uuid`; force constraints immediate; drop/rename/not-null the through column; promote Purchase; drop redundant UUID uniqueness; recreate the through FK/index/unique pair.
- [ ] Implement reverse by locking `games_purchase` and `games_purchase_games` together, rejecting any populated state, restoring Purchase's bigint identity plus separate UUID, restoring bigint through `purchase_id`, and recreating its FK/index/unique pair.
- [ ] Update the model and remove exactly Purchase's two residual-integer inventory entries.
- [ ] Rewrite the through-table tripwire so both relation columns are UUIDv7 and preserve the direct pair-uniqueness enforcement test.
- [ ] Update Purchase identity tests to exercise promoted `pk`, raw database defaults, duplicate rejection, and wrong-version rejection while retaining historical `0007` migration coverage.
- [ ] Run the focused migration/identity tests and commit with `git commit -m "feat: promote purchase UUID primary key"`.

### Task 3: Convert Purchase runtime routes

**Files:**
- Create: `tests/test_purchase_runtime_identity.py`
- Modify: `games/urls.py`
- Modify: `games/views/purchase.py`
- Modify: existing route/authentication/isolation tests only where their declared types require it

**Interfaces:**
- Seven Purchase identity routes use `<uuidv7:purchase_id>`.
- Purchase view and identity helper parameters use `UUID`.

- [ ] Write failing route tests covering UUIDv7 reverse/resolve, integer and UUIDv4 rejection, successful owned reads/actions, and foreign-library 404 behavior.
- [ ] Run the focused test and confirm failure is caused by the existing integer route contract.
- [ ] Convert view, edit, delete, refund confirmation/action, and split confirmation/action routes and parameter annotations while retaining library-scoped lookups and response behavior.
- [ ] Run the focused runtime/isolation tests and commit with `git commit -m "feat: route purchase identities by UUID"`.

### Task 4: Promote Purchase fixture identities and document the handoff

**Files:**
- Modify: `games/fixtures/sample.yaml.gz`
- Modify: `tests/test_anonymize_sample.py`
- Modify: fixture/sample-loading tests as required by observed failures
- Modify: `docs/superpowers/specs/2026-08-17-uuid-identity-cutover-wave-plan.md`

- [ ] Write or update failing fixture-shape tests so `games.purchase` stores its UUIDv7 identity under `pk` and has no `fields.uuid`.
- [ ] Mechanically transform Purchase records without changing relationships, ordering, unrelated fields, or gzip determinism.
- [ ] Update promoted-model fixture expectations; production loader/anonymizer logic remains generic unless a failing behavior test proves otherwise.
- [ ] Verify deterministic anonymization, committed sample loading, and anonymize/load round trips.
- [ ] Update the wave plan with delivered ID-13 behavior and prepare the #647 handoff noting that #849 converted seven bare Purchase routes while canonical URL policy remains there.
- [ ] Commit with `git commit -m "feat: promote sample purchase identities"`.

### Task 5: Integrate and verify

**Files:**
- Review all branch changes; modify only to fix verified branch-caused failures.

- [ ] Run focused Purchase migration, identity, runtime, audit, and fixture tests.
- [ ] Run `make migrate`, `make audit-uuid-identity`, and `make check-migrations` against real PostgreSQL.
- [ ] Run full `make check` with the default worker count.
- [ ] Review the complete diff against the design and issue comments, then commit any verification-driven fixes.
