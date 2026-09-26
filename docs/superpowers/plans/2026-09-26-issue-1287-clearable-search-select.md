# A SearchSelect that clears — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `SearchSelect(clearable=True)` gains a trailing × that empties query and value in one press. Optional form pickers get it by default.

**Architecture:** The Python component renders a hidden-by-default `<button data-search-select-clear>`, and its presence is the element's opt-in. `ts/elements/search-select.ts` keeps it visible through the two existing sync points and performs the press. `SearchSelectWidget` resolves `clearable` from `is_required` and renders the label id as the description.

**Tech Stack:** Python components (`common/components/search_select.py`), Django widget (`games/forms.py`), TypeScript custom element, pytest, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-26-issue-1287-clearable-search-select-design.md`. Read it first. This plan names files and cases. The spec argues the rules.

## Global Constraints

- One press clears query and committed value together, in single and multi mode.
- Name `aria-label="Clear"`, `title="Clear"`. The description is `aria-describedby` pointing at `field_label_id(id)`, from the widget only.
- Events in order: `search-select:change` `{values: [], last: null}` only when a committed value was removed, then `search-select:clear` `{name}` on every press.
- Focus: a pointer press never focuses the button. A press while the button holds focus moves focus to the box. `event.detail` is never read.
- The button is a Tab stop. Its `focus` closes the panel.
- A disabled box hides the button through `peer` / `peer-disabled:hidden`. No observer.
- No new element prop. Button presence is the opt-in.
- `FilterSelect` and `PresetSelect` do not change.
- Complete-word identifiers. No issue references in comments.
- Wrap every pytest target in `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`. Iterate with `make check-fast`. The gate is one full `make check` at the end.

## Step 0

- [ ] `git fetch origin && git rebase origin/main`.

---

### Task 1: The component renders the button

**Files:**
- Modify: `common/components/search_select.py`: `SearchSelect()` (~432-640) and `_combobox_children()` (~349-429)
- Test: `tests/test_search_select.py`

**Interfaces:**
- Produces: `SearchSelect(..., clearable: bool = False, clear_description_id: str = "")`. The button carries `data-search-select-clear`, `type="button"`, `aria-label="Clear"`, `title="Clear"`, and `aria-describedby=clear_description_id` when non-empty. It carries `hidden` unless `selected` is non-empty. `_combobox_children` takes `clear_button: Node | None` and places it after `search`, before `marker`.

**Layout:**
- The button's classes include `peer-disabled:hidden shrink-0 ml-auto`, plus the pill × look (`_filter_remove_button` / pill remove).
- The search input gains `peer`, only when `clearable`, so other flavours' markup stays byte-identical, as `_UNCOMMITTED_SEARCH_CLASS` does.
- Use `Icon("x", …)` if the icon set has one (`ls games/templates/icons/`). Otherwise use the "×" text the pill remove uses.

- [ ] Tests (fail first):
  - Clearable single with no selection renders a button with `hidden`, and one selected renders it without.
  - Same for `multi_select=True`.
  - Attributes as above. `aria-describedby` is present only when an id is given.
  - Default `SearchSelect` renders no `data-search-select-clear`.
  - A clearable search input carries `peer`, and a default one does not.
- [ ] Implement. `make test-fast ARGS="tests/test_search_select.py -x"` goes green.
- [ ] Commit `feat: SearchSelect renders a clear button`.

### Task 2: The widget resolves who gets it

**Files:**
- Modify: `games/forms.py`: `SearchSelectWidget.__init__`/`render` (~303-378), `SearchSelectMultiple` (~380), `PlaythroughSelectWidget.__init__` (~782-804)
- Test: `tests/test_search_select.py` (or `tests/test_forms.py` if widget tests live there: `grep -ln SearchSelectWidget tests/`)

**Interfaces:**
- Consumes: Task 1's `clearable`, `clear_description_id`.
- Produces: `SearchSelectWidget(clearable: bool | None = None)`. `render` passes `clearable=not self.is_required if self.clearable is None else self.clearable` and `clear_description_id=field_label_id(id) if id else ""`. `field_label_id` comes from `common/components/primitives.py:1768`. `PlaythroughSelectWidget(*, game_field, clearable=None, attrs=None)` forwards it.

- [ ] Tests (fail first):
  - A form field with `required=False` renders the button, and one with `required=True` does not.
  - `clearable=True` on a required field renders it, and `clearable=False` on an optional one does not.
  - The description equals `field_label_id(bound_field.id_for_label)`.
  - `SessionForm`'s `device` renders a button, and its `game` and `playthrough` do not.
- [ ] Implement. Name the resolved flag with a helper if the expression reads poorly. Keep the widget signature keyword-only.
- [ ] Run `tests/test_rendered_pages.py` and `tests/test_paths_return_200.py`. Rendered-page assertions over the session and purchase forms may pin markup, so update any expectation the new button breaks. Update none that fail for another reason.
- [ ] Commit `feat: optional form pickers are clearable`.

### Task 3: The element clears

**Files:**
- Modify: `ts/elements/search-select.ts`
- Test: create `ts/elements/search-select.clear.test.ts`, mounted like `search-select.single-select.test.ts` (`mountSingle`), with a `<button data-search-select-clear hidden>` after the input and an optional `<label id>` plus `aria-describedby`.

**Interfaces:**
- Produces: exported `interface SearchSelectClearDetail { name: string }` beside `SearchSelectChangeDetail`. Event `"search-select:clear"`, `bubbles: true`. Container state `_searchSelectSoleDeclined?: boolean` on `SearchSelectContainer`.

**Implementation points** (line numbers as of `55b13852`):
- Query `clearButton = container.querySelector<HTMLButtonElement>("[data-search-select-clear]")` in `initWidget` beside `search` / `pills`. Every step below is a no-op when it is null.
- `syncClearButton()`: `clearButton.hidden = !(pills.querySelector('input[type="hidden"], [data-pill]') || search.value.trim())`.
  - Call it first in `syncUncommitted()` (:297), ahead of the early return. That early return must not skip it, including in multi mode.
  - Call it in `emitChange()` (:1227).
  - Call it once at the end of init, after the `sync_url` restore (:1251).
- Press handler (`clearButton` `click`):
  1. `const hadValue = currentValues().length > 0` (single: hidden input; multi: pills).
  2. `const keyboard = document.activeElement === clearButton`.
  3. `clearTimeout(debounceTimer)`. Abort `pendingRequest`, as the focusout handler does (:1275-1282).
  4. `container._searchSelectClear()`.
  5. `container._searchSelectSoleDeclined = true`.
  6. `filterRows("")`, `setCreateRow("")`, `setNoResults(false)`.
  7. If `hadValue`, `emitChange(null)`. Then dispatch `search-select:clear`.
  8. `syncClearButton()`. If `keyboard`, `search.focus()`.
- `clearButton` `mousedown` → `preventDefault()`.
- `clearButton` `focus` → `hidePanel()`.
- `commitTheSoleOption` (:693) returns early when `_searchSelectSoleDeclined`. `selectOption` with `emit` true and `onDependencyChange` (:708) set it to `false`. `_searchSelectClear` itself must **not** reset it, because the press calls clear before it sets the flag and the dependency path resets it explicitly.
- Confirm `focusout` (:1270) still closes the panel when focus leaves from the button, since `relatedTarget` is outside the container.

- [ ] Tests (fail first), in the new file:
  - **Visibility:** hidden at mount with nothing committed. Shown after a pick and after typing. Hidden again after typing is deleted back to empty with nothing committed. Shown at mount with a committed seed. Shown after `_searchSelectSetSelected`. Hidden after `_searchSelectClear`. Multi: shown with a pill, and hidden after the last pill ×.
  - **Single press, committed:** the hidden input is gone, the box is empty, and the events are `["search-select:change", "search-select:clear"]` with change `values: []`, `last: null`.
  - **Query-only press** (typed, nothing committed): only `search-select:clear` fires. Its detail is `{ name: "device" }`.
  - **Multi press** with two pills and a query: every pill and hidden input is removed, the box is empty, change fires, then clear.
  - **Pending debounce:** stub `fetch`, type with a `search-url`, press before the timer fires, advance fake timers. No fetch was made for the old query, and no rows from it render.
  - **Sole option:** `commit-sole-option="true"` with `prefetch`. Seed a commit, focus the button, press, and let the focus fetch answer one option. The field stays empty. A later explicit pick commits.
  - **Focus:** a press with focus on the button leaves `document.activeElement === search`. A press dispatched while focus is on `<body>` leaves focus on `<body>`.
  - **Panel:** focus on the button closes an open panel (`aria-expanded="false"`).
  - **No button:** a widget without the button behaves as today. The existing suites pass unchanged.
- [ ] Implement. Then run `make test-ts` and `make ts-check`.
- [ ] Commit `feat: SearchSelect clears on ×`.

### Task 4: e2e, one per flavour

**Files:**
- Modify: `e2e/test_search_select_e2e.py`: add one harness view rendering `SearchSelect(multi_select=True, clearable=True, …)` with two selected options inside a `<form>`, plus its `urlpatterns` entry, modelled on `e2e_test_view` (:10)
- Test: the same file for multi. Single goes on the real session form: find its existing e2e (`grep -ln "session" e2e/*.py`, the add-session page test) and add beside it.

- [ ] **Single, real form** (add-session page, `device` holding a device):
  - Tab from the device box to the × and check that the panel is closed. Press Enter. The box is empty, focus is on the box, and submitting posts no `device`. Assert from the server-rendered redirect or row, not the DOM, as CLAUDE.md's "UI assertion is not database assertion" says.
  - Reload, pick a device, click × with the mouse: the box is empty and focus is not on the box. Seed focus on another field first, then assert it is still there.
- [ ] **Multi, harness:**
  - Keyboard: Tab to ×, press Space. No pills remain.
  - Pointer: click × from focus elsewhere. No pills remain and focus is unchanged.
  - Collect `console` errors and assert none.
- [ ] `make ts` first. Never run e2e while `make dev` is up. Then `flock … make test-e2e ARGS="e2e/test_search_select_e2e.py"` plus the session file.
- [ ] Commit `test: clearing a SearchSelect end to end`.

### Task 5: Docs and records

**Files:**
- Modify: `CLAUDE.md`, the `search_select.py` bullet under Component system. One clause: `clearable` renders a trailing × that clears query and value in one press, emits `search-select:clear`, and defaults on for optional form fields.
- Spec: rewrite timeless if anything moved during implementation.
- Delete: this plan (`docs-sweep` convention) once implementation merges.

- [ ] `make vale`, `make format`, `make lint-fix`, `make format-check`.
- [ ] Full gate: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check 2>&1 | tee …; echo exit=$?`. Read the exit code, not grep.
- [ ] Commit `docs: SearchSelect clears`.

## Gotchas

- `_searchSelectClear` is also the preset picker's silent reset and the dependency reset. It must stay silent. The press adds the events, not clear.
- `add_purchase.ts:151` disables `#id_related_game`, which is now clearable. Check the Add Purchase page by hand once: type "game" hides ×, and a pick survives.
- Browser form-state restore can fill the box without an input event (see the `syncUncommitted` comment). × may then be stale until the next interaction, which is accepted.
- `time-zone-row.ts:52` ignores a change with `last: null`. It is not clearable, so nothing changes there.
