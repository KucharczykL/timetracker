# The form dialog

A link with `data-form-dialog` opens its form page in a modal. Without
scripting, the link is a link. No form page knows about the dialog.

The code is in `ts/elements/form-dialog.ts`, `ts/elements/form-dialog/` and
`common/components/form_dialog.py`.

## Server side

`form_dialog_link(chrome)` gives the attribute. `"header"` shows a title row
with a ×. `"bare"` shows the content only and names the dialog with
`aria-label`. `DropdownLinkItem` accepts `attributes`.

Each page has one `<form-dialog>` beside `<toast-stack>`. It holds a
`<template>` of the chrome. `#main-container` carries `data-page-title`,
`data-read-only` and `tabindex="-1"`. The navbar has `id="navbar"`. A page is
read-only when its route is in `READ_ONLY`.

## Open

A plain primary click opens the dialog. A modifier or middle click stays
native. The host runs one open at a time. The host drops an answer when the
top modal changed.

| Answer | Result |
|---|---|
| Redirect to the host page | Toast only |
| Read-only page elsewhere | Hand off the messages, then go there |
| Page | Present it in a new dialog |
| No page, network failure, module failure | Follow the link |

## Present

The host prefixes every id and every reference to it. The host resolves
`href`, `action` and `formaction` against the answer's URL. A form without
`action` gets that URL. The host imports the module scripts. Classic scripts
do not run. The header shows the page title, and the host removes the
content's `h1`. Focus goes to the first invalid control, else the first
control of the form, else the ×.

## Submit

The host sends a POST form through `fetch`, with its submitter. A dialog
that is submitting refuses dismissal.

| Answer | Result |
|---|---|
| Not redirected, page | Present it in the same dialog |
| No page | Error toast; the dialog stays |
| Redirect to a page that is not read-only | Present it in the same dialog |
| Redirect to a read-only page, alone, the host page | Close, swap the host |
| Redirect to a read-only page, alone, elsewhere | Hand off, go there |
| Redirect to a read-only page, nested | Close the top dialog, toast below |

A redirect marks the host stale. When the last dialog closes and the host is
stale, the host fetches the page again and swaps it. A changed `csrftoken`
cookie causes a reload. A Cancel link to the host page closes its dialog. An
Undo toast posts through `fetch` while a dialog is open. A page answer opens
in a new dialog.

## Swap

The swap replaces the children of `#main-container` and `#navbar`, the page
stamps, the document title and the `data-*` attributes of `<html>`. Then it
sends `form-dialog:swapped`. Focus goes to the opener's twin, else its
`<drop-down>` toggle, else `#main-container`.

Content must wire itself on connect and unwire on disconnect. A lookup by
field name searches its own form first.

## Hand-off

A fetch consumes the session messages. `ts/toast-handoff.ts` keeps them in
`sessionStorage` for the next page. `<toast-stack>` shows them on connect.
