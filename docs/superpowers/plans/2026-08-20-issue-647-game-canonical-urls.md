# Game Canonical URLs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans`. Steps use checkbox syntax for tracking.

**Goal:** Give Game detail pages readable slug-plus-UUID canonical URLs while
preserving UUID authority, compatibility redirects, and library isolation.

**Architecture:** Derive the slug dynamically on `Game`, centralize canonical
URL generation in `get_absolute_url()`, and place two UUID-only redirect routes
beside the canonical detail route. Internal links consume Game instances so a
display-label override cannot accidentally become the canonical slug.

**Tech Stack:** Django 6, PostgreSQL 17, pytest-django, Playwright.

**Spec:**
`docs/superpowers/specs/2026-08-20-issue-647-game-canonical-urls-design.md`

## Global Constraints

- Do not create a worktree; work on `codex/issue-647-planning`.
- Keep the Makefile's default `PYTEST_WORKERS` for normal verification.
- Keep `UUIDv7Converter` registration in `games/urls.py`.
- Add no slug field, migration, uniqueness rule, alias table, or data backfill.
- Keep every non-detail and non-Game route UUID-only.

---

### Task 1: Canonical Game route behavior

**Files:** modify `games/models.py`, `games/urls.py`, and
`games/views/game.py`; create `tests/test_game_canonical_urls.py`.

**Interfaces:** produce `Game.url_slug`, `Game.get_absolute_url()`, canonical
`games:view_game`, and two named read-only UUID redirect routes.

- [ ] Add focused failing tests for slug derivation, canonical reversal,
  redirects, query preservation, stale slugs, renames, UUIDv7 rejection, and
  foreign-library 404s.
- [ ] Implement the model helpers, canonical route, redirect routes, and
  library-scoped redirect helper.
- [ ] Run the focused canonical URL suite and relevant route/isolation suites.

### Task 2: Canonical internal links and returns

**Files:** modify the domain components and Game-related views; update their
focused component, return/origin, rendered-page, and E2E tests.

**Interfaces:** `GameLink` consumes a Game instance and all generated detail
links use `Game.get_absolute_url()`.

- [ ] Add or update failing assertions that expose UUID-only internal links and
  one-argument `games:view_game` reversals.
- [ ] Switch components, statistics, purchases, play history, mutation
  fallbacks, deletion rejection, and origin contracts to canonical Game URLs.
- [ ] Run the affected focused Python and E2E collection suites.

### Task 3: Cross-cutting verification and cleanup

- [ ] Run `make check` with the Makefile's default parallel workers.
- [ ] Run `git diff --check` and inspect the complete branch diff.
- [ ] Remove these issue-specific planning documents in a final cleanup commit,
  preserving the approved planning evidence in branch history.
