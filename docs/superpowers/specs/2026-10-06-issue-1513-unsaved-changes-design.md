# A form dialog with unsaved changes asks before it closes

Issue #1513, part of #1485. Builds on
[The form dialog](2026-10-04-issue-1384-form-dialog-design.md) and
[The modal layer](2026-10-04-issue-1499-modal-layer-design.md).

## The record

`<form-dialog>` keeps one baseline per open dialog: a snapshot of every
form in the dialog's body.

- A snapshot maps each form, by its index in the body, to its `FormData`,
  read as `name → list of values`. Every form counts, hidden tabs and
  sections included, because `FormData` reads hidden controls; disabled
  controls are out, as in a submit.
- In a browser, `new FormData(form)` fires the form's `formdata` event, so
  content that contributes there counts (a `SelectTyped` draft). A listener
  there must stay free of side effects. jsdom fires no `formdata`, so no
  unit test reaches this path. A search query typed without a pick is not a
  value and is no change.
- A file value reads as `file:<name>:<size>:<lastModified>`; an empty file
  input reads as an empty value. No form has a file field today.
- `csrfmiddlewaretoken` is left out: a sign-in rewrites it in every form.
- Two snapshots differ when a key's value lists differ. A key absent from
  one snapshot reads as an empty list, and a list of empty strings reads as
  an empty list, so a field added empty or a section opened and left empty
  is no change. Order inside one name's list counts.
- The module is `ts/elements/form-dialog/unsaved.ts`: `snapshotForms(body)`,
  `changedForms(body, baseline)` (the forms whose snapshot differs).

When the baseline is taken:

- At every presentation: the first one and each re-presented answer (a
  refusal). A refused submit therefore reads as unchanged until the person
  edits again; this is the issue's stated rule.
- After an unconfirmed submit (failure or timeout): the write may have
  landed, and the toast already says so.
