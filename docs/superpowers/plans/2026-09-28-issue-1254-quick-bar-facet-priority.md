# Quick bar facet priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Applied facets spill into `⋯` last and carry a mark; every mode's
facet list is reordered for the idle row.

**Architecture:** The server stamps `data-quick-facet-applied` and renders
the mark; `layoutOverflow` fits over a priority sequence (applied, then
idle) and renders the kept and spilled sets in declared order; the `⋯`
dot and label follow what `⋯` holds.

**Tech Stack:** Python components (`common/components`), TypeScript custom
element, vitest, pytest, Playwright.

**Spec:** [Which facets the quick bar shows inline](../specs/2026-09-28-issue-1254-quick-bar-facet-priority-design.md)

## Global Constraints

- `make` targets only; wrap pytest targets in
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- `ts/elements/priority-plus.ts` does not change.
- Mark classes: dot `bg-brand`, label `Span(class_="text-fg-brand")`,
  screen-reader text `sr-only`. Never a color class on the ghost button.
- `⋯` accessible name: `More filters` / `More filters, some applied`.
- `⋯` dot is `invisible`, never `hidden`, when off.
- Complete-word identifiers; comments state present design, no issue refs.
- `make format`, `make lint-fix`, then full `make check` once, at the end.

---

### Task 1: Layout over a priority sequence, `⋯` mark in TS

**Files:**
- Modify: `ts/elements/quick-filter-bar.ts` (`setupOverflow`, `layoutOverflow`)
- Test: `ts/elements/quick-filter-bar.test.ts` (overflow `describe`)

