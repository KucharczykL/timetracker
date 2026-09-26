# A SearchSelect that holds "none" — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single-select `SearchSelect` takes `none_label`, and holds "none" as a committed value apart from "nothing picked".

**Architecture:** The Python component renders a pinned none row and, where nothing resolves, a held none (a marked empty hidden input and the label in the box). The element gets one `holdNone()` path that every "drop the value" site in a none picker calls. The change event gains `none: boolean`. Three optional form pickers adopt it. Purchase platform autofill yields to the person's own act.

**Tech Stack:** Django 6 components (`common/components`), TypeScript custom element, vitest (jsdom), pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-26-issue-1288-search-select-none-design.md`. Read it first. It holds the state table, the event table, the hidden-input reader table and the rules for other features. This plan names where each rule goes. It does not restate them.

## Global Constraints

- Hooks: row `data-search-select-none-option`, held input `data-search-select-none`. Never `data-search-select-modifier-option` for the none row.
- Event: `SearchSelectChangeDetail.none: boolean`. For none: `values: []`, `last: null`, `none: true`. A picker without `none_label` always emits `false`.
- Refusals: `none_label` with `multi_select=True` or `panel=True` raises `ValueError`. `SearchSelectWidget.render` raises `ValueError` when `none_label` is set and `is_required` is true.
- Labels: session and historical `device` → `"No device"`. Purchase `platform` → `"Unspecified"`.
- Every command through `make`. Pytest targets under `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`. Run `make ts` after a `.ts` edit, before e2e.
- Complete-word identifiers. Comments explain intent only, with no issue references.
- Tasks 1 and 2 change the component, and the adopting forms come after them. Commit after each task.

---

### Task 1: The component renders none

**Files:**
- Modify: `common/components/search_select.py`: `RowKind`, `_option_row`, `SearchSelect`
- Modify: `common/components/custom_elements.py`: `SearchSelectProps`
- Test: `tests/test_search_select.py`

**Produces:** `SearchSelect(..., none_label: str | None = None)`, `RowKind.NONE`, prop `none_label: str` (blank means none), TS name `props.noneLabel`, after `make gen-element-types`.

- [ ] Write failing tests in `tests/test_search_select.py`:
  - `none_label="No device"` with no `selected` renders the none row as the options panel's first row: `role="option"`, `data-search-select-none-option`, `data-label="No device"`, no `id`. It also renders `<input type="hidden" name=… value="" data-search-select-none>` in `[data-search-select-pills]`, and the search box `value="No device"`.
  - With `selected=[device]`, the row is still first, and the box and input hold the device. No `data-search-select-none` input renders.
  - The row renders with `search_url` set, where no option rows render, and without it.
  - The element carries `none-label="No device"`. Without `none_label`, the attribute is blank and nothing else changes: an existing render test stays green.
  - `none_label` with `multi_select=True` raises `ValueError`. So does `none_label` with `panel=True`.
- [ ] Run: `make test-fast ARGS="tests/test_search_select.py -x"`. Expect FAIL.
- [ ] Implement:
  - `RowKind.NONE` (doc comment: "Pinned; picking it holds none."). The `_option_row` branch uses `_option_role_attributes(False)`, `("data-search-select-none-option", "")` and `("data-label", label)`.
  - In `SearchSelect`, refuse the two combinations at the top.
  - In the single branch of the pills block, `elif none_label:` appends `Input(type="hidden", name=name, value="", data_search_select_none="")` and sets `search_value = none_label`.
  - Prepend `_option_row({"value": "", "label": none_label, "data": {}}, RowKind.NONE)` to `option_rows` in every branch.
  - Pass `none_label=none_label or ""` to `_SearchSelect`.
  - Add `none_label: str` to `SearchSelectProps`, with a `#:` comment.
- [ ] Run `make gen-element-types`, then the same test command. Expect PASS.
- [ ] Commit `feat: SearchSelect renders a held none and its pinned row`.

### Task 2: The element holds none

**Files:**
- Modify: `ts/elements/search-select.ts`
- Test: create `ts/elements/search-select.none.test.ts`. Copy the `mount` harness of `search-select.clear.test.ts`, and add a `noneLabel` mount option that renders the row and, when there are no seeds, the held none input.

**Consumes:** the markup from Task 1 and `props.noneLabel`. **Produces:** `SearchSelectChangeDetail.none`, and the internal `holdNone()`.

- [ ] Write failing vitest cases, one `it` each. These are the spec's Testing list:
  1. Clicking the none row holds none: the marked input exists, the box reads the label, and the change event carries `{values: [], last: null, none: true}`.
  2. ArrowDown/ArrowUp reach the none row in both directions. Enter on it holds none and does not throw.
  3. × on a held value holds none, emits change `none: true` then `search-select:clear`, and × is hidden afterwards.
  4. Typing into a held none, then ×, holds none again with `none: true`.
  5. The first keystroke into a held value or a held none emits `values: []` with `none: false`.
  6. A non-empty query never highlights the none row, and an empty query highlights as before.
  7. Typing the exact none label offers no Create row (mount with `createRow: true`).
  8. A server answer (mock `fetch`) and `setOptions` both keep the row and a held none.
  9. `commit-sole-option="true"` with a held none: an answer of one row leaves none held.
  10. A dependency change (the `params` mount of `search-select.params.test.ts`) turns a held value into none with no event, and leaves a held none alone.
  11. `setSelected` replaces a held none, and the input is no longer marked.
  12. Two cloned mounts hold none independently.
  13. A picker without `none-label`: every change event carries `none: false`, and filter-mode modifier rows are unchanged (the existing filter suites cover this).
