# CAT-04 Shared/Private Catalog Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Represent shared catalog Games with a NULL owner, expose them only through explicit catalog visibility queries and Game search, and keep every current player-history and mutation path private-only.

**Architecture:** Make Game ownership nullable without rewriting data, add opt-in visibility querysets derived through the catalog graph, and broaden only `/api/games/search`. Keep the existing exact-owner queryset as the authorization boundary and enforce graph ownership in model/service validation inside atomic writes.

**Tech Stack:** Python 3.14, Django 6 ORM/migrations, PostgreSQL 17, Django Ninja, pytest-django, pytest-xdist, Make.

**Spec:** `docs/superpowers/specs/2026-08-20-issue-651-shared-private-catalog-design.md`

## Global Constraints

- Treat issue #651 and the catalog foundation wave as authoritative.
- Preserve all existing Game rows, UUIDs, owners, hierarchy identities, compatibility fields, and incoming relationships; never merge or rewrite by name.
- Keep `Game.objects.for_library(library)` private-only and require explicit `visible_to(library)` for shared catalog reads.
- Derive Edition and Release ownership only through their owning Game; do not add owner columns.
- Broaden only `/api/games/search`; keep lists, details, forms, filters, statistics, Sessions, Purchases, histories, and mutations private-only.
- Shared query matching may use catalog fields; `sort_name` may match only the requesting library's private Games.
- Keep the established Game search response shape and add no status, mastered, playtime, history, timestamp, or owner fields.
- Reject shared-Game writes, persisted-Game owner transfers, and foreign private Platforms atomically.
- A private Release may use a shared or same-library Platform; a shared Release may use only a shared Platform.
- Preserve current private uniqueness. Add no shared-name uniqueness, normalized-name merge, or shadow rule.
- Keep IGDB, PlayerGame, reconciliation, overrides, shared editing, external references, tombstones, and redirects out of scope.
- Run normal verification with the Makefile's unchanged default `PYTEST_WORKERS`; do not set it to `0`.
- Stop and return to the design gate if actual scope crosses three independent runtime subsystems, 40 files, or 2,000 non-generated changed lines.

## File structure

- Modify `games/models.py`: nullable Game owner, explicit Game/Edition/Release querysets, and Release Platform validation.
- Create `games/migrations/0021_alter_game_library.py`: schema-only nullable owner change.
- Modify `games/catalog_writes.py`: lock and validate persisted ownership before any private graph mutation.
- Modify `games/api.py`: use visible Games for catalog search with owner-only `sort_name` matching.
- Modify `tests/test_catalog_hierarchy.py`: hierarchy visibility, Release ownership, and same-name/private uniqueness coverage.
- Modify `tests/test_catalog_writes.py`: shared writes, transfers, foreign Platforms, and atomic graph preservation.
- Modify `tests/test_library_api_isolation.py`: shared discovery, foreign exclusion, safe response, and shared/foreign mutation 404s.
- Create `tests/test_shared_catalog_migration.py`: forward/back migration preservation and shared graph creation.
- Remove this plan and its paired design after all implementation and verification gates pass; preserve their planning commit in branch history.

## Planning gate checkpoint

Commit this plan and paired design before changing tests or runtime code. The
approved plan supplied in the implementation request satisfies the explicit
approval gate.

---

### Task 1: Add nullable ownership and hierarchy visibility contracts

**Files:**
- Modify: `tests/test_catalog_hierarchy.py`
- Create: `tests/test_shared_catalog_migration.py`
- Modify later: `games/models.py`
- Create later: `games/migrations/0021_alter_game_library.py`

**Interfaces:**
- Produces `Game.objects.visible_to(library)` alongside unchanged private-only `for_library(library)`.
- Produces `Edition.objects.for_library/visible_to` and `Release.objects.for_library/visible_to` through the owning Game.
- Produces schema `games.0021_alter_game_library` with nullable `Game.library` and no data rewrite.

