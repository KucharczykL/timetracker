# Plan: unsaved changes in a form dialog (#1513)

Spec: [2026-10-06-issue-1513-unsaved-changes-design.md](../specs/2026-10-06-issue-1513-unsaved-changes-design.md).
Inline, TDD, `make check-fast` under the lock while iterating.

## Task 1: the layer skips dismiss on a non-cancelable cancel

- `ts/elements/modal-layer.ts` cancel listener: `preventDefault()`, then
  `if (!event.cancelable) return;` before `dismiss()`.
- `ts/elements/modal-layer.test.ts:740-755`: flip the assertion
  (`dismiss` not called, modal still finishes on `close`).
- Modal-layer spec: one sentence under Dismissal.

## Task 2: the snapshot module

- New `ts/elements/form-dialog/unsaved.ts`:
  - `type FormSnapshot = ReadonlyMap<string, readonly string[]>` keyed
    `${formIndex}\u0000${name}`; `type DialogSnapshot` alias if clearer.
  - `snapshotForms(body: ParentNode): FormSnapshot`.
  - `changedForms(body, baseline): HTMLFormElement[]`.
  - `fieldValue(value: FormDataEntryValue): string` (file formatter).
  - Empty-list normalisation; skip `csrfmiddlewaretoken`.
- `unsaved.test.ts` (jsdom): typed and typed back, absent key, all-empty
  list, multiple values order, file formatter, CSRF skipped, second form
  changed only, disabled control out.

## Task 3: the confirmation template (Python)

- `common/components/form_dialog.py`: `FormDialogPart` gains `unsaved`,
  `discard`, `save`; `FORM_DIALOG_PARTS` entries
  `data-form-dialog-unsaved`, `-discard`, `-save`.
- `FormDialogHost()` renders a second `Template([(unsaved, "")])` holding
  `ModalDialog([("role","alertdialog"), aria-labelledby, aria-describedby])`
  → panel (`max-w-sm`, same surface classes) → `PlainH2(id=…)` "Unsaved
  changes", `P(id=…)` "Your changes are not saved.", button row
  `flex flex-col gap-2 sm:flex-row`: Discard `ControlButton(color="red")`
  with `sm:mr-auto` and the discard part, Return to edit
  `ControlButton(color="gray")` with `data-modal-dismiss` and
  `data-modal-initial-focus`, Save `ControlButton(color="blue")` with the
  save part. All `type="button"`. Ids are prefixed per clone by
  `prefixIds`; check that `aria-describedby` is in
  `FORM_DIALOG_ID_LIST_ATTRIBUTES` (it is).
- `make gen-element-types`; `ts/generated/form-dialog.ts` regenerates.
- `tests/test_form_dialog.py`: parts render; alertdialog wiring; extend
  `test_the_dialog_lives_only_inside_the_template` to both templates.

## Task 4: baseline and dismiss veto in `<form-dialog>`

- `OpenDialog` gains `baseline: FormSnapshot`.
- `rebaseline(entry)` after `fill()` in `openDialog` and `present()`;
  `setTimeout(0)` re-takes (guard: entry still in stack, same
  presentation — count presentations per entry).
- `unconfirmed()` callers re-take the baseline of the entry (pass entry).
- `dismiss`: submitting → nothing; changed → `askAbout(entry)`; else close.
- `askAbout(entry): Promise<UnsavedChoice>` where
  `type UnsavedChoice = "discard" | "return" | "save"`; opens the cloned
  confirmation via `attachModal(..., { onClosed })`, appends to `this`,
  hides Save per the rule, resolves on button/close. Missing template or
  refused open → report, resolve `"discard"`.
- Acts: discard → `entry.modal.close()`; save → `defaultButton(form)` +
  `form.requestSubmit(button)` after the confirmation closes; return →
  nothing.
- `defaultButton(form)`: first submit-type control in `form.elements`.
- One confirmation at a time (`this.asking`).
- Tests in `form-dialog.test.ts`; `mountHost` gains the template markup.
  Cases: Escape/backdrop/× each warn when changed and close when not;
  each act; Save submitter name/value posted; Save hidden for two changed
  forms and for a GET form; refusal re-baselines; deferred baseline absorbs
  a value set in a microtask; missing template closes and reports.

## Task 5: link walk and beforeunload

- `onClick`: a navigating link in a dialog (not fragment, not
  `data-form-dialog`) is intercepted only when some entry has changes.
  `firstAboveTarget` path and navigation path both run `walk(entries,
  act)`, topmost first: submitting → stop; unchanged → close, continue;
  changed → ask; discard → close, continue; return/save → stop (save runs
  its act).
- Navigation end: `this.leaveTo = url` before closing the bottom one;
  `closed()` with `leaveTo` set always calls `requestReload`; `runReload`
  with `leaveTo` hands off and `browser.assign(leaveTo)` on any host. If
  the stack was already empty (cannot happen; guard), assign directly.
- `beforeunload` listener on `window` in connected/disconnected:
  `if (this.stack.some(changed)) event.preventDefault()`.
- Tests: walk over a two-dialog stack (upper unchanged, lower changed;
  discard → navigate once; return → stays), a submitting dialog stops it,
  stale + navigate assigns once, `beforeunload` cancelled only while
  changed.

## Task 6: e2e

- `e2e/test_form_dialog_e2e.py`, Edit device opened by click:
  `fill()` name, Escape → alertdialog visible with focus on Return to
  edit; Return to edit keeps value; Escape again + Discard → closed, no
  write; Save → saved and reloaded; unchanged → Escape closes at once.

## Gotchas

- `make ts` before e2e; never with `make dev` up.
- The confirmation must not sit inside any entry body.
- `requestSubmit` needs the button's `form` to be this form.
- Vale: avoid refused words in comments (`docs/vocabulary.md`).

## After

- Comment #1335 with the Orca check.
- Docs sweep per skill; CLAUDE.md "form dialog" convention gains one line.
