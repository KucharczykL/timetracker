# Selectable table (#711) implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development
> or superpowers:executing-plans. Steps are checkboxes.

**Goal:** `StyledTable` gains a selectable personality — a Select mode, a
footer selection line, and a selection statement — proven on a synthetic page,
used by nothing on `main`.

**Architecture:** The server renders the row's name (`data-selection-key`), the
row's mobile summary, and the footer's selection line. `<selectable-table>`
builds every checkbox when the mode turns on, holds the selection, and
announces it. The actions slot stays empty until #712.

**Tech stack:** Python component tree (`common/components/primitives.py`),
TypeScript custom element (`ts/elements/`), vitest, pytest, Playwright.

**Spec:** [A selectable table](../specs/2026-09-19-issue-711-selectable-table-design.md)
**Wave:** [Selectable tables](../specs/2026-09-19-selectable-tables-wave-design.md)

## Global constraints

- Every command through `make`; never raw `uv run`/`pnpm`/`pytest`.
- Gate before the PR: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`, green, including `e2e/`. Iterate with `make check-fast`.
- Run `make ts` after editing any `.ts`, or e2e serves stale `dist/`.
- Markup is htpy builders only; no HTML strings, no inline JS, no new Alpine.
- Behaviour lives in `ts/elements/<tag>.ts`; props go through `register_element` + `make gen-element-types` (the generated `ts/generated/props.ts` is committed).
- Complete words in identifiers (`checkbox` not `cb`, `element` not `el`).
- `make vale` is part of `make check`; the vocabulary applies to comments too.
- Never run e2e while `make dev` is up.

## Files

| Path | Responsibility |
|---|---|
| `common/components/primitives.py` | `make_row` key/summary, `TableRowData`/`TableData`, `TableRow` summary line, `StyledTable` selection parameter + footer composite + shell clip, the selection line builder |
| `common/components/custom_elements.py` | `SelectableTableProps`, `register_element` |
| `ts/generated/props.ts` | regenerated, committed |
| `ts/elements/selection-statement.ts` | pure selection model: toggle, range, check-all state, statement |
| `ts/elements/selection-statement.test.ts` | vitest for the model |
| `ts/elements/selectable-table.ts` | the element: mode, checkbox building, keyboard, live region, event, height variable |
| `ts/elements/selectable-table.test.ts` | vitest (jsdom) for the DOM half |
| `ts/elements/responsive-table.ts` | name floor gains the checkbox below `md` |
| `ts/elements/responsive-table.test.ts` | floor cases |
| `common/components/toast.py`, `common/layout.py` | stand off `--selection-line` |
| `tests/test_components.py` | render rules |
| `e2e/test_selectable_table_e2e.py` | synthetic page: mode, keyboard, sticky, region, stacked cell |
| `e2e/test_responsive_table_e2e.py` | floor assertion moves to the name content |

---

### Task 1: the row's name, the table's declaration

**Files:** modify `common/components/primitives.py` (`TableRowData` ~2057, `TableData` ~2100, `make_row` ~2115, `TableRow` ~2136, `StyledTable` ~2543, `paginated_table_content` ~2763); modify `games/views/playthrough_rows.py:116`; test `tests/test_components.py`.

**Interfaces — produces:**

```text
class SelectionDeclaration(TypedDict):
    filter: str            # the list's filter JSON, "" when none

