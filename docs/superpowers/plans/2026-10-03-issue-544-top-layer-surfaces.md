# Every floating surface in the top layer — Implementation Plan

**Goal:** every floating panel renders in the top layer as `popover="manual"`,
and one surface stack owns dismissal.

**Architecture:** new `ts/elements/surface-stack.ts` holds open surfaces and
the only document listeners (capture-phase Escape, pointerdown/pointerup
outside press). Controllers (`attachMenu`, `attachTooltip`, the sheet) push
and remove themselves and show panels through `showInTopLayer`/
`hideFromTopLayer`. Server markup stamps `popover="manual"` beside `hidden`.

**Spec:** `docs/superpowers/specs/2026-10-03-issue-544-top-layer-surfaces-design.md`

## Global constraints

- `hidden` stays the state; clear it only after `showPopover()` succeeds.
- Escape: capture phase on `window`; skip `isComposing` and `repeat`; skip a
  `modal` on top; `preventDefault`, never `stopPropagation`.
- Outside press: `isPrimary`, button 0 `pointerdown` → matching `pointerId`
  `pointerup`; `pointercancel` discards.
- Every node invocation through `make`; pytest targets under
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- Names in full words; comments seven words or fewer.
- Before each commit: `make format`, `make lint-fix`, `make format-check`,
  `make vale`, each read by exit code.

---

### Task 1: jsdom popover shim

**Files:** create `ts/test-setup/popover.ts`; modify `vitest.config.ts`
(`setupFiles`), `tsconfig.check.json` if it must include the setup dir.

- Shim only where `typeof HTMLElement !== "undefined"` and
  `showPopover` is missing.
- `showPopover`: throw `DOMException("…", "NotSupportedError")` without a
  `popover` attribute, `InvalidStateError` when disconnected; no-op when
  already open; add to a module `WeakSet`.
- `hidePopover`: no-op when not open; remove from the set.
- `Element.prototype.matches` is not patched; code reads `hidden`.

**Tests:** `ts/test-setup/popover.test.ts` (jsdom): throws without attribute,
throws disconnected, show/hide idempotent.

**Gotcha:** a node-environment suite imports nothing DOM; prove with
`make test-ts` that every suite still runs.

### Task 2: the surface stack

**Files:** create `ts/elements/surface-stack.ts`,
`ts/elements/surface-stack.test.ts`.

**Produces:**

```text
export type SurfaceKind = "panel" | "hint" | "modal";
export interface Surface { host: HTMLElement; kind: SurfaceKind;
  close(): void; restoreFocus?(): void; }
export function pushSurface(surface: Surface): void;
export function removeSurface(surface: Surface): void;     // idempotent
export function showInTopLayer(panel: HTMLElement): boolean; // false if not shown
export function hideFromTopLayer(panel: HTMLElement): void;
export function openSurfaces(): readonly Surface[];        // read by tests
export function resetSurfacesForTests(): void;
```

- Listeners bound lazily on first `pushSurface`, once per document; a
  `resetSurfacesForTests()` export clears stack and listeners (vitest
  isolation between files shares no module state, but cases within a file
  do).
- `pushSurface`: re-push of a present surface moves nothing; for
  `panel`/`modal` close every open surface whose host does not contain the
  new host (iterate a copy, topmost first).
- `removeSurface`: first close (via their `close()`) every open surface
  whose host the removed surface's host contains and that sits above it,
  topmost first; then splice it out.
- Escape: topmost; `modal` on top → return; else `restoreFocus?.()`
  first (it reads where focus is before the panel hides), then `close()`,
  then `preventDefault()`.
- Outside press: store `{pointerId, path}` on pointerdown; on matching
  pointerup find topmost index whose host is in path; close all above.
- `showInTopLayer`: return false when `!panel.isConnected`; `showPopover()`
  unless `:popover-open`… jsdom cannot match it, so guard with try and the
  shim's no-op on re-show; then `hidden = false`.

**Tests (one `it` each):**
- single open closes unrelated panel, keeps ancestor-hosted panel;
- hint push closes nothing; panel push closes an unrelated hint;
- modal push closes panels outside it;
- removing a parent closes nested surfaces first (order recorded);
- Escape closes only topmost and marks spent; empty stack leaves unspent;
- Escape with `isComposing` / `repeat` does nothing;
- Escape with modal on top is unspent and closes nothing;
- `restoreFocus` runs before close, while focus is still inside;
- press inside an inner surface closes only those above it;
- press outside all closes all; `pointercancel` between discards;
- pointerup with another `pointerId` is ignored;
- target removed by its own handler still counts inside (path recorded at
  pointerdown);
