# The form dialog

A link with `data-form-dialog` opens its form page in a modal. The dialog
asks the server for the page in dialog mode. The server answers with the
content alone, or with a result. A view knows nothing about the dialog;
`render_page()` and one middleware do. Scripting off is not supported.

## Request

Every fetch of the dialog carries `X-Form-Dialog: 1` and
`Accept: application/json`. `is_form_dialog(request)` in
`common/form_dialog.py` names the test.

## Answers

`common/components/form_dialog.py` states the answer kinds as `TypedDict`s
with a `kind` literal; `gen_element_types` writes them to
`ts/generated/form-dialog.ts`. The codegen learns optional keys
(`__optional_keys__`), because a toast payload's `action` is optional.

| `kind` | Fields | Sent by |
|---|---|---|
| `page` | `title`, `html`, `modules`, `messages` | `render_page()` |
| `done` | `url`, `messages` | the middleware |
| `continue` | `url` | the middleware |
| `created` | `value`, `label`, `messages` | a view that states its row |

Every answer carries `Vary: X-Form-Dialog` and `Cache-Control: no-store`.
The client decides by `kind`, never by status.

- **`page`.** `render_page()` answers a dialog request with the content
  alone, under the view's status (200, 400, 403, 409, 500). `modules`
  holds the module scripts of `collect_media(content)` and of `scripts=`,
  which takes `ModuleScript` nodes only. A component with `js_external`
  is refused in dialog mode. `messages` holds the consumed queue.
- **`done` and `continue`.** `FormDialogResultMiddleware` turns a 301, 302,
  303, 307 or 308 with a `Location` into a result. It resolves the
  location's path, relative to the request, against the root urlconf. A
  route in `READ_ONLY` gives `done` with the consumed queue and the
  location. Any other same-origin target gives `continue` and leaves the
  queue alone. An off-origin target passes through. A test walks the root
  urlconf through the same classification.
- **`ToastMessagesMiddleware`** skips a dialog request; `render_page()` and
  the result middleware own its messages.
- **`created`.** A view returns it explicitly. #1501 adopts it.
- **`done` means finished, not saved.** A refusal that redirects arrives
  as `done` with an error message.
- An answer that is not JSON (a Django 404, a CSRF 403, a proxy error) has
  no kind.

## Open

A plain primary click on a marked link opens. While one open runs, another
marked link follows natively. The fetch has a 15 second deadline.

| Answer | Result |
|---|---|
| `page` | Present it in a new dialog |
| `done` | Toast only |
| `continue` | Fetch its `url` the same way |
| No kind, failure, timeout | Follow the link |

A chain of `continue` stops after five and follows the last link.

## Present

The host imports `modules`, prefixes every id and the references in the
attributes `form_dialog.py` lists, plus fragment links, and resolves
`href`, `action` and `formaction` against `response.url`. A form without
`action` gets that URL. Header chrome titles the dialog with `title` and
drops a content `h1`; bare chrome names it with `aria-label`. Focus goes to
the first invalid control, else the first tabbable element of the first
form, else the ×.

## Links inside a dialog

A link to the host page or to a lower dialog's page closes the dialogs
above it. A fragment link stays native. Any other link navigates the
window, which closes every dialog.

## Submit

The host sends a POST form inside a dialog body through `fetch`, with its
submitter. A GET form stays native. While a form submits, no dismissal and
no link closes its dialog.

| Answer | Result |
|---|---|
| `page` | Present it in the same dialog |
| `continue` | Fetch its `url` into the same dialog |
| `done` or `created`, alone | Close; reload |
| `done` or `created`, nested | Close the top dialog; toast below |
| No kind | Error toast; the dialog stays |
| Failure | Unconfirmed toast; the host is stale |

Any result to a POST marks the host stale. When the bottom dialog closes by
any path and the host is stale, the host reloads.

## Reload

One reloader, in `<form-dialog>`, serves every trigger: a closing stale
stack and `page:stale` on `document` (#1507). It waits until no modal is
open, then runs once. Before it runs, it hands off the waiting messages
(`ts/toast-handoff.ts`, for the target page, one minute) and stores the
opener's id, else its `href`, for one load.

- **Target.** A `done` whose `url` is the host page reloads it. A `done`
  elsewhere (the origin was refused, as after removing the page's own
  row) navigates to its `url`.
- **Form host.** A host whose `#main-container` lacks `data-read-only`
  never reloads. Its messages show in place; the opener and its form stay
  reachable.
- **After the load.** Focus goes to the stored element, else its
  `<drop-down>` toggle, else `#main-container`.
- **What a reload loses.** Unsent filter edits and the builder tree, as a
  manual reload does. A selection comes back from `sessionStorage`.

## CSRF

A sign-in inside a dialog rotates the token. When the `csrftoken` cookie
differs from the one read at load, the host rewrites every
`csrfmiddlewaretoken` input in the page and its dialogs to the cookie's
secret, which Django accepts. A POST that met the sign-in redirect is lost;
its form is fetched again after sign-in.

## Toast actions

A toast's action form posts natively, which closes every dialog. #1507
intercepts it.

## Inserted content

Content must wire on connect and unwire on disconnect. A lookup by field
name searches its own form first. Page glue is an element
(`<field-mirror>`). The id-reference contract test covers each route a
conversion marks.

## Removed by this design

The page swap (`swap.ts`, `events.ts`, `form-dialog:swapped` and its
listener in `ts/library-conversion-status.ts`), `id="navbar"`,
`data-page-title`, the busy classes on `#main-container`, `#main-container`
extraction from a full page, and the routes' read-only and host-URL
matching.
