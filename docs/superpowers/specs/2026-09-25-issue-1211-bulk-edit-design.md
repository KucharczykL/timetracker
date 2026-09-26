# Set one device across many sessions

A person sets a device, the emulated flag, a note, or any two or three of
them, on each selected session. The batch is one act with one Undo, in
`games/bulk_edit.py`, through the runner of the
[Selectable tables wave](2026-09-19-selectable-tables-wave-design.md), shaped
as the [move confirmation](2026-09-21-issue-714-bulk-move-design.md).

The row's own Edit is a different act and stays in the row's menu. Timing
belongs to one row, so this act does not offer it: one start on forty rows
puts them on one instant. A shift of timing is a different act (#1294).
Playthrough is the Move act.

## The statement

`EditStatement` holds three facts. `device` is a `StatedDevice` or `None`.
`emulated` is a `bool` or `None`. `note` is a `str` or `None`. `None` is
"leave as it is". `StatedDevice(None)` is "no device", and `""` is "no note".
A statement must state one fact or more.

The statement goes through the hidden field, `settle` and the waypoint as one
JSON string, `EditJson`. An absent key is an unstated fact. `decode` refuses
text that is not JSON, an unknown key, a wrong type, a null `emulated` or
`note`, a device key that is not a UUID, and an empty object.

## The question

Each field has three states: leave, set, and unset.

- Device is a picker joined to a ⊘ toggle. An empty picker is "leave". The
  picker searches and creates devices as the session form's picker does. The
  toggle states "no device", and the picker then fades. A picked device with
  the toggle on is refused.
- Note is a text area joined to a ⊘ toggle, the same way. A blank text area
  is "leave".
- Emulated is a segmented group of three radios: `—`, `Emulated`,
  `Not emulated`. `—` is "leave". The flag has no unset state.

The ⊘ toggle is a checkbox drawn as a joined button, so it needs no script.
Each placeholder shows what the selected rows hold now: one value when all
agree, "Mixed (N devices)" when they differ.

`EditFields` puts a suffix on the runner's field name for each control, and
no control uses `CHOICE_FIELD`. The create row makes a device outside the
batch, so the Undo keeps it.

The first press posts the control fields; each later chunk posts
`CHOICE_FIELD`, an earlier settle's answer. `settle_edit` decodes that when
present, and composes from the controls when not. A stated device must be in
`Device.objects.for_library(library)`. The answer is `encode()`, so
`settle(settle(x)) == settle(x)`.

Every chunk settles again. `settle_edit` refuses, each with a sentence: no
fact; a value and ⊘ on one field; a device the library does not hold as a
live row; a value it cannot read. The runner then shows the confirmation
again on the same token, with empty controls. A second statement in one
batch is correct, because each row's Undo reads its own events.

`edit_one` decodes a statement that `settle` gave in the same request. A
failure there is a defect, `RowUnreadable`, and ends the batch.

## The act

`edit_one` dispatches one `DescribeSession` for each row through
`describe_session`, which takes `idempotency_key` and `source_metadata` and
gives the `CommandResult`. A row that already agrees gives `Unchanged` and
writes no event, so the Undo does not see it.

## The inverse

`edit_back` reads the events of the row. The family of a fact is the creation
and the change event of that fact. For each fact that the batch changed, the
earlier value is in the latest family event before the batch's event. A
change with no creation before it, or a payload of the wrong shape, is a
defect, `RowUnreadable`. `edit_back` dispatches one `DescribeSession` with
those values.

Like the other restating inverses, it accepts the hazard: it overwrites a
value set after the batch. A second Undo gives `Unchanged` if the row did not
change after the first. The command refuses a device removed since, unless
the row already names it.

The Undo reads the row through `session_of` in `games/bulk_sessions.py`, on
the plain manager: `library_sessions` hides a row whose catalog game was
removed.

## The tray and the confirmation

The tray order is Finish, Move, Edit, Reclassify, Remove. The label is
"Edit…". The preview columns are Game, Day, Duration, Device, Emulated and
Note.

Every act's heading states the count: `ActTitle.many` holds `{count}`, which
reads the number, or "these" where no rows are counted yet. One row reads
`ActTitle.one`. The confirmation asks no second question under the heading.
