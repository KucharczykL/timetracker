# Every floating surface in the top layer (#544)

Step 1 of the modal epic #1485. Prerequisite of #1384, the `<form-dialog>`
element.

## Problem

Every floating panel (dropdown menus, listbox and combobox panels, calendar
and year popups, tooltips) is `position: fixed` in the document's own stacking
contexts. A `fixed` element takes the nearest ancestor with `transform`,
`filter`, `contain` or `backdrop-filter` as its containing block. That
ancestor then clips it and offsets its coordinates. Three workarounds keep
this in check today:

- `pinFixedAndMeasureOrigin` (`ts/elements/anchored-position.ts`) measures the
  containing block's origin and subtracts it from every coordinate.
- `OVERLAY_SURFACE_CLASS` (`common/components/custom_elements.py`) puts the
  dark-mode blur on a `::before` layer, because a blurred panel would become
  the containing block of its own submenu flyouts.
- The table shell (`common/components/primitives.py`) carries a ban on
  `transform`/`filter`/`contain`/`backdrop-filter`, and the pinned column
  raises its cell to `z-[3]` while a panel inside it is open.

#1384 puts form pages in a modal `<dialog>`. Their pickers open inside the
dialog; the bottom sheet's panel animates `transform`, so it becomes the
containing block of every `fixed` picker panel inside it. A dialog stacked on
another dialog needs Escape to close the innermost layer first.

Dismissal has three hand-rolled engines: `attachMenu`'s document `click`
listener plus the `dropdown-menu:open` single-open event
(`ts/elements/menu-behavior.ts`), `bindPopupDismiss` (`ts/utils.ts`) for tap
tooltips and every unhosted SearchSelect, and the tooltip's own document
Escape listener (`ts/elements/tooltip-behavior.ts`). Beside them the year
picker toggle and the date segments handle Escape themselves. They agree on
nothing: one closes on `click`, one on `pointerdown`/`mousedown`; the
tooltips answer Escape from anywhere, a menu only with focus on its toggle or
inside its panel.

## Measurements

Each claim below ran in a scratch page, Chrome 154 through Playwright, and
where marked, Firefox 157 through Marionette.

1. A `popover="manual"` element shown with `showPopover()` and styled
   `position: fixed` resolves `left`/`top` against the viewport, even inside
   an ancestor with `transform`, `filter`, `contain: paint` and
   `overflow: hidden`. A nested popover inside a panel that carries
   `backdrop-filter` also resolves against the viewport. Chrome and Firefox.
2. `showModal()` on a dialog leaves `manual` popovers open. Chrome and
   Firefox.
3. A press on an `<input>` outside an open `popover="auto"` panel
   light-dismisses the panel, also with `showPopover({source: input})` and
   with `preventDefault()` on the input's `pointerdown`. An inline-trigger
   combobox (SearchSelect, the date fields) therefore cannot use `auto`.
4. An imperative toggle button on an `auto` panel: `pointerdown`
   light-dismisses the panel, then the `click` handler sees it closed and
   opens it again. `source` does not prevent this; only a declarative
   `popovertarget` does.
5. `preventDefault()` on an Escape `keydown` inside an open modal dialog keeps
   the dialog open.
6. A `manual` popover shown after `showModal()`, outside the dialog, is inert:
   a click on its button lands on the dialog. A top-layer toast stack
   therefore does not fix the toast under a dialog; that belongs to #1384,
   which renders toasts inside the open dialog.
7. When a parent popover closes, a nested `manual` popover stays
   `:popover-open` but renders no box. The engine closes nested surfaces
   itself, so state stays honest.
8. jsdom 30.0.1 has no `showPopover`, `hidePopover`, `popover` property,
   `ToggleEvent` or `HTMLDialogElement.prototype.showModal`.

## Decisions

### `manual`, never `auto`

Measurements 3 and 4 rule out `auto`: the UA's light dismiss cannot know
that an inline trigger belongs to its panel, and imperative toggles race it.
Mixing `auto` for button-triggered panels with `manual` for inline triggers
keeps two engines. Every panel is `popover="manual"`; the top layer gives
escape from containing blocks and correct stacking, and the app owns
dismissal through one engine.

### One engine: the surface stack

New module `ts/elements/surface-stack.ts`. It holds the open surfaces in
open order and binds its listeners once, on first use. It owns the stack and
dismissal; each controller keeps owning its panel.

