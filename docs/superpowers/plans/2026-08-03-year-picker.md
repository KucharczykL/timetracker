# In-house Stats YearPicker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stats page's Flowbite YearPicker with an in-house four-column year grid and remove `datepicker.umd.js`.

**Architecture:** Keep the public `YearPicker(year, available_years, url_template)` Python API unchanged. Render the picker inside the existing `<drop-down behavior="date-calendar">` host, reuse `bindCalendarPopupHost()` for popup lifecycle, and add only the YearPicker-specific decade rendering/selection logic. Extend the shared date-calendar menu behavior so Tab can traverse its native controls and focus-leave closes the panel.

**Tech Stack:** Django component builders, TypeScript custom elements, Tailwind utility classes generated from Python, Vitest/jsdom, pytest-django, Playwright, and the repository's `make` targets.

## Global Constraints

- Preserve immediate navigation when an enabled year is selected.
- Preserve the public `YearPicker()` call and the `selected-year`, `available-years`, and `url-template` custom-element props.
- Preserve the twelve-cell sequence `decadeStart - 1` through `decadeStart + 10` in four columns.
- Keep selectable years bounded to `1999` through the browser's current year and filtered by `available_years`.
- Use the existing dropdown/date-calendar machinery; do not introduce a generic grid framework or Flowbite keyboard clone.
- Keep YearPicker cells as native buttons; use `aria-current="page"` for the selected stats page and native `disabled` for unavailable years.
- Preserve the current empty-URL guard: an empty `url_template` must not navigate.
- Remove all source, test, runtime-asset, and product-documentation references to `datepicker.umd.js`; the historical design/spec documents may mention it.
- Do not remove or redesign the separate global `flowbite.min.js` bundle tracked by issue #98.

---

### Task 1: Add shared Tab traversal for date-calendar panels

**Files:**
- Modify: `ts/elements/menu-behavior.ts`
- Modify: `ts/elements/behaviors/date-calendar.ts`
- Test: `ts/elements/menu-behavior.test.ts`

**Interfaces:**
- Add `keepOpenOnTab?: boolean` to `MenuOptions`.
- `date-calendar` returns `keepOpenOnTab: true` from its `menuOptions()` result.
- When enabled, `attachMenu()` leaves the panel open while focus moves between descendants of `[data-menu]`; its focus-leave handler closes the panel when `relatedTarget` is outside the menu or absent.

- [ ] **Step 1: Add failing shared-menu tests**

Extend `ts/elements/menu-behavior.test.ts` with a fixture whose menu contains two buttons and whose controller is created with `{ inlineTrigger: true, keepOpenOnTab: true }`. Cover:

```ts
it("keeps an itemless date-calendar panel open while focus moves inside it", () => {
  const { menu, controller } = mountDateCalendarMenu();
  const [first, second] = menu.querySelectorAll("button");
  controller.open();
  first.focus();
  first.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
  first.dispatchEvent(
    new FocusEvent("focusout", { bubbles: true, relatedTarget: second }),
  );
  expect(controller.isOpen()).toBe(true);
});
```

Add assertions that a `focusout` with an outside button or `relatedTarget: null` closes the panel, and that the existing default behavior still closes an itemless menu on Tab when `keepOpenOnTab` is absent.

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
pnpm exec vitest run ts/elements/menu-behavior.test.ts
```

Expected: the new `keepOpenOnTab` fixture fails because `MenuOptions` has no such option and the current Tab branch closes the panel.

- [ ] **Step 3: Implement the shared option and focus-leave behavior**

In `ts/elements/menu-behavior.ts`:

1. Add the documented `keepOpenOnTab?: boolean` option.
2. Read it once in `attachMenu()`.
3. In the menu `keydown` handler's `Tab` branch, call `close()` only when `keepOpenOnTab` is false.
4. When `keepOpenOnTab` is true, add a `focusout` listener to the menu. Keep the panel open when `event.relatedTarget` is another descendant of the menu; otherwise call `close()`.

Do not alter the existing roving/typeahead logic or the default behavior for ordinary menus.

In `ts/elements/behaviors/date-calendar.ts`, set `keepOpenOnTab: true` beside `inlineTrigger: true`, and update the comments to say that date-calendar panels use their own inner controls while shared focus-leave logic closes the panel after focus exits.

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
pnpm exec vitest run ts/elements/menu-behavior.test.ts
```