- `showInTopLayer` on a disconnected panel returns false, leaves `hidden`.

Commit: `feat: surface stack for floating panels (#544)`.

### Task 3: markup and the UA reset

**Files:** `common/input.css` (`@layer base` rule),
`common/components/custom_elements.py` (`_stamp_target_contract`,
`_DROPDOWN_PANEL_CLASS`, `OVERLAY_SURFACE_CLASS`),
`common/components/primitives.py` (`_tooltip_panel`, `_TOOLTIP_PANEL_CLASS`
if it carries `z-10`, year picker popup), `common/components/date_range_picker.py`
(`date_calendar_shell` non-static branch, `_STATIC_CALENDAR_CLASS`),
`common/components/search_select.py` (inline-layout panel stamp).

- Stamp `popover="manual"` wherever `hidden` is stamped on a panel; not on
  the sheet, not on the static calendar.
- Remove `absolute z-20 isolate` from `_DROPDOWN_PANEL_CLASS`, `absolute
  z-20` from the year popup, `z-20` from the calendar popup, `z-10` from the
  tooltip panel.
- `OVERLAY_SURFACE_CLASS` = `bg-surface-overlay text-type-body
  dark:backdrop-blur-xl`; drop the `::before` comment block.
- Static calendar: drop `relative`; rewrite its comment.
- `make css` then grep `games/static/base.css` for the new `[popover]` rule.

**Tests:** extend `tests/test_dropdown_panel.py` (every listed site carries
`popover="manual"`, no `isolate`/`absolute`), `tests/test_date_range_picker.py`
and `tests/test_date_picker.py` (popup stamped, static calendar not),
`tests/test_components.py` (tooltip panel stamped), `tests/test_column_picker.py`
(drop `absolute`,`z-20`), `tests/test_custom_elements.py`
(`DropdownMenuPanel` assertions), `tests/test_search_select.py`
(inline panel stamped).

**Gotcha:** this task alone breaks the browser. A stamped panel whose
`hidden` is cleared without `showPopover()` renders: its `flex` utility beats
the UA's closed-popover `display: none`, and the UA `position: fixed` with
`inset: auto` leaves it at its static position. Land Tasks 3–6 before any e2e
run; vitest and pytest only in between.

### Task 4: attachMenu onto the stack

**Files:** `ts/elements/menu-behavior.ts`, `ts/elements/drop-down.ts`,
`ts/elements/behaviors/*.ts` that read `bindDocument`, `ts/elements/year-picker.ts`
(drop toggle Escape branch), `ts/elements/menu-behavior.test.ts`,
`ts/elements/drop-down.controller.test.ts`, every vitest fixture holding
`data-menu hidden` (add `popover="manual"`).

- `MenuController` loses `bindDocument`; `DropdownElement` loses
  `unbindDocument` and the reconnection branch keeps only "controller
  exists → return".
- `open()`: `pinFixed`-free order stays (position fixed before show), then
  `showInTopLayer(menu)`; bail if it returns false; then `pushSurface`.
- `close()`: `hideFromTopLayer`, `removeSurface`, rest unchanged.
- Surface `restoreFocus`: focus the toggle when focus was inside the menu
  (inline trigger: nothing).
- Delete `onDocumentClick`, `onOtherMenuOpen`, `OPEN_MENUS_EVENT`,
  `notifyDropdownOpen`, `OpenMenuDetail`, and the panel/toggle Escape
  branches.
- Keep `keepOpenOnTab` focusout logic as is.

**Tests:** replace `bindDocument` cases with: moved `<drop-down>` wires once
(one toggle click opens); disconnect leaves stack empty. Move the two
Escape tests to Task 2's suite if not already covered. Keep `isOpen`
assertions.

### Task 5: tooltips onto the stack

**Files:** `ts/elements/tooltip-behavior.ts`, `ts/elements/pop-over.test.ts`,
`ts/elements/truncated-text.test.ts` fixtures.

