# A form page opens in a modal: `<form-dialog>`

Issue #1384, part of #1485, after #544 and #1499. Builds on the modal layer
(`ts/elements/modal-layer.ts`, `ModalDialog` in `common/components/modal.py`).
The modal epic organizer answered the wave decisions; the person answered
the UI ones.

## Outcome

A link marked `data-form-dialog` opens its target page in a modal dialog on
top of the current page. The dialog presents that page's content, submits
its forms through `fetch`, presents a refusal in place, and on success
closes and refreshes the page underneath. Without scripting the link is a
link. No form page knows about the dialog.

This issue marks no production link. #1385 converts pages; the tests mark
real links in the browser.

## Server side

- `common/components/form_dialog.py` states `FORM_DIALOG_ATTRIBUTE =
  "data-form-dialog"`, `type FormDialogChrome = Literal["header", "bare"]`
  and `form_dialog_link(chrome="header")`, which answers the attribute pair.
  `"header"` is the empty value; `"bare"` opts out of the header row (the
  person asked for a per-link opt-out).
- `DropdownLinkItem` takes `attributes: Attributes = ()`, appended to the
  link's, because row menus are where most marked links live.
- `gen_element_types` writes the attribute and the chrome words into
  `ts/generated/form-dialog.ts`, beside `modal-attributes.ts`; a drift test
  follows `tests/test_modal_dialog.py`.
- `TimetrackerDocument` places one `<form-dialog>` beside `<toast-stack>`,
  outside `#main-container`, and adds it to `collect_media`. It holds a
  `<template>` of the chrome: `ModalDialog` around a panel whose header is
  `ModalPanelHeader` (title plus the × `[data-modal-dismiss]`), extracted
  from `BottomSheet` so both share it.
- `TimetrackerDocument` stamps three layout facts, none of which a form page
  states: `data-page-title` (the raw `title`) and `data-read-only` (present
  when the route is in `READ_ONLY`) on `#main-container`, which also gains
  `tabindex="-1"`; and `id="navbar"` on the `Nav`. The `READ_ONLY` test is
  the one `navbar_origin` already makes, computed once. `games:index` (a
  redirect) and the settings export (a download) are members that never
  answer a page; the login route is outside it by construction.

## Vocabulary

- **Answer**: a fetched page, read at its final URL after redirects.
- **Host page**: `location`. URLs compare normalized: path plus sorted
  query, hash dropped.
- **Read-only answer**: its `#main-container` carries `data-read-only`.
  Only a read-only page may be an origin, so a write never returns to a
  form.
- **Alone**: the layer's stack holds only this dialog. The layer exports
  `openModals(): readonly HTMLDialogElement[]` for this. A dialog opened
  from another dialog, or from a `BottomSheet`, is not alone.

## Open

A primary click without modifier on `a[data-form-dialog]` is prevented; a
modifier or middle click stays native. The listener is on `document`, so a
marked link inside an open dialog opens a dialog on top. The host runs one
open at a time and ignores clicks meanwhile; the link carries `aria-busy`.
The open is dropped if the top modal changed before the answer arrives.
The host records the link at click time and passes it to `open(link)`: the
click closed the row menu, so the active element is `body` by then.

The open fetches `link.href` and routes the answer:

- Redirected to the host page: toast its messages; open nothing.
- Read-only answer elsewhere: hand off its messages and
  `location.assign` the answer's URL. The fetch consumed them; a second
  GET would find none.
- Otherwise, with a `#main-container`: present it in a new dialog.
- No `#main-container`, a network failure, or a failed `import()`:
  `location.assign(link.href)`.

A new dialog is the template stamped and appended to the host, then
mounted with `attachModal`. If `open()` answers false, the dialog is
removed and reported. `onClosed` removes it.

## Presenting an answer

Applied to the parsed fragment, in this order, before insertion:

1. Ids. Every id gets the dialog's prefix `form-dialog-<n>-`, including
   inside `template.content`, recursively, and including the chrome's own.
   Every reference is rewritten: `list`, `form`, `popovertarget`,
   `aria-activedescendant` and `href="#…"` whole; `for`, `headers`,
   `aria-labelledby`, `aria-describedby`, `aria-controls`, `aria-owns`,
   `aria-flowto`, `aria-errormessage` and `aria-details` token by token,
   because they hold lists (`UnsetField` and the settings kit build them).
   The components use `for`, `aria-controls`, `aria-labelledby`,
   `aria-describedby` and `href="#…"`; no `data-*` attribute holds an id. `randomid()`
   hashes content, so one component on two pages carries one id twice.
   Props name sibling fields by form field name, and runtime ids come from
   counters.
2. URLs. A form without `action` gets the answer's URL. Every `href`,
   `action` and `formaction` read by `getAttribute` is resolved against the
   answer's URL; `DOMParser` resolves against the host.
3. Modules. Each `script[type=module][src]` in the answer is `import()`ed;
   one the host loaded resolves to its instance. Classic scripts do not
   run. Page glue imported this way runs once against the host document
   (`ts/add_game.ts` logs a missing `#add-form`): #1385's Add game slice
   turns it into an element.