Expected: all existing menu tests and the new Tab/focus-leave tests pass.

- [ ] **Step 5: Commit the shared behavior**

```bash
git add ts/elements/menu-behavior.ts ts/elements/behaviors/date-calendar.ts ts/elements/menu-behavior.test.ts
git commit -m "feat: let date-calendar panels keep focus while tabbing"
```

### Task 2: Render the in-house YearPicker shell and state-class vocabulary

**Files:**
- Modify: `common/components/primitives.py`
- Modify: `games/management/commands/gen_element_types.py`
- Create: `tests/test_year_picker.py`
- Modify: `tests/test_rendered_pages.py`

**Interfaces:**
- `YearPicker()` continues to accept `year`, `available_years`, and `url_template` without signature changes.
- Add a public Python vocabulary `YEAR_PICKER_CLASSES: dict[str, str]` in `common/components/primitives.py`; generate it into `ts/generated/calendar-classes.ts` beside the existing calendar class vocabularies.
- The rendered hooks are `data-toggle`, `data-year-picker-toggle`, `data-menu`, `data-year-picker-popup`, `data-year-picker-period`, `data-year-picker-prev`, `data-year-picker-next`, `data-year-picker-grid`, and `data-year-picker-template="year"`.

- [ ] **Step 1: Write failing Python component tests**

Create `tests/test_year_picker.py` with a `SimpleTestCase` that renders:

```python
html = str(
    YearPicker(
        year=2024,
        available_years=(2023, 2024, 2025),
        url_template="/stats/__year__/",
    )
)
```

Assert that the output contains a `<drop-down>` with `behavior="date-calendar"`, `placement="bottom-end"`, and `submenu="false"`; a toggle with both `data-toggle` and `data-year-picker-toggle`; server-rendered `aria-expanded="false"`; a hidden `data-menu` popup with `role="group"`; a period label referenced by `aria-labelledby`; previous/next decade buttons with accessible labels; the four-column grid hook; and the year template hook. Assert that `year-picker-input`, `datepicker.umd.js`, and `_DATEPICKER_MEDIA` are absent from the rendered component.

Add a test for the `YEAR_PICKER_CLASSES` keys:

```python
assert set(YEAR_PICKER_CLASSES) == {
    "default",
    "selected",
    "adjacent",
    "disabled",
    "adjacent-disabled",
}
```

Assert every variant contains the fixed year-cell geometry and a complete `ControlButton` class set rather than relying on a client-side class append.

- [ ] **Step 2: Run the focused Python tests and verify they fail**

Run:

```bash
uv run --frozen --with pytest-django pytest tests/test_year_picker.py -q
```

Expected: the new tests fail because the component still emits the hidden Flowbite input and datepicker media.

- [ ] **Step 3: Define complete Python-generated year-cell classes**

Near the existing `YearPicker()` implementation in `common/components/primitives.py`, define the fixed `w-14 shrink-0` geometry and compose complete variants with `control_button_class()`:

```python
YEAR_PICKER_CLASSES = {
    "default": f"{control_button_class(variant='ghost')} {_YEAR_CELL_GEOMETRY_CLASS}",
    "selected": f"{control_button_class(color='blue', variant='filled')} {_YEAR_CELL_GEOMETRY_CLASS}",
    "adjacent": f"{control_button_class(variant='ghost')} {_YEAR_CELL_GEOMETRY_CLASS} opacity-40",
    "disabled": f"{control_button_class(variant='ghost')} {_YEAR_CELL_GEOMETRY_CLASS} opacity-40",
    "adjacent-disabled": f"{control_button_class(variant='ghost')} {_YEAR_CELL_GEOMETRY_CLASS} opacity-40",
}
```

Keep each mapping a complete class list so selected/disabled/adjacent states cannot fight through Tailwind stylesheet order. Preserve the existing control radius, minimum height, and colors supplied by `ControlButton`.

- [ ] **Step 4: Replace the server-rendered Flowbite DOM**

In `common/components/primitives.py`:

1. Remove `_DATEPICKER_MEDIA`.
2. Keep `_YearPicker = custom_element_builder("year-picker")` so the TypeScript element media remains automatic.
3. Add `aria-expanded="false"` to the trigger button.
4. Add `data-toggle` to the trigger while retaining `data-year-picker-toggle`.
5. Remove the hidden `#year-picker-input`.
6. Wrap the `_YearPicker` node in `_Dropdown(placement="bottom-end", submenu="false", behavior="date-calendar")`.
7. Render a hidden `[data-menu]` popup using the existing overlay surface pattern.
8. Render a `role="group"` popup with `aria-labelledby` pointing to the period label; give the period label the `data-year-picker-period` hook and a stable id.
9. Render named previous/next decade buttons, the `data-year-picker-grid` four-column fixed-width container, and a `Template(data_year_picker_template="year")` containing one `ControlButton` prototype.
10. Attach no `.with_media()` call for `datepicker.umd.js`.

The server-side props remain exactly `selected-year`, `available-years`, and `url-template`.

- [ ] **Step 5: Publish the class vocabulary through code generation**

In `games/management/commands/gen_element_types.py`, import `YEAR_PICKER_CLASSES` from `common.components.primitives` and add a `TsConstant("YEAR_PICKER_CLASSES", dict[str, str], YEAR_PICKER_CLASSES)` to the existing generated calendar-classes module. Do not hand-edit `ts/generated/calendar-classes.ts`; it is produced by `make gen-element-types`.

- [ ] **Step 6: Update rendered-page expectations**

In `tests/test_rendered_pages.py`:

1. Rename `test_stats_page_auto_loads_datepicker` to a no-bundle assertion and assert that `js/datepicker.umd.js` is absent from the stats HTML.
2. Replace the `id="year-picker-input"` marker in `test_stats_alltime` with the new `drop-down`, `data-year-picker-grid`, and `data-year-picker-template` markers.
3. Assert the server-rendered `aria-expanded="false"` state.

- [ ] **Step 7: Run the focused Python tests and verify they pass**

Run:

```bash
make gen-element-types
uv run --frozen --with pytest-django pytest tests/test_year_picker.py tests/test_rendered_pages.py -q
```

Expected: the new component contract and updated stats-page expectations pass.

- [ ] **Step 8: Commit the server shell and generated contract changes**

```bash
git add common/components/primitives.py games/management/commands/gen_element_types.py tests/test_year_picker.py tests/test_rendered_pages.py
git commit -m "feat: render stats year picker as an in-house calendar"
```

### Task 3: Implement the TypeScript year grid

**Files:**
- Modify: `ts/elements/year-picker.ts`
- Create: `ts/elements/year-picker.test.ts`
- Generated by Task 2: `ts/generated/calendar-classes.ts`, `ts/generated/props.ts`

**Interfaces:**
- Export pure helpers from `year-picker.ts` for deterministic unit coverage:
  - `YEAR_PICKER_MIN_YEAR = 1999`
  - `decadeStartFor(year: number): number`
  - `visibleYears(decadeStart: number): number[]`
  - `buildYearUrl(urlTemplate: string, year: number): string | null`
- `buildYearUrl()` returns `null` for an empty template and otherwise returns `urlTemplate.replace("__year__", String(year))`.
- The custom element continues to register as `year-picker` and uses `readYearPickerProps()`.

- [ ] **Step 1: Add the jsdom fixture and failing behavior tests**

Create `ts/elements/year-picker.test.ts` with `// @vitest-environment jsdom`, a fake `<drop-down>` exposing `open()`, `close()`, and `dropdown:hide`, and a fixture containing the server hooks from Task 2. Cover:

```ts
expect(visibleYears(2020)).toEqual([
  2019, 2020, 2021, 2022, 2023, 2024,
  2025, 2026, 2027, 2028, 2029, 2030,
]);
expect(buildYearUrl("/stats/__year__/", 2024)).toBe("/stats/2024/");
expect(buildYearUrl("", 2024)).toBeNull();
```

Add tests for:

- selected-year initialization and current-year initialization when selected-year is empty;
- exactly twelve rendered buttons in four columns;
- selected `aria-current="page"` and selected class;
- adjacent and disabled class variants;
- unavailable years disabled even when within the visible decade;
- previous disabled on the `1990` decade page and next disabled at the current-year boundary;
- previous/next decade buttons re-render the grid;
- trigger ArrowDown opens without moving focus away from the trigger;
- trigger Escape closes an open popup;
- clicking an enabled year calls the URL seam, while clicking a disabled year does not;
- the custom element does not register duplicate listeners when connected twice.