- `kind: "hint"`; open → `showInTopLayer` + push; close → hide + remove.
- Delete `onKeyDown` and the `bindPopupDismiss` branch (tap tooltips are
  dismissed by the stack's outside press).
- Tap path: the tooltip's own trigger click toggles; the trigger is inside
  the host, so the stack's outside press never races it.

**Tests:** pop-over tap closes on outside press via pointerdown+pointerup
(was pointerdown alone: update dispatches); Escape closes via the stack.

### Task 6: the sheet as a modal surface

**Files:** `ts/elements/sheet-controller.ts`, `sheet-controller.test.ts`,
`ts/elements/section-nav.ts` if it reads `bindDocument`.

- Push `kind: "modal"` after `showModal()`; `removeSurface` in
  `finishClose`. `close` = the animated close.
- Delete `onOtherDropdownOpen`, `bindDocument`, `notifyDropdownOpen` call;
  keep `closeImmediately` for a sibling sheet.
- Existing "no Escape listener" test stays green.

### Task 7: SearchSelect hosted only

**Files:** `common/components/search_select.py` (remove
`_STANDALONE_LAYOUT`, `_STANDALONE_PANEL_CLASS`, `host_dropdown` param),
`games/forms.py`, `common/components/filters.py` (two calls),
`ts/elements/search-select.ts` (hosted ARIA on `dropdown:hide`; remove the
two hosted Escape `hidePanel` calls; remove the `bindPopupDismiss` binder and
the `connectedCallback`/`disconnectedCallback` use), `ts/utils.ts` (delete
`bindPopupDismiss`), tests listed below.

- `dropdown:hide` listener checks `event.target === dropdownHost`.
- Dialog layout keeps Escape → `hidePanel` (highlight only).
- Shared vitest helper `ts/elements/search-select.fixture.ts` (or the
  nearest existing fixture module): `mountHosted(innerHtml)` wraps in
  `<drop-down behavior="inline-combobox">` with `data-toggle` on the
  container and `popover="manual"` on the panel.

**Tests:** rehost the nine suites
`search-select.{api,aria,clear,create,filter-action,grouped,hint,none,params}.test.ts`;
`aria` gains "host close writes aria-expanded false and clears
aria-activedescendant". Python: `tests/test_unset_field.py`,
`tests/test_control_button_size.py`, `tests/test_node_tree.py`,
`tests/test_search_select.py` (drop `top-full` test). E2E harness pages:
`e2e/test_compact_button_e2e.py`, `e2e/test_search_select_e2e.py`,
`e2e/test_search_select_clear_e2e.py`.

### Task 8: remaining Escape owners and hidden hosts

**Files:** `ts/elements/date-field-core.ts` (Escape returns before the
catch-all), `ts/elements/quick-filter-bar.ts`, `ts/elements/selection-actions.ts`
(close the overflow `<drop-down>` before adding `hidden` class),
their tests.

**Tests:** segment Escape is not spent with no calendar open; overflow
host hidden while open leaves stack empty.

### Task 9: workarounds that go

**Files:** `ts/elements/anchored-position.ts` (`pinFixedAndMeasureOrigin` →
`pinFixed`, returns void; drop subtraction in `positionAnchored`),
`ts/elements/menu-behavior.ts` (`positionSubmenu` measures items against
the (0,0) pin), `common/components/primitives.py` (`PINNED_COLUMN_CLASS`
`has-[...]` variants, shell comment, scroll-region note, pinned comment),
`tests/test_components.py` (drop `z-[3]` and strata tests),
`e2e/test_pinned_column_e2e.py` (drop the raise test).

**Gotcha:** `firstItemInset` read relative to viewport 0 now; keep the pin
before measuring.

### Task 10: e2e proofs

**Files:** `e2e/test_top_layer_e2e.py` (new; synthetic page where it can,
real list page where the spec says so).

Cases: panel inside a `transform` ancestor opens at its anchor, unclipped;
submenu first item aligns with its row; tooltip over open menu — Escape
closes tooltip only; combobox in an open facet panel — Escape closes only the
combobox; Games list with quick bar — select a row, Escape clears it; touch
scroll (`page.touchscreen` + `pointercancel` via CDP or `mouse.wheel` is not
touch — use `dispatchEvent` of pointerdown/pointercancel) keeps a row menu
open; dark-mode screenshot of the date facet for the nested blur.

Then full focused e2e on the touched areas: `make test-e2e ARGS="-k
'dropdown or menu or pop or tooltip or search_select or pinned or
selectable or year_picker or truncated or column_picker or played or
filter_builder or settings_ui_kit or calendar or date'"`.

### Task 11: docs and issues

- `docs/dropdown-lifecycle-events.md`, `docs/settings-mobile-bottom-sheet-plan.md`,
  CLAUDE.md SearchSelect entry (`host_dropdown`) and the custom elements /
  dropdown notes.
- Update #544 (manual not auto; toast out), #1384 (toast inside dialog;
  jsdom `showModal`), #1485 step 1 text.
- Docs sweep per skill (step 8): delete this plan, rewrite spec timeless.
