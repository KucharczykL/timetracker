# The toast stack

Issue [#1089](https://github.com/KucharczykL/timetracker/issues/1089). The
code is in `ts/elements/toast-stack.ts`, `ts/toast.ts` and
`common/components/toast.py`.

## The element

`<toast-stack>` is a light-DOM custom element with no props. `ToastStack()`
in `common/components/toast.py` renders the empty tag with `role="region"`,
`aria-label="Notifications"`, `aria-live="polite"`, `aria-atomic="false"` and
the fixed corner classes, and no `tabindex`: one e2e test selects the one
focusable region on the page. The container is the live region, so a toast
inserted and filled in one task is still announced; a toast carries its
`role` only. `custom_element_builder` attaches the element's module as its
`Media`. `common/components/__init__.py` imports the module, because the
codegen command imports only the package.

`common/layout.py` builds one before it sums the media and places it at the
end of the body. Its media goes first: `collect_media(toast_container) +
collect_media(content) + ...`. `Media` keeps the first order it sees, so the
stack's module is the first body module the page runs, and the element, parsed
by then, upgrades ahead of every element the content holds. `dist/toast.js`
is a head module; `dist/library-conversion-status.js`, which toasts as it
evaluates, comes after the collected ones.

## The store

`ts/elements/toast-stack.ts` holds `ToastStore`: a read-only `toasts`,
`addToast(message, type, options)`, `dismissToast(id, notify)`,
`removeToast(id)`, `clearToastTimer(id)`, `resumeToastTimer(id)`. A `Toast`
holds one `countdown`, `sticky`, `paused` with its remaining time, or
`running` with its deadline and timer, and one `leaving` handle, null while
the toast shows; no field pair can disagree. The rules: five types, `info`
for a word it does not know; a duration of 5 s, 3 s for `debug`, none for
`error`, `null` for no timer; at most three toasts, the oldest leaving first;
a stable string id replacing its toast in place and clearing the old timer; a
dismiss that stops the countdown, fires `toast-dismissed` on `window` when a
person did it, and removes the toast after 300 ms, a second dismiss meanwhile
doing nothing; a paused timer that keeps its remaining time. The store calls
the element's `render()` after every mutation the DOM shows.

The element attaches its `window` listeners for `show-toast`, one payload or
a list, and for `remove-toast` in `connectedCallback` and removes them in
`disconnectedCallback`; it reads the `django-messages` script once on
connect. A parse failure, and a payload with no `message`, go through
`reportClientError` with the toast off, and the other payloads still show.
It builds each toast with `document.createElement`: the wrapper with
`tabindex="0"`, the type's class, `role` `alert` for `error` and `warning` and
`status` otherwise; the panel; the type's icon, five inline SVG paths; the text in an
element of its own; the close button. Every class string is one literal, so
Tailwind's scan of `ts/` finds it.

A click on the toast dismisses it, a click on the close button dismisses it
without bubbling, Escape dismisses it, `mouseenter` pauses its timer and
`mouseleave` resumes it. The leave transition is the leave classes on
dismiss and removal 300 ms later. There is no enter transition.

`ts/toast.ts` keeps what is not the store: `window.toast`,
`window.removeToast`, `window.dispatchHtmxTriggers` and
`window.fetchWithHtmxTriggers`. `window.removeToast` dispatches `remove-toast`
on `window`. Alpine and its mask plugin stay loaded for three `x-mask` inputs
in the game and settings forms
([#1095](https://github.com/KucharczykL/timetracker/issues/1095)).

## Load order

Alpine is a deferred head script and starts in a microtask after it
evaluates, ahead of every body module. The order is: head modules, then
Alpine, then the body modules, the stack's first. A toast raised in a
content element's `connectedCallback` is never lost.

## Verification

- `ts/elements/toast-stack.test.ts` in jsdom: each case connects one
  `<toast-stack>` and disconnects it after. Types and roles, the sticky
  error, the cap of three, stable ids through `window.removeToast`, pause and
  resume, the three dismiss paths and the second dismiss, a payload with no
  message, the `django-messages` script, detach. Fake timers only.
- `ts/toast.test.ts` holds the two `fetchWithHtmxTriggers` cases.
- `tests/test_rendered_pages.py` asserts `<toast-stack` on every page.
