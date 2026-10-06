# A stacked modal steps the ones below back and names them

Issue #1514, part of epic #1485.

## Purpose

A modal over another must not hide it. Each covered modal moves up,
becomes smaller and darker, and its title shows above the top modal, which
names the modals below it.

## Header

`ModalPanelHeader` (`common/components/modal.py`, `data-modal-header`) is
44 px high while its trail is hidden: `py-1.5` and a compact ×. A hidden
`<p data-modal-trail>` is above the title.

## Panel

`ModalPanel` builds the visible panel with `data-modal-panel`. The form
dialog, its unsaved-changes warning and `BottomSheet` use it. A test
refuses a module that builds a `ModalDialog` without both. The layer writes
four properties; `data-modal-depth` is on a covered panel only:

- `--modal-reserve`: a top margin. The form surfaces also subtract it from
  their maximum height.
- `--modal-shift`: one arbitrary `transform` moves the panel up.
- `--modal-scale`: the same `transform` scales by `1 - .05·d`, computed
  once, in the layer.
- `--modal-depth`: a `brightness` filter, `max(.5, 1 - .15·d)`, darkens the
  panel. Opacity is not used, because a translucent panel shows the page
  through it.

The `translate` property stays free for the sheet's slide, and `translate`
stays in the transition list, because the sheet controller waits on it.

## Layer

`markStack` (`ts/elements/modal-stack.ts`) runs at each open, close start
and finish. A window resize or a `ResizeObserver` entry on a panel or header
schedules it for the next animation frame, once per frame.
`refreshModalStack()` runs it on request; `<form-dialog>` calls it after
each fill. It writes a value only when the value changes. The layer catches
and reports a throw from it, so the layer always settles.

- Only open modals count; a leaving modal keeps its marks.
- A nested dialog's parts are its own.
- The depth of a modal is the number of open modals above it.
- The reserve of a panel is the sum of the scaled header heights below it.
- From the top down, each covered panel aims one scaled header height above
  the panel over it. The shift is never positive.
- Shift and reserve are in `px`; a unitless length voids the transform.
  Depth and scale are bare numbers.

## Trail

Only the top open modal shows its trail: the names of the open modals
below it, bottom first. A name is the `aria-labelledby` text, else
`aria-label`. A modal with no name is reported and left out; with no names
the trail stays hidden. A `"bare"` form dialog has no header, so on top it
shows no trail. A visible `›` is `aria-hidden`; a `sr-only` comma is spoken
instead. While the trail shows, its id is in `aria-describedby`: first on
a dialog, last on an `alertdialog`, which must read its message first. A
hidden trail is removed from the description.

`finish` removes the marks of the modal it closes and marks the rest
again. `resetModalLayerForTests` removes every mark.

Tests: `modal-stack.test.ts`, `test_modal_dialog.py`, and the e2e in
`test_modal_layer_e2e.py`.
