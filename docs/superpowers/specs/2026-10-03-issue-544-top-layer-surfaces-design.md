# Floating surfaces in the top layer

A floating surface is a panel that opens over the page: a dropdown menu, a
listbox, a combobox panel, a calendar popup, a year popup, or a tooltip. Each
one opens in the browser's top layer. No ancestor clips it, and no z-index
orders it.

The code is in `ts/elements/surface-stack.ts`.

## Markup

The server renders each panel with `popover="manual"` beside `hidden`. The
`hidden` attribute is the state. A panel class sets a display utility, and
that utility overrides the closed-popover `display: none` of the browser.
Thus only `hidden` hides a closed panel.

A panel class has no `absolute`, no `z-*` and no `isolate`. One rule in
`common/input.css` removes the browser's popover defaults: `inset`,
`overflow`, `color` and `background-color`.

The static calendar in the date facet is not a surface. It has no `popover`
attribute.

## Show and hide

`showInTopLayer(panel)` calls `showPopover()` and then clears `hidden`. It
returns false for a disconnected panel. `hideFromTopLayer(panel)` calls
`hidePopover()` and then sets `hidden`. It accepts a panel that the browser
hid already.

A top-layer panel uses viewport coordinates. `pinFixed` puts a panel at
(0, 0) before a caller measures it.

## The surface stack

A controller pushes a `Surface` when it opens and removes it when it closes.
A surface has a host, a kind (`panel`, `hint` or `modal`), a `close`, and an
optional `restoreFocus`. A press in the host is a press inside.

- **Single open.** A `panel` or a `modal` closes each surface whose host does
  not contain the new host. A `hint` closes nothing.
- **Nested close.** A removal closes the surfaces in its host first.
- **Escape.** One capture listener on `window` closes the topmost surface. It
  calls `restoreFocus` first, and then it marks the key spent. It ignores
  composition and repeat. A `modal` on top keeps its native `cancel`.
- **Outside press.** A primary `pointerdown` records its path. The
  `pointerup` of the same pointer closes each surface above the topmost host
  on that path. A `pointercancel` discards the press, so a touch scroll keeps
  a panel open. The stack never closes a `modal` on a press.

`attachMenu` pushes a `panel`. A tooltip pushes a `hint`. The bottom sheet
pushes a `modal`.

## Why `manual`

The browser's `auto` popover closes a combobox when the person presses its
own input. It also races a toggle button: the press closes the panel, and the
click opens it again. Thus each surface is `manual`, and the stack does the
dismissal.

## SearchSelect

A SearchSelect lives in `<drop-down behavior="inline-combobox">`, or in a
dialog panel with `panel=True`. When its host closes, the widget resets
`aria-expanded` and the active option.

## Limits

An open panel paints above the toasts. A toast under a modal dialog stays
inert in the top layer too. The form dialog work (#1384) puts the toasts in
the dialog.