make_row(*cells, key: str | None = None, summary: str | None = None, **attributes)
TableRowData: cell_data, attributes, key (NotRequired), summary (NotRequired)
TableData: caption, columns, rows, sort_terms, selection (NotRequired[SelectionDeclaration])
StyledTable(..., selection: SelectionDeclaration | None = None)
```

**Gotchas:**
- `make_row(**attributes)` turns every kwarg into a `<tr>` attribute, so `key`/`summary` MUST be keyword-only parameters declared before `**attributes`, or they render as `key="…"`. No caller passes either today (87 call sites).
- `key` renders as `data-selection-key` on the `<tr>`; the element reads it.
- `TableData` keys must be `NotRequired`, or the five existing dict literals (`device.py:84`, `platform.py:89`, `purchase.py:233`, `session.py:193`, `game.py:239`) redden under mypy.
- The refusal is **always-on**, not `settings.DEBUG`. `StyledTable`'s cell-count guard is DEBUG-only on purpose ("prod degrades to a ragged table over a 500"); a missing row key silently breaks an act instead. The precedent to copy is `games/views/playthrough_rows.py:138`.
- `playthrough_rows.py:116` builds `make_row(*cells) for cells in kept_rows` with the `Playthrough` out of scope — thread the key with `zip(runs, kept_rows)` when that table becomes selectable (#712). This task only keeps it compiling.
- The summary renders inside the identity `<th>`, which is `whitespace-nowrap` plus `max-md:w-full max-md:max-w-0`: give the summary its own block with its own `overflow-hidden text-ellipsis`, and `md:hidden` so it exists below `md` alone.

- [ ] **Step 1: failing tests** in `tests/test_components.py`:
  `test_make_row_renders_the_key_as_a_row_attribute`,
  `test_make_row_treats_a_positional_argument_as_a_cell` (so `key`/`summary` cannot be passed positionally),
  `test_selectable_table_refuses_a_row_with_no_key` (always, with `settings.DEBUG=False`),
  `test_summary_renders_below_md_only`,
  `test_a_table_with_no_selection_renders_as_before` (byte-equal to the current output for one fixture table).
- [ ] **Step 2:** `make test-fast ARGS="tests/test_components.py -k selection or summary"` → FAIL.
- [ ] **Step 3:** implement the TypedDict keys, the signature, the `<th>` summary line, the refusal, and the `selection=` pass-through in `paginated_table_content`.
- [ ] **Step 4:** the same command → PASS; then `make typecheck`.
- [ ] **Step 5:** commit `feat: name a table row for selection`.

---

### Task 2: the footer composite and the selection line

**Files:** modify `common/components/primitives.py` (`StyledTable` footer ~2723-2744); test `tests/test_components.py`.

**Interfaces — produces:** `SelectionLine(declaration, page_obj)` → `Node`, rendered above the pagination nav inside the shell.

The line's children, in order: the Select toggle (`ControlButton`, `aria-pressed="false"`), the check-all `Checkbox`, the count (`role="status"`), "Select all N matching" (only with a paginator), Clear, and an empty actions slot element #712 fills.

**Gotchas:**
- The generic `footer=` slot keeps raising `ValueError` beside pagination (`primitives.py:2723`); the selection line is a **third, named** region, not the general slot. Exactly one test breaks today: `tests/test_components.py::test_footer_plus_pagination_raises` — keep it passing.
- `N` is `page_obj.paginator.count`. Do not add a count to `TableData`. No paginator (Game detail's tables, `per_page=0`) → no all-matching control; the line still renders check-all, the count and Clear.
- The line carries the `selectable-table:not(:defined)` hide class, in the style of `_FALLBACK_HIDE_HEADER_CLASS` (`primitives.py:2429`), so a page with no scripting shows today's table.
- Shell class changes `overflow-hidden` → `overflow-clip` (`primitives.py:2744`). `clip` still clips the radius but is not a scroll container, which is what lets a sticky child reach the window. Do not add `transform`/`filter`/`contain` (see the comment there and `e2e/test_dropdown_clipping_e2e.py`).
- Sticky classes go on the line (`sticky bottom-0 z-10`): `z-10` is under the menu stratum (`custom_elements.py:738` is `z-20`), so #712's actions menu opens over it.
- `Checkbox()` bakes no size (`primitives.py:1199`); the check-all and every row checkbox need ≥24 px (`e2e/test_touch_targets_e2e.py:18`).

- [ ] **Step 1: failing tests:** `test_selection_line_renders_above_the_pagination_nav`, `test_selection_line_without_a_paginator_offers_no_all_matching`, `test_selection_line_hides_until_the_element_is_defined`, `test_shell_clips_instead_of_hiding`, and the existing `test_footer_plus_pagination_raises` unchanged.
- [ ] **Step 2:** `make test-fast ARGS="tests/test_components.py -k selection_line or shell_clips"` → FAIL.
- [ ] **Step 3:** implement `SelectionLine` and the footer composite.
- [ ] **Step 4:** tests PASS; `make check-fast`.
- [ ] **Step 5:** commit `feat: give a selectable table its footer line`.

---

### Task 3: the element's registration and skeleton

**Files:** modify `common/components/custom_elements.py`; modify `common/components/primitives.py` (wrap the region); create `ts/elements/selectable-table.ts`; regenerate `ts/generated/props.ts`.

**Interfaces — produces:**

```text
class SelectableTableProps(TypedDict):
    filter: str   # the list's filter JSON, for the all-matching statement
    count: int    # the paginator's matching count, 0 with no paginator

