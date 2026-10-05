# Set one device across many sessions

A person sets a device, the emulated flag, a note, or more than one of them,
on each selected session. The batch is one act with one Undo. The act is in
`games/bulk_session_edit.py` and uses the runner of the
[Selectable tables wave](2026-09-19-selectable-tables-wave-design.md).

Timing belongs to one row: one start on forty rows puts them on one instant.
A shift of timing is a different act (#1294).

## The statement

`EditStatement` holds three facts: `device` (a `StatedDevice`), `emulated`
(a `bool`) and `note` (a `str`). `None` keeps the fact. `StatedDevice(None)`
is "no device", and `""` is "no note". A statement states one fact or more.

Each chunk carries it as one JSON string, `EditJson`. An absent key keeps
its fact. `decode` refuses bad JSON, an unknown key, a wrong type, a null, a
bad key and an empty object.

## The question

`BulkEditForm` is an `UnsetFieldsForm`, and `FormFields` renders it. Its
prefix is the runner's `CHOICE_FIELD`. Each field has three states: keep, a
value, and none. An empty field keeps. Its placeholder shows what the rows
keep: "Keep: Steam Deck", or "Keep: mixed" when the rows differ.

- Device is a `SearchSelectWidget` in an `UnsetWidget`. It searches and
  creates devices. Its ⊘ states "No device".
- Emulated is a `ChoiceSearchSelectWidget` with two choices, Emulated and Not
  emulated. An empty picker keeps. The flag has no "none".
- Note is a text area in an `UnsetWidget`. Its ⊘ states "No note".

A ⊘ has priority over a value in its field.

The press posts the form. `settle_edit` decodes `CHOICE_FIELD`, else
validates the form, and checks that the device is live. Its answer is
`encode()`, stored on the batch, so settling twice gives the same text. A
refused settle shows the confirmation again on the same token.

## The act

`edit_one` sends one `DescribeSession` for each row, with the act name in
`source_metadata`. A row that agrees gives `Unchanged` and no event. A
settled statement that `edit_one` cannot decode is a defect.

## The inverse

`edit_back` reads the events of the row. The family of a fact is the
creation event and the change event of that fact. For each fact that the
batch changed, the earlier value is in the latest family event before the
event of the batch. A change with no creation before it, or a payload of the
wrong shape, is a defect.

The inverse restates those values and overwrites a later edit, as the other
restating inverses do. A second Undo gives `Unchanged`. It reads the row
through `session_of`, on the plain manager: `library_sessions` hides a row
whose catalog game was removed.

## The confirmation

The tray order is Finish, Edit, Reclassify, Remove; Move left with #1310. The preview shows
Game, Day, Duration, Device, Emulated and Note.

Each act's heading states the count: `ActTitle.many` holds `{count}`, the
number or "these". One row reads `ActTitle.one`. No question follows.
