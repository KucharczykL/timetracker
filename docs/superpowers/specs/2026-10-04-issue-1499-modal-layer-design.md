# The modal layer

The modal layer is `ts/elements/modal-layer.ts`. It is a module, not an
element. It knows no form and no fetch.

## Interface

```text
attachModal(dialog, { host?, initialFocus?, leave?, dismiss?, onClosed? }) → Modal
Modal: open(opener?) → boolean, close(), isOpen(), state() → "closed" | "open" | "leaving", focusInitial()
isModalOpen(), topModal(), isReachable(element)
window event "modal-layer:change" when the top modal changes
```

`ModalDialog` (`common/components/modal.py`) makes the dialog: `data-modal`
and the layer's classes together. The dialog is a transparent viewport hit
area, so a press on it is a press on the backdrop. The host must contain the
dialog. `MODAL_ATTRIBUTES` names each attribute once; the codegen writes it
to `ts/generated/modal-attributes.ts`.

## The stack

Modals nest. The stack holds the open modals in opening order.

- `open` takes the scroll lock, calls `showModal`, pushes a `modal` surface
  and focuses `initialFocus()`, else the dialog's own
  `[data-modal-initial-focus]`. The opener defaults to the active element.
  It answers false while a modal leaves, and false with a report for a
  detached dialog or host, an `InvalidStateError`, or a dialog left closed.
  Other errors propagate.
- `close` first closes each modal above, topmost first, with no leave. Then
  the modal stops being the top modal and calls `leave(finish)`. `finish` is
  idempotent. A leave that throws, or runs past one second, is reported and
  finished.
- Finish closes the dialog, releases the lock after the last modal, returns
  focus and calls `onClosed`. A native `close` event and a removal from the
  document finish too.

Focus returns to the opener. If the opener is gone, hidden, inert or in a
closed dialog, it returns to the nearest reachable `<drop-down>` toggle.
Under a remaining modal, a target outside it yields to its initial element.

## Dismissal

Escape (`cancel`), a backdrop press and a click on `[data-modal-dismiss]`
call `dismiss`; the default is `close`. `dismiss` is best effort: the
browser may close the dialog anyway, and Chrome can close several modals
that code opened with one Escape. `onClosed` always runs. A hook that
throws is reported; a throwing `dismiss` closes the modal.

## Backdrops

Only the topmost shown dialog dims, at 70 %. A leaving dialog keeps the dim
until its finish. The layer stamps `data-modal-covered` and
`data-modal-over`, so only the first open and the last close change the
dim. A backdrop transition applies only to a closing state.

## Toasts

`<toast-stack>` moves its toasts into a region at the top edge of the top
modal, and mutes its own live region meanwhile. When the last close starts,
they move back. A region removed with the modal's content is rebuilt and
reported.

## Presentation

`ModalDialog` centres a modal at all widths. A bottom sheet is an opt-in for
each modal: `BottomSheet` and `<drop-down behavior="sheet">` add the bottom
alignment and the slide.