- [ ] Write model/query tests with two libraries for shared visibility, foreign-private exclusion, derived child visibility, equal-name coexistence, and unchanged same-library uniqueness.
- [ ] Run the focused new tests and confirm failures are caused by the absent nullable/query contracts.
- [ ] Write migration tests from `0020` to `0021` that snapshot private Game/Edition/Release identities and fields, prove the owner field becomes nullable, create a shared graph, and prove no row is merged or rewritten.
- [ ] Run the migration tests and confirm the `0021` target is absent.
- [ ] Implement the minimal querysets and nullable model field; generate the schema-only `0021` migration.
- [ ] Run `tests/test_catalog_hierarchy.py`, `tests/test_library_models.py`, and `tests/test_shared_catalog_migration.py` until green.
- [ ] Commit the task with its tests.

---

### Task 2: Enforce Release and private-writer ownership atomically

**Files:**
- Modify: `tests/test_catalog_hierarchy.py`
- Modify: `tests/test_catalog_writes.py`
- Modify later: `games/models.py`
- Modify later: `games/catalog_writes.py`

**Interfaces:**
- `Release.save()` validates `platform.library_id` against `edition.game.library_id`, allowing NULL/shared as specified.
- `save_private_game(...)` accepts only a new private Game or a persisted Game whose database owner equals the supplied owner.

- [ ] Add Release validation tests for same-library private, shared, and foreign Platforms on private graphs, plus shared-only Platforms on shared graphs.
- [ ] Run them and confirm foreign Platform saves currently succeed.
- [ ] Add service tests proving a shared Game, a foreign Platform, and a mutated owner transfer raise `ValidationError` without changing the persisted Game/default graph.
- [ ] Run them and confirm shared persisted writes/transfers currently reach mutation or fail for the wrong reason.
- [ ] Add minimal Release clean/save validation and persisted-owner locking/validation in `save_private_game` before mutation.
- [ ] Run both focused files until green and confirm rollback assertions inspect database state after failure.
- [ ] Commit the task with its tests.

---

### Task 3: Expose shared Games through catalog-only search

**Files:**
- Modify: `tests/test_library_api_isolation.py`
- Modify later: `games/api.py`

**Interfaces:**
- `GET /api/games/search` returns requesting-library private Games plus shared Games.
- Query matching uses shared/private `name`, but only owner-private `sort_name`.
- Status and PlayEvent mutation endpoints continue resolving Games with `for_library` and return 404 for shared/foreign UUIDs.

- [ ] Extend the two-library fixture with a NULL-owner shared Game and hierarchy-safe shared Platform.
- [ ] Add tests proving both users discover the shared row, neither sees the other's private row, shared `sort_name` cannot match, and the owner can match its own private `sort_name`.
- [ ] Assert each search object exposes only `value`, `label`, and `data`, with `data` limited to the established Platform keys and no private/history fields.
- [ ] Add shared and foreign status-update/PlayEvent-create assertions for 404 and unchanged database state.
- [ ] Run the focused API file and confirm only the new shared-search expectations fail.
- [ ] Change only Game search to `visible_to`, with an owner-qualified `sort_name` predicate; leave mutation querysets unchanged.
- [ ] Run `tests/test_library_api_isolation.py`, `tests/test_api.py`, and current catalog-write view tests until green.
- [ ] Commit the task with its tests.

---

### Task 4: Complete verification, audit, cleanup, and delivery

**Files:**
- Delete after all gates pass: `docs/superpowers/specs/2026-08-20-issue-651-shared-private-catalog-design.md`
- Delete after all gates pass: `docs/superpowers/plans/2026-08-20-issue-651-shared-private-catalog.md`
- Review: every file changed from `origin/codex/catalog-wave`

- [ ] Run focused model, migration, writer, catalog-write-view, API, and library-isolation tests.
- [ ] Run `make check-migrations` and confirm no missing model-state changes.
- [ ] Run `git diff --check origin/codex/catalog-wave...HEAD`.
- [ ] Run the complete `make check` with the Makefile's default worker configuration.
- [ ] Audit every `Game.objects.for_library` and mutation boundary touched by the issue; confirm only catalog search opted into `visible_to`.
- [ ] Compare actual files and non-generated changed lines with the forecast and re-slice thresholds.
- [ ] Remove the temporary plan/design with `apply_patch` only after all green gates and commit their removal.
- [ ] Run final diff/status checks and a whole-branch code review against this plan.
- [ ] Commit only issue #651 changes, push `codex/issue-651-shared-private-catalog`, and open a PR targeting `codex/catalog-wave` with `Closes #651`; do not merge it.
