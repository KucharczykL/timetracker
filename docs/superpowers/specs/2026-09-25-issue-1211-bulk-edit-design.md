# Set one device across many sessions

A person selects sessions on the session list and sets one device, one
emulated flag, or both, on every selected row. The batch is one act with one
Undo. The code is in `games/bulk_edit.py`. The act runs through the runner of
the [Selectable tables wave](2026-09-19-selectable-tables-wave-design.md), and
its confirmation has the shape of the
[move confirmation](2026-09-21-issue-714-bulk-move-design.md).

This act is not the row's own Edit. The row's Edit opens the form of one
session and stays in the row's menu, which does not change: that form already
states both facts for one row. The tray's Edit sets a shared value. Its two
facts are the only facts a shared value is correct for: timing and note belong
to one row.

## The statement

`EditStatement` holds two facts. `device` is a `StatedDevice` or `None`, and
`emulated` is a `bool` or `None`. `None` means "leave as it is", and
`StatedDevice(None)` means "no device", as in `DescribeSession`. A statement
that states neither fact is refused when it is made.

The statement crosses the hidden field, `settle` and the waypoint as one JSON
string. An unstated fact is an absent key. `decode` refuses a key it does not
know, a value of the wrong type, and an empty object.

## The question

`offer_edit` gives two groups. Device: the session form's creating
`SearchSelect` over `POST /api/devices/`, empty for "leave as it is", and a
"No device" checkbox. Emulated: three radios, "Leave as it is" (checked),
"Emulated" and "Not emulated". Every control is named from the runner's field
name with a suffix (`-device`, `-no-device`, `-emulated`), and none is
`CHOICE_FIELD` itself. Both groups round-trip with scripting off.

A device made through the create row is made in its own request, before the
submit and outside the batch. The Undo does not remove it.

`settle_edit` has two inputs. The confirmation posts the control fields and no
`CHOICE_FIELD`. Each later chunk posts `CHOICE_FIELD`, the statement an earlier
settle answered, and no control. So a posted `CHOICE_FIELD` is decoded, and
otherwise the statement is composed from the control fields. Either way a
stated device must be in `Device.objects.for_library(library)`, which reads
live rows only. The answer is `encode()`, so `settle(settle(x)) == settle(x)`.

`settle_edit` refuses, with a sentence each: no fact stated; a device picked
and "No device" checked; a device the library does not hold or removed. The
runner then draws the confirmation again on the same token, and the controls
are drawn empty. A batch whose later chunk is confirmed again can carry a
second statement under one correlation id. Each row's Undo reads its own
events, so the Undo is still correct.

## The act

`edit_one` dispatches one `DescribeSession` per row through `describe_session`.
The wrapper grows to the shape of the other session wrappers: it takes
`idempotency_key` and `source_metadata` and answers the `CommandResult`. The
two API callers do not change. A row that already reads so answers
`Unchanged`, counted "already so", and writes no event, so the Undo does not
see it. A row removed since the confirmation is refused by the command.

## The inverse

No column keeps a row's earlier device. `edit_back` reads the row's events.
For each fact, the family is the creation and that fact's change event. For
each fact the batch changed, the earlier value is the one stated by the most
recent event of the family before the batch's own. A fact the batch did not
change is not stated.

`edit_back` dispatches one `DescribeSession` with those values. As the other
restating inverses do, it reads the row as it stands and accepts the hazard:
a value set after the batch is overwritten. A second press of Undo answers
`Unchanged` from the command. A restated device removed since is refused by
the command with its own sentence.

The Undo reads the row through the plain manager, as the other session
inverses do, because `library_sessions` hides a row whose catalog game was
removed, and that row is still the library's to put back. That resolve moves
to `games/bulk_sessions.py`, and Move reads it there too.

## The tray and the confirmation

The session list's tray order is Finish, Move, Edit, Reclassify, Remove. The
label is "Edit…", and the three dots say the act asks first.

The preview columns are Game, Day, Duration, Device and Emulated.
