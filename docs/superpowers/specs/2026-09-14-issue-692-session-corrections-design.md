# Correct a session's timing, description, and run

A recorded `PlayerSession` states three independent things: when it happened,
what it was, and which run it belongs to. Three commands state them, one each.
Part of the [session delivery wave](2026-09-12-session-wave-design.md), over the
[PlayerSession aggregate](2026-09-13-issue-689-playersession-aggregate-design.md)
and beside [the end of a running session](2026-09-13-issue-691-session-end-design.md).

## Why three commands

A move between runs changes a reference from one projection to another. A
description corrects a typing error. A timing statement rewrites eight columns.
One command for all three would put a bulk reassignment one field away from a
bulk rewrite of time. #714 states the bulk form of the move. It is the bulk form
of one command, not a second way to state the same fact.

## The timing correction

`CorrectSessionTiming` holds `session_id` and one `TimingStatement`, which is
the union `CreateSession` holds. A statement names a whole mode and every value
that mode admits. The event carries one `TimingPayload`, which is the union the
creation carries.

The whole statement is the transition law. A mode pair needs no rule of its own,
because each statement is complete and consistent by its shape. An override with
no elapsed time cannot be stated: `CorrectedTiming` holds both instants.

Every transition is permitted, in both directions. A correction may leave the
session running, which is a Timed row with a start and no end. A person who
states an end by mistake has a remedy, and the trail shows the row went back to
running.

The refusals are about values: an end before a start, a negative duration, a
duration finer than a second, a duration of zero on a Duration-only statement, a
zone that the two tzdata sets do not both read, an unstated day zone, a zone for
an endpoint that the statement does not hold, and an instant with no offset.
`CreateSession` states each of these refusals today, as instance methods over its
own fields. This issue moves them to module functions that take the statement,
thus one set of rules serves the creation and the correction. The payload
builder, the zone normalisation, the note check and the device resolution move
with them. A refusal of a naive instant runs in `__post_init__`, before the
fingerprint.

`build` reads the row with `_live_session`. It makes the payload, then compares
`columns_for_timing(payload)` with the eight columns of the row. The projector
states that function. The comparison and the write therefore cannot drift. An
equal statement answers `Unchanged`.

`effective_time` holds `stated_day_of(payload)`: the written day, or the start
read in `day_zone`. A correction of a playthrough endpoint dates itself by the
value now stated, and this follows it. A correction that changes only the end is
therefore dated by the start. The end of a running session dates the act; a
correction states the whole session again, so it dates the session. The zone
check runs before the payload is made, thus `stated_day_of` never meets a zone
that tzdata does not know.

## The description

`DescribeSession` holds `note`, `device` and `emulated`. `None` is a fact that
the caller does not state. An empty note clears the note. `StatedDevice(None)`
states that there was no device, because `None` in that field is already a fact
not stated. `StatedDevice` is a NamedTuple, because the fingerprint writes a
NamedTuple as an array and refuses an object it does not know.

A command that states no fact is a `ValueError` in `__post_init__`. It is a
defect of the caller, and it carries no sentence.

Each fact has its own event: `.note_changed`, `.device_changed` and
`.emulated_changed`. `build` appends only the events whose value differs from
the row. A statement that the row already holds answers `Unchanged`. A
description states no timing act, and a timing statement states no description.

A note that holds a NUL byte is refused, as the creation refuses it: JSONB cannot
store the character, and the database refusal comes after the lock, with no
sentence.

`build` compares each stated fact with the row before it resolves anything. A
device that the row already names answers `Unchanged`, even when that device is
now removed. A device that differs is resolved with the function the creation
uses, which refuses a device of another library and a removed device.
`.device_changed` holds a `Reference | None` built as the creation builds its
device, because the reference index reads the payload annotation.

## The move

`MoveSessionToPlaythrough` holds `session_id` and `playthrough_id`. `build`
reads the session with `_live_session` and the target run with `_live_run`. The
target may record another game. A session logged against the wrong game has no
other remedy, and a session reaches its game only through its run, which stays
true after the move. The same run answers `Unchanged`. The target may be a run of
any kind, as the creation admits.

`_live_session` refuses a session whose run or game is removed. That holds for
the move too. `alive()` hides such a session from every read, thus no person can
find it to move it. A person who removed the wrong game restores it first.

The payload holds a bare `ReferenceId`, as the creation payload does. A required
reference kind for a projection would make the check of a replay read the live
table before the first row.

## The events

Five types, all under `library.playersession`. `.timing_corrected` holds one
`TimingPayload`. `.note_changed`, `.device_changed` and `.emulated_changed` hold
one value each. `.moved` holds the run. Only the timing correction holds an
`effective_time`. A description and a move happen on no day.

## The handlers

Five handlers, each one `amend`. The timing correction names all eight columns
through `columns_for_timing`, thus no value of the old mode stays in the row.
The other four name one column each. No event marks an act with an `<act>_at`
column: each states a value, and the value is the live state.

## The surfaces

This issue states the commands. #702 states the screens.

`reset_session` is "set the start to now". It is a timing act, and the
placeholder set holds no command for it. It is `CorrectSessionTiming` with a
`TimedTiming` statement: the start is `now`, `started_at_zone` is the zone the
browser reports, `day_zone` is the row's, and there is no end. The screen offers
it only on a running session. On a session with an end, the new start comes
after that end, and the command refuses it. The edit of a session is two acts,
not one. The times go to
`CorrectSessionTiming`, and the note, the device and the emulated flag go to
`DescribeSession`.
