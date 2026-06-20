# Convert Remaining onSwap Widgets to Custom Elements

**Date:** 2026-06-20  
**Issue:** #18  
**Relates to:** #17 (TS migration), spec `2026-06-13-html-js-authoring-design.md`

## Context

PR #16 established the custom-element pattern (TypeScript custom elements, `connectedCallback` lifecycle, codegen'd typed prop contracts) and converted three components. Four interactive widgets still use the old pattern: a hand-written `.ts` file registered with `onSwap(selector, fn)` + `data-*` attributes.

**Goal:** Migrate all four remaining widgets to the custom-element pattern so the whole interactive surface uses one model.

## Widgets and Dependency Order

Convert in this order (least-to-most dependent):

1. `range-slider` — no cross-widget deps
2. `date-range-picker` — no cross-widget deps
3. `search-select` — no deps; exports `readSearchSelect()` consumed by filter-bar
4. `filter-bar` — imports `readSearchSelect`; removes all `window.*` globals

`onSwap` is NOT retired by this issue — `year_picker.ts` and `add_purchase.ts` still use it (see #17).

## Per-Widget Conversion Pattern

Each widget follows the same steps:

### Python side

1. Add `XxxProps(TypedDict)` to `common/components/custom_elements.py`
2. Call `register_element("xxx", "Xxx", XxxProps)` immediately after
3. Create `_Xxx = custom_element_builder("xxx")`
4. Update the Python component (in `filters.py`, `search_select.py`, or `date_range_picker.py`) to use the builder; remove old `_XXX_MEDIA` and `.with_media(...)` calls

### TypeScript side

5. Create `ts/elements/xxx.ts` (move logic from `ts/xxx.ts`)
6. Replace IIFE + `onSwap(selector, fn)` with `class XxxElement extends HTMLElement { connectedCallback() { ... } }`
7. Read typed props via generated `readXxxProps(this)` instead of `el.getAttribute("data-xxx")`
8. Add `disconnectedCallback()` to remove any document-level event listeners
9. End with `customElements.define("xxx", XxxElement)`

### Build

10. `uv run manage.py gen_element_types` — regenerates `ts/generated/props.ts`
11. `make ts` — compiles all TypeScript
12. `make check` — linting + type-check + tests

### E2E

13. Update Playwright locators to match new element tags and attribute names

## Widget Specifics

### `range-slider`

**Props:**
```python
class RangeSliderProps(TypedDict):
    min: int
    max: int
    step: int
    mode: str  # "range" | "point"
```

**Structural change:** `<range-slider>` replaces the outer `.range-slider-block` wrapper div AND the inner `.range-slider` div. The mode toggle button and the track/handles all become light-DOM children of `<range-slider>`. This eliminates `slider.closest(".range-slider-block")` — the TS can use `this.querySelector(".range-mode-toggle")` directly.

The `data-mode` attribute becomes the typed `mode` prop (attribute `mode` on the element). The JS updates this attribute on toggle: `this.setAttribute("mode", newMode)`.

E2E: `.range-slider-block` → `range-slider`; `slider[data-mode]` → `range-slider[mode]`.

### `date-range-picker`

**Props:**
```python
class DateRangePickerProps(TypedDict):
    input_name_prefix: str
```

**Structural change:** `<date-range-picker>` replaces the outer `<div data-date-range-picker data-input-name-prefix="...">`. `DateRangeField` and `DateRangeCalendar` remain unchanged as light-DOM children.

The `data-input-name-prefix` attribute on `DateRangeCalendar` can be removed since the prefix is now a typed prop on the element itself, readable as `readDateRangePickerProps(this).inputNamePrefix`.

### `search-select`

**Props:**
```python
class SearchSelectProps(TypedDict):
    name: str
    search_url: str      # empty string when no URL
    multi: bool
    filter_mode: bool    # true for FilterSelect; replaces data-search-select-mode="filter"
    free_text: bool
    always_visible: bool
    prefetch: int
    sync_url: bool
```

**Structural change:** `<search-select>` replaces the outer `<div data-search-select ...>`. All internal child elements (`[data-search-select-search]`, `[data-search-select-options]`, etc.) remain unchanged.

**`readSearchSelect` export:** Remove `window.readSearchSelect = ...`. Export as a named module function:
```typescript
export function readSearchSelect(scope: HTMLElement): void { ... }
```
`filter_bar.ts` will import it. Update the function to query `search-select[filter-mode="true"]` instead of `[data-search-select][data-search-select-mode="filter"]`.

E2E: `[data-search-select][data-name="status"]` → `search-select[name="status"]`.

### `filter-bar`

**Props:**
```python
class FilterBarProps(TypedDict):
    preset_list_url: str
    preset_save_url: str
```

**Structural change:** `<filter-bar>` wraps the entire filter bar structure (collapse toggle + form + action row). The Python `_FilterBarBase.render()` wraps its output in the builder.

**Window globals removed:** `applyFilterBar`, `clearFilterBar`, `toggleStringFilterInput`, `showPresetNameInput`, `savePreset` are no longer assigned to `window`. `connectedCallback` wires all handlers:
- `this.querySelector("form")` → `submit` listener (replaces `onsubmit`)
- `this.querySelector("[data-filter-bar-clear]")` → `click` listener  
- `this.querySelector("[data-filter-bar-save]")` → `click` listener
- `this.querySelector("[data-filter-bar-confirm-save]")` → `click` listener
- `this.querySelectorAll("[data-string-modifier-radio]")` → `change` listeners

**Python changes in `filters.py`:**
- Remove `onsubmit="return applyFilterBar(event)"` from form
- Replace `onclick="clearFilterBar(...)"` → `data-filter-bar-clear`
- Replace `onclick="showPresetNameInput()"` → `data-filter-bar-save`
- Replace `onclick="savePreset(...)"` → `data-filter-bar-confirm-save`
- Replace `onclick="toggleStringFilterInput(this)"` → `data-string-modifier-radio` (already present)
- Move `preset_list_url` from `data-preset-list-url` on `#preset-dropdown` to a typed prop on `<filter-bar>`
- Preset dropdown: `this.querySelector("[data-preset-dropdown]")` (add this attr)

**Import:** `filter-bar.ts` imports `{ readSearchSelect }` from `./search-select.js`.

**`globals.d.ts`:** Remove all entries except `fetchWithHtmxTriggers` and `toast` (which remain as globals).

## Verification

```bash
uv run manage.py gen_element_types   # codegen passes
make ts                              # tsc --noEmit passes
make test                            # unit tests pass
make test-e2e                        # e2e tests pass (after locator updates)
make check                           # full CI gate
```

Manual visual check each widget after conversion (per issue requirement).
