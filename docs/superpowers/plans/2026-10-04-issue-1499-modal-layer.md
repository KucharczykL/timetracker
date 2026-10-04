# Plan: one modal layer that nests (#1499)

Spec: `docs/superpowers/specs/2026-10-04-issue-1499-modal-layer-design.md`.
Implement inline, TDD per task. Iterate with
`flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-ts TS_ARGS=…`
and `make ts-check`.

## Task 1: dialog stand-in

- New `ts/test-setup/dialog.ts`: guarded install of `showModal`/`close` on
  `HTMLDialogElement.prototype` (only where missing). Track modal state in a
  `WeakSet`. `close` queues `close` via `setTimeout(0)`.
- `vitest.config.ts`: add to `setupFiles` before `surface-stack.ts`.
- `ts/test-setup/dialog.test.ts` (jsdom): open/close, double showModal,
  disconnected refuse, close on closed fires nothing.

## Task 2: surface stack keeps modals

- `ts/elements/surface-stack.ts` `pushSurface`: filter `open.kind !== "modal"`
  in the single-open dismissal. Comment: modal leaves only by its own act.
- `surface-stack.test.ts`: a pushed modal keeps an open modal; a pushed panel
  outside keeps an open modal; panel outside still closed by a modal push.

## Task 3: `ts/elements/modal-layer.ts`

Interfaces:

```text
export interface ModalOptions {
  host?: HTMLElement;
  initialFocus?: () => HTMLElement | null;
  leave?: (finish: () => void) => boolean;
  dismiss?: () => void;
  onClosed?: () => void;
}
export interface Modal { open(opener?): boolean; close(): void; isOpen(): boolean; focusInitial(): void }
export function attachModal(dialog: HTMLDialogElement, options?: ModalOptions): Modal
export function isModalOpen(): boolean
export function topModal(): HTMLDialogElement | null
export const MODAL_CHANGE = "modal-layer:change"
export function resetModalLayerForTests(): void
```

Internals: module `stack: Entry[]` (open, not leaving), `leaving: Set<Entry>`,
scroll-lock refcount + snapshot (moved verbatim from the sheet), one
`MutationObserver` connected while `stack.length + leaving.size > 0`.
Backdrop press tracks one pointer id; `pointercancel` clears it.
Per-modal state `closed | open | leaving` and a `generation` counter bound
into each `finish` closure. `nearestDialog(event.target)` gate on every
listener. `tabbableElements` moved from the sheet, filtered by nearest dialog.
Focus fallback walks `closest("drop-down")` outward using an own-toggle
lookup (same rule as `ownChild` in `drop-down.ts`; export `ownChild` from
there or a tiny shared helper in `ts/elements/own-child.ts` — prefer the
shared helper so the layer does not import the element module).

Test `ts/elements/modal-layer.test.ts` — cases listed in the spec's Tests
section. Add `ts/test-setup/modal-layer.ts` registering
`afterEach(resetModalLayerForTests)` beside the surface-stack one.

Gotchas:
- On every change, set `data-modal-covered` on stacked dialogs below the top,
  clear it on the top and on any leaving/closed dialog.
- Scroll lock releases at finish only, never at close start.
- Change event must fire on close start (leave) and on finish only if the
  top changed; dedupe by comparing previous `topModal()`.
- Close-above in `close()` uses each above modal's immediate finish, not its
  `close()` (no leave).
- Unlock before focus return (scroll restore first), `preventScroll: true`.

## Task 4: CSS + Python

- `common/input.css`: move the viewport hit-area block from
  `dialog[data-bottom-sheet]` to `dialog[data-modal]` (+ `[open]` flex,
  `align-items: center`); `dialog[data-modal]::backdrop` opacity transition
  200 ms; `dialog[data-modal][data-modal-covered]::backdrop { opacity: 0 }`
  placed after the sheet's backdrop rules (equal specificity); sheet keeps `align-items: flex-end`, backdrop and
  slide.
- `common/components/custom_elements.py` `BottomSheet`: add `data-modal`,
  rename `data-sheet-dismiss` → `data-modal-dismiss`.
- `tests/test_custom_elements.py:235`, `e2e/test_settings_ui_kit_e2e.py:457`,
  `ts/elements/section-nav.test.ts:31`: rename.

## Task 5: sheet on the layer

- `ts/elements/sheet-controller.ts`: `attachSheet` builds
  `attachModal(dialog, { host, initialFocus, leave, onClosed })`. Keeps
  states, hidden-trigger guard, `aria-expanded`, `dropdown:show/hide`,
  section-link click (gate on own dialog), slide `leave` (transitionend on
  panel `transform` or 250 ms timer; reduced motion → false). Opener: toggle.
  Delete `activeSheet`, snapshot, tabbables, pointer and cancel handlers.
- `sheet-controller.test.ts`: drop prototype stubs; rewrite the three cases
  the spec names; add `data-modal` to fixtures.

## Task 6: toast host

- `common/components/toast.py`: `TOAST_MODAL_REGION_CLASS` (fixed top-0
  right-0, flex col items-end, pointer-events-none, p-4, top padding
  `max(1rem, env(safe-area-inset-top))`), prop `modal_region_class`; run
  `make gen-element-types`. Pin in `tests/test_components.py` beside the
  existing class pin.
- `ts/elements/toast-stack.ts`: import `topModal`, `MODAL_CHANGE`. Field
  `container: HTMLElement` (self or region). `rehost()` on change and in
  `connectedCallback`: build region (`modal_region_class`, copy role/aria-*), move nodes,
  append to dialog, drop old region, reset hover/focus flags for each toast.
  `render()` appends new nodes to `container`.
- `toast-stack.test.ts` (find existing test file): re-host on open, nested,
  back on last close, new toast lands in the region, flags cleared.

## Task 7: e2e

- `e2e/test_modal_layer_e2e.py` (or extend settings ui kit): on the settings
  page, `import()` the built `modal-layer.js`, mount two `data-modal`
  dialogs (one nested in DOM, one at body), open both, close the lower: no
  `:modal` left, scroll style restored, focus on the opener.
- Settings mobile sheet: open it, dispatch `show-toast`, assert the toast is
  inside the dialog, its box ends above the sheet panel's top, and its
  dismiss click removes it.

## Task 8: docs

- `gh issue comment` #1384 and #1094: top-edge region under a modal;
  `isModalOpen()` false from the last close's start; backdrops dim once.

- #544 spec: single-open sentence and toast limit.
- CLAUDE.md top-layer bullet: one line on `modal-layer.ts`.

Gate: `make check` under the lock, exit code.
