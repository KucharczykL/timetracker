# Plan: the filter acts and the presets panel (#1267)

Spec: [The filter acts and the presets panel](../specs/2026-09-28-issue-1267-filter-acts-group-design.md).

## 0. Start

- Rebase onto `origin/main`.
- `make render-pages ARGS="--user <name> --out <before>"` on a restored dump,
  kept for the attribution at the end.

## 1. Icons

- Add `games/templates/icons/funnel-off.html` and `bookmark.html`, outline
  style matching the existing snippets (same stroke width, `viewBox`,
  `currentColor`).
- `make gen-icons`; commit `common/components/icons_generated.py`.

## 2. A segment that opens a panel

- `primitives.py`: `ButtonGroupMember` gains `panel: Node` and
  `aria_label: str`; `ButtonGroup` gains `class_` (accumulated on the shell)
  and `aria_label` (on the `role="group"` element).
- A member with `panel` renders `Dropdown(trigger_element=<segmented
  ControlButton with its shape>, target_element=panel,
  placement="bottom-end", behavior=...)`, with `Dropdown` imported inside
  the function. Follow `SplitButtonDropdown` (`custom_elements.py`) for
  shaping the trigger with `with_shape()`.
- Tests in `tests/test_button_group.py` (or wherever `ButtonGroup` is
  tested): shape per place with a panel member, the `class_` merge, the
  group label, `title` and `aria-label` on an icon member.

## 3. Combobox behavior that keeps Tab

- `ts/elements/behaviors/combobox.ts`: a variant (or an option read from
  the `<drop-down>`) that passes `keepOpenOnTab: true` to
  `menu-behavior.ts`, keeping the refetch on `dropdown:show`, the search
  focus, and the Enter guard. Register it the way `column-picker.ts`
  registers its own behavior.
- vitest: Tab from the preset search box to the name box keeps the panel
  open; Escape still closes; `dropdown:show` still refetches.

## 4. `<preset-panel>`

- Python: `PresetPanel(*, api_url, mode, id)` in `search_select.py` (next to
  `PresetSelect`), a registered element with `PresetPanelProps`
  (`api_url`, `mode`). Children: `PresetSelect`, the name `Input`, the Save
  `ControlButton` (`data-save-preset`), the hint `P` (`role="status"`,
  `aria-live="polite"`). The wrapper keeps `data-preset-picker`.
- TS: `ts/elements/preset-panel.ts`.
  - Pick (`search-select:change`) → dispatch `preset-panel:load` with
    `{filter, sort, perPage}`; clear the selection; close the dropdown.
    Invalid JSON → toast + `reportClientError`, keeping the
    "preset load failed" console substring the e2e crash guards grep.
  - Save (click, or Enter in the name box with `preventDefault`) →
    dispatch `preset-panel:save` with a mutable detail
    `{state: null, refusal: null}`; toast a refusal; `reportClientError`
    when neither is written; else `savePreset`, then refetch the list,
    empty the name box, clear the hint.
  - Name focus → `fetchPresetNames`; input → hint and "Overwrite" relabel
    (move `updatePresetNameWarning` from `filter-builder.ts`).
  - Removal: `wirePresetDelete` on itself, disposed in
    `disconnectedCallback`.
- `presets.ts` keeps the API functions; its header comment names the panel
  as the one caller.
- vitest `ts/elements/preset-panel.test.ts`: load event detail; save asks
  the host, posts the host's state, refuses on a refusal, reports on no
  answer; Enter saves and does not submit an enclosing form; overwrite
  relabel; removal still refetches.
- Remove `LoadPresetDropdown` and its export in `common/components/__init__.py`;
  update `tests/test_search_select.py`.

## 5. Quick bar

- `quick_filter.py`:
  - `_editable`: drop the picker; the action group becomes
    `ButtonGroup(members, class_="ml-auto", aria_label="Filter actions")`
    with Apply, Clear (`funnel-off`, href), Presets (`bookmark`, panel
    `PresetPanel`), Advanced filter (`list-tree`, href) when `builder_url`.
  - `_degraded`: render the pill inside `_QuickFilterBarElement` with the
    new `filter` prop, no form and no `data-quick-row`; the pill keeps its
    sentence and gets the group without Apply.
  - Update the class and module docstrings (the pill now mounts the
    element and loads its JS).
- `custom_elements.py`: `QuickFilterBarProps.filter: str` (empty on the
  editable branch); `make gen-element-types`.
- `quick-filter-bar.ts`: drop `onPresetPick` and the delete wiring; listen
  for `preset-panel:load` (navigate) and `preset-panel:save` (write
  `serialize()` or the `filter` prop, the URL sort, `perPage`; stop
  propagation). Update the header comment.
- Tests: `tests/test_quick_filter_bar.py` (`>Advanced filter…<` at 819/824,
  picker placement and id at 829-846 → group contents, `ml-auto`, panel,
  degraded pill inside the element with the `filter` prop);
  `quick-filter-bar.test.ts` (load and save handlers, degraded state).

## 6. Builder

- `FilterBuilder`: the toolbar is the group with Apply (`data-apply`),
  Clear (`data-clear`, `funnel-off`), Presets (panel), `ml-auto`; drop the
  name input, Save button and hint.
- `filter-builder.ts`: drop `onPresetPick`, the save and name-hint code
  and the delete wiring; handle `preset-panel:load` (`loadFilter`, take
  sort and per-page) and `preset-panel:save` (refusal while an incomplete
  criterion exists, else `serializeForQuery()` with sort and per-page).
  Rewrite `ensureToolbar`'s test stub to the new markup.
- Fix `filter-group.ts`'s `serialize()` docstring, which claims it reads
  live widgets.
- vitest `filter-builder.test.ts` (282-394): save posts the edited
  widget's value, not the default leaf (fails before the fix); refusal
  while incomplete; load into the tree.

## 7. End to end

Rewrite the selectors, keep the coverage:

- `e2e/test_filter_builder_e2e.py` 312, 398, 999-1085: open via the Presets
  segment; save from the panel; add a new case that edits a leaf, saves,
  reloads the preset and sees the edited value.
- `e2e/test_quick_filter_e2e.py` 151 ("Edit in builder"), 451; new cases:
  save from the quick bar with unapplied facets and load it back; keyboard
  Tab from the preset search to Save; Enter in the name box saves and does
  not navigate; save from the degraded pill.
- `e2e/test_widgets_e2e.py` 582; `e2e/test_playtime_page_e2e.py` 105
  (`name="Advanced filter"`).
- Visual check at desktop and 390px: group at the row's end, wraps whole,
  panel aligned to the group's end; screenshots in the PR.

## 8. Docs and finish

- CLAUDE.md quick-bar paragraph: row anatomy now "facets, ⋯, then the
  filter-acts group at the end (Apply | Clear | Presets | Advanced
  filter…)", Presets loads and saves; drop "load-only".
- `make vale`, `make format`, `make lint-fix`.
- `make render-pages` after; `diff -r`; attribute every differing file
  (expected: every list page's bar, the builder toolbar).
- Full `make check` under the shared lock.

## Gotchas

- The row must keep flat children; do not wrap the facets.
- The degraded pill must not carry `data-quick-row`, or `setupOverflow`
  reports a missing overflow host.
- The name box must not carry `data-search-select-search`, or the combobox
  focuses it on open.
- A Save button outside `ControlButton` fails `tests/test_button_guard.py`.
- Import cycle: `ButtonGroup` imports `Dropdown` inside the function.