- [ ] Run: `make test-ts ARGS="ts/elements/search-select.none.test.ts"`. Expect FAIL. `test-ts` takes no `ARGS` today, so first change its recipe to `pnpm test:ts $(ARGS)`; vitest reads the trailing path as a filter.
- [ ] Implement in `search-select.ts`:
  - Add `"[data-search-select-none-option]"` to `NAVIGABLE_ROWS`.
  - Add `SearchSelectChangeDetail.none: boolean`. `emitChange(last, none = false)` puts it in `detail`.
  - Add `const noneLabel = multi ? "" : props.noneLabel;`.
  - Add a helper that returns the hidden inputs other than `[data-search-select-none]`. `currentValues`, `getSelectedValues` and `syncClearButton` use it. `syncUncommitted` and `commitTheSoleOption` stay as they are.
  - `holdNone()`: `_searchSelectClear?.()`, then append the marked empty input (`buildHidden("")` plus the attribute), set `search.value` and `_searchSelectLabel` to `noneLabel`, set `_searchSelectDirty = false`, then `syncUncommitted()`.
  - Click handler: a branch for `[data-search-select-none-option]` placed before the filter-modifier branch. It runs `holdNone(); hidePanel(); soleDeclined = false; emitChange(null, true)`.
  - Enter handler: the same branch, placed before the `data-search-select-modifier-option` check.
  - × click: `if (noneLabel) { holdNone(); emitChange(null, true); } else if (heldValue) emitChange(null);`. The clear event follows as today.
  - `onDependencyChange`: after `_searchSelectClear`, call `holdNone()` when `noneLabel` is set. Emit nothing, as today.
  - `_searchSelectSetOptions`: where it clears a stale value, call `holdNone()` after it when `noneLabel` is set.
  - `autoHighlight`: with a non-empty `lower`, skip rows that match `[data-search-select-none-option]`.
  - `loadedLabels`: add `noneLabel.trim().toLowerCase()` when set.
- [ ] Run the new file, then `make test-ts`. Expect every suite PASS.
- [ ] Commit `feat: the SearchSelect element holds none`.

### Task 3: Forms adopt none; platform autofill yields

**Files:**
- Modify: `games/forms.py`: `SearchSelectWidget`, `SessionForm.device` (about line 946), `HistoricalPlaytimeForm.device` (about 1197), `PurchaseForm.platform` (about 1435)
- Modify: `ts/add_purchase.ts`: platform autofill
- Test: `tests/test_search_select.py`, the file that already covers `SearchSelectWidget`
- Test: create `e2e/test_search_select_none_e2e.py`, and extend `e2e/test_purchase_e2e.py`

**Consumes:** `SearchSelect(none_label=…)`, and change events with `none`.

- [ ] Write failing tests:
  - pytest: each of the three forms, unbound, renders the none row with its label and holds none.
  - pytest: a `SearchSelectWidget(none_label="x")` on a `required=True` field raises `ValueError` on render.
  - pytest: `SessionForm` posted with `device=""` and posted with no `device` key both clean to `None`.
  - e2e: on Edit Session with a device held, pick "No device" and save, and the row's `device_id` is `None`. Press × on a held device and save, with the same result. Wait on the redirect page before reading the ORM.
  - e2e: on Add Purchase, pick a game with a platform, and Platform fills. Pick "Unspecified", then pick another game, and Platform stays "Unspecified".
- [ ] Run: `make test-fast ARGS="tests/test_search_select.py -x"`. Expect FAIL.
- [ ] Implement:
  - `SearchSelectWidget(none_label: str | None = None)` stores the label. `render` raises when `self.none_label and self.is_required`, and passes it to `SearchSelect`.
  - Set `none_label="No device"` on the two device widgets and `"Unspecified"` on platform.
  - `add_purchase.ts`: add `let platformOwnedByPerson = false`. A `search-select:change` whose `detail.name === "platform"` sets it to `true`; programmatic `setSelected` emits no event, so autofill never trips it. The platform autofill returns early when the flag is set.
- [ ] Run `make ts`, then the pytest file. Then run under the lock: `make test-e2e ARGS="e2e/test_search_select_none_e2e.py e2e/test_purchase_e2e.py"`. Expect PASS.
- [ ] Commit `feat: optional device and platform pickers hold none`.

### Task 4: Gate

- [ ] In `CLAUDE.md`, the `search_select.py` bullet gets one clause: `none_label` pins a row that holds none (an empty hidden input with the key present), apart from nothing picked (key absent), and the change event marks it with `none`.
- [ ] `make format`, `make lint-fix`, `make vale`.
- [ ] Run the full gate under the lock, and read the exit code from a log:
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check > "$SCRATCH/check.log" 2>&1; echo $?`. Expect `0`.
- [ ] Commit `docs: CLAUDE.md names none_label`.

## Follow-up issues

None to file. #1303 is already filed. #1289, #1301 and #1302 carry their own comments.
