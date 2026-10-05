# The form dialog

A link with `data-form-dialog` opens its form page in a modal. Without
scripting, the link is a link. No form page knows about the dialog.

The code is in `ts/elements/form-dialog.ts`, `ts/elements/form-dialog/` and
`common/components/form_dialog.py`.

## Server side

`form_dialog_link(chrome)` gives the marker and a busy style. `"header"`
shows a title row with a ×. `"bare"` names the dialog with `aria-label`.
`DropdownLinkItem` accepts `attributes`.

Each page has one `<form-dialog>` with a `<template>` of the chrome.
`#main-container` carries `data-page-title`, `data-read-only` and
`tabindex="-1"`. The navbar has `id="navbar"`.

## Open

A plain primary click opens. The host runs one open at a time. After 15
seconds, or on any failure, the host follows the link.

| Answer | Result |
|---|---|
| Redirect to the host page | Toast only |
| Read-only page | Hand off the messages, then go there |
| Page | Present it in a new dialog |
| No page | Follow the link |

## Present

The host prefixes every id and the references in the attributes
`rewrite.ts` lists. It resolves `href`, `action` and `formaction` against
the answer. It imports the module scripts and reports a classic script it
cannot load. Focus goes to the first invalid control, else the first form
control, else the × (a bare dialog has none).

## Submit

The host sends a POST form through `fetch`, with its submitter. A GET form
stays native. While a form submits, no dismissal and no link closes its
dialog.

| Answer | Result |
|---|---|
| Not redirected, page | Present it in the same dialog |
| Not redirected, no page | Error toast; the dialog stays |
| Redirect, no page | Go there |
| Redirect to a page that is not read-only | Present it in the same dialog |
| Redirect to a read-only page, alone, the host page | Close, swap the host |
| Redirect to a read-only page, alone, elsewhere | Hand off, go there |
| Redirect to a read-only page, nested | Close the top dialog, toast below |

A redirect, a failed request or a close during a submit marks the host
stale. A failed request says the save is unconfirmed. When the last modal
closes and the host is stale, the host fetches it again and swaps it. A
changed `csrftoken` cookie causes a reload. A link to the host page closes
its dialog. While a dialog is open, an Undo posts through `fetch`; an Undo
answered with a page opens it in a new dialog.

## Swap

The swap replaces the children of `#main-container` and `#navbar`, the page
stamps and the document title. It writes the `<html>` `data-*` attributes
the answer states. Then it sends `form-dialog:swapped`. Focus goes to the
opener's twin, else its `<drop-down>` toggle, else `#main-container`.

Content must wire on connect and unwire on disconnect. A lookup by field
name searches its own form first.

## Hand-off

A fetch consumes the session messages. `ts/toast-handoff.ts` keeps them in
`sessionStorage` for the next page. `<toast-stack>` shows them on connect.
