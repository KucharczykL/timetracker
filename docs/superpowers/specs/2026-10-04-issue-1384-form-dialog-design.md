# The form dialog

A link with `data-form-dialog` opens its form page in a modal. Without
scripting, the link is a link. No form page knows about the dialog.

## Server side

`form_dialog_link(chrome)` gives the marker and a busy style. `"header"`
shows a title row with a ×. `"bare"` names the dialog with `aria-label`.
Each page has one `<form-dialog>` with a `<template>` of the chrome.
`#main-container` carries `data-page-title` and `tabindex="-1"`, and
`data-read-only` on a read-only page. The navbar has `id="navbar"`.

## Open

A plain primary click opens. While one link loads, other links stay links.
After 15 seconds, or on any failure, the host hands off the messages and
follows the link.

| Answer | Result |
|---|---|
| Redirect to the host page | Toast only |
| Read-only page | Hand off the messages, then go there |
| Page | Present it in a new dialog |
| No page | Follow the link |

## Present

The host prefixes every id and the references in the attributes
`form_dialog.py` lists. It resolves `href`, `action` and `formaction`
against the answer and imports the module scripts. Focus goes to the first
invalid control, else the first form control, else the ×.

## Submit

The host sends a POST form through `fetch`. A GET form stays native. While
a form submits, no dismissal and no link closes its dialog.

| Answer | Result |
|---|---|
| Not redirected, page | Present it in the same dialog |
| Not redirected, no page | Error toast; the dialog stays |
| Redirect, no page | Go there |
| Redirect to a page that is not read-only | Present it in the same dialog |
| Redirect to a read-only page, alone, the host page | Close, swap the host |
| Redirect to a read-only page, alone, elsewhere | Hand off, go there |
| Redirect to a read-only page, nested | Close the top dialog, toast below |

A form that cannot be read sends nothing. A redirect, a failed request or a
close during a submit marks the host stale. When the last modal closes, a
stale read-only host is fetched again and swapped. A changed `csrftoken`
cookie causes a reload. A link to the host page or to a dialog below closes
its dialog; a fragment link stays native. While a dialog is open, an Undo
posts through `fetch` and its button goes away.

## Swap

The swap replaces the children of `#main-container` and `#navbar`, the page
stamps and the document title, and writes the page-state `data-*`
attributes of `<html>`. The page is busy meanwhile. Then the swap sends
`form-dialog:swapped`. Focus goes to the opener's twin, else its
`<drop-down>` toggle, else `#main-container`.

Content must wire on connect and unwire on disconnect. A lookup by field
name searches its own form first.

## Hand-off

A fetch consumes the session messages. `ts/toast-handoff.ts` keeps them in
`sessionStorage` for one target page, for one minute. `<toast-stack>` shows
them there on connect.