Use `vi.setSystemTime()` around current-year tests so the boundary is deterministic. Do not assert `window.location.href` assignment in jsdom; cover `buildYearUrl()` in Vitest and actual browser navigation in Task 5.

- [ ] **Step 2: Run the focused TypeScript tests and verify they fail**

Run:

```bash
pnpm exec vitest run ts/elements/year-picker.test.ts
```

Expected: the new helper and custom-element behavior tests fail against the current Flowbite implementation.

- [ ] **Step 3: Replace the Flowbite client implementation**

In `ts/elements/year-picker.ts`:

1. Remove the `Datepicker` declaration, hidden-input lookup, Flowbite constructor, `changeDate` listener, and `bindPopupDismiss()` import.
2. Import `YEAR_PICKER_CLASSES` from `../generated/calendar-classes.js`, `readYearPickerProps()`, and `bindCalendarPopupHost()`.
3. Parse `availableYears` once into a `Set<number>` and compute `currentYear` from `new Date().getFullYear()` on connection.
4. Guard `connectedCallback()` with an initialization flag so reconnecting or moving the element does not stack listeners.
5. Locate the trigger, popup, period label, grid, template, previous button, and next button. Return without wiring if the required nodes are absent.
6. Keep `decadeStart` state. Initialize it from `selectedYear` or `currentYear` in `beforeOpen`.
7. Render `visibleYears(decadeStart)` by cloning the server template, setting `textContent`, `data-year`, `aria-label`, and `aria-current="page"` on the selected button, applying one complete `YEAR_PICKER_CLASSES` variant, and setting native `disabled` for unavailable years.
8. Set the period label to `${decadeStart}-${decadeStart + 9}`.
9. Disable previous when `decadeStart <= YEAR_PICKER_MIN_YEAR`; disable next when `decadeStart + 9 >= currentYear`.
10. Wire navigation buttons to decrement/increment the decade by 10 and re-render without navigating.
11. Use `bindCalendarPopupHost({ picker: this, popup, toggleButton: toggle, idPrefix: "year-picker", beforeOpen, render })` for open/close and ARIA synchronization.
12. Add only the trigger keyboard gap: ArrowDown calls `host.open()` and prevents default; Escape calls `host.close()` when open and prevents default. Leave focus on the trigger after ArrowDown.
13. On a year-button click, ignore disabled cells, build the URL with `buildYearUrl()`, close the host, and assign `window.location.href` only for a non-null URL.

- [ ] **Step 4: Run the focused TypeScript tests and verify they pass**

Run:

```bash
make gen-element-types
pnpm exec vitest run ts/elements/year-picker.test.ts
```

Expected: all YearPicker unit tests pass and the generated props/class imports resolve.

- [ ] **Step 5: Run TypeScript checking**

Run:

```bash
pnpm exec tsc --noEmit -p tsconfig.check.json
```

Expected: no type errors in the new custom element, generated vocabulary, or shared dropdown option.

- [ ] **Step 6: Commit the TypeScript implementation**

```bash
git add ts/elements/year-picker.ts ts/elements/year-picker.test.ts
git commit -m "feat: replace Flowbite stats year picker"
```

### Task 4: Remove the vendored asset and stale references

**Files:**
- Delete: `games/static/js/datepicker.umd.js`
- Modify: `games/views/general.py`
- Modify: `CLAUDE.md`
- Modify: `games/views/general.py`
- Modify: `CLAUDE.md`

**Interfaces:**
- No runtime code may refer to `datepicker.umd.js`, `Datepicker`, or `year-picker-input` after this task.
- The historical design/spec document is exempt from the reference search because it records the migration context.

- [ ] **Step 1: Record the remaining references before deletion**

Run:

```bash
rg -n "datepicker\.umd\.js|Datepicker|year-picker-input" --glob '!docs/superpowers/**' .
```

Use the output as the exact cleanup list. The known cleanup targets are the stale comments in `games/views/general.py` and `CLAUDE.md`; Tasks 2 and 3 also remove the old TypeScript/Python comments in `ts/elements/year-picker.ts` and `common/components/primitives.py`.

- [ ] **Step 2: Remove stale source and documentation references**

Delete the Flowbite-specific comments from `games/views/general.py` and the Flowbite datepicker entry from `CLAUDE.md`. Tasks 2 and 3 update the component docstring and TypeScript module comment; the final search must confirm that no other source/test/product-documentation reference remains. Update retained comments to describe the in-house year grid and shared date-calendar dropdown.

