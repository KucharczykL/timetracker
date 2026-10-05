# The form dialog

A link with `data-form-dialog` opens its form page in a modal
(`form_dialog_link()`; `"bare"` drops the header). Views know nothing of
the dialog.

Two URLs are equal when origin, path and sorted query match. The hash is
ignored.

## Request and answers

Every dialog fetch sends `X-Form-Dialog: 1` and `Accept: application/json`
(`is_form_dialog`, `common/form_dialog.py`). The answer kinds are
`TypedDict`s in `common/components/form_dialog.py`; codegen writes them to
`ts/generated/form-dialog.ts`.

| `kind` | Fields | Sent by |
|---|---|---|
| `page` | `title`, `html`, `modules`, `messages` | `render_page()` |
| `done` | `url`, `messages` | `FormDialogResultMiddleware` |
| `continue` | `url` | `FormDialogResultMiddleware` |

- `page` holds the content alone, under the view's status. A
  `js_external` script is refused.
- The middleware reads a redirect's `Location`. A `READ_ONLY` route gives
  `done` with the message queue. Another route on this origin gives
  `continue` and keeps the queue. Another origin passes through.
- `done` means finished, not saved.
- An answer that is not JSON has no kind.
- Dialog answers carry `Cache-Control: no-store`.
  `ToastMessagesMiddleware` skips dialog requests.

## Open

| Answer | Result |
|---|---|
| `page` | Present it in a new dialog |
| `done` | Show its messages |
| `continue` | Fetch its `url` |
| No kind, failure, 15 s | Follow the link |

After five `continue` answers, the link is followed.

Presenting imports `modules`, prefixes ids and their references, and
resolves URLs against the answer's URL. Focus goes to the first invalid
control, else the first control of the form, else the ×.

A link inside a dialog back to the host or to a lower dialog closes the
dialogs above it. A fragment link stays native. Any other link navigates.

## Submit

A POST form in a dialog is sent through `fetch`.

| Answer | Result |
|---|---|
| `page` | Present it in the same dialog |
| `continue` | Fetch it into the same dialog; five at most |
| `done`, alone | Close; reload |
| `done`, nested | Close the top dialog; show messages below |
| No kind | Error toast; the dialog stays |
| Failure | "Not confirmed" toast; the host is stale |

A result or a failure makes the host stale.

## Reload

The element reloads the host once no modal is open, after a stale stack
closes or on `page:stale` on `document`. A `done` URL that is not the host navigates there. A host
without `data-read-only` never reloads; its messages show in place.

Before it leaves, the element stores the messages and the opener key in
`sessionStorage` (`ts/handoff.ts`). The next load reads them within one
minute, at any URL. Focus goes to the opener by id, then by `href`, then
its drop-down toggle, then `#main-container`.

## CSRF

When a sign-in changes the cookie, every `csrfmiddlewaretoken` input
takes its value.

## Inserted content

Content wires on connect and unwires on disconnect. A field lookup
searches its own form first. Page glue is an element (`<field-mirror>`).
