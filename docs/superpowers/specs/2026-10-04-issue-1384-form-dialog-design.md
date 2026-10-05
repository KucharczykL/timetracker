# The form dialog

A link with `data-form-dialog` opens its form page in a modal. The dialog
asks the server for the page in dialog mode. The server answers with the
content alone, or with a result. A page knows nothing about the dialog;
`render_page()` and one middleware do.

## Request

Every fetch of the dialog carries `X-Form-Dialog: 1`. The dialog sends
`Accept: application/json`.

## Answers

`common/components/form_dialog.py` states the answer kinds as `TypedDict`s;
`gen_element_types` writes them to `ts/generated/form-dialog.ts`.

| Kind | Fields | Sent by |
|---|---|---|
| `page` | `title`, `html`, `modules`, `messages` | `render_page()` |
| `done` | `messages` | the middleware |
| `continue` | `url` | the middleware |
| `created` | `value`, `label`, `messages` | a view that states its row |

The status of a `page` stays the view's: 200, or 409 for a refusal.

- **`page`.** `render_page()` answers a dialog request with the content
  alone: no layout, navbar or toast stack. `modules` holds the module
  scripts of `collect_media(content)` and of `scripts=`, which takes nodes.
  `messages` holds the consumed message queue.
- **`done` and `continue`.** `FormDialogResultMiddleware` turns a 3xx on a
  dialog request into a result. A target route in `READ_ONLY` gives `done`
  with the consumed messages. Any other target gives `continue`. It sits
  after `ToastMessagesMiddleware`, so it acts first and that middleware
  finds the queue empty. A test walks the route table and resolves every
  route through the classification.
- **`created`.** A view returns it explicitly. #1501 adopts it.
- An answer that is not JSON (a Django 404, a CSRF 403, a proxy error)
  is no answer kind.

## Open

A plain primary click on a marked link opens. One open runs at a time. The
fetch has a 15 second deadline.

| Answer | Result |
|---|---|
| `page` | Present it in a new dialog |
| `done` | Toast only |
| `continue` | Fetch its `url` the same way |
| No answer kind, failure | Error toast; follow the link |

## Present

The host imports `modules`, prefixes every id and the references in the
attributes `form_dialog.py` lists, and resolves `href`, `action` and
`formaction` against the fetched URL. A form without `action` gets that
URL. Header chrome titles the dialog with `title` and drops a content
`h1`; bare chrome names it with `aria-label`. Focus goes to the first
invalid control, else the first tabbable element of the first form, else
the ×.

## Submit

The host sends a POST form inside a dialog body through `fetch`, with its
submitter. A GET form stays native. While a form submits, no dismissal and
no link closes its dialog.

| Answer | Result |
|---|---|
| `page` | Present it in the same dialog |
| `continue` | Fetch its `url` into the same dialog |
| `done` or `created`, alone | Close; reload the host |
| `done` or `created`, nested | Close the top dialog; toast below |
| No answer kind | Error toast; the dialog stays |
| Failure | Unconfirmed toast; the host is stale |

Any result to a POST marks the host stale. When the bottom dialog closes
by any path and the host is stale, the host reloads.

## Reload

The reload waits until no modal is open, then runs once. A host whose
`#main-container` lacks `data-read-only` is a form; it never reloads, and
the opener and its form stay reachable. Before the reload the host hands
off the messages (`ts/toast-handoff.ts`, for this page, one minute) and
stores the opener's id, else its `href`. After the reload, focus goes to
that element, else its `<drop-down>` toggle, else `#main-container`.

## Toast actions

A toast's action form posts natively. #1507 intercepts it.

## Inserted content

Content must wire on connect and unwire on disconnect. A lookup by field
name searches its own form first. Page glue is an element
(`<field-mirror>`).
