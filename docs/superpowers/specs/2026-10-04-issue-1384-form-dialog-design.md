# The form dialog

A link with `data-form-dialog` opens its form page in a modal
(`form_dialog_link()`; `"bare"` drops the header). Views know nothing of
the dialog. URLs are equal when origin, path and sorted query match.

## Request and answers

Every dialog fetch sends `X-Form-Dialog: 1`. The answer kinds are
`TypedDict`s in `common/components/form_dialog.py`.

| `kind` | Fields | Sent by |
|---|---|---|
| `page` | `title`, `html`, `modules`, `messages` | `render_page()` |
| `done` | `url`, `messages` | `FormDialogResultMiddleware` |
| `created` | `done`'s, and `option` | A redirect tagged by `created_row()` |
| `continue` | `url` | `FormDialogResultMiddleware` |

- `page` holds the content alone, under the view's status.
  `render_page()` refuses a `js_external` script.
- The middleware reads a redirect's `Location`. A `READ_ONLY` route gives
  `done` with the message queue. Any other target on this origin gives
  `continue` and keeps the queue. Another origin passes through.
- `done` means finished, not saved.
- `created` hands a row to the opening picker. See
  [A dialog hands a created row to its picker](2026-10-05-issue-1501-dialog-created-design.md).
- Dialog answers carry `Cache-Control: no-store`.
  `ToastMessagesMiddleware` skips dialog requests.

## Open

| Answer | Result |
|---|---|
| `page` | Present it in a new dialog |
| `done` | Show its messages; with none, go to `url` |
| `continue` | Fetch its `url`; a sixth follows the link |
| No kind, failure, 15 s | Follow the link |

A host without `data-read-only` stays and shows an error toast.

Presenting drops every script but data scripts, imports `modules`,
prefixes ids, and resolves URLs against the answer's URL. Focus goes to
the first invalid control, else the form's first control, else the ×.

A link back to the host or a lower dialog closes every dialog above that
page. A fragment link stays native. Any other link navigates.

## Submit

The element posts a dialog's form through `fetch`.

| Answer | Result |
|---|---|
| `page` | Present it in the same dialog |
| `continue` | Fetch it into the same dialog; a sixth is an error |
| `done`, bottom dialog | Close; reload |
| `done`, upper dialog | Close it; show messages below |
| No kind | Error toast; the dialog stays |
| Failure, 15 s | The save could not be confirmed |

A result or a failure makes the host stale; a later failure then reads
as unconfirmed.

## Reload

The element reloads the host once no modal is open, after a stale stack
closes or on `page:stale` on `document`. A `done` URL that is not the
host navigates there. A host without `data-read-only` neither reloads
nor navigates; its messages show in place.

Before it leaves, the element stores the messages and the opener key in
`sessionStorage` (`ts/handoff.ts`); refused, they show in place. The
next load reads them within one minute, at any URL. Focus goes to the opener by id or `href`, else its
drop-down toggle, else `#main-container`.

## CSRF

When a sign-in changes the cookie, every `csrfmiddlewaretoken` input
takes its value.

## Inserted content

Content wires on connect, unwires on disconnect, and looks up fields in
its own form first. Page glue is an element (`<field-mirror>`).
