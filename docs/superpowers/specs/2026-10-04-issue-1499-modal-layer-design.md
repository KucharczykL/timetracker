# One modal layer that nests

Issue #1499, step 2a of the modal epic #1485. After #544, before #1384.

## Problem

The bottom sheet (`ts/elements/sheet-controller.ts`) holds every modal
mechanic: `showModal`, the scroll lock, the Tab boundary, the backdrop press,
the `modal` surface. It is a `<drop-down>` behavior and it refuses to nest:
a module-level `activeSheet` closes any other sheet, the scroll lock is one
snapshot, and `pushSurface` closes every surface whose host does not contain
the new one, a modal included. `<form-dialog>` (#1384) must nest.

## Design

### `ts/elements/modal-layer.ts`

A module, not an element. It knows no form and no fetch.

```text
attachModal(dialog, { host?, initialFocus?, leave?, dismiss?, onClosed? }) → Modal
Modal: open(opener?) → boolean, close(), isOpen(), focusInitial()
isModalOpen(), topModal() → HTMLDialogElement | null
window event "modal-layer:change" on every change of the top modal
```

- The dialog carries `data-modal`. `attachModal` refuses a dialog without
  it. `dialog[data-modal]` in `common/input.css` makes it a surface-less
  viewport hit area: fixed, inset 0, no padding, no border, transparent,
  `overflow: clip`, flex when open. Its content is a child panel, so a press
  on the dialog itself is a press on the backdrop. The dialog carries no
  `transform`, `filter` or `contain`, so a fixed child (the toast region)
  uses the viewport. The sheet's `dialog[data-bottom-sheet]` rules keep only
  the bottom alignment, the backdrop and the slide.
- `host` is the surface host; it defaults to the dialog. The sheet passes its
  `<drop-down>`.
- **The stack** holds the open modals that are not leaving, in opening
  order. `topModal()` is its last.
- `open(opener)` acts only on a closed modal, and not while any modal
  leaves. It records the opener (default `document.activeElement`; the sheet
  passes its toggle, since Safari does not focus a clicked button), takes the
  scroll lock, calls `showModal`, joins the stack, pushes the `modal`
  surface, calls `focusInitial()`, and dispatches the change event.
  `focusInitial()` focuses `initialFocus()`, else
  `[data-modal-initial-focus]`; with neither, the native focusing steps
  stand. A `showModal` that throws releases the lock, leaves the stack,
  reports through `reportClientError` with `{ toast: false }`, and answers
  false. A disconnected host answers false.
- `close()` on a closed modal does nothing. On a leaving one it does nothing
  unless the host is disconnected; then it finishes. Else it closes every
  modal above this one, topmost first, at once. Then it leaves the stack,
  removes the surface (panels inside close before any exit animation) and
  dispatches the change event (toasts leave the dialog before it slides).
  Then it calls `leave(finish)`. `leave` answers true when it will call
  `finish` itself; false, or no `leave`, finishes at once. The `finish` it
  receives is one-shot and bound to this close: once the modal finished,
  or reopened, a late call does nothing. A disconnected host skips `leave`.
- Finish is idempotent. It closes every modal above it still in the stack,
  topmost first; calls `dialog.close()`; leaves the stack; removes the
  surface; releases the scroll lock; returns focus; dispatches the change
  event; calls `onClosed`. `onClosed` runs last, so the sheet's
  close-then-navigate focus wins over the focus return.
- Focus return. The candidate is the opener if it is connected and not
  inside `[hidden]` or `[inert]`. Else it is the own toggle of the first
  `<drop-down>` around the opener, walking outward, whose toggle is not
  inside `[hidden]` or `[inert]`: a menu item that opened a modal sat in a
  panel the modal's push closed. If a modal stays open and the candidate is
  not inside it, the page under it is inert: that modal's `focusInitial()`
  runs instead.
- A native `close` event finishes, unless the dialog is open again (the event
  is queued, so it can arrive after a reopen). Thus a `method="dialog"` form,
  a bare `dialog.close()` and a `cancel` the browser does not let us cancel
  all end in finish, and the modals above close too.
- A dialog removed from the document while open fires no `close`. While any
  modal is open or leaving, one `MutationObserver` (`childList`, `subtree`)
  on the document finishes each modal whose dialog is no longer connected.
  Its callback is a microtask. Limit: a dialog removed and put back in one
  task stays open but not modal; the owning element closes it in its own
  `disconnectedCallback`, as `<drop-down>` does.
- Dismissal: `cancel` (always `preventDefault`), a press that starts and ends
  on the dialog itself with one pointer (a `pointercancel` discards it, so a
  touch scroll that starts on the backdrop closes nothing), and a click on
  `[data-modal-dismiss]`
  call `dismiss()`, which defaults to `close()`. A veto in `dismiss` holds
  only where `cancel` is cancelable.
- Tab boundary: on Tab, only while this dialog is `topModal()`, focus wraps
  among tabbables whose nearest `<dialog>` is this one.
- Every listener acts only on events whose nearest `<dialog>` is its own, so
  a nested dialog in the DOM of another fires no handler of the outer one.

### Scroll lock

One lock for the stack. The first modal takes the snapshot and fixes the
body; the last finish restores it. A leave holds the lock, so the page does
not move behind a sheet that slides out. A modal in between changes nothing.

### Backdrops

Only one backdrop dims, at 70 %. The dimmer is the topmost dialog still
shown, leaving or not. The layer sets `data-modal-covered` on every other
shown dialog. A covered `::backdrop` has opacity 0, with no transition in
either direction. A leaving dialog with a modal below it keeps its backdrop
until finish; the sheet's backdrop fades out only when it is the last
modal. At that finish the one below is uncovered in the same frame. Thus
the dim stays at 70 % through a nested close; only the lower panel goes
from dim to clear. A cross-fade would dip to about 58 % midway. Under
`prefers-reduced-motion` every backdrop change is instant. Checked by eye
in Chromium and Firefox; the user approves the look.

### While the last modal leaves

`isModalOpen()` is false from the start of the last modal's close, but the
dialog stays `:modal` until finish (at most the sheet's 250 ms fallback). In
that window `<toast-stack>` already hosts the toasts and is still inert. This
is accepted: nothing interactive opens during a leave.

### Surface stack

A push never closes a `modal`. A new `panel` or `modal` still closes each
non-modal surface whose host does not contain the new host. Thus a modal
closes only by its own act or by a nested removal. Two sheets opened by code
nest.

Limit: a panel that code opens outside the top modal stays open, inert,
and takes Escape first. No person can open one: the page under a modal is
inert.

### Toast host

`<toast-stack>` keeps its element and its listeners. On each change event it
renders into the top modal: it builds a region, copying `role`,
`aria-label`, `aria-live` and `aria-atomic` off its own element, moves the
toast nodes into it, then appends the region to the dialog. The region of
the dialog below goes.

The region anchors to the top edge, right-aligned, inside the top safe
area. At the bottom corner a toast would cover a bottom sheet's panel on a
phone (a 288 px toast on a 375 px screen), and an error toast stays until
dismissed. With no modal open the corner is unchanged. The class lives in
Python beside `TOAST_STACK_CLASS`, as `TOAST_MODAL_REGION_CLASS`, and
reaches the element as the `modal_region_class` prop beside
`action_class`, so TypeScript holds no class literal. A live region inserted with its
content is usually not announced. With no modal open, the nodes move back
into `<toast-stack>`; that move may announce again, a check for #1335.
While hosted, toast wrappers (tab index 0) join the dialog's Tab boundary;
#1094 inherits this. A press on a toast is not a backdrop press: its target
is the toast. A move fires no `mouseleave`, so a re-host clears each toast's
hover and focus flags. `connectedCallback` reads `topModal()`, for a modal
open before the element connects.

### The bottom sheet

`attachSheet` keeps the slide (`data-sheet-state`, its `leave`), the
close-then-navigate section link (in `onClosed`), the hidden-trigger guard,
`aria-expanded` and `dropdown:show`/`dropdown:hide`. `dropdown:show` now
fires after the layer's change event; its listeners (`section-nav.ts`,
`choice-grid.ts`, `combobox.ts`) read nothing the change moves. It passes
`initialFocus`: the first nav link, else the dismiss control, because the
native steps would pick the header's close button. `activeSheet` and the
snapshot go. `BottomSheet` stamps `data-modal`. `data-sheet-dismiss` becomes `data-modal-dismiss` everywhere:
`BottomSheet`, `tests/test_custom_elements.py`,
`e2e/test_settings_ui_kit_e2e.py`, `section-nav.test.ts` and the sheet tests.

### Test stand-in

jsdom has no `showModal`/`close`. `ts/test-setup/dialog.ts` adds them:
`showModal` returns on a dialog open as a modal, refuses a non-modal open or
a disconnected dialog with `InvalidStateError`, and sets `open`. `close` on
a closed dialog does nothing; else it clears `open` and queues a `close`
event with `setTimeout(0)`, a task as in browsers, which fake timers
control. Like `popover.ts`, it installs only
where `HTMLDialogElement` exists and lacks `showModal`, and it joins
`setupFiles` in `vitest.config.ts`. The sheet tests drop their own stubs,
whose `close` moved focus itself.

## Mobile

- The scroll lock fixes the body, because iOS Safari scrolls under
  `overflow: hidden` alone. One lock for the stack keeps a lower modal from
  restoring the page under a higher one.
- `dialog[data-modal]` is `100dvh` high, so it follows the URL bar.
- Safari does not focus a tapped button, so a caller that opens from a
  click passes its opener; the sheet passes its toggle.
- Android's back gesture raises `cancel` on the top modal: the same path as
  Escape.

- Stacked sheets: the upper slides over the lower, which stays dimmed under
  the one backdrop. A press on the visible part of the lower one lands on
  the upper backdrop and closes the upper one only.

## Measured in Chromium

1. Escape on a focused element in a modal dialog whose keydown calls
   `preventDefault` fires no `cancel`. A hosted toast closes before the modal.
2. Closing a dialog while a modal dialog inside it is open leaves the inner
   one open, `:modal`, with a 0×0 box: an invisible trap. Close-above is
   required. An e2e test pins that no `:modal` remains.
3. Native `close` restores focus to the opener in the dialog below.
4. A `position: fixed` region inside a modal dialog takes presses while
   `<toast-stack>` outside it is inert.
5. Two dialogs opened by code, one nested in the other: each Escape fires a
   cancelable `cancel` on the top one only.

## Tests

- vitest `modal-layer.test.ts`: nest by DOM and by body placement; close
  below closes above in stack order; one scroll lock; focus return to the
  opener and none to a hidden one; dismiss paths act only on the own dialog;
  Tab only on the top modal; leave holds and a disconnect cuts it; a stale
  `close` event or a late `finish` after reopen does nothing; `close` during
  a leave does nothing; `open` while one leaves answers false; focus falls
  back to an outer `<drop-down>` toggle and, under a remaining modal, to its
  initial focus; the observer finishes a removed dialog (async test, one
  `await` for the microtask); change events.
- vitest surface stack: a pushed modal or panel keeps an open modal.
- vitest toast stack: re-hosts on change, back on last close, a new toast
  lands in the top modal, the region wears `modal_region_class`.
- vitest layer: a `pointercancel` between down and up on the backdrop
  closes nothing; `data-modal-covered` marks every shown dialog but the
  topmost shown one, and moves at finish; the scroll lock holds through a
  leave.
- vitest sheet: the existing cases, with three rewritten. "Fully closes a
  sibling sheet" becomes "two sheets nest and the last close restores the
  page style". The failed-open case asserts the report, not `console.error`.
  Focus return comes from the layer, not the stub.
- e2e: real nested dialogs leave no `:modal` and restore scroll and focus; a
  toast raised under the open settings sheet, at a phone viewport, is in
  the dialog, sits above the sheet's panel without overlapping it, and its
  dismiss works.

## Docs

The #544 spec's single-open rule and its toast limit change. CLAUDE.md's
top-layer bullet gains the modal layer.

## Follow-up issues to file

None. A modal that hands back a result is #1501.
