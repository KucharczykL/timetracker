# A stacked modal steps the ones below back and names them

Issue #1514, part of epic #1485.

## Purpose

A modal that opens over another modal must not hide it. Each covered modal
moves up, becomes smaller and darker, and its title shows in a strip above
the modal on top. The modal on top names the modals below it.

## Header

`ModalPanelHeader` (`common/components/modal.py`) is 44 px high: `py-1.5`,
and a `ControlButton(size="compact")` ×. The title stays
`text-type-section`. Above the title is a hidden trail line,
`<p data-modal-trail>`. The header carries `data-modal-header`.

## Panel

`ModalPanel` builds the visible panel with `data-modal-panel`. The form
dialog, its unsaved-changes warning and `BottomSheet` use it. Its classes
read three properties that the layer writes:

- `--modal-reserve`: a top margin, which the form surfaces also subtract
  from their maximum height.
- `--modal-shift` and `--modal-depth`: under `data-modal-depth`, one
  arbitrary `transform` moves the panel up and scales it by `1 - .05·d`.
  The `translate` property stays free for the sheet's slide.
- `--modal-depth`: a `brightness` filter darkens the panel. Opacity is not
  used, because a translucent panel shows the page through it.

## Layer

`markStack` (`ts/elements/modal-stack.ts`) runs at each open, close start
and finish, on window resize, and from a `ResizeObserver` on panels and
headers. `refreshModalStack()` runs it on request; `<form-dialog>` calls
it after each fill. It writes a value only when the value changes, so the
observer cannot loop.

- Only open modals count. A leaving modal keeps its marks.
- A part belongs to a dialog only when it is not inside a nested dialog.
- The depth of a modal is the number of open modals above it.
- The reserve of a panel is the sum of the scaled header heights below it.
- From the top down, each covered panel aims one scaled header height above
  the panel over it. The shift is never positive.
- Values are in `px`. A unitless value voids the transform.

## Trail

Only the top open modal shows its trail: the names of the open modals
below it, bottom first. A name is the `aria-labelledby` text, else
`aria-label`. A visible `›` is `aria-hidden`; a `sr-only` comma is spoken
instead. While the trail shows, its id is in `aria-describedby`: first on
a dialog, last on an `alertdialog`, which must read its message first. A
hidden trail is removed from the description.

`finish` and `resetModalLayerForTests` remove every mark.

## Tests

- vitest `modal-stack.test.ts`: depth, reserve, shift, nested parts, trail
  order, description order, rename on refresh.
- pytest `test_modal_dialog.py`: header, panel classes, built CSS.
- e2e: three sibling modals keep each covered title in its strip; the
  nested Add New Game dialog shows its trail.