- Once more, one task after each presentation. `prepare()` imports the
  page's modules before `fill()` inserts the content, so its custom elements
  upgrade on insertion, and their late fills (`<unset-field>` waits on
  `whenDefined`, Alpine's `x-mask` on a mutation observer) are microtasks.
  After a `setTimeout(0)` they have run; the element takes the baseline
  again. A close before then compares with the presentation's baseline.

## The warning

The confirmation is a second template inside `FormDialogHost`. New parts
join `FormDialogPart` (and the generated TS): `unsaved` (the template),
`discard`, `save`. Each use clones it, prefixes its ids, appends the
dialog to the `<form-dialog>` host (never inside a form dialog's body) and
attaches it to the modal layer over the form dialog. Its `onClosed`
removes it: earlier, `<toast-stack>` would find its region detached.

Approved UI (mockup, 2026-10-06):

- `role="alertdialog"`, labelled by its title **Unsaved changes**,
  described by **Your changes are not saved.** No ×, so a plain `PlainH2`
  and `P` inside `ModalDialog`, not `ModalPanelHeader`.
- Buttons, in DOM and visual order: **Discard** (`ControlButton` red,
  left, apart), **Return to edit** (gray, initial focus,
  `data-modal-dismiss`), **Save** (blue, primary). Below `sm` they stack
  in the same order.

Acts:

- **Return to edit** (also Escape and a backdrop press, through the layer's
  default dismiss) closes only the confirmation. Focus goes back to the
  confirmation's opener, the active element when it opened; where that is
  the body (a backdrop press, a × in Safari), the layer gives the form
  dialog its initial focus.
- **Discard** closes the form dialog (for a link, continues; below). The
  layer closes the confirmation first, through `closeAbove`.
- **Save** closes the confirmation and calls `requestSubmit(button)` on the
  one changed form. `button` is the form's default button: the first
  submit button in `form.elements`, so a `form=`-owned button counts. Save
  is hidden unless exactly one form changed, that button exists and is
  enabled, and its `formmethod`, else the form's `method`, is `post`.
  `requestSubmit` runs constraint validation and reports it; an invalid
  form stays open.

One confirmation opens at a time. A submitting dialog asks nothing; its
close stays refused, and a link walk that reaches it stops there. When the template is missing or the layer refuses to
open the confirmation, the element reports it and closes the form dialog:
a broken warning must not trap anyone.

## The guards

- **`dismiss`** (Escape, backdrop, `[data-modal-dismiss]`): a dialog with
  changes opens the warning instead of closing.
- **A link in a dialog** that navigates, or that closes dialogs (back to
  the host or a lower dialog). Navigating links are intercepted only while
  some dialog has changes; otherwise they stay native. The element walks
  the dialogs the act ends, topmost first:
  - a dialog without changes closes, and the walk moves down;
  - a dialog with changes asks. Discard closes it and the walk moves down;
    Return to edit and Save end the walk, and the link's act is dropped.
  - When the walk ends with no dialog left to ask, the link acts. A close
    needs nothing more. A navigation goes through the reload: the walk sets
    the element's leave target before it closes the bottom dialog, and
    `runReload` then hands off messages and the opener and assigns the
    link's URL on any host. The last close therefore triggers one
    navigation, never a reload beside the link's own.
  A fragment link and a `data-form-dialog` link stay as they are.
- **`beforeunload`**: while any dialog has changes, the element calls
  `preventDefault()`, so the browser shows its own prompt. This also
  catches what the walk does not: a GET form submit, a failed nested open
  that follows its link, and the toast stack posting behind a modal.

## The layer

A `cancel` that is not cancelable no longer calls `dismiss`: the browser
closes the dialog regardless, and the `close` event finishes it. Opening a
warning there would only be torn down.

## Known limits

- Chrome lets a dialog veto `cancel` only after user activation since the
  open or the last veto. A click or a typed key grants it; Escape and
  `insertText` (dictation, Playwright's `fill()`) do not. Escape warns; a
  second Escape returns to the edit; a third Escape with no activation
  between may close the form dialog without a warning. Not worked around.
- An open picker panel takes the first Escape; the warning comes on the
  second.
- After a refused Save, the re-presented form is the baseline, so the next
  close loses the refused input without a warning. This is the issue's
  rule.
- A dialog removed from the document is not guarded.
- A value that content fills later than one task after insertion (a
  fetch) reads as a change.
- On the `beforeunload` paths, `handOffMessages` has already stored the
  messages; if the person stays, a later load shows them.

## Decisions

- Baseline per presentation, not per form element: a refusal replaces the
  form, so element identity does not survive.
- The confirmation lives in the host's markup: UI is Python components, and
  button classes come from `ControlButton`.
- Save hides rather than guesses when two forms changed.
- A baseline one task after insertion, not one taken at the person's first
  key or pointer: an edit with no key or pointer before it (dictation,
  autofill, a screen reader's click) would be absorbed, and a window of
  person events needs a replaceable trust test that proves nothing about the browser.

## Tests

- vitest `unsaved.test.ts`: typed and typed back, absent key, empty list,
  multiple values, the file formatter, CSRF left out, form index, a
  `formdata` contribution.
- vitest `form-dialog.test.ts` (the `mountHost` fixture gains the
  template): the veto per dismissal path, each act, Save's submitter and
  hiding, the link walk over a stack (a submitting dialog stops it; a
  navigation after a stale close assigns once), `beforeunload`, the
  deferred baseline, a refusal and an unconfirmed submit re-taking the baseline, the
  missing-template fallback.
- vitest `modal-layer.test.ts`: "finishes on a cancel the browser will not
  let it veto" flips: a non-cancelable `cancel` skips `dismiss` and still
  finishes.
- pytest `tests/test_form_dialog.py`: the second template's parts and its
  alertdialog wiring; `test_the_dialog_lives_only_inside_the_template`
  covers both templates.
- e2e `test_form_dialog_e2e.py` (dialogs opened by a click): Escape warns
  after `fill()`; Return to
  edit keeps the input; Discard closes; Save submits; an unchanged form
  closes at once.

## Follow-up issues to file

- #1335 gains an Orca check (comment on #1335): the warning is announced as
  a dialog and focus lands on Return to edit.
