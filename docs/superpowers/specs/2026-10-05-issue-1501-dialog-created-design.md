# A dialog hands a created row to its picker

Issue #1501, part of #1485, after #1384. Contract decided with the modal
epic organizer and the user on 2026-10-05.

## Problem

A picker can create a row by name alone (`PostCreate`). A row that needs
more than a name (a Game: platform, year, editions) has no way in: the
person leaves the form, adds the game, and comes back to a form that has
lost their input.

## Decisions

1. **`created` answer.** `created` is `done` plus one picker option:
   `{kind: "created", url, messages, option: {value, label, data}}`
   (`CreatedAnswer` in `common/components/form_dialog.py`, codegen'd into
   `ts/generated/form-dialog.ts`). The option is its own wire `TypedDict`,
   `CreatedOption`, every field text: `SearchSelectOption.value` is
   `str | int` and the TS element already exports a `SearchSelectOption`
   of its own. `readAnswer` checks `value` and `label` as text and `data`
   as a text record. `CreatedAnswer` joins `RedirectAnswer`, so
   `dialog_result`'s type admits it, and `CreatedOption.data` is
   `dict[str, str]` (codegen knows `dict`, not `Mapping`).
2. **A view tags its normal redirect.** `created_row(response, option)`
   (`common/form_dialog.py`) marks a redirect with the option. The view
   keeps `return redirect(...)`; it never branches on `is_form_dialog`.
   `FormDialogResultMiddleware` turns a tagged redirect whose target is
   `READ_ONLY` into `created`; the middleware reads the tag beside
   `dialog_result`, whose signature stays. It consumes the message queue as `done` does;
   untagged redirects answer as before, and a tagged off-origin redirect
   passes through as a redirect. `add_game`'s two failure redirects stay
   untagged and answer `done`.
3. **The option comes from the picker's own helper.** `game_option(game)`
   in `games/forms.py` is the one builder that `/api/games/search`,
   `_game_options` and `add_game` share, so the selected label reads as the
   search row does. It states `value` as `str(game.id)`. `GameForm.parent`
   keeps `_parent_options` for a stored parent; a fresh game reads the
   same there.
4. **A tagged redirect into a non-read-only target answers `continue`
   and drops the option.** Add game's "Submit & Add to library" chain
   therefore selects nothing in the picker; accepted.
5. **The opener routes the value, no ids travel.** `OpenDialog` keeps
   the opening link as an element (`openerElement`), beside the key it
   keeps for focus after a reload; a lookup by key would find the first
   + of the same href, which in a nested dialog is the wrong picker. On
   `created`, `routeSubmit` answers a `created` route carrying the option
   and the route `done` would take. The element dispatches a cancelable,
   bubbling `form-dialog:created` (`FORM_DIALOG_CREATED`,
   `ts/elements/form-dialog/events.ts`) on that link, detail the option,
   when the link is still connected. An element that takes it calls
   `preventDefault()`.
   - **Taken:** the dialog closes and its messages show in place, as
     `closeTop` does, whether or not other dialogs are open. Nothing
     navigates. The host is marked stale only when the link sits inside a
     lower dialog: that dialog's own close then reloads a read-only host
     that a game was written behind. A link on the host page itself marks
     nothing, because the reload once no modal is open would wipe the
     selection just made (a picker on a read-only page, such as a filter
     bar).
   - **Not taken** (no listener, or the link left the document): the
     answer routes exactly as `done`, stale included.
   - `created` counts as a write for the failure paths (`unconfirmed`),
     but `submit()`'s mark before routing skips it: the route decides.
     The taken path settles the entry before `modal.close()`, because
     the layer calls `onClosed` inside `close()` and `closed()` marks
     stale for an entry still submitting.
   - `postBehindModal` in `ts/elements/toast-stack.ts` reads `created` as
     `done`.
6. **`created` on open** routes as `done`.
7. **The picker offers the dialog through its own builder.**
   `SearchSelect(..., dialog_create=DialogCreate(url, label))` and the
   same keyword on `SearchSelectWidget` render a ghost compact
   `ControlButton(href=url)` carrying `form_dialog_link()`, `title` and
   `aria-label` = `label`, in the field box directly after the × and
   before any marker. `url` may be lazy (`reverse_lazy`): class-level
   widgets are built while the URLconf loads; the builder renders
   `str(url)`. The search input carries `peer` when a × or this link
   renders. Classes, all on the link:
   - `ml-auto`, and `ml-0` plus a left divider while a shown × precedes
     it (sibling variant on `[data-search-select-clear]:not([hidden])`);
   - `peer-disabled:hidden`, as the ×: a disabled picker offers no
     create.
   `ts/elements/search-select.ts` listens for `form-dialog:created` on its
   container. Unless its input is disabled, it upserts the option, selects
   it through `selectOption` with the change event (the dependent pickers
   re-search on it), and takes the event. `DialogCreate` is not a
   `CreateRow`: it adds no panel row and combines with any create row.
8. **First consumers: "New game".** `DialogCreate(reverse_lazy(
   "games:add_game"), "New game")` on every game picker of a form:
   `SessionForm.game` (Add and Edit session), `EntryAddForm`'s game field
   (Add to library without a game; built in `__init__`), `GameForm.parent`
   ("Add-on of", on Add and Edit game), and `PlaythroughForm.game` (Add
   playthrough). The link carries no `?origin=`, a deliberate exception to
   "mutating links carry their origin": a widget holds no request, and the
   dialog closes back onto the form. A link followed outside the dialog
   lands on the Games list after the save. `add_game` tags its final
   redirect with `game_option(game)`. Historical playtime has no game
   picker (its form is per game) and gets nothing.

## Behaviour around the value

- The new game is tracked by `add_game`, so the session's playthrough
  picker and the entry's release picker re-search on the change event and
  find its placeholder run and releases.
- "Add-on of" searches main games only. A new add-on selected there is
  refused on save by `state_addon` (`PARENT_NOT_MAIN`), answered on the
  field. The same holds for Edit playthrough's bucket, whose game the
  command refuses to change.
- Focus returns to the + link when the dialog closes (the modal layer's
  opener return); the picker's input shows the label.
- Nested: a picker inside a dialog opens a second dialog; the value lands
  in the lower dialog's picker.

## Tests

- pytest: middleware answers `created` for a tagged redirect to a
  `READ_ONLY` target, `continue` for a tagged redirect elsewhere, `done`
  untagged; the generated module holds `kind: "created"` and
  `CreatedOption`; `add_game` in dialog mode answers `created` with
  `game_option`; a non-dialog POST still redirects; the widget renders the
  link with `data-form-dialog` on each of the four forms;
  `/api/games/search`'s JSON and `game_option` agree; the input carries
  `peer` with a link and no ×.
- vitest: `readAnswer` reads and refuses `created`; `routeSubmit`/
  `routeOpen` route it.
- vitest: the element dispatches on the opening link; taken shows the
  messages and marks stale only for a link inside a lower dialog; not
  taken routes as `done` and marks stale; a disconnected link is not
  taken; a taken sole dialog over a read-only host does not reload.
- e2e: Add session → + → Add game in a dialog → save → the dialog closes,
  the game picker's hidden input holds the new id, the run picker holds
  its placeholder run, the note typed before is kept; the same from inside
  a dialog (Add-on of in a nested Add game), the value landing in the
  nested picker. A not-taken `created` on a form host closes, toasts, and
  selects nothing.

## Follow-up issues to file

- None yet; other "New X" pickers convert as #1385 reaches their pages.
