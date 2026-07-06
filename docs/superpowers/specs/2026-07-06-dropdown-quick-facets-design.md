# Dropdown quick facets (tryout) — design

Date: 2026-07-06
Refs: #315, #314 (motivating), #197 (quick bar), #297 (preset picker precedent),
#272 (ControlButton variant taxonomy)

## Problem

Quick filter bar facets render `LABEL: [widget]` with the full widget always
visible. This makes the bar tall and uneven (#314) and leaves Apply/Clear
floating mid-row (#315). GitHub's filter bar instead renders each facet as a
compact `Label ▾` trigger; the actual field appears in a dropdown panel only
when clicked.

The repo already has this interaction pattern: `LoadPresetDropdown`
(`common/components/search_select.py`) — a `ControlButton` trigger + a
`role="dialog"` panel hosting a combobox, composed via
`Dropdown(behavior="combobox")` (`common/components/custom_elements.py`).

## Goal (tryout scope)

1. Generalize the preset-dropdown composition into a reusable component.
2. Replace the **Game** and **Device** facets on the **sessions** list quick
   bar with dropdown facets.
3. Add an outline-less-until-hover ("ghost") trigger style, used by these
   facets.

Everything else (other facets, other modes, flat FilterBar, apply semantics)
stays unchanged. If the tryout is adopted bar-wide later, #314/#315 largely
degenerate — for the tryout itself they are merely not worsened (the tall
inline Started/Ended/Duration widgets remain).

## Decisions (interview outcomes + adversarial review)

- **Apply timing**: unchanged in principle — bar-level Apply/Enter serializes
  and navigates. **Known, accepted asymmetry**: inside an open panel the
  combobox behavior unconditionally `preventDefault`s Enter on the hosted
  search input (`ts/elements/behaviors/combobox.ts`, deliberate — it stops
  implicit form submission), so Enter inside the Game/Device panel picks a
  row / does nothing; it never applies the bar. The user applies via the
  bar's Apply button (or Enter in one of the remaining inline facets). This
  matches GitHub's model (panel edits, then explicit apply) and needs no TS
  change.
- **Closed trigger**: label only ("Game ▾"). No count, no summary, no
  active-state hint.
- **Panel interior**: pills above search. The FilterSelect keeps its
  pill-based state; the panel personality only restyles: pills row, then a
  bordered search input, then a statically flowing always-visible options
  list (PresetSelect layout).
- **Ghost style**: first-class `ControlButton` variant in the **colorless
  single-look family** established by #272 (`outline`, `plain`): like those,
  `ghost` has no color axis — the `color` parameter is ignored exactly as it
  is for `outline`/`plain`. No per-color policy, no loud-fail: the variant
  taxonomy already settles this. Ghost differs from `outline` in look only:
  `outline` is always-bordered; `ghost` is transparent (bg and border) until
  hover.
- **Component shape**: new generic `ComboboxDropdown`; `LoadPresetDropdown`
  refactored to a thin composition over it. Lives in
  `common/components/search_select.py` beside `LoadPresetDropdown` (that
  module already imports both `ControlButton`/`Icon` and
  `Dropdown`/`DROPDOWN_COMBOBOX_PANEL_CLASS`; there is no import-cycle
  question either way, this is just cohesion).
- **Panel personality**: a `layout` parameter on `FilterSelect`
  (`"field"` default | `"panel"`), not a separate function — logic, pills,
  templates, and the serializer DOM contract are identical; only classes,
  the search input's accessible name, and `always_visible` differ.
- **One TS change is required** (found in adversarial review, F1): the
  dropdown's outside-click close guard must not close when the clicked node
  was inside the host but got detached synchronously by the click handler
  (pill ×). See "TS change" below. All other reuse claims verified clean
  (no prefetch-at-connect waste, refetch preserves pills, no id collisions,
  serializer depth-agnostic, no clipping — panel is position:fixed).

## Components

### 1. `ControlButton` `variant="ghost"`

Fifth variant in `common/components/primitives.py`, joining the colorless
single-look family (`outline`, `plain` — #272):

- transparent background **and** `border-transparent` (border box present, so
  hover adds no layout shift)
- hover: subtle surface bg + visible default border (visual target: the
  GitHub filter-bar trigger)
- same padding/typography/icon-gap as the other variants; `color` ignored
  like `outline`/`plain`
- implemented in the shared class assembly, so `<button>`, `href=`, and
  `method="post"` renderings all get it for free; only the `<button>`
  rendering has a caller in this tryout and only it is tested (the algebra
  extension is incidental, not a goal).

### 2. `ComboboxDropdown`

Generic trigger + combobox-dialog composition in `search_select.py`:

```python
def ComboboxDropdown(
    *,
    label: str,
    content: Node,
    id: str,
    ghost: bool = False,
    config: dict[str, str] | None = None,
) -> Node
```

- trigger: `ControlButton(variant="ghost" if ghost else "filled",
  color="gray", aria_haspopup="dialog")[label, Icon("arrowdown",
  size="h-3 w-3")].as_element()` (`Dropdown` stamps attributes onto an
  `Element`)
- panel: `Div(role="dialog", aria_label=label,
  class_=DROPDOWN_COMBOBOX_PANEL_CLASS)[content]` — the dialog's accessible
  name is always the trigger label; no separate `aria_label` parameter
  (YAGNI).
- returns `Dropdown(trigger_element=…, target_element=…, id=id,
  behavior="combobox", config=config)`
- reuses the existing `combobox` behavior: open/close, outside-click,
  Escape-refocuses-trigger, focus-search-on-open, `refetchOptions()` on
  `dropdown:show`.

`LoadPresetDropdown` becomes a one-line call:
`ComboboxDropdown(label="Load preset", content=PresetSelect(...), id=id,
config={"data_preset_picker": ""})` (keeps its filled gray trigger).
Existing `tests/test_search_select.py` LoadPresetDropdown contract tests must
pass unchanged.

### 3. `FilterSelect(layout="panel")`

Second visual personality for the existing filter combobox
(`search_select.py`). `layout: Literal["field", "panel"] = "field"`.

`"panel"` differences (styling + one behavior flag + input naming; **no**
state-logic change):

- root class: block container (no bordered field wrapper, no
  focus-within ring) — analogous to `_PRESET_CONTAINER_CLASS`
- pills wrapper: instead of `contents`, a `flex flex-wrap gap-1` row above
  the search box, `empty:hidden` so an empty pill set adds no stray gap
- search input: self-bordered field styling (analogous to
  `_PRESET_SEARCH_CLASS`), and an explicit accessible name:
  `aria-label` = the facet label (e.g. "Game") — the visible `Label:` span
  is gone in dropdown facets, and the dialog's `aria-label` names the
  dialog, not the combobox input. New keyword-only
  `search_aria_label: str = ""` on `FilterSelect`, emitted when non-empty
  (both layouts accept it; panel callers pass it).
- options panel: static flow below search (`mt-2 overflow-y-auto`, via the
  existing `options_class` knob of `_combobox_children`)
- `always_visible=True` (options list always rendered open inside the panel)

Pill overflow hardening (both layouts, uniform — no fork): value/modifier
pills gain `max-w-full` and their label slot `truncate`, so a long game
title cannot overflow the `w-72` panel (`DROPDOWN_COMBOBOX_PANEL_CLASS` is
`overflow-hidden`; today's pill classes have no overflow treatment).

Unchanged: pill templates, include/exclude/modifier rows and buttons, all
`data-search-select-*` hooks, `data-filter-widget` self-describe attributes.
**The serializer contract is unchanged** (`readSearchSelect` reads the same
DOM). (`always_visible` is TS-visible, but it is an existing supported path —
PresetSelect uses it.)

Both Game and Device facets have a `search_url` (`/api/games/search`,
`/api/devices/search`) — the hosting dropdown's combobox behavior refetches
options on every open, same freshness mechanism as the preset picker.
`prefetch` stays at the facet's current value; verified: no fetch fires at
connect, only on show/focus, and refetch preserves existing pills.

### 4. TS change: close-guard containment via composedPath (fix F1)

`ts/elements/menu-behavior.ts` `onDocumentClick` currently tests
`host.contains(event.target)`. The pill × handler in `search-select.ts`
removes the pill **synchronously during bubble**, so by the time the
document-level guard runs, `event.target` is detached, containment is false,
and the dropdown closes — every "remove this game" click would slam the
panel shut and strand focus.

Fix at the root: the guard uses `event.composedPath().includes(host)`
(the path is captured at dispatch time, immune to later detachment) with the
existing `contains` check retained as fallback for synthetic events lacking
a path. This is a general correctness fix for every `<drop-down>` (the
preset picker only avoided it because its delete flow is async), not a
facet-specific hack. Covered by a vitest case (synchronously self-removing
click target inside an open dropdown must not close it).

`make ts` after edits; `make check` gates.

### 5. Quick bar wiring (sessions mode only)

`common/components/quick_filter.py`:

- `QuickFacet` gains `dropdown: bool = False`; sessions' `game` and `device`
  facets set it True.
- `QuickFilterBar._facet`: when `facet.dropdown`, render
  `ComboboxDropdown(label=label, ghost=True, id=f"quick-{field}-dropdown",
  content=field_widget(..., layout="panel"))` **bare** — no `Label:` span
  (the trigger is the label) and **no** `_QUICK_FACET_CLASS` /
  `_QUICK_WIDGET_WRAP_CLASS` (`min-w-56`) wrappers, which would force the
  ~5rem trigger into a 14rem slot and defeat the compactness goal.
- Guard: `dropdown=True` on a facet whose kind is not `set` raises
  `ValueError` at render (a real exception, not `assert` — must survive
  `python -O`).
- `field_widget` (`common/components/filters.py`) accepts
  `layout: Literal["field", "panel"] = "field"` and threads it through
  `_model_filter`/`_enum_filter` to `FilterSelect` (also passing
  `search_aria_label=label` when panel). Non-set kinds given
  `layout="panel"` raise `ValueError` — silent ignore would hide a wiring
  bug in the shared dispatcher (also used by the nested-builder leaf rows).
- While touching the file: fix the stale `readFacetWidget` comment
  (serializer is `readLeafWidget` now).

Serializer safety: the bar's TS scans
`this.querySelectorAll("[data-filter-widget]")` — the `<search-select>` root
keeps its attributes and simply sits deeper (inside the hidden dropdown
panel, inside the form). Verified depth- and visibility-agnostic; a vitest
fixture with the widget nested inside a `hidden` `[data-menu]` panel pins it
at the unit level.

Degrade path (`is_quick_editable`) unchanged — it inspects filter JSON, not
widgets.

## What a user sees (sessions list)

Closed: `Game ▾  Device ▾  Started: [range] Ended: [range] Duration: […] [Apply] [Clear]`
— Game/Device are ghost buttons (no outline until hover), height-matched to
Apply/Clear (all compact scale; list pages have no `@container` ancestor).

Click "Game ▾": panel opens, search focused; current include/exclude pills at
top; type-to-filter list with +/− per row. Picks and pill removals keep the
panel open (the composedPath fix guarantees the removal case). Close via
Escape (refocuses trigger) or outside click, hit Apply → navigates with
`?filter=` JSON identical to today's serialization. Reload renders the same
state back into the panel (verified: refetch-on-open preserves
server-rendered pills).

## Error handling

No new endpoints, no new filter JSON shapes. Misuse guards (both
`ValueError`, both negative-tested):

- `dropdown=True` on a non-set facet — raised by `QuickFilterBar._facet`.
- `layout="panel"` for a non-set field kind — raised by `field_widget`.

## Testing

Verification gate: full `direnv exec . make check` (lint, format, mypy,
ts-check, vitest, pytest incl. e2e) green before push.

- **Unit (pytest, tests/)**
  - ghost `ControlButton`: transparent-border classes on the `<button>`
    rendering; `outline`/`plain`/`filled` outputs unchanged.
  - `ComboboxDropdown`: trigger + dialog panel structure,
    `behavior="combobox"`, config passthrough, dialog `aria-label` = label.
  - `LoadPresetDropdown`: existing contract tests in
    `test_search_select.py` pass unchanged after the refactor.
  - `FilterSelect(layout="panel")`: block root (no bordered-field class),
    `always-visible` on, pills-row class with `empty:hidden`, search input
    `aria-label`, and **identical** `data-search-select-*` /
    `data-filter-widget` attribute sets vs `layout="field"`.
  - Pill overflow: pill `max-w-full` + label `truncate` present in both
    layouts.
  - `test_quick_filter_bar.py`: `_editable_markers` gains a dropdown-aware
    branch — for dropdown facets it asserts the trigger (label text +
    chevron) and the `data-path` widget **inside** the panel instead of the
    `Label:` span; all-modes blank-filter test keeps passing. Negative
    tests: the two `ValueError` guards.
  - Sessions bar: Game/Device render as ghost dropdown facets, no label
    span, no `min-w-56` wrap; other facets and other modes byte-identical
    to before.
- **vitest (ts/)**
  - menu-behavior: click on a synchronously-removed node inside an open
    dropdown does not close it (composedPath guard); outside click still
    closes.
  - quick-filter-bar: serialization finds a set widget nested inside a
    `hidden` `[data-menu]` panel.
- **e2e (Playwright)**: sessions list — open Game facet, include a game,
  **remove a pill (panel must stay open)**, Apply, assert navigated
  `?filter=` contains the criterion and the reloaded bar is editable with
  the pill inside the reopened panel.
- **Synthetic e2e harness** (stripped ROOT_URLCONF files): unaffected —
  `layout` defaults `"field"`, `ComboboxDropdown` never calls `reverse()`;
  quick-bar e2e (`test_quick_filter_e2e.py`) runs on the real URLconf.

## Docs

- CLAUDE.md ControlButton bullet: variant list updated (it already lags —
  says filled/segmented; now filled/segmented/outline/plain/ghost).

## Non-goals

- Other facets/modes, apply-on-close/-on-pick semantics, trigger
  active-state styling, removing pills (option C), fixing #314/#315
  directly.

## Review notes

Three-agent adversarial review folded in: F1 (pill-remove close bug) →
composedPath fix; Enter-asymmetry made an explicit accepted decision; ghost
repositioned into the #272 colorless family; wrapper divs pinned off for
dropdown facets; combobox input accessible name added; guards pinned to
`ValueError`; pill overflow hardening; test-plan gaps closed. Reported
"filters.py syntax error" was a false positive — `except ValueError,
TypeError:` is valid PEP 758 syntax on CPython 3.14.

## Follow-up issues to file (after tryout lands)

- Roll dropdown facets out to all set-kind facets / all modes (would
  supersede #314's inline-layout fix for set facets and simplify #315).
- Consider apply-on-close semantics once all facets are dropdowns.
