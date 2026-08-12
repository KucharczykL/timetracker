# Database Documentation Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dated PostgreSQL migration series with one timeless database contract and align current documentation with the resulting PostgreSQL-only application.

**Architecture:** `docs/database.md` is the durable source for database invariants. Onboarding, deployment, configuration, and developer guidance link to it and retain only the details needed for their own audiences; dated migration designs, execution plans, and this one-use consolidation plan are removed from the final tree.

**Tech Stack:** Markdown, Git, ripgrep, repository `make check` gate.

## Global Constraints

- Remove only the dated PostgreSQL migration series and this one-use consolidation plan; unrelated dated feature records remain untouched.
- Keep `CHANGELOG.md` as historical release documentation.
- Keep present-tense facts only: no issue sequencing, migration phases, cutover paths, production snapshots, or one-use verification transcripts.
- Preserve PostgreSQL major version 18, UTF8, `builtin`, and `C.UTF-8` as the current enforced database contract.
- Do not change application behavior, schema, deployment topology, or tests.
- Keep `docs/database.md` as the single durable explanation of database architecture.

---

### Task 1: Connect current documentation to the database contract

**Files:**

- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/configuration.md`
- Modify: `docs/deployment.md`
- Verify: `docs/database.md`

**Interfaces:**

- Consumes: the approved current-state contract in `docs/database.md`.
- Produces: discoverable, consistent links from each current documentation audience without duplicating migration history.

- [ ] **Step 1: Fix the developer-guide version and link the durable contract**

In `CLAUDE.md`, change `PostgreSQL 17 is required` to `PostgreSQL 18 is required` and link the database section to `docs/database.md`. Keep the existing concise notes about local provisioning, `DATABASE_URL`, generated fields, and xdist; do not copy the full contract into the developer guide.

- [ ] **Step 2: Link onboarding and operator references**

In `README.md`, add `docs/database.md` beside the existing deployment link so a developer can find the database invariants from onboarding.

In `docs/deployment.md`, add a direct link to `database.md` in the opening contract paragraph. Keep the deployment, backup, and restore commands because they are reusable operator procedures.

In `docs/configuration.md`, link the `DATABASE_URL` description to `database.md` while retaining the exact version and locale requirements in the settings table.

- [ ] **Step 3: Audit current documentation for contradictory database claims**

Run:

```powershell
rg --hidden -n -i "PostgreSQL 17|SQLite|PG-0[1-7]|PG-13|PG-14|post-cutover|#628" README.md CLAUDE.md docs .env.example --glob '!.git/**' --glob '!CHANGELOG.md' --glob '!docs/superpowers/plans/**' --glob '!docs/superpowers/specs/**'
```

Expected: no matches. PostgreSQL 18 references are current requirements and remain.

- [ ] **Step 4: Verify links and formatting**

Run:

```powershell
git diff --check
rg -n "docs/database\.md|\(database\.md\)" README.md CLAUDE.md docs/configuration.md docs/deployment.md
```

Expected: no whitespace errors and all four current entry points reference the durable contract.

### Task 2: Remove the dated migration series

**Files:**

- Delete: `docs/superpowers/plans/2026-08-09-pg-01-generated-duration-columns.md`
- Delete: `docs/superpowers/plans/2026-08-09-pg-02-generated-purchase-price-columns.md`
- Delete: `docs/superpowers/plans/2026-08-09-pg-03-days-to-finish.md`
- Delete: `docs/superpowers/plans/2026-08-09-pg-04-deterministic-null-ordering.md`
- Delete: `docs/superpowers/plans/2026-08-09-pg-05-postgresql-collation-contract.md`
- Delete: `docs/superpowers/plans/2026-08-09-pg-06-postgresql-compatibility-audit.md`
- Delete: `docs/superpowers/plans/2026-08-10-pg-07-postgresql-migration-baseline.md`
- Delete: `docs/superpowers/plans/2026-08-10-pg-07-review-followups.md`
- Delete: `docs/superpowers/plans/2026-08-10-pg-14-ci-postgresql-17.md`
- Delete: `docs/superpowers/plans/2026-08-12-postgresql-post-cutover-cleanup.md`
- Delete: `docs/superpowers/specs/2026-08-09-pg-01-generated-duration-columns-design.md`
- Delete: `docs/superpowers/specs/2026-08-09-pg-02-generated-purchase-price-columns-design.md`
- Delete: `docs/superpowers/specs/2026-08-09-pg-03-days-to-finish-design.md`
- Delete: `docs/superpowers/specs/2026-08-09-pg-04-deterministic-null-ordering-design.md`
- Delete: `docs/superpowers/specs/2026-08-09-pg-05-postgresql-collation-contract-design.md`
- Delete: `docs/superpowers/specs/2026-08-09-pg-06-postgresql-compatibility-audit-design.md`
- Delete: `docs/superpowers/specs/2026-08-10-pg-01-06-postgresql-reverification-design.md`
- Delete: `docs/superpowers/specs/2026-08-10-pg-07-postgresql-migration-baseline-design.md`
- Delete: `docs/superpowers/specs/2026-08-10-pg-07-review-followups-design.md`
- Delete: `docs/superpowers/specs/2026-08-10-pg-13-postgresql-xdist-design.md`
- Delete: `docs/superpowers/specs/2026-08-10-pg-14-ci-postgresql-17-design.md`
- Delete: `docs/superpowers/specs/2026-08-12-postgresql-post-cutover-cleanup-design.md`
- Delete after execution: `docs/superpowers/plans/2026-08-12-database-documentation-consolidation.md`

**Interfaces:**

- Consumes: the durable facts consolidated into `docs/database.md` and the current entry-point updates from Task 1.
- Produces: no dated PostgreSQL migration design or execution document in the working tree.

- [ ] **Step 1: Verify the deletion set is exact**

Run:

```powershell
$series = @(rg --files docs/superpowers/plans docs/superpowers/specs | Where-Object { $_ -match '(?i)pg-|postgres.*(migration|cutover|cleanup)|database-documentation-consolidation' })
$series | Sort-Object
```

Expected: the 23 paths listed in this task and no unrelated feature document. Stop if the result differs.

- [ ] **Step 2: Delete the series together**

Delete the 23 exact paths with `apply_patch`. Do not rewrite unrelated historical files.

- [ ] **Step 3: Prove no dated migration-series document remains**

Run:

```powershell
rg --files docs/superpowers/plans docs/superpowers/specs | Where-Object { $_ -match '(?i)pg-|postgres.*(migration|cutover|cleanup)|database-documentation-consolidation' }
```

Expected: no output.

- [ ] **Step 4: Prove current guidance is timeless and references resolve**

Run:

```powershell
rg --hidden -n -i "SQLite|PostgreSQL 17|PG-0[1-7]|PG-13|PG-14|post-cutover|#628" README.md CLAUDE.md docs .env.example --glob '!.git/**' --glob '!CHANGELOG.md' --glob '!docs/superpowers/plans/**' --glob '!docs/superpowers/specs/**'
git grep -n -E "2026-08-(09|10|12)-(pg-|postgresql-post-cutover|database-documentation)" -- ':!CHANGELOG.md'
```

Expected: both commands produce no matches after the deletion is committed. `CHANGELOG.md` remains exempt as release history.

### Task 3: Verify and publish the documentation consolidation

**Files:**

- Verify: all changed documentation
- Verify: entire repository

**Interfaces:**

- Consumes: Tasks 1 and 2.
- Produces: a verified update to PR #825 with one timeless database reference and no migration-series documents.

- [ ] **Step 1: Review the final documentation diff**

Run:

```powershell
git status --short
git diff --stat origin/main
git diff --check
git diff -- README.md CLAUDE.md docs/database.md docs/configuration.md docs/deployment.md
```

Expected: only approved documentation changes and the exact series deletions appear; no whitespace errors.

- [ ] **Step 2: Run the repository gate**

On Windows Codex desktop, run `make check` through a managed hidden process using the Makefile's default `PYTEST_WORKERS`, and wait for the actual process-tree exit status.

Expected: lint, formatting, types, generated artifacts, migration drift, TypeScript tests, and Python tests all pass.

- [ ] **Step 3: Commit the final consolidation**

```powershell
git add README.md CLAUDE.md docs/database.md docs/configuration.md docs/deployment.md
git add -u docs/superpowers/plans docs/superpowers/specs
git diff --cached --check
git commit -m "docs: replace migration series with database contract"
```

- [ ] **Step 4: Push the reviewed branch**

```powershell
git push
gh pr view 825 --json url,headRefName,baseRefName,state
```

Expected: PR #825 remains open from `codex/issue-628-postgres-cleanup` into `main` and includes the consolidation commit.
