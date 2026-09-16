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

`ts/client-errors.ts` records a gap that does not exist: it says a toast
raised in a custom element's `connectedCallback` on first load is lost,
because the store's listener attaches on `alpine:init`, later. Alpine is a
deferred head script and starts in a microtask after it evaluates, ahead of
every body-end module, so the listener already stands before any element
connects. The comment states the real order instead: head modules, then
Alpine, then the body modules.

## The element

`<toast-stack>` is a light-DOM custom element with no props. Its Python
builder `ToastStack()` in `common/components/toast.py` comes from
`custom_element_builder("toast-stack")`, which attaches the element's module
as its `Media`. It renders the empty tag with `role="region"`,
`aria-label="Notifications"`, `aria-atomic="true"` and the fixed corner
classes the container has today, and no `tabindex`: an e2e test selects the
one focusable region on the page and must not find this one.
`ToastStackProps` is an empty `TypedDict`, registered so the codegen states
the contract, and `common/components/__init__.py` imports the module, because
the codegen command imports only the package.

`common/layout.py` builds one before it sums the media and places it at the
end of the body where the string was. Its media goes ahead of everything the
layout collects: `collect_media(toast_container) + collect_media(content) +
collect_media(navbar) + ...`. `Media` keeps the first order it sees, so the
stack's module is the first body module the page runs; the element is parsed
by then and upgrades at once, ahead of every element the content holds.
`dist/toast.js` stays in the head, ahead of the body modules, and
`dist/library-conversion-status.js`, which toasts as it evaluates, stays
after the collected ones.

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

The element renders the store, and the store calls the element's `render()`
after every mutation, the timer callbacks included, because Alpine's
reactivity leaves with it. The element attaches its `window` listeners for
`show-toast`, one payload or a list, and for `remove-toast` in
`connectedCallback` and removes them in `disconnectedCallback`; it reads the
`django-messages` script once on connect, and a parse failure goes through
`reportClientError` with the toast suppressed, as today. It builds each
toast's DOM with `document.createElement`: the wrapper with `tabindex="0"`,
the bare type class, `role` `alert` for `error` and `warning` and `status`
otherwise, `aria-live` `assertive` for `error` and `polite` otherwise; the
panel; the type's icon, five inline SVG paths kept as constants; the text in
an element of its own, which is what the e2e reads find; the close button.
Every class string the template holds today moves over whole, so Tailwind's
scan of `ts/` finds each literal and the tokens stay the ones the design
conventions name. The `console.log` lines go.

A click on the toast dismisses it, a click on the close button dismisses it
without bubbling, Escape dismisses it, `mouseenter` pauses its timer and
`mouseleave` resumes it. The leave transition is the one Alpine ran: the
leave classes on dismiss, removal 300 ms later. The template declares an
enter transition too, but Alpine's `x-show` skips the first toggle, so no
toast has ever run it; the element declares none, and nothing moves that did
not move before.

`ts/toast.ts` keeps what is not the store: `window.toast`,
`window.removeToast`, `window.dispatchHtmxTriggers` and
`window.fetchWithHtmxTriggers`. `window.removeToast` dispatches `remove-toast`
on `window` always; the Alpine branch goes. The `alpine:init` listener and
the `Alpine.data("toastStore")` registration go. Alpine and its mask plugin
stay loaded for three `x-mask` inputs in the game and settings forms; the two
domain selectors CLAUDE.md names left Alpine already. Retiring Alpine is a
follow-up, filed apart.

## What does not change

`window.toast(message, type, options)`. The `show-toast`, `remove-toast` and
`toast-dismissed` events and their details. The `django-messages` script and
the `HX-Trigger` header. `ts/htmx-redirect-toast.ts`. Every caller:
`library-conversion-status.ts` keeps its stable id and its
`toast-dismissed` listener. The classes, the icons, the colours, the corner.

## Verification

- `ts/elements/toast-stack.test.ts` in jsdom, on the pattern of
  `copy-control.test.ts`: each case connects one `<toast-stack>` and
  disconnects it after. The three lifecycle cases `ts/toast.test.ts` holds
  today, run against the element rather than a stubbed Alpine store, the
  stable-id removal through `window.removeToast` included; a `show-toast`
  list; the `django-messages` script read on connect; the DOM of one toast of
  each type carries its `role` and `aria-live`; the close button's click does
  not reach the wrapper. Fake timers only; no animation frame is awaited.
- `ts/toast.test.ts` keeps the two `fetchWithHtmxTriggers` cases.
- `tests/test_rendered_pages.py` asserts `<toast-stack` where it asserts
  `toastStore()` now.
- The comment in `ts/client-errors.ts` states the load order; the one in
  `e2e/test_filter_builder_e2e.py` names the element, not Alpine.
- The docs sweep: CLAUDE.md's frontend and Alpine paragraphs and
  `docs/settings-panel-epic.md` stop describing the Alpine store.
- The existing e2e toast reads, the settings kit's and the filter builder's,
  pass unchanged.
- `make check`.

## Filed apart

- Retiring Alpine: three `x-mask` inputs are all that remain.
