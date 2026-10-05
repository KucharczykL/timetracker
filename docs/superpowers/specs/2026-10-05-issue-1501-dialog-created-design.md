# A dialog hands a created row to its picker

A picker can create a row that needs more than a name. A + in the picker
opens the create page in a form dialog. When the save succeeds, the dialog
closes and the picker selects the new row. The form below keeps its input.

## The picker

`SearchSelect(dialog_create=DialogCreate(url, label))` shows the +. The
form widgets on `_SearchSelectAdapter` take the same keyword, but
`TextSearchSelectWidget` does not: its value is typed text. A panel
`SearchSelect` refuses it. The url can be lazy (`reverse_lazy`), because
class-level widgets are made while the URLconf loads.

`_combobox_children`, the shared shell, builds the trailing controls:
`clear=ClearControl(...)` gives the ×, and `dialog_create` gives a divider
and the +. Either control makes the search input their `peer`. A disabled
input hides all three. The divider shows only while the × shows.

The + is a link with `form_dialog_link()`. It has no `?origin=`: a widget
holds no request, and a form page is not a valid origin.

`NEW_GAME` (`games/forms.py`) is the + on each game picker: Add and Edit
session, Add to library, Add and Edit playthrough, and "Add-on of" on Add
and Edit game.

## The answer

A view answers `CreatedRedirect(url, option=...)` (`common/form_dialog.py`)
in place of its normal redirect. Use the option helper of the picker, for
example `game_option`. Then the selected label is the same as the search
row. `SearchSelectOption` extends `CreatedOption`; each field is text.

`FormDialogResultMiddleware` changes a `CreatedRedirect` to a `READ_ONLY`
page into `created`: `{kind, url, messages, option}`. A `CreatedRedirect`
to another page answers `continue`, or passes through off-origin; the
option is lost and a WARNING names it. "Submit & Add to library"
answers a plain redirect, so it selects nothing.

## The dialog

`<form-dialog>` keeps the link that opened each dialog. On `created`, it
sends `form-dialog:created` on that link. The event bubbles, it can be
cancelled, and its detail is the option. `<search-select>` selects the
option and sends `search-select:change`, then takes the event with
`preventDefault()`. A failed select does not take it.

- **Taken:** the dialog closes and its messages show. If the link is in a
  lower dialog, the host is stale and reloads after that dialog closes. If
  the link is on the host page, nothing is stale: a reload would remove
  the new selection.
- **Not taken** (no listener, a disabled picker, or the link is not in
  the document): the answer is the same as `done`. When the link sits in a
  picker, an error toast tells the person to pick the row from the list.

On open, `created` is the same as `done`. `<toast-stack>` reads `created`
as `done`. A `created` answer with an option that is not text is read as
`done`, and the client reports it.

## Limits

- "Add-on of" shows main games only. A new game of another kind is
  selected, and the save refuses it on the field.
- `ChoiceSearchSelectWidget` holds fixed choices. A created row passes
  validation only when the form reads its choices at each request.
