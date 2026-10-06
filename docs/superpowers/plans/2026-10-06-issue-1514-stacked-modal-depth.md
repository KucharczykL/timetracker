# Plan: stacked modal depth and trail (#1514)

Spec: `docs/superpowers/specs/2026-10-06-issue-1514-stacked-modal-depth-design.md`.
Implementation is inline, TDD per behaviour. Iterate with focused runs under
the shared lock; full `make check` once at the end.

## Task 1 — Python: roles, header, panel

Files: `common/components/modal.py`, `common/components/form_dialog.py`,
`common/components/custom_elements.py` (`BottomSheet`),
`common/components/__init__.py`, `tests/test_modal_dialog.py`,
`tests/test_form_dialog.py`.

- `ModalAttributeRole` + `MODAL_ATTRIBUTES`: `panel`, `header`, `trail`,
  `depth`.
- `ModalPanelHeader`: outer `Div` gets `MODAL_ATTRIBUTES["header"]`; class
  becomes `flex shrink-0 items-center justify-between gap-4 py-1.5 pl-4 pr-1.5`
  plus the divided border/surface (drop `py-3`/`pt-4`). × is
  `size="compact"`. Title column `Div(class_="flex min-w-0 flex-col")[trail,
  h2]`, trail `P([(trail, ""), ("hidden", True)], class_="text-type-micro
  text-body")`.
- `ModalPanel(attributes=(), *, class_="") -> Element`: `Div` with
  `data-modal-panel` and `_MODAL_PANEL_CLASS` (constant, the step classes in
  the spec, literal for Tailwind). Export it.
- `form_dialog.py`: `_SURFACE_CLASS` max-h becomes
  `max-h-[calc(100dvh-2rem-var(--modal-reserve,0px))]`; form and warning
  panels use `ModalPanel(class_=...)`.
- `BottomSheet`: panel via `ModalPanel([("data-sheet-panel", "")], ...)`;
  `_SHEET_PANEL_MOTION_CLASS` drops `motion-safe:transition-transform` and
  the duration/ease (now from `ModalPanel`).
- Tests: header height classes and compact ×; hidden trail present;
  `ModalPanel` marker; `_MODAL_PANEL_CLASS` names `data-modal-depth:`,
  `--modal-shift`, `--modal-reserve`, `--modal-depth`, contains `[transform:`
  and no `translate-y-`; sheet panel carries both markers.
- Gotcha: `_DIVIDER` in `tests/test_form_dialog.py:158` reads the header's
  class — update it to the new string, keep it reading the constant.

## Task 2 — codegen

- `make gen-element-types` (or `make ts`) regenerates
  `ts/generated/modal-attributes.ts`; the existing generated-module test
  covers the new roles.

## Task 3 — layer: depth and geometry

File: `ts/elements/modal-layer.ts`, tests in `modal-layer.test.ts`.

- `ownPart(dialog, role)`: `querySelectorAll` + `nearestDialog === dialog`.
- `markStack()`: open entries; for each shown entry compute depth (open
  above it; leaving entries get none), trail (top open only), then measure
  header heights, write `--modal-reserve`, measure `offsetTop`, compute
  targets top-down and write `--modal-shift`, `--modal-depth`, stamp
  `data-modal-depth`. Write-if-different helper for style properties and
  attributes. Order: trails → header heights → reserves → offsets → shifts.
- Called after `markBackdrops()` at open, close start, finish; window
  `resize` listener and `ResizeObserver` (guarded) over panels and headers,
  created with the first shown modal, torn down with the last (beside
  `watchRemovals`). `finish()` unobserves and clears the entry's panel and
  dialog. `refreshModalStack()` exported; no-op when `shown` is empty.
- `resetModalLayerForTests()` clears covered/over, depth state, observer,
  listener.
- Tests (stub `offsetTop`/`offsetHeight` with `Object.defineProperty`):
  three levels → depths 2/1/none; values end in `px`; shift ≤ 0; a higher
  covered panel gets shift 0 and the next target follows its real top;
  reserve sums scaled strips; leaving top → lower depth none; nested panel
  ignored; harness dialogs without parts raise and report nothing.

## Task 4 — layer: trail and description

- Fill: clear children; names via `aria-labelledby` ids' `textContent`
  (trimmed, joined by space) else `aria-label`; separator spans per spec;
  `hidden` off. Hide/empty for every non-top shown entry, except a leaving
  one (untouched).
- `aria-describedby` token: id minted `modal-trail-<n>` when absent; insert
  first, or last when `role="alertdialog"`; remove when hidden and on
  finish. Keep the attribute absent rather than empty when no tokens remain.
- Tests: bottom first; covered dialogs hidden; separators aria-hidden + sr
  comma; dialog vs alertdialog order; other tokens kept; `aria-label`
  fallback; nameless skipped; rebuilt after top closes and a new one opens;
  `refreshModalStack()` after a title rename.

## Task 5 — form dialog hook

- `ts/elements/form-dialog.ts`: call `refreshModalStack()` at the end of
  `fill()`. Vitest: a renamed lower dialog appears in the upper trail.

## Task 6 — e2e

- `e2e/test_modal_layer_e2e.py`: new fixture of three **sibling** dialogs
  built with `ModalDialog` + `ModalPanel` + `titled_header`, titles Lower,
  Middle, Top; Lower tall (forces max height), Middle short, Top medium;
  `page.emulate_media(reduced_motion="reduce")`. Assert per covered panel:
  `getBoundingClientRect().top` < the one above, ≥ 0, and its `<h2>` rect
  bottom ≤ the top of the panel above. Top trail text `Lower › Middle`,
  accessible description via `aria-describedby` id text.
- `e2e/test_dialog_create_e2e.py`: in the nested-dialog test, the top
  dialog's `[data-modal-trail]` reads `Add New Game` and is visible.
- Existing sheet e2e must stay green (slide still on `translate`).

## Task 7 — CSS check and spot check

- `make css`; grep `games/static/base.css` for the depth transform and
  reserve rules (pytest beside `tests/test_control_height.py` precedent).
- Dev server: Add session page → Add game (+) → Add-on of + for the stacked
  view; screenshot for the person's spot check before the gate.

## Gotchas

- `offsetTop` in jsdom is 0; geometry is e2e-proven, vitest stubs it.
- `ResizeObserver` absent in jsdom: guard.
- Tailwind needs literal class strings; keep them in Python constants.
- Write `--modal-*` with `px` units.
- Do not stamp anything on the `<dialog>` but covered/over and describedby.
- `make lint-fix` sorts imports; run before commits with `make format`,
  `make format-check`, `make vale`.