register_element("selectable-table", "SelectableTable", SelectableTableProps)
customElements.define("selectable-table", SelectableTableElement)
```

**Gotchas:**
- `<selectable-table>` wraps `<responsive-table>`, which keeps owning the column drop; build it with `custom_element_builder("selectable-table")` so `Media` attaches itself and `Page()` emits `dist/elements/selectable-table.js`.
- `<selection-fields>` already exists and means something else; do not shorten this element's name toward it.
- Run `make gen-element-types` and commit `ts/generated/props.ts`; `make ts-check` regenerates and a drift leaves the tree dirty.

- [ ] **Step 1:** add the props, register, wrap, `make gen-element-types`.
- [ ] **Step 2:** `make ts-check` → passes with an element that only defines itself.
- [ ] **Step 3:** pytest: `test_selectable_table_wraps_the_responsive_table`.
- [ ] **Step 4:** `make check-fast`.
- [ ] **Step 5:** commit `feat: register the selectable-table element`.

---

### Task 4: the selection model (pure, vitest)

**Files:** create `ts/elements/selection-statement.ts` and `ts/elements/selection-statement.test.ts`.

**Interfaces — produces:**

```text
type SelectionStatement =
  | { keys: string[] }
  | { all: true; filter: string; count: number; except: string[] };

type SelectionState = { keys: Set<string>; all: boolean; except: Set<string> };

emptySelection(): SelectionState
toggleKey(state, key): SelectionState          // under all: adds/removes an exclusion
setPage(state, pageKeys, checked): SelectionState
selectAllMatching(state): SelectionState
clearSelection(): SelectionState
rangeKeys(pageKeys, anchorKey, targetKey): string[]
checkAllState(state, pageKeys): "checked" | "indeterminate" | "unchecked"
selectionCount(state, pageKeys): number
statementFor(state, filter, count): SelectionStatement
```

**Test cases:** toggle adds and removes; toggle under `all` records and un-records an exclusion; a range from anchor to target, in both directions, inclusive; check-all's three states, including "all matching minus one exclusion" reading indeterminate; `statementFor` emits `{keys}` sorted and stable, and `{all,filter,count,except}` with exclusions; clearing drops `all` and every exclusion.

- [ ] **Step 1:** write `selection-statement.test.ts` for the cases above.
- [ ] **Step 2:** `make test-ts` → FAIL.
- [ ] **Step 3:** implement `selection-statement.ts` (pure functions, no DOM).
- [ ] **Step 4:** `make test-ts` → PASS.
- [ ] **Step 5:** commit `feat: model a table selection`.

---

### Task 5: the element's behaviour

**Files:** modify `ts/elements/selectable-table.ts`; create `ts/elements/selectable-table.test.ts`.

**Interfaces — produces:** event `selectable-table:change`, `detail` = `SelectionStatement`; the element sets `--selection-line` on `document.documentElement` while the mode is on.

**Behaviour:**
1. The toggle flips the mode: build a checkbox as the **first child** of every `tbody th[scope="row"]`, named by that row's identity text (excluding the summary line); remove them all when the mode turns off, clearing the selection.
2. Shift and a click, or Shift and Space, takes the range from the last checkbox toggled. `keydown` with Space must `preventDefault()` and apply the range itself, or the anchor toggles twice.
3. Check-all sets the page; "Select all N matching" sets `all`; Clear empties.
4. One `role="status"` region, updated at four moments only: mode on, check-all, all-matching, Clear.
5. Escape clears the selection **unless** `event.defaultPrevented` — `ts/elements/menu-behavior.ts:343` closes a menu on Escape without `stopPropagation`, and the session list's rows host `<drop-down>` device selectors.
6. A `MutationObserver` on `tbody` decorates a row that arrives while the mode is on, restoring its mark when its key was marked, and drops keys the table no longer holds.
7. While the mode is on, publish the line's measured height as `--selection-line`.

**Gotchas:**
- Inserting checkboxes mutates `tbody`, which `<responsive-table>`'s own observer already watches (`responsive-table.ts:146`), so the refit happens on its own — do not call it directly.
- The checkbox needs an accessible name; take it from the identity cell's text content, trimmed.
- jsdom has no layout: keep measurement behind a method the test can call, as `applyDecision` is on `<responsive-table>`.

**Test cases (vitest, jsdom):** the mode builds one checkbox per row and removes them; a row inserted while the mode is on arrives with a checkbox and keeps its mark; a key removed from the table leaves the selection; Escape with `defaultPrevented` changes nothing; the change event carries the statement; the live region text changes at the four moments and not on a single tick.

- [ ] **Step 1:** write the vitest cases.
- [ ] **Step 2:** `make test-ts` → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** `make test-ts` → PASS; `make ts`.
- [ ] **Step 5:** commit `feat: select rows in a table`.

---

### Task 6: the sticky line's neighbours

**Files:** modify `common/components/toast.py:16` and `common/layout.py:348`.

Both hold the bottom corner: `TOAST_STACK_CLASS` is `fixed z-50 bottom-0 right-0`, the version stamp is `fixed left-2 bottom-2`. Each reads the variable in its own class — `bottom-[calc(var(--selection-line,0px))]` and the stamp likewise — so the styling stays on the element that owns it. Toast stays `z-50`, deliberately above the line.

- [ ] **Step 1:** pytest `test_toast_stack_stands_off_the_selection_line`, `test_version_stamp_stands_off_the_selection_line`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: stand the bottom chrome off the selection line`.

