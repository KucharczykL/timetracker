# The modal layer

The modal layer is `ts/elements/modal-layer.ts`. It is a module, not an
element. It knows no form and no fetch.

## Interface

```text
attachModal(dialog, { host?, initialFocus?, leave?, dismiss?, onClosed? }) → Modal
Modal: open(opener?) → boolean, close(), isOpen(), focusInitial()
isModalOpen(), topModal()
window event "modal-layer:change" when the top modal changes
```

The dialog must have `data-modal`. Its CSS makes it a transparent viewport
hit area. Its child panel is the visible surface. Thus a press on the dialog
itself is a press on the backdrop. The dialog has no `transform`, `filter` or
`contain`.

## The stack

Modals nest. The stack holds the open modals in opening order.

- `open` acts only on a closed modal, and not while a modal leaves. It takes
  the scroll lock, calls `showModal`, pushes a `modal` surface and focuses
  the initial element.
- `close` first closes each modal above, topmost first, with no leave. Then
  the modal leaves the stack and calls `leave(finish)`. A `finish` from an
  earlier close does nothing.
- Finish closes the dialog, releases the lock after the last modal, returns
  focus and then calls `onClosed`.
- A native `close` event finishes the modal. A dialog removed from the
  document finishes too.

Focus returns to the opener. If the opener is hidden or inert, it returns to
the toggle of the nearest `<drop-down>` around it. Under a remaining modal,
that modal gets the focus.

## Dismissal

Escape (`cancel`), a press that starts and ends on the backdrop, and a click
on `[data-modal-dismiss]` call `dismiss`. Its default is `close`. Each
listener acts only on its own dialog. Tab wraps only in the top modal.

## Backdrops

Only the topmost shown dialog dims, at 70 %. A leaving dialog keeps the dim
until its finish. The layer sets `data-modal-covered` on each other shown
dialog and `data-modal-over` on each dialog above another. Thus only the
first open and the last close change the dim. A backdrop transition applies
only to a closing state.

## Toasts

`<toast-stack>` moves its toasts into a region in the top modal. The region
is at the top edge, so a bottom sheet does not cover it. The class is
`TOAST_MODAL_REGION_CLASS` in Python. After the last close the toasts move
back. While the last modal leaves, the toasts are inert.

## Presentation

The layer centres a modal at all widths. A bottom sheet is an opt-in for
each modal: `BottomSheet` and `<drop-down behavior="sheet">` add the bottom
alignment and the slide. No width changes a modal into a sheet.

## Tests

jsdom has no `showModal` and no `close`. `ts/test-setup/dialog.ts` adds
them. Its `close` sends the `close` event in a later task.
