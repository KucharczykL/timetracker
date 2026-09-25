# Set one device across many sessions

A person sets one device, one emulated flag, or both, on each selected
session. The batch is one act with one Undo, in `games/bulk_edit.py`, through
the runner of the [Selectable tables wave](2026-09-19-selectable-tables-wave-design.md),
shaped as the [move confirmation](2026-09-21-issue-714-bulk-move-design.md).

The row's own Edit is a different act and stays in the row's menu. Timing and
note belong to one row, so this act does not offer them.

## The statement

`EditStatement` holds two facts. `device` is a `StatedDevice` or `None`.
`emulated` is a `bool` or `None`. `None` is "leave as it is".
`StatedDevice(None)` is "no device". A statement must state one fact or more.

The statement goes through the hidden field, `settle` and the waypoint as one
JSON string, `EditJson`. An absent key is an unstated fact. `decode` refuses
text that is not JSON, an unknown key, a wrong type, a null `emulated`, a
device key that is not a UUID, and an empty object.

## The question

`offer_edit` gives a device picker, a "No device" checkbox and three emulated
radios. The picker searches and creates devices as the session form's picker
does. An empty picker is "leave as it is". `EditFields` puts a suffix on the
runner's field name for each control, and no control uses `CHOICE_FIELD`.

The create row makes a device outside the batch, so the Undo keeps it.

The first press posts the control fields; each later chunk posts
`CHOICE_FIELD`, an earlier settle's answer. `settle_edit` decodes that when
present, and composes from the controls when not. A stated device must be in `Device.objects.for_library(library)`. The
answer is `encode()`, so `settle(settle(x)) == settle(x)`.

Every chunk settles again. `settle_edit` refuses, each with a sentence: no
fact; a device and "No device"; a device the library does not hold as a live
row; a value it cannot read. The runner then shows the confirmation again on
the same token, with empty controls, and the person states again for the rows
that remain. A second statement in one batch is correct, because each row's
Undo reads its own events.

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
earlier value is in the latest family event before the batch's event.
A change with no creation before it, or a payload of the wrong shape, is a
defect, `RowUnreadable`. `edit_back` dispatches one `DescribeSession` with
those values.

Like the other restating inverses, it accepts the hazard: it overwrites a value
set after the batch. A second Undo gives `Unchanged` if the row did not change
after the first. The command refuses a device removed since, unless the row
already names it.

The Undo reads the row through `session_of` in `games/bulk_sessions.py`, on
the plain manager: `library_sessions` hides a row whose catalog game was
removed.

## The tray and the confirmation

The tray order is Finish, Move, Edit, Reclassify, Remove. The label is
"Edit…". The confirmation's question drops the three dots of the label. The
preview columns are Game, Day, Duration, Device and Emulated.