- [ ] **Step 3: Delete the vendored UMD file**

Delete only the explicit file `games/static/js/datepicker.umd.js`. Do not remove `games/static/js/flowbite.min.js` or any unrelated static asset.

- [ ] **Step 4: Verify the cleanup**

Run:

```bash
rg -n "datepicker\.umd\.js|Datepicker|year-picker-input" --glob '!docs/superpowers/**' .
git diff --check
```

Expected: the reference search returns no output and the diff has no whitespace errors.

- [ ] **Step 5: Commit the removal**

```bash
git add -u games/static/js/datepicker.umd.js games/views/general.py CLAUDE.md
git add -A
git commit -m "chore: remove stats datepicker bundle"
```

### Task 5: Add real-browser YearPicker coverage

**Files:**
- Create: `e2e/test_year_picker_e2e.py`

**Interfaces:**
- Use the existing login pattern from `e2e/test_date_picker_e2e.py`.
- The test targets `reverse("games:stats_alltime")` and the public stats navigation URL generated by the YearPicker.

- [ ] **Step 1: Add deterministic stats data and authentication**

Create an `authenticated_page` fixture following the existing E2E login helper. In each test, create one platform, one game, and sessions in 2024 and 2025 so the stats page has available years and renders the picker with a selected/unselected state.

- [ ] **Step 2: Add the popup interaction test**

Navigate to the all-time stats page, assert that the YearPicker toggle is visible, and assert that no request URL contains `datepicker.umd.js`. Click the toggle and assert:

- the `[data-year-picker-popup]` panel is visible;
- the year grid has twelve buttons;
- the grid has four columns via the rendered class/hook;
- the period label and named previous/next controls are present;
- the selected/unavailable state attributes are present.

- [ ] **Step 3: Add shared-tab and activation coverage**

Open the picker with the trigger's ArrowDown key, verify focus remains on the trigger, press Tab through the period, previous, next, and first year controls, and verify the panel remains open. Tab beyond the final popup control and assert the panel closes. Use Shift+Tab from the first popup control and assert the panel closes when focus returns outside the panel. Activate an enabled year with Enter or Space and assert navigation to the corresponding `stats_by_year` URL.

- [ ] **Step 4: Run the focused browser test**

Run:

```bash
make test-e2e ARGS="e2e/test_year_picker_e2e.py"
```

Expected: the new stats-page browser tests pass without loading the removed bundle.

- [ ] **Step 5: Commit the browser coverage**

```bash
git add e2e/test_year_picker_e2e.py
git commit -m "test: cover stats year picker in a browser"
```

### Task 6: Run the complete verification gate

**Files:**
- No new files; regenerate ignored static/TypeScript build output as required by the commands.

- [ ] **Step 1: Regenerate contracts and compile TypeScript**

Run:

```bash
make gen-element-types
make ts-check
```

Expected: generated props/class modules and TypeScript type checking complete successfully.

- [ ] **Step 2: Run focused Python and TypeScript tests**

Run:

```bash
uv run --frozen --with pytest-django pytest tests/test_year_picker.py tests/test_rendered_pages.py -q
pnpm exec vitest run ts/elements/menu-behavior.test.ts ts/elements/year-picker.test.ts
```

Expected: all focused tests pass.

- [ ] **Step 3: Run the focused E2E test again after a clean build**

Run:

```bash
make test-e2e ARGS="e2e/test_year_picker_e2e.py e2e/test_date_picker_e2e.py"
```

Expected: both the new YearPicker behavior and existing date-picker behavior pass with the shared Tab change.

- [ ] **Step 4: Run the repository verification gate**

Run:

```bash
make check
```

Expected: lint, formatting, mypy, TypeScript checks, icon checks, Python tests, TypeScript tests, and E2E tests all pass.

- [ ] **Step 5: Verify the final diff and status**

Run:

```bash
git diff --check origin/main...HEAD
git status --short --branch
rg -n "datepicker\.umd\.js|Datepicker|year-picker-input" --glob '!docs/superpowers/**' .
```

Expected: no diff-check errors, no forbidden source/test/product-documentation references, and only the intended commits/files are present.

- [ ] **Step 6: Commit any generated or final test corrections**

```bash
git add -A
git commit -m "test: verify in-house stats year picker replacement"
```

Skip this commit only when `git status --short` is clean after the verification gate.
