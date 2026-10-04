# Floating surfaces in the top layer

A floating surface is a panel that opens over the page: a menu, a listbox, a
popup or a tooltip. It opens in the browser's top layer, so no ancestor clips
it and no z-index orders it.

The code is in `ts/elements/surface-stack.ts`.

## Markup

The server renders each panel with `popover="manual"` beside `hidden`, which
is the state: a panel's display utility overrides the closed popover's
`display: none`.

A panel class has no `absolute`, no `z-*` and no `isolate`. One rule in
`common/input.css` resets the four popover defaults that the preflight
keeps: `inset`, `overflow`, `color` and `background-color`.

The static calendar in the date facet is not a surface. It has no `popover`
attribute.

## Show and hide

`showInTopLayer(panel)` calls `showPopover()` and then clears `hidden`. It
returns false for a disconnected panel. `hideFromTopLayer(panel)` calls
`hidePopover()` and then sets `hidden`. It accepts a panel that the browser
hid already.

A top-layer panel uses viewport coordinates. `pinFixed` puts a panel at
(0, 0) before a caller measures it.

A panel stays in the top layer when CSS hides its host. Thus code that
hides a host closes its `<drop-down>` first.

## The surface stack

A controller pushes a `Surface` when it opens and removes it when it closes.
A surface has a host, a kind (`panel`, `hint` or `modal`), a `close`, and an
optional `restoreFocus`. A press in the host is a press inside.

- **Single open.** A `panel` or a `modal` closes each surface whose host does
  not contain the new host. A `hint` closes nothing.
- **Nested close.** A removal closes the surfaces in its host first.
- **Escape.** One capture listener on `window` closes the topmost surface. A
  panel calls `restoreFocus` first. The listener marks the key spent. It
  ignores composition and repeat. A `modal` on top keeps its native `cancel`.
- **Outside press.** A `pointerdown` of the primary pointer and button
  records its path. The `pointerup` of the same pointer finds the topmost
  `panel` or `modal` host on that path. It closes each surface above that
  host that the press did not touch. A hint never shields the surfaces below
  it. A `pointercancel` discards the press, so a touch scroll keeps a panel
  open. The stack never closes a `modal` on a press.
- **Failure.** A `close` that throws still leaves the stack.

`attachMenu` pushes a `panel`. A tooltip pushes a `hint`. The bottom sheet
pushes a `modal`.

## Why `manual`

An `auto` popover closes a combobox on a press in its own input, and a
toggle button reopens it after the press closes it. Thus each surface is
`manual`.

## SearchSelect

A SearchSelect lives in `<drop-down behavior="inline-combobox">`, or in a
dialog panel with `panel=True`. When its host closes, the widget resets
`aria-expanded` and the active option.

## Limits

An open panel paints above the toasts. Under a modal dialog a toast is
inert, and the top layer does not change that. The form dialog work (#1384)
puts the toasts in the dialog.