**Interfaces:**
- Consumes (from Task 2's markup): facet `<drop-down data-quick-facet
  data-quick-facet-applied>`; inside `[data-quick-overflow]` one
  `[data-quick-overflow-trigger]` (the button holding `aria-label`) and one
  `[data-quick-overflow-mark]` span, `invisible` when off.
- Produces: `OverflowItem` gains nothing; the element keeps a private
  `applied: boolean` per facet (a local `PrioritizedFacet` interface
  extending `OverflowItem`).

- [ ] **Step 1: Failing vitest.** Extend `mountOverflow` with
  `applied?: string[]` (ids to stamp) and render the trigger and mark
  hooks inside the host. New cases:
  - `f1` idle, `f3` applied, row 300 (one fits): row holds `f3` alone,
    `⋯` holds `f1, f2` in that order.
  - Kept set renders in declared order: `f1` and `f3` applied, room for
    two → row `f1, f3`, `⋯` `f2`.
  - Stepwise narrowing, nothing applied: 1000 → 400 → 300 → `⋯` reads
    `f2, f3` (fails today: `f3, f2`).
  - Narrow-wide-narrow keeps both orders.
  - Mark: `f3` applied, all fit → mark `invisible`, label `More filters`;
    row too narrow for `f3` → mark visible, label `More filters, some
    applied`; widen → back.
  - Existing five cases stay green unchanged.
- [ ] **Step 2:** `make test-ts TS_ARGS="ts/elements/quick-filter-bar.test.ts"` — new cases fail.
- [ ] **Step 3: Implement.**
  - `setupOverflow` reads `applied` per facet from the attribute and finds
    the two hooks; the host is measured unhidden as today (the mark takes
    its width because it is `invisible`).
  - `layoutOverflow`: priority = applied facets then idle, each in
    declared order; `fitCount` from `priorityPlusFitCount` over those
    widths (fast path unchanged: same total); `kept = new Set(priority
    .slice(0, fitCount))`. Row: for each facet in declared order that is
    kept, `row.insertBefore(element, overflowHost)` when its position is
    wrong — reinsert kept facets in declared order before the host.
    `⋯`: append every spilled facet in declared order each layout
    (`appendChild` moves; skip when `overflowItems.children` already
    equals the spilled list, so an unchanged layout moves no node and an
    open facet panel inside `⋯` survives a resize).
  - Mark: `someApplied = spilled.some(facet => facet.applied)`; toggle
    `invisible` on the mark, set the trigger's `aria-label`.
- [ ] **Step 4:** Same command — all pass.
- [ ] **Step 5:** Commit `feat: quick bar spills idle facets first (#1254)`.

### Task 2: Stamp and mark on the server

**Files:**
- Modify: `common/components/search_select.py` (`ComboboxDropdown`)
- Modify: `common/components/quick_filter.py` (`_facet`, `_overflow_dropdown`)
- Test: `tests/test_quick_filter_bar.py`

**Interfaces:**
- Produces: `ComboboxDropdown(..., applied: bool = False)`; markup hooks
  named in Task 1.

- [ ] **Step 1: Failing pytest.**
  - `ComboboxDropdown(applied=False)` renders exactly as before (compare
    against the rendered string without the kwarg).
  - `applied=True`: trigger holds a `bg-brand` dot span, the label inside
    a `text-fg-brand` span, and `sr-only` "(applied)"; the button's own
    class list holds no `text-fg-brand`; the panel's `aria-label` is the
    bare label.
  - `QuickFilterBar` over `{"device": {...}, "day": {...}}` in sessions
    mode: exactly those two facets carry `data-quick-facet-applied` and
    the mark; one case per kind (set, date, number, string, bool) across
    modes.
  - The `⋯` host holds `data-quick-overflow-trigger` on the button whose
    `aria-label` is `More filters`, and `data-quick-overflow-mark` with
    `invisible`.
- [ ] **Step 2:** `flock … make test-fast ARGS="tests/test_quick_filter_bar.py -x"` — fails.
- [ ] **Step 3: Implement.** `ComboboxDropdown` builds the trigger's
  children from `applied`; `_facet` passes
  `applied=facet.field in self.existing` and adds
  `data_quick_facet_applied` to `config` when applied. `_overflow_dropdown`
  passes the trigger hook through `EllipsisTrigger`'s positional attrs and
  puts the mark beside the `Dropdown` in a `flex items-center` wrapper
  inside the host, so the host's `hidden` toggle stays the only display
  class on it.
- [ ] **Step 4:** Same command — pass. `make ts` then
  `make test-ts TS_ARGS="ts/elements/quick-filter-bar.test.ts"` — the
  vitest hooks match the rendered markup names.
- [ ] **Step 5:** Commit `feat: mark applied quick facets (#1254)`.

### Task 3: The orders, and the e2e that reads them

**Files:**
- Modify: `common/components/quick_filter.py` (`QUICK_FACETS`)
- Modify: `wave doc` `docs/superpowers/specs/2026-09-19-selectable-tables-wave-design.md:519-521`
- Test: `tests/test_quick_filter_bar.py`, `e2e/test_quick_filter_e2e.py`,
  `e2e/test_set_filter_e2e.py`, plus any e2e the gate finds (candidates:
  `test_string_filter_e2e.py` name clicks on games/purchases,
  `test_boolean_filter_e2e.py` mastered)
- Create: `e2e/quick_bar.py` holding `open_facet(page, field)` (moved from
  `e2e/test_number_filter_e2e.py:_open_facet`, which imports it)

- [ ] **Step 1: Failing pytest** pinning each mode's field order exactly
  as the spec's table (one parametrized test, a dict literal per mode).
- [ ] **Step 2:** Run — fails. Reorder `QUICK_FACETS`; drop the
  `#: The run's facts, after the session's.` comment, now false. Run —
  passes.
- [ ] **Step 3: New e2e** in `e2e/test_quick_filter_e2e.py`: at 2000px,
  the session list opened with `{"outside_playthrough_dates":
  {"value": true}}` shows that facet in the row with
  `data-quick-facet-applied` and the mark visible; at 520px it spills
  last (idle facets first), and the `⋯` trigger's `aria-label` reads
  `More filters, some applied`.
- [ ] **Step 4: Fix the tests the order breaks.** Priority-plus test:
  wide row now spills Device, Timing, Duration (assert Timing **in** `⋯`,
  Outside dates not); docstring and the Duration test's "four fit"
  comment restated. `test_set_filter_presence_is_null` and every other
  click on a facet that may spill go through `open_facet`. Run
  `flock … make test-e2e ARGS="-k quick or filter or playtime" -x` and
  follow every failure to a position assumption.
- [ ] **Step 5:** Wave doc: the sentence "which facets ride inline is
  #1254's" becomes one line naming the rule and linking the spec.
- [ ] **Step 6:** Commit `feat: order every quick bar's facets (#1254)`.

### Task 4: Page diff and gate

- [ ] **Step 1:** `make render-pages ARGS="--user <dev user> --out <scratch>/after"`
  and the same at `origin/main` in a scratch worktree; `diff -r`. Every
  differing file is a reordered facet list or an applied mark on a page
  whose URL carries a filter. Record the tally in the PR body.
- [ ] **Step 2:** `make format`, `make lint-fix`, `make vale`.
- [ ] **Step 3:** `flock … make check`, read from a log with its exit
  code. Green before the docs sweep and the PR.
