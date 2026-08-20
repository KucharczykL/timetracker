# Library Configuration UUID Primary Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans`. Steps use checkbox syntax for tracking.

**Goal:** Remove the legacy integer identities for Device and FilterPreset and
make their existing UUIDv7 values the complete database and runtime identity.

**Architecture:** A `SeparateDatabaseAndState` migration owns the PostgreSQL
promotion and Device constraint detach/reattach sequence. Runtime boundaries
switch atomically to strict UUIDv7, while transitional filters, form shims, and
integer selector machinery are deleted.

**Tech Stack:** Django 6, Django Ninja/Pydantic, PostgreSQL 17, pytest-django,
TypeScript/Vitest.

**Spec:**
`docs/superpowers/specs/2026-08-20-issue-850-library-config-uuid-primary-key-design.md`

## Global Constraints

- Do not create a worktree; work on `codex/issue-850-planning`.
- Keep the Makefile's default `PYTEST_WORKERS` for normal verification.
- Use strict UUIDv7 at every identity-bearing boundary; do not add integer
  aliases, redirects, or UUID unions.
- Never use migration-state `RenameField` for the referenced Device UUID.
- Populated reversal is unsupported and must fail before schema mutation.
- Preserve FilterPreset JSON unchanged; do not add a saved-criterion remapper.

---

### Task 1: PostgreSQL identity promotion

**Files:** create `games/migrations/0016_library_config_uuid_primary_key.py`
and `tests/test_library_config_uuid_primary_key.py`; modify
`games/models.py`.

**Interfaces:** produce UUIDv7 `Device.id`/`FilterPreset.id` and Device FKs that
target the promoted primary key.

- [ ] Write migration/model contract tests and run them to observe failures
  because migration `0016` and the promoted declarations do not exist.
- [ ] Implement state-only remove/add promotion, relation state changes,
  Python-owned PostgreSQL DDL, constraint recreation, row reconciliation, and
  guarded empty reversal.
- [ ] Cover populated forward preservation, physical constraints/defaults,
  enforced FKs and uniqueness, populated reverse refusal, table locks, empty
  reverse, and one-executor reverse/reapply.
- [ ] Run the focused migration suite and the existing library/session identity
  suites.

### Task 2: Runtime UUID identity boundaries

**Files:** modify `games/api.py`, `games/urls.py`, `games/views/device.py`,
`games/filters.py`, `games/forms.py`, `common/criteria.py`,
`common/components/domain.py`, `common/components/custom_elements.py`, and
`ts/elements/behaviors/select.ts`; update their focused Python/Vitest tests.

**Interfaces:** Device and FilterPreset identities are UUIDv7 strings on routes,
schemas, criteria, settings, preset operations, and selector payloads.

- [ ] Add focused failing tests for valid UUIDv7 behavior, legacy/non-v7
  rejection, two-library isolation, UUID device criteria, removal of integer
  criterion behavior, and nullable UUID selector payloads.
- [ ] Switch Device and preset API/view schemas and routes to strict UUIDv7.
- [ ] Replace Session device criteria and lookups with UUID/direct-attname
  behavior; delete `MultiCriterion`, both registry entries, and the final form
  initial shim.
- [ ] Replace selector numeric coercion with `empty_is_null`, keeping UUID
  strings unchanged and clear actions as null.
- [ ] Run focused Python and Vitest suites.

### Task 3: Fixture, anonymizer, and audit contraction

**Files:** modify the committed sample fixture, sample loader relationship
metadata, anonymizer, ownership audit, UUID identity audit, and focused command
tests.

**Interfaces:** promoted fixture records use UUIDv7 `pk`; Device relations name
that primary key; residual audit contains only permanent integer exceptions.

- [ ] Add failing tests for promoted fixture representation, deterministic
  scrubbed Device names, hidden Device referrer rewriting, direct ownership
  projections, and the contracted residual inventory.
- [ ] Transform Device/FilterPreset fixture records, switch Device relationship
  metadata to `pk`, and use ordinal scrub names that never contain a pre-rewrite
  UUID.
- [ ] Contract audit entries and replace transitional ownership projections with
  FK attnames while retaining all permanent checks.
- [ ] Run fixture/load/anonymizer/ownership/identity-audit focused suites.

### Task 4: Cross-cutting verification

- [ ] Run `make check-migrations` and fix any migration-state drift.
- [ ] Run `make audit-uuid-identity` against PostgreSQL.
- [ ] Run `make check` with the Makefile's default parallel workers.
- [ ] Inspect `git diff --check`, the final diff, and a whole-branch code review;
  resolve all load-bearing findings before handoff.

