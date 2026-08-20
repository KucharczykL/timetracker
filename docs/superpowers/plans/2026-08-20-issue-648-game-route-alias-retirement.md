# Game Compatibility Route Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans`. Steps use checkbox syntax for tracking.

**Goal:** Retire the two UUID-only Game compatibility aliases while preserving
the canonical slug-plus-UUID detail contract.

**Architecture:** Remove both public compatibility route names and their shared
redirect view. Leave the UUID-only path unmatched, and use one unnamed 404 guard
for the exact no-slash `/view` path so Django cannot revive it through
`APPEND_SLASH`; keep the canonical slug route and stale-slug redirect unchanged.

**Tech Stack:** Django 6, PostgreSQL 18 development environment, pytest-django.

**Spec:**
`docs/superpowers/specs/2026-08-20-issue-648-game-route-alias-retirement-design.md`

## Global Constraints

- Work on `codex/issue-648-planning` created from current `main`.
- Keep the Makefile's default `PYTEST_WORKERS` for normal verification.
- Keep `UUIDv7Converter` registration in `games/urls.py`.
- Add no migration, legacy identity field, alias table, or data backfill.
- Preserve canonical and stale-slug behavior at `/game/<uuid>/<slug>/`.

---

### Task 1: Retire the compatibility routes

**Files:** modify `games/urls.py`, `games/views/game.py`,
`games/views/returns.py`, `tests/test_game_canonical_urls.py`,
`tests/test_returns.py`, and `tests/test_returns_classification.py`.

**Interfaces:** remove `games:view_game_by_uuid`, `games:view_game_legacy`,
`redirect_game_to_canonical`, and `COMPATIBILITY_REDIRECTS`; add an unnamed
exact-path view that raises `Http404` for `/game/<uuid>/view`.

- [ ] Replace the compatibility redirect assertions with failing tests proving
  the two public names cannot reverse and both old request paths return 404
  without a redirect.
- [ ] Add a failing regression test proving `/game/<uuid>/view/` remains a
  valid canonical URL when the Game slug is `view`.
- [ ] Remove the two named redirect routes and UUID-only redirect view, add the
  unnamed exact-path 404 guard, and remove the empty return-classification
  bucket.
- [ ] Run the focused Game URL and returns suites with the Makefile's default
  worker count and confirm they pass.

### Task 2: Cross-cutting verification and cleanup

- [ ] Run `make check` with the Makefile's default parallel workers.
- [ ] Run `git diff --check` and inspect the complete branch diff against the
  approved specification.
- [ ] Remove these issue-specific planning documents in a final cleanup commit,
  preserving the approved planning evidence in branch history.
