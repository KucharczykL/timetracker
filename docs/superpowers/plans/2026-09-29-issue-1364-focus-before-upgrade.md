# A picker focused before its script runs: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `<search-select>` whose box holds focus when the element is defined runs `runFocus` once, so the #1364 flake cannot happen.

**Spec:** `docs/superpowers/specs/2026-09-29-issue-1364-focus-before-upgrade-design.md`. Every "why" lives there.

## Global constraints

- Everything through `make`. Wrap every pytest target in
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- Run `make ts` after editing `.ts`, before any e2e run.
- Comments state intent, no issue references.
- Gate: full `make check`, read by exit code, before the PR.

### Task 1: The regression test, red

**Files:** `e2e/test_search_select_e2e.py`

- [ ] Add `test_a_box_clicked_before_its_script_opens_its_panel`, on the
  `searchurl-committed` page (search url, `prefetch=6`, committed
  `Item 03`).
- [ ] Route `**/elements/search-select*.js` with the
  `e2e/test_dropdown_host_order_e2e.py` shape: `route.fetch()`, record the
  status, and `route.fulfill` with a top-level `await` delay prepended
  (500 ms is enough there; use the same constant shape).
- [ ] `page.goto`, then click
  `search-select[name="item"] input[data-search-select-search]`.
- [ ] Right after the click: `page.evaluate('customElements.get("search-select") === undefined')`
  is true. Then `expect(options :visible).to_have_count(6)` and the
  recorded statuses equal `[200]`.
- [ ] Run `make test-e2e ARGS="e2e/test_search_select_e2e.py -k clicked_before"`. It must fail on the
  options count, not on either guard. If a guard fails, the delay is wrong;
  fix the delay, not the guard.

### Task 2: The replay

**Files:** `ts/elements/search-select.ts` (the autofocus block, ~line 1543)

- [ ] Rewrite the block as one "focus that happened before wiring" block
  with two branches:
  - `autofocus`: unchanged (snapshot `startedEmpty`, one frame later, only
    when empty or holding none).
  - otherwise: `if (document.activeElement === search) runFocus();`
- [ ] Keep it above `if (delegated) return null`, so a hosted picker gets it.
- [ ] Rewrite the block's comment to state the one rule; drop "Autofocus
  lands before wiring" as the heading.
- [ ] `make ts`, then Task 1's test is green.

### Task 3: Prove the flake gone

- [ ] Loop the #1364 test twenty times, stopping on the first failure:
  `for run in (seq 20); flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-e2e ARGS="e2e/test_bulk_edit_e2e.py -k two_sessions_take_one_device"; or break; end`
- [ ] `make test-e2e ARGS="e2e/test_dropdown_host_order_e2e.py e2e/test_search_select_e2e.py"` green (autofocus paths).

### Task 4: Gate and PR

- [ ] `make format`, `make lint-fix`, then full `make check` under the lock, exit code 0.
- [ ] Commit spec, plan, test and fix; PR closes #1364 and names #1367 as the follow-up.
