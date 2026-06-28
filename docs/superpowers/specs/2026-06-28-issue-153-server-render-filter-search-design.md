# Issue #153 — Server-render free-text filter search (input + exclude toggle)

## Problem

The filter-bar body is server-rendered Python (`_FilterBarBase.render` →
`build_fields()` in `common/components/filters.py`); every widget's markup and
Tailwind classes live in Python components — **except** the free-text search
input and its "Exclude matches" checkbox, which are hand-built imperatively in
TypeScript by `injectSearchInput` (`ts/elements/filter-bar.ts`) with hardcoded
class strings.

This violates the project rule (CLAUDE.md: "Do NOT author HTML/JS as Python
f-strings"; markup/classes live in Python components) and produces concrete
debt introduced by #147:

- **Class drift / no single source.** The exclude checkbox uses a hand-rolled
  `className` instead of the `Checkbox` primitive, so it can drift from every
  other checkbox.
- **Missing disabled state.** The hardcoded string omits `DISABLED_CONTROL_CLASS`
  that `Checkbox` stamps.

## Goal

Render the free-text search input **and** its exclude toggle server-side in the
Python filter bar, reusing the `Input` + `Checkbox` primitives. Reduce the TS to
wiring only (read input value + checkbox state for `buildFilterJSON`); delete the
imperative DOM construction and the TS-side prefill. Single source of truth
restored; Tailwind duplication, drift, and the disabled-state gap removed.

## Constraints / findings

- `SearchField` primitive is a full `<form>` — cannot nest inside the filter
  `<form>`. So the text field uses the plain `Input` primitive, not `SearchField`.
- `buildFilterJSON` (filter-bar.ts) already reads the controls by name
  (`filter-search`, `filter-search-exclude`) and emits `{value, modifier}` with
  `modifier` = `EXCLUDES` when checked else `INCLUDES`. The reader is agnostic to
  who created the elements, so it needs no change.
- The search field is shared chrome (injected for every bar today), so it belongs
  in the base `_FilterBarBase.render()`, not per-entity `build_fields()`.
- `self.existing` is cross-entity-canonicalized in `__init__`; `search` is a plain
  top-level key, untouched by that fold.
- Visual treatment (decided): align with the rest of the bar — a labelled
  `_filter_field("Search", …)` block (uppercase "Search" label, input, exclude
  checkbox below), rather than reproducing the current label-less look.

## Design

### 1. New component — `_filter_search_field(existing: dict) -> Node`

In `common/components/filters.py`. Returns a labelled field built with the
existing `_filter_field("Search", widget)` helper, where `widget` is a `Div`
holding two primitive controls:

- Text input: `Input(type="text", name="filter-search", value=value,
  placeholder="Search…", class_=INPUT_CLASS)`.
  - `INPUT_CLASS` imported from `games.forms` (canonical app-wide text-input
    look; same import precedent as `SELECT_CLASS` used by `FieldComparisonSet`).
- Exclude toggle: `Checkbox(name="filter-search-exclude",
  label="Exclude matches", checked=(modifier == "EXCLUDES"))` — carries the
  canonical checkbox classes including `DISABLED_CONTROL_CLASS`, closing the
  drift + missing-disabled gap.
- Prefill: `value, modifier = _string_from_field(existing.get("search", {}))`.

Rendered shape:

```
SEARCH                              ← _FILTER_LABEL_CLASS (uppercase)
[ Input  name=filter-search ]       ← Input primitive, INPUT_CLASS
[x] Exclude matches                 ← Checkbox primitive, name=filter-search-exclude
```

### 2. Render wiring — `_FilterBarBase.render`

Insert the search field once in the base, right after the hidden `filter` input:

```python
Form(id_=_FILTER_FORM_ID)[
    Input(type="hidden", id_=_FILTER_INPUT_ID, name="filter", value=self.filter_json),
    _filter_search_field(self.existing),     # new — top of every bar
    *self._body_fields(),
    _filter_action_row(),
]
```

Same DOM position as today's injection (top of form, inside `#filter-bar-body`)
→ identical collapse/visibility behavior. Applies to all six bars
(Game / Session / Purchase / Device / Platform / PlayEvent) automatically.

### 3. TS reduction — `ts/elements/filter-bar.ts`

- **Delete** `injectSearchInput()` (the imperative DOM build + TS-side prefill).
- **Delete** its call in `connectedCallback`.
- **Keep** the `buildFilterJSON` search block unchanged (reads the now
  server-rendered controls by name).
- Recompile: `make ts` so `dist/` and e2e/local serving see the trimmed module.

## Testing

- **Existing e2e** (`e2e/test_search_filter_e2e.py`) — no changes expected; all
  four assertions still hold (input present; empty → INCLUDES; checked →
  EXCLUDES; prefill from filter JSON, now server-side; end-to-end list filter).
- **New Python unit assertions** (`tests/test_filter_bars.py`): a rendered bar's
  HTML contains `name="filter-search"` and `name="filter-search-exclude"`; a bar
  built from `{"search": {"value": "x", "modifier": "EXCLUDES"}}` renders the
  input value `x` and the checkbox `checked`. Locks the server-render contract
  that the TS no longer guards.

## Verification

- `make check` (lint + format check + mypy + ts-check + tests).
- `make test-e2e`.

## Out of scope

- The nested boolean filter builder (#168) and any change to `to_q` search
  semantics. This is a pure source-of-truth relocation of existing behavior,
  with one deliberate, approved visual alignment (labelled field).
