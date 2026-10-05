# A dialog hands a created row to its picker

A picker can create a row that needs more than a name. A + in the picker
opens the create page in a form dialog. When the save succeeds, the dialog
closes and the picker selects the new row. The form below keeps its input.

## The picker

`SearchSelect(dialog_create=DialogCreate(url, label))` shows the +. Every
form widget on `_SearchSelectAdapter` takes the same keyword. The url can
be lazy (`reverse_lazy`), because class-level widgets are made while the
URLconf loads.

`_combobox_children` builds the trailing controls for every builder:
`clear=ClearControl(...)` gives the ×, and `dialog_create` gives a divider
and the +. Either control makes the search input their `peer`. A disabled
input hides both. The divider shows only while the × shows.

The + is a link with `form_dialog_link()`. It has no `?origin=`, because a
widget holds no request.

`NEW_GAME` (`games/forms.py`) is the + on each game picker: Add and Edit
session, Add to library, Add and Edit playthrough, and "Add-on of" on Add
and Edit game.

## The answer

A view tags its normal redirect: `created_row(redirect(...), option)`
(`common/form_dialog.py`). Use the option helper of the picker, for example
`game_option`. Then the selected label is the same as the search row.

`FormDialogResultMiddleware` changes a tagged redirect to a `READ_ONLY`
page into `created`: `{kind, url, messages, option}`. `option` is a
`CreatedOption`, with text in each field. A tagged redirect to another page
answers `continue`, and the option is lost. Thus "Submit & Add to library"
selects nothing. A request that is not a dialog request gets the redirect.

## The dialog

`<form-dialog>` keeps the link that opened each dialog. On `created`, it
sends `form-dialog:created` on that link. The event bubbles, it can be
cancelled, and its detail is the option. `<search-select>` takes the event,
selects the option, and sends `search-select:change`. A dependent picker
then searches again.

- **Taken:** the dialog closes and its messages show. If the link is in a
  lower dialog, the host is stale and reloads after that dialog closes. If
  the link is on the host page, nothing is stale: a reload would remove
  the new selection.
- **Not taken** (no listener, or the link is not in the document): the
  answer is the same as `done`.

On open, `created` is the same as `done`. `<toast-stack>` reads `created`
as `done`.

## Limits

- "Add-on of" shows main games only. A new game of another kind is
  selected, and the save refuses it on the field.
- `ChoiceSearchSelectWidget` holds fixed choices. A created row passes
  validation only when the form reads its choices at each request.
