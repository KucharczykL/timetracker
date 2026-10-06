# A form dialog with unsaved changes asks before it closes

Builds on [The form dialog](2026-10-04-issue-1384-form-dialog-design.md) and
[The modal layer](2026-10-04-issue-1499-modal-layer-design.md).

## The baseline

`<form-dialog>` keeps one baseline for each open dialog. The baseline is a
snapshot of each form in the dialog body: `name → list of values`, from
`FormData`. The code is in `ts/elements/form-dialog/unsaved.ts`.

- A hidden control counts. A disabled control does not count.
- `csrfmiddlewaretoken` does not count. A sign-in changes it in each form.
- An absent key and a list of empty strings are equal to an empty list.
- A file reads as `file:<name>:<size>:<lastModified>`.

The element takes the baseline when it shows a page, and again one task
later. The second snapshot includes values that content fills after
insertion. An unconfirmed submit also takes a new baseline, because the
write possibly occurred.

## The warning

The warning is a second template in `FormDialogHost`. It is an
`alertdialog` with a plain `ModalPanelHeader`: no ×, no line. It has three
buttons: Discard, Return to edit, Save.

- Return to edit, Escape and the backdrop close only the warning.
- Discard closes the form dialog.
- Save submits the changed form with its default button. Save is hidden
  when more than one form changed, or when that button is absent, disabled,
  or does not post. The server can refuse the save. Then the dialog stays
  open and focus goes to the error.

One warning opens at a time. A submitting dialog does not ask. If the
template is absent or the layer refuses to open it, the element reports
this and closes the form dialog.

## The guards

- **Dismissal** (Escape, backdrop, ×) opens the warning.
- **A link** that closes dialogs, or that leaves the page while a dialog has
  changes, closes the dialogs from the top down. Each changed dialog asks.
  Return to edit or Save stops the link. After the last dialog closes, a
  leaving link goes to its URL once, through `runReload`.
- **`beforeunload`** calls `preventDefault()` while a dialog has changes.

The modal layer calls no `dismiss` for a `cancel` that is not cancelable.

## Errors take focus

`FieldErrors` marks each error list with `data-form-errors` and
`tabindex="-1"`. A form dialog focuses an invalid control first, and an
error list second.

## Limits

- Chrome lets a dialog stop `cancel` only after user activation. A third
  Escape with no click or key between can close without a warning.
- A value that content fills later than one task (a fetch) reads as a
  change.
- After a refused save, the refused page is the baseline.
