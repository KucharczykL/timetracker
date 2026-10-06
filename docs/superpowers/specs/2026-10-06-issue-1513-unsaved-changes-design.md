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
- A file reads as `file:<name>:<size>:<lastModified>`. An empty file input
  reads as an empty string.

The element takes the baseline when it shows a page, and again one task
later. The second snapshot includes values that content fills after
insertion. A page that follows a write is a new baseline. A refused page
and a failed request keep the old baseline, so the input still reads as
changed.

## The warning

The warning is a second template in `FormDialogHost`. It is an
`alertdialog` with a plain `ModalPanelHeader` (`close_label=None`,
`divided=False`): no ×, no line. Its parts are `UNSAVED_WARNING_PARTS`. It has three
buttons: Discard, Return to edit, Save.

- Return to edit, Escape and the backdrop close only the warning.
- Discard closes the form dialog.
- Save submits the changed form with its default button. Save is hidden
  when more than one form changed, or when that button is absent, disabled,
  or does not post. The server can refuse the save. Then the dialog stays
  open and focus goes to the error.

One warning opens at a time. A submitting dialog does not close and does
not ask, and it stops a link. While another modal leaves, a close returns
to the edit; the next close asks. If the template is absent, the layer
refuses the warning, or the warning fails, the element reports this, shows
an error toast, and closes the form dialog.

## The guards

- **Dismissal** (Escape, backdrop, ×) opens the warning.
- **A link in a dialog** that closes dialogs, or that leaves the page while
  a dialog has changes, closes the dialogs from the top down. Each changed dialog asks.
  Return to edit or Save stops the link. After the last dialog closes, a
  leaving link goes to its URL once, through `runReload`.
- **`beforeunload`** calls `preventDefault()` while a dialog has changes.

The modal layer calls no `dismiss` for a `cancel` that is not cancelable.

## Errors take focus

`FieldErrors(..., form_wide=True)` marks a list that no field owns with
`data-form-errors` and `tabindex="-1"`. A form dialog focuses an invalid
control first, and that list second.

## Limits

- Chrome lets a dialog stop `cancel` only after user activation. Repeated
  Escapes with no click or key between can close without a warning.
- A value that content fills later than one task (a fetch) reads as a
  change.
- When the browser refuses session storage, a leaving link loses the
  queued messages.
