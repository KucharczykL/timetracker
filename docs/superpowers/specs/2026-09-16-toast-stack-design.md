# The toast stack is a custom element

Issue [#1089](https://github.com/KucharczykL/timetracker/issues/1089), the
first member of the stack that delivers
[#695](https://github.com/KucharczykL/timetracker/issues/695). The code is in
`ts/elements/toast-stack.ts`, `ts/toast.ts`, `common/components/toast.py` and
`common/layout.py`.

## Why

The toasts are the one screen the layout still draws from a raw HTML string:
`_TOAST_CONTAINER` in `common/layout.py`, an Alpine `x-for` template a
hundred lines long, bound to an Alpine store `ts/toast.ts` registers on
`alpine:init`. #695 adds a form to every toast. Adding it to that string
would grow the one exception to the component rule; the rule says new
behaviour is a custom element. This member moves the toasts there first and
changes nothing a person sees.

The move also closes a gap `ts/client-errors.ts` records: a toast raised
during a custom element's `connectedCallback` on first load was lost, because
the store's listener attached on `alpine:init`, later. The stack's listener
attaches when its module runs, and its module runs first.

## The element

`<toast-stack>` is a light-DOM custom element with no props. Its Python
builder `ToastStack()` in `common/components/toast.py` renders the empty tag
with `role="region"` and `aria-label="Notifications"`, the fixed corner
classes the container has today, and declares
`Media(js=("dist/elements/toast-stack.js",))`. `ToastStackProps` is an empty
`TypedDict`, registered so the codegen states the contract.

`common/layout.py` places one at the end of the body where the string was,
and puts its media ahead of everything it collects:
`collect_media(toast_container) + collect_media(content) +
collect_media(navbar) + ...`. `Media` keeps the first order it sees, so the
stack's module is the first element module the page runs and its listener
stands before any other element connects. `dist/toast.js` stays in the head
and stays first of all.

## The store

`ts/elements/toast-stack.ts` holds the store as a module-level object with
the shape the Alpine store has today: `toasts`, `addToast(message, type,
options)`, `dismissToast(id, notify)`, `removeToast(id)`,
`clearToastTimer(id)`, `resumeToastTimer(id)`, `startToastTimer(toast)`. The
rules do not move: five types with `info` the default for a word it does not
know; a duration of 5 s, 3 s for `debug`, none for `error`, `null` for no
timer; at most three toasts, the oldest leaving first; a stable string id
replacing its toast in place and clearing the old timer; a dismiss that hides
the toast, fires `toast-dismissed` on `window` when a person did it, and
removes it after 300 ms; a paused timer that keeps its remaining time.

The element renders the store. It listens on `window` for `show-toast`, one
payload or a list, and for `remove-toast`; it reads the `django-messages`
script once in `connectedCallback`. It builds each toast's DOM with
`document.createElement`: the wrapper with `tabindex="0"`, `role` `alert`
for `error` and `warning` and `status` otherwise, `aria-live` `assertive`
for `error` and `polite` otherwise; the panel; the type's icon, five inline
SVG paths kept as constants; the text; the close button. Every class string
the template holds today moves over whole, so Tailwind's scan of `ts/` finds
each literal and the tokens stay the ones the design conventions name.

A click on the toast dismisses it, a click on the close button dismisses it
without bubbling, Escape dismisses it, `mouseenter` pauses its timer and
`mouseleave` resumes it. Enter and leave transitions are the classes Alpine
applied, toggled by the element: enter-start on insertion, enter-end on the
next frame, leave on dismiss, removal 300 ms later as today.

`ts/toast.ts` keeps what is not the store: `window.toast`,
`window.removeToast`, `window.dispatchHtmxTriggers` and
`window.fetchWithHtmxTriggers`. `window.removeToast` dispatches `remove-toast`
on `window` always; the Alpine branch goes. The `alpine:init` listener and
the `Alpine.data("toastStore")` registration go. Alpine itself stays loaded
for the two domain selectors that still use it.

## What does not change

`window.toast(message, type, options)`. The `show-toast`, `remove-toast` and
`toast-dismissed` events and their details. The `django-messages` script and
the `HX-Trigger` header. `ts/htmx-redirect-toast.ts`. Every caller:
`library-conversion-status.ts` keeps its stable id and its
`toast-dismissed` listener. The classes, the icons, the colours, the corner.

## Verification

- `ts/elements/toast-stack.test.ts` in jsdom: the three lifecycle cases
  `ts/toast.test.ts` holds today, run against the element rather than a
  stubbed Alpine store; a `show-toast` list; the `django-messages` script
  read on connect; the DOM of one toast of each type carries its `role` and
  `aria-live`; the close button's click does not reach the wrapper.
- `ts/toast.test.ts` keeps the two `fetchWithHtmxTriggers` cases.
- `tests/test_rendered_pages.py` asserts `<toast-stack` where it asserts
  `toastStore()` now.
- The comment in `ts/client-errors.ts` and the one in
  `e2e/test_filter_builder_e2e.py` name the element, not Alpine.
- The existing e2e toast reads, the settings kit's and the filter builder's,
  pass unchanged.
- `make check`.