```text
interface Surface {
  host: HTMLElement;              // a press inside the host is inside
  kind: "panel" | "hint" | "modal";
  close(): void;                  // the controller's own close
  restoreFocus?(): void;          // on Escape, before the close
}
pushSurface(surface)    // called by the controller's open
removeSurface(surface)  // called by the controller's close; idempotent
```

Controllers show and hide a panel through two helpers in the same module,
`showInTopLayer(panel)` and `hideFromTopLayer(panel)`, so the call order is
written once: `showPopover()` first, then `hidden = false`; on close
`hidePopover()`, then `hidden = true`. A disconnected panel is not shown.
Hiding tolerates a popover the UA already hid: moving or removing a node
hides its popover, and `<drop-down>` closes on disconnect as it does today,
so an open facet that the quick bar reorders still closes.
Dismissal calls `surface.close()`, which calls `removeSurface`; removal of an
absent surface does nothing, so the two never recurse.

Rules:

- **Single open.** Pushing a `panel` or `modal` closes every open surface
  whose host does not contain the new surface's host. This replaces
  `dropdown-menu:open` and `notifyDropdownOpen`, and it keeps the old
  sheet rule: a panel that opens outside an open sheet closes the sheet.
  Pushing a `hint` closes nothing, so hovering a tooltip never closes a
  menu.
- **Nested close.** Removing a surface first closes every open surface whose
  host it contains, topmost first (measurement 7).
- **Escape.** One `keydown` listener on `window` in the capture phase. It
  ignores a key press during IME composition (`isComposing`) and an
  auto-repeat (`repeat`), so one press closes one layer. While the topmost
  surface is a `panel` or `hint`, Escape calls its `restoreFocus` (which
  reads where focus is before the panel hides), closes it, and marks the
  event spent (`preventDefault`). It runs before every element handler, so no widget can mark the press spent first (the date
  segments do so for every key) or forget to (SearchSelect never does).
  It does not stop propagation: a selectable table still reads
  `defaultPrevented` and keeps its selection, and an enclosing modal
  dialog stays open (measurement 5). Topmost means last opened, so a
  tooltip hovered over an open menu closes first. A `modal` on top is left to
  the dialog's native `cancel`, which already owns the sheet's Escape and
  every other close request (`sheet-controller.ts`).
- **Outside press.** The engine records the path of a primary
  (`isPrimary`, button 0) `pointerdown` and closes on the `pointerup` with the
  same `pointerId`; a `pointercancel` in between
  (the browser took the touch for scrolling) discards it. It finds the
  topmost surface whose host is on the recorded `composedPath()` and closes
  every surface above it; a press inside none closes all. This is the UA's
  own light-dismiss shape. It replaces `click` (iOS Safari fires none for a
  tap on page space) and bare `pointerdown` (a touch scroll and a right
  click must not dismiss). `composedPath()` at `pointerdown`, so a target
  that its own handler removes still counts as inside. A press on the page's
  scrollbar counts as outside, as in the UA's light dismiss. A `modal` surface's
  host contains its dialog and backdrop, so the sheet keeps its own backdrop
  handling.

Escape handlers that the engine replaces go: `attachMenu`'s panel and toggle
Escape branches (focus return becomes the menu's `restoreFocus`), the
tooltip's document listener, the year picker toggle's Escape branch,
SearchSelect's two `hidePanel()` Escape calls when hosted (the dialog
layout keeps them: there Escape only clears the highlight), and the date segments'
catch-all no longer swallows Escape. `bindPopupDismiss`,
`MenuController.bindDocument`, `OPEN_MENUS_EVENT`, `notifyDropdownOpen` and
`attachMenu`'s document `click` listener are deleted. `<drop-down>` binds no
document listener per connection; a disconnected `<drop-down>` still closes
its panel, which removes it from the stack.

The bottom sheet is a `modal` surface. The engine never touches its dialog;
its `close` runs the sheet's animated close, and `finishClose`, the one path
every close reaches (a native `close` event included), calls
`removeSurface`. The sheet keeps closing a sibling sheet through
`closeImmediately` before `showModal()`, because its scroll-lock snapshot
needs an unlocked document; the engine's single-open finds that sheet
already gone.

