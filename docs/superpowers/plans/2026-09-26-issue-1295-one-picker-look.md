# One picker look — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every dropdown shares one panel and one hover model, and `SearchSelect`, `FilterSelect` and `PresetSelect` share one row and one pill, matching the menus.

**Architecture:** `DropdownPanel` is the one panel builder: a non-scrolling surface around a `[data-menu-scroll]` scroller. `followPointer` is the one hover model for menus and pickers. The menu item look is split into a shape and an active state. Pickers build every row through one `_option_row(option, layout, kind, *, selected, actions)`, and every pill comes from `Pill(kind=…)`.

**Tech Stack:** Python components, TypeScript custom element, pytest, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-26-issue-1295-one-picker-look-design.md`. Read it first.

## Global Constraints

- Every `data-*` hook the element, the filter serializer, `selection-fields.ts` and `add_purchase.ts` read stays.
- Rows stay 2.25rem high (`_ROW_HEIGHT_REM`); row actions take `-my-1`.
- Row actions keep `tabindex="-1"`.
- No `hover:` utility on a picker row; the active look comes only from `data-[search-select-highlighted]:`.
- "Remove", never "delete", in prose and labels.
- Complete-word identifiers; comments ≤7 words; no issue references in comments.
- Wrap pytest targets in `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`. Iterate with focused targets; one full `make check` at the end.

---

### Task A: One dropdown panel

**Files:** `common/components/custom_elements.py` (`_DROPDOWN_PANEL_SURFACE`, `_menu_panel_class`, `dropdown_combobox_panel_class`, `DROPDOWN_PANEL_OUTLINE_CLASS`, `DropdownMenuPanel`, `ListboxPanel`), `common/components/search_select.py` (`ComboboxDropdown`), `common/components/column_picker.py`, `common/components/quick_filter.py` (~438), `common/components/primitives.py` (~3052), `ts/elements/quick-filter-bar.ts` and the selection-bar overflow script (the element that moves items: `grep -rn "data-selection-overflow-items\|data-quick-overflow-items" ts`), `common/components/__init__.py`.

**Produces:** `DropdownPanel(attributes=…, *, width: str, content_attributes=…, content_class: str = "") -> Node[children]` in htpy form: `DropdownPanel(role="menu", width="w-44")[items]`. The panel carries `absolute z-20 isolate flex flex-col rounded-base p-2 border border-default-medium shadow-sm {OVERLAY_SURFACE_CLASS} {width}`. The one child is `Div(data_menu_scroll="", class_=f"min-h-0 overflow-y-auto overflow-x-hidden {content_class}")`. The class-string helpers are removed once no caller is left.

**Gotchas:**
- Items the overflow scripts move go into the scroller: the `data-*-items` hook moves onto it, and so do `flex flex-col items-stretch gap-1`.
- attachMenu's `enabledItems()` queries descendants, so it is unaffected.
- `clearAnchoredPosition` clears only the panel, which is still where the positioner writes.
- Submenu flyouts stay `fixed`; nothing here is a containing block.

- [ ] Tests (fail first): each of the six sites renders a panel whose one child is `[data-menu-scroll]`; the panel classes carry no `overflow-y-auto`.
- [ ] Implement.
- [ ] `make test-fast ARGS="tests/test_dropdown*.py tests/test_column_picker*.py tests/test_quick_filter*.py tests/test_search_select.py"` (match what exists), `make test-ts`.
- [ ] `make test-e2e ARGS="-k 'dropdown or menu or overflow or column or quick or preset'"`.
- [ ] Commit `refactor: every dropdown panel scrolls inside its surface`.

### Task B: One pointer-follow model

**Files:** create `ts/pointer-follow.ts` and `ts/pointer-follow.test.ts`; modify `ts/elements/menu-behavior.ts` (~422-428, `setActive` gains `{ scroll }` → `focus({ preventScroll: !scroll })`).

**Produces:** `followPointer(container: HTMLElement, itemSelector: string, activate: (item: HTMLElement) => void): () => void` (returns the disposer). Mouse `pointermove` only; ignores a move whose `clientX/clientY` equal the last recorded ones.

- [ ] vitest (fail first):
  - A mouse move over an item activates it.
  - A touch move does not.
  - A second move at the same position does not.
  - The disposer detaches.
  - Fake `pointerType` as `pop-over.test.ts` does.
- [ ] Implement; menu-behavior replaces its `pointerover` listener with `followPointer(menu, itemSelector, item => setActive(index, { scroll: false }))`, own items only.
- [ ] `make test-ts`; `make test-e2e ARGS="-k 'dropdown or menu'"`.
- [ ] Commit `refactor: menus follow the pointer without scrolling`.

### Task 1: One menu item look

**Files:** `common/components/custom_elements.py` (~838-845), `tests/test_admin_settings_page.py` (~433).

**Produces:** `DROPDOWN_ITEM_SHAPE`, `DROPDOWN_ITEM_ACTIVE` (plain class strings, exported from `common/components/__init__.py`). `DROPDOWN_ITEM_CLASS = f"block w-full text-left no-underline {SHAPE} hover:… focus:… focus:outline-hidden aria-disabled:…"`, with the two active tokens prefixed by `hover:` and `focus:`.

- [ ] Update the pinned string in the admin settings test (fails first).
- [ ] Split the constant; `make test-fast ARGS="tests/test_admin_settings_page.py"`.
- [ ] Commit `refactor: the menu item look is a shape and an active state`.

### Task 2: One row builder

**Files:** `common/components/search_select.py` (row constants ~174-248, `_option_row`, `_create_row`, `_grouped_option_rows`, `_filter_option_row`, `_filter_modifier_row`, `_preset_option_row`, `_filter_action_button`, the preset remove button), `tests/test_search_select.py`.

**Produces:**
- `class RowKind(Enum): OPTION, MODIFIER, CREATE`.
- `_option_row(option, layout, kind=RowKind.OPTION, *, selected=False, actions: Sequence[Node] = ()) -> Node`.
- `_ROW_CLASS` = `DROPDOWN_ITEM_SHAPE` + `data-[search-select-highlighted]:` active tokens.
- `_ROW_ACTION_CLASS`.

**Notes:**
- `MODIFIER` stamps `data-search-select-modifier-option=<value>` and `data-label`, with no `data-search-select-option` and no `data-value`.
- `CREATE` stamps `data-search-select-create`, `hidden` and `Span(data-label)`.
- With actions: `flex items-center justify-between`, label slot `truncate min-w-0`, actions wrapper `flex gap-1 ml-2 shrink-0`.
- `_ComboboxLayout.row_class` goes: every layout's rows are one look now.
- `_GROUP_HEADER_CLASS` and `_NO_RESULTS_CLASS` take `px-4`.

- [ ] Tests (fail first):
  - Each widget's row carries `_ROW_CLASS`.
  - `MODIFIER` has no `data-search-select-option`; `CREATE` is hidden.
  - Actions render after the label.
  - No row class contains `hover:`.
  - The filter serializer contract test still passes.
- [ ] Implement; delete the replaced constants.
- [ ] `make test-fast ARGS="tests/test_search_select.py tests/test_filter_widgets.py"`, `make test-ts`.
- [ ] Commit `refactor: every picker row comes from one builder`.

### Task 3: One pill builder

**Files:** `common/components/primitives.py` (`Pill`, ~1429-1480), `common/components/search_select.py` (`_filter_value_pill`, `_filter_modifier_pill`, the `_FILTER_*_PILL_CLASS` constants), `tests/test_search_select.py`.

**Produces:** `Pill(..., kind: PillKind | None = None)`, where `type PillKind = Literal["include", "exclude", "modifier"]`. The tone class replaces `bg-brand-soft text-heading` (never appends). Include prefixes "✓ " and exclude prefixes "✗ ", outside the label slot. The label is always a `Span`, with `truncate` and `max-w-full` on the pill.

- [ ] Tests (fail first):
  - Each kind's tone and glyph.
  - A plain `Pill` keeps its tone.
  - The label is always a span.
  - Filter pills keep `data-search-select-type` and `data-search-select-modifier`.
- [ ] Implement; the filter builders call `Pill`.
- [ ] Commit `refactor: every pill comes from Pill`.

### Task 4: The picker list is a DropdownPanel; pills in the box

**Files:** `common/components/search_select.py` (`_ComboboxLayout`, `_combobox_children`, layout constants, `_OPTIONS_CLASS`, `_INLINE_OPTIONS_CLASS`, `_PANEL_OPTIONS_CLASS`, `_PANEL_PILLS_CLASS`), `ts/elements/search-select.ts` (`isPanelOpen`, `showPanel`, `hidePanel` toggle the panel found as `options.closest("[data-search-select-panel]") ?? options`), `tests/test_search_select.py`, vitest fixtures that assert visibility on the listbox.

**Produces:**
- Standalone and drop-down layouts: `DropdownPanel(data_search_select_panel="", width="w-full")` whose scroller *is* the listbox. `content_attributes` carry `role="listbox"`, `data-search-select-options`, `tabindex=-1`, the `max-height` cap and `scroll-py-2`.
- Standalone adds `top-full left-0 right-0 mt-1 hidden`.
- Drop-down adds `[data-menu]` and `hidden`; `matchToggleWidth` sizes it.
- Dialog layout: the listbox alone (`mt-2 scroll-py-2`), no panel.
- `_ComboboxLayout` keeps `container_class` and `menu_target`; `pills_in_box`, `options_class` and `row_class` go.

**Gotchas:**
- The cap needs `DropdownPanel` to let the scroller take attributes; Task A's `content_attributes` is that.
- The e2e #295 contrast test reads the dialog `[data-menu]`, which is unchanged.

- [ ] Tests (fail first):
  - Each layout's list structure.
  - Pills inside the box in both FilterSelect layouts.
  - Remove `test_panel_pills_row_hides_when_empty`.
- [ ] Implement; `make ts`; `make test-ts`; `make test-fast ARGS="tests/test_search_select.py"`.
- [ ] `make test-e2e ARGS="e2e/test_search_select_e2e.py e2e/test_widgets_e2e.py e2e/test_filter_builder_e2e.py e2e/test_quick_filter_e2e.py"`.
- [ ] Commit `refactor: a picker list is a dropdown panel`.

### Task 5: Pickers follow the pointer

**Files:** `ts/elements/search-select.ts` (`highlightOption(row, { scroll = true } = {})`; `followPointer(options, "[data-search-select-option], [data-search-select-modifier-option], [data-search-select-create]:not([hidden])", row => highlightOption(row, { scroll: false }))`), `ts/elements/search-select.hover.test.ts` (new).

- [ ] Tests (fail first):
  - A mouse move highlights the row under it and clears the previous one.
  - A hover never calls `scrollIntoView`.
  - ArrowDown, then a move at the same position, keeps the keyboard row.
- [ ] Implement; `make test-ts`, `make ts-check`.
- [ ] Commit `feat: pickers follow the pointer`.

### Task 6: Verify and document

- [ ] Throwaway screenshot harness (scratchpad `shots_e2e.py`): form picker, facet, preset picker, time zone picker, a navbar menu, the column picker; light and dark; a long picker list and a long menu scrolled in dark mode. Compare side by side, then send to the user.
- [ ] `CLAUDE.md`: one clause in the `search_select.py` bullet (one row builder, one pill, hover follows the pointer) and one line on `DropdownPanel` beside the dropdown notes.
- [ ] `make format`, `make lint-fix`, `make vale`, then the full gate: `flock … make check`; read the exit code.
- [ ] Commit `docs: one picker look`.