4. Chrome. Header chrome titles the dialog from `data-page-title` and drops
   a content `h1` (`ConfirmPage`'s `DialogTitle` states the same title).
   Bare chrome keeps the content whole; `aria-label` reads
   `data-page-title`.

Then: insert into the panel body, focus the first `[aria-invalid=true]`
control, else the first tabbable control of the first form, else the ×,
and dispatch the answer's `#django-messages` as one `show-toast`.

Three lookups by field name become scoped to the element's form, else the
document: `date-time-field` (zone row, copy control) and `temporal-field`
(copy control). Two forms on one document otherwise answer each other.

## Submit

A `submit` on a `method=post` form inside a dialog's body is prevented. The
toast region the stack appends to the dialog is outside the body. The body
is `new FormData(form, event.submitter)`, so a named submitter travels. The
target is `submitter.formAction`, else `form.action`; the method
`submitter.formMethod`, else `form.method`.
While it runs the form carries `aria-busy`, a second submit is ignored and
`dismiss` is vetoed. The answer of a dialog that closed meanwhile is
dropped. A GET form navigates the window.

Routing the answer:

- Not redirected, with a `#main-container` (200 invalid, 409 refused, 500
  defect): present it in the same dialog.
- No `#main-container` (a Django 404, 403 or 500 page, a proxy error): the
  dialog stays; an error toast names the status and a report id.
- Redirected to a page that is not read-only: present it in the same
  dialog. "Submit & Add to library" continues in the dialog, as the issue
  asks. A login page is not read-only, so an expired session signs in
  inside the dialog.
- Redirected to a read-only page, alone: if it is the host page, close the
  dialog, then in `onClosed` swap the host page from this answer and toast
  its messages. Else hand off the messages and `location.assign` it.
- Redirected to a read-only page, not alone: close this dialog only and
  toast its messages in the modal below. Nothing below changes: a form
  below holds unsaved input. Getting a new row into it is #1501.

A link inside a dialog whose target equals the host page closes the dialog
(Cancel).

### A chain that wrote

A redirected submit answer has changed server state, even when the chain
continues in the dialog (Add game, then its copy). The host marks the
stack dirty. When the bottom dialog closes by any path (Cancel, Escape, ×,
backdrop) while dirty, the host GETs the host page and swaps from it. A
sign-in inside a dialog rotates the CSRF token, which every server-rendered
form on the host still carries: when the `csrftoken` cookie differs from
the one read at load, the host reloads the page instead of swapping.

## Undo inside a dialog

A toast's Undo is a POST form. While a form dialog is open, the host
fetches it instead of letting it navigate. A redirected answer toasts its
messages and marks the stack dirty; nothing else changes. A page answer
(a batch Undo larger than one chunk renders its waypoint) opens in a
dialog on top. Its `<continuing-batch>` calls `requestSubmit`, so the rest
of the batch posts through that dialog, and its final redirect closes it
as any nested write does.

## Message hand-off

A `location.assign` loads a page whose GET finds the messages consumed by
the `fetch`. The host writes the payloads to `sessionStorage` under one
key; `<toast-stack>` reads and clears it on connect beside
`#django-messages`. Storage that throws loses the toast and is reported.

## Swap

The issue asked for `<refreshing-section>`'s move. Most pages hold no
section, and the navbar's playtime figures change on a Log, so the swap
takes the whole: the children of `#main-container` and `#navbar`,
`data-page-title`, `data-read-only`, `document.title`, and the `data-*`
attributes of `<html>`. The host then dispatches `form-dialog:swapped` on
`document`; the library conversion coordinator, which read its state once
at load, reads it again. The answer's
modules are imported first. `<toast-stack>`, `<form-dialog>` and its
dialogs sit outside both. The result equals a reload: an unsaved filter
edit is lost, and a selection comes back from `sessionStorage` as it does
on a reload.

The layer returns focus before `onClosed`, to an opener the swap then
removes, so this step always runs. Focus moves after the swap: to the
element with the opener's id, else the
first with its `href`; when that is unreachable, to its `<drop-down>`
toggle (the layer's `focusReturnTarget`, exported); else
`#main-container`.

Swapped content must wire itself on connect and unwire on disconnect:

- `search-field`'s Enter handler moves from `onReady` into the element.
- `temporal-field`'s document listener and `catalog-editor`'s `pageshow`
  listener are removed on disconnect.

## Presentation

Centred at every width; the person chose against a phone sheet. The panel
is the viewport less a 16px gutter on phones and as wide as the content's
own max width above; its body scrolls under the header. The classes are
settled on the dev server with the person.

## Tests

- vitest, `ts/elements/form-dialog.test.ts`: click filtering; every open
  and submit routing branch; id rewrite incl. templates and `#` hrefs; the
  stamped `action`; scoped lookups; races (busy open, dropped answer,
  refused `open()`); Undo fetch and its waypoint; hand-off; the dirty
  close; the CSRF reload; focus after swap.
- e2e, each marking a real link with `setAttribute` first: Edit device from the Devices row menu (swap shows the new name,
  focus on the menu toggle); an invalid submit stays in the dialog; a
  refused `form_page` act toasts inside the dialog; two nested dialogs and
  Escape closes the top; Add game's "Submit & Add to library" continues in
  the dialog; scripting off follows the link.
- pytest: the host renders on every page, the three stamps,
  `DropdownLinkItem` attributes, codegen drift.

## Follow-up issues to file

None new: `add_game.ts` is recorded in #1385; a close result is #1501.