SearchSelect's ARIA follows its host. Today only the widget's own Escape
runs `hidePanel()`, which clears the highlight and writes
`aria-expanded="false"`; a close by the host (outside press, Tab, single
open) leaves both stale. The hosted widget listens for its own host's
`dropdown:hide` and runs the same two steps, as the date calendar already
does, so an engine Escape and every host close leave the same ARIA state.

SearchSelect's dialog layout (`panel=True`: presets, panel-layout
FilterSelect, the time zone row) renders an always-visible listbox, never a
surface. Today it binds `bindPopupDismiss` because it is not hosted, and its
"open" check reads the always-visible listbox, so every Escape on a page with
a quick bar is marked spent and a selectable table never clears its
selection. With `bindPopupDismiss` gone, nothing binds there.

`hidden` does more than record state: every panel class carries a display
utility (`flex`, `inline-block`) that beats the UA's closed-popover
`display: none`, and only `[hidden]` hides a closed panel. That is why
`hidden` is cleared only after a successful `showPopover()`.

The overflow hosts of `quick-filter-bar` and `selection-actions` hide their
wrapper on resize. Each closes its overflow `<drop-down>` before it hides
the wrapper, so no open surface sits on the stack without a box.

### Markup

Every panel the server renders carries `popover="manual"` beside its
`hidden`: `_stamp_target_contract` (every `<drop-down>` behavior but the
sheet), `_tooltip_panel`, the date calendar popup (`date_calendar_shell`'s
non-static branch only; the static calendar inside the date facet stays in
flow), the year picker popup, and the SearchSelect inline-layout panel.
`absolute`, `z-*` and `isolate` (which only contained the `::before` blur)
leave the panel classes; a top-layer panel needs none of them.

### UA stylesheet reset

`[popover]` brings `position: fixed`, `inset: 0`, `width`/`height:
fit-content`, `margin: auto`, a border, `padding: .25em`, `overflow: auto`,
`color: CanvasText` and `background-color: Canvas`. Tailwind's preflight
already zeroes margin, padding and border in `@layer base`. Only the tooltip
panel sets a text colour (`text-heading`), and `DropdownPanel` sets no
overflow on the panel itself. One rule in `common/input.css`, inside
`@layer base` so every utility wins:

```css
[popover] { inset: auto; overflow: visible; color: inherit;
            background-color: transparent; }
```

A reset of UA defaults is document bootstrapping, which `input.css` holds.
`position: fixed` and `fit-content` stay: positioned panels want both.
`color: inherit` reads the DOM parent, which is what the panel read before.
`overflow: visible` keeps the tooltip arrow, which overhangs the panel edge.
Every panel's surface class sets its own background, so `tintArrow` reads the
real one.

### Workarounds that go

- `pinFixedAndMeasureOrigin` stops measuring an origin: a top-layer `fixed`
  panel's containing block is the viewport. It becomes `pinFixed`, which
  still pins the panel at (0, 0) before callers measure, because the
  submenu's first-item inset reads item positions relative to that pin. Both
  callers drop the origin subtraction.
- `OVERLAY_SURFACE_CLASS` puts `dark:backdrop-blur-xl` on the surface itself
  and drops the `::before` layer and its comments. The static calendar inside
  the date facet keeps its own surface, as a deliberate choice that it looks
  the same everywhere; it drops `relative`, which only anchored the
  `::before`. A blurred facet panel is a backdrop root, so the nested blur now
  samples the panel rather than the page; a dark-mode screenshot checks it.
- The table shell's ban comment, the scroll region's note and the pinned
  column's containing-block note go. `e2e/test_dropdown_clipping_e2e.py` and
  the column picker's clipping test stay as the proof.
- `PINNED_COLUMN_CLASS` drops its two `has-[...]:z-[3]` variants, with the
  e2e test that pins the raise and the strata test that compares pinned
  z-values with panel z-values. The two occlusion tests stay.
- Open panels now paint above the navbar, the selection line and the toast
  stack. A toast raised while a panel stays open shows beneath it until the
  next press closes the panel; this is accepted.

### Standalone SearchSelect goes

The standalone layout (`_STANDALONE_LAYOUT`, `absolute top-full`) has no
production caller: every form and filter passes `host_dropdown=True`
(`games/forms.py`, `common/components/filters.py` twice), and the time zone row uses
`panel=True`. It is the last panel positioned by CSS alone and would stay
clipped. It is removed: `host_dropdown` leaves the signature and the inline
layout is the default.