---

### Task 7: the name floor below `md`

**Files:** modify `ts/elements/responsive-table.ts:25,101`; modify `ts/elements/responsive-table.test.ts`.

Below `md` column 0 costs the flat `NAME_FLOOR_PX = 160`, which budgets a name — not a name plus a checkbox plus a summary line. The cost model gains the checkbox's width while the mode is on; state the constant, do not measure per table.

- [ ] **Step 1:** vitest: `columnCosts` with selection on returns the raised floor for column 0 below `md`, and the unchanged floor with selection off.
- [ ] **Step 2:** `make test-ts` → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** `make test-ts` → PASS.
- [ ] **Step 5:** commit `fix: budget the checkbox in the name floor`.

---

### Task 8: the synthetic page

**Files:** create `e2e/test_selectable_table_e2e.py`; modify `e2e/test_responsive_table_e2e.py:179`.

**Harness:** `@override_settings(ROOT_URLCONF=...)` with module-level `urlpatterns` and a hand-written `_PAGE_TEMPLATE`, as `e2e/test_set_filter_e2e.py:28-76` does. `render_page` is not used there, so list both modules by hand: `dist/elements/responsive-table.js` and `dist/elements/selectable-table.js`. `StyledTable` itself is harness-safe — it calls no `reverse()`.

**Test cases:**
- the mode: no checkbox until Select is pressed; every row has one after; none after a second press.
- shift-click takes the range; Shift+Space takes the same range from the keyboard **and the anchor is not toggled twice** (this is the binding the review could not verify in a browser — assert the exact count).
- check-all reads indeterminate with one row unchecked.
- all-matching then unchecking a row leaves the scope with one exclusion, read from the change event.
- the live region says the four things and stays silent on a single tick.
- the line sticks: scroll a long table, the line's bounding box bottom equals the window's inner height; it stops at the table's end.
- a dropdown inside a row still opens over the line, and Escape on it does not clear the selection.
- at 390 px the summary is the second line of the identity cell and the name keeps its floor.

- [ ] **Step 1:** write the e2e file.
- [ ] **Step 2:** `make test-e2e ARGS="-k selectable_table"` → FAIL.
- [ ] **Step 3:** fix what it finds (expect the sticky and floor cases to need real work).
- [ ] **Step 4:** move `test_name_column_keeps_the_floor_at_mobile` from `tbody th`'s width to the name content's width, so a checkbox cannot satisfy it.
- [ ] **Step 5:** `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check` green.
- [ ] **Step 6:** commit `test: prove the selectable table in a browser`.

---

## Verification

- `make check` green, `e2e/` included, at every merged commit.
- `make render-pages` before and after shows no differing file: nothing on `main` declares a selection, so every page must render byte-identically apart from the shell's `overflow-clip`.
- The Orca transcript is #718's, on the finished pages; this issue only proves the region and the keyboard in Playwright.

## Follow-ups to file

- #712 fills the actions slot, and inherits the `z-10` stratum and the `--selection-line` variable.
- #715 fills `summary=` for the session list and threads `key=` through `playthrough_rows.py`.
- #718 records two accepted costs in its scoping comment: with scripting off there is no per-row act once the Actions columns retire, and a single-row act is three presses.
