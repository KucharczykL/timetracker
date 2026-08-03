# YearPicker Intrinsic Popup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the stats YearPicker popup derive its width from the existing calendar grid without duplicating width arithmetic in the popup shell.

**Architecture:** Keep the YearPicker's established `w-14` cells and `w-56` four-column grid, matching the existing date calendar's explicit equal-cell geometry. Move `p-2` from the popup surface into a body wrapper and make the outer surface width-auto/flex so its intrinsic width is grid plus padding and borders. The shared anchored positioner continues to measure and clamp the resulting popup.

**Tech Stack:** Django component builders, Tailwind utility classes, Playwright browser tests, and the existing shared dropdown positioner.

## Global Constraints

- Do not introduce JavaScript width measurement or component-specific `w-64` arithmetic.
- Preserve the existing `ControlButton` styling and `w-14`/`w-56` equal-cell geometry.
- Preserve shared dropdown positioning and viewport clamping.
- Verify centering, equal cell geometry, font-size scaling, and narrow viewport containment.

---

### Task 1: Add failing geometry and markup tests

**Files:**
- Modify: `e2e/test_year_picker_e2e.py`
- Modify: `tests/test_year_picker.py`

- [ ] **Step 1: Add browser geometry assertions**

Extend the YearPicker browser coverage with helpers that assert:

```python
left_gap = grid_box["x"] - popup_box["x"]
right_gap = popup_box["x"] + popup_box["width"] - (
    grid_box["x"] + grid_box["width"]
)
assert abs(left_gap - right_gap) <= 1
```

Also assert that all twelve cell boxes have equal widths, each row has equal
column positions, and the assertions hold after setting the root font size to
`12px`, `16px`, and `24px`. Add a narrow-viewport assertion that the popup
stays at least eight pixels from both viewport edges.

- [ ] **Step 2: Assert that popup width is not independently fixed**

Update the component rendering test to require a `data-year-picker-body` hook,
retain `w-14 shrink-0` and `w-56` on the calendar geometry, and reject the
popup's independent `w-64` width class.

- [ ] **Step 3: Run the focused tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=/tmp/timetracker-uv-cache uv run --frozen pytest \
  e2e/test_year_picker_e2e.py tests/test_year_picker.py -q
```

Expected: the centering and intrinsic-width assertions fail against the current
left-aligned `w-64` popup.

### Task 2: Use the intrinsic calendar popup surface

**Files:**
- Modify: `common/components/primitives.py`

- [ ] **Step 1: Move padding into the YearPicker body**

Render the popup surface without `p-2` or `w-64`, using the existing overlay
surface pattern with `flex w-auto`. Add a `Div(data_year_picker_body="", class_="p-2")`
inside the popup and move the existing header, grid, and template into it.
Keep the grid class `grid grid-cols-4 gap-y-0.5 mt-1 w-56` and the cell class
`w-14 shrink-0` unchanged.

- [ ] **Step 2: Run the focused tests and verify they pass**

Regenerate the ignored static output if needed, then run:

```bash
UV_CACHE_DIR=/tmp/timetracker-uv-cache uv run --frozen pytest \
  e2e/test_year_picker_e2e.py tests/test_year_picker.py -q
```

Expected: the popup width equals its intrinsic body content plus padding and
borders; the grid is centered, equal-cell, font-size-stable, and viewport-safe.

- [ ] **Step 3: Commit the focused change**

```bash
git add common/components/primitives.py e2e/test_year_picker_e2e.py tests/test_year_picker.py
git commit -m "fix: size year picker popup from calendar content"
```

### Task 3: Run final verification and update the PR

- [ ] **Step 1: Run the full repository gate**

Run:

```bash
export UV_CACHE_DIR=/tmp/timetracker-uv-cache
source .direnv/nix-profile-26.11-lj0fr41wwbrx2mwq.rc
make check
```

The gate must finish with zero failures.

- [ ] **Step 2: Inspect the final tree**

Run `git diff --check`, `git status --short`, and verify the branch contains no
uncommitted changes.

- [ ] **Step 3: Push the verified commit**

Run:

```bash
git push origin feat/in-house-stats-year-picker
```