`common/components/filters.py` passes it twice. CLAUDE.md's
SearchSelect entry names `host_dropdown=True` and changes with it.

The cost is in tests. Python callers that build a bare `SearchSelect`
(`tests/test_unset_field.py`, `tests/test_control_button_size.py`,
`tests/test_node_tree.py`, `tests/test_search_select.py`) and the e2e
harness pages (`e2e/test_compact_button_e2e.py`,
`e2e/test_search_select_e2e.py`, `e2e/test_search_select_clear_e2e.py`)
render the inline layout instead; a test
that asserts `top-full` goes. Nine vitest suites
(`search-select.{api,aria,clear,create,filter-action,grouped,hint,none,params}.test.ts`)
mount a bare `<search-select>`; they mount it inside a
`<drop-down behavior="inline-combobox">` through one shared fixture helper.
The `bindPopupDismiss` test in `search-select.aria.test.ts` moves to
`surface-stack.test.ts`. In TypeScript the non-delegated branch remains only
for the dialog layout, which never opens or closes.

### jsdom

A vitest setup file (`ts/test-setup/popover.ts`, named in
`vitest.config.ts` `setupFiles`) defines `showPopover`/`hidePopover` on
`HTMLElement.prototype` where jsdom lacks them, tracking open state in a
`WeakSet`. It throws where the UA throws: `NotSupportedError` on an element
without a `popover` attribute, `InvalidStateError` on a disconnected one. So
every fixture carries `popover="manual"`, and a stamp site that omits it
fails in vitest as it would in a browser. The suite's default environment
is `node`, so the file does nothing where `HTMLElement` is undefined. Production code calls the API unconditionally: every supported
browser ships it. Unit tests keep asserting `hidden`, which stays the state.

## Out of scope

- The toast stack stays out of the top layer. Measurement 6 shows a
  top-layer toast is still inert under a modal dialog; rendering toasts inside
  the open dialog belongs to #1384.
- `selection-actions` and `quick-filter-bar` overflow hosts toggle a wrapper
  class, not a panel; the panel inside each is a `<drop-down>` and moves
  with the rest.

## Testing

- Unit (vitest, jsdom with the shim): `surface-stack.test.ts` covers single
  open, the hint kind, the modal kind, nested close, Escape closing only the
  topmost and marking it spent, Escape with an empty stack left unspent,
  outside press by pointerdown and pointerup, a pointercancel in between,
  and a target removed by its own handler. `menu-behavior.test.ts` and
  `drop-down.controller.test.ts` replace their `bindDocument` cases with:
  a moved `<drop-down>` does not wire twice, and its close on disconnect
  leaves the stack. The two `menu-behavior` Escape tests ("marks the press
  spent", "leaves a press that closed nothing") move to the engine's suite.
  `sheet-controller.test.ts` keeps its Escape case: a sheet on top is left
  to native `cancel`. Picker, tooltip and search-select tests keep their
  `hidden` assertions; their fixtures gain `popover="manual"`.
- E2E (real Chrome): a panel inside a `transform`ed ancestor opens unclipped
  at its anchor; a submenu's first item lines up with its row; Escape with a
  tooltip over an open menu closes the tooltip only; Escape in a combobox
  inside an open facet panel closes the combobox only; on a real list page
  with a quick bar, Escape clears a selection; a touch scroll keeps a row menu
  open. The existing clipping, pinned-column occlusion, selectable-table and
  played-dropdown tests stay green.
- Python: panel markup carries `popover="manual"`; the static calendar
  carries none; tests that pin `absolute z-20` (`test_column_picker.py`),
  `isolate` (`test_dropdown_panel.py`), `top-full` or the pinned `z-[3]`
  strings and strata (`test_components.py`) change with the classes.

## Documents to sweep

`docs/dropdown-lifecycle-events.md` (attachMenu's open and close) and
`docs/settings-mobile-bottom-sheet-plan.md` (the sheet and
`bindPopupDismiss`) describe the old engines. CLAUDE.md's SearchSelect
entry names `host_dropdown`.

## Follow-up issues to file

- None new. #1384 gains the toast-under-dialog item and the jsdom
  `showModal` gap; #544, #1384 and #1485 are corrected to say `manual`.
