# Correct a session's timing, description, and run

A `PlayerSession` states three independent facts: when it happened, what it
was, and which run it belongs to. Three commands state them, one each. Part of
the [session delivery wave](2026-09-12-session-wave-design.md), over the
[PlayerSession aggregate](2026-09-13-issue-689-playersession-aggregate-design.md).

## Why three commands

One command for all three would put a bulk move of runs one field away from a
bulk rewrite of time. #714's bulk move is the bulk form of the move command.

## The timing correction

`CorrectSessionTiming` holds `session_id` and one `TimingStatement`. The event
`.timing_corrected` holds one `TimingPayload`.

The whole statement is the transition law. Each statement is complete by its
shape, thus every mode can follow every other mode. A correction can make a
session run again.

The creation and the correction share one set of module functions: the
normalization, the payload builder, and every value refusal. A naive instant is
refused before the fingerprint, and so is a timestamp given as a written day.
An instant that a stated zone's calendar cannot hold is refused.

`build` compares `columns_for_timing(payload)` with the eight columns of the
row. The projector writes through the same function, thus the comparison and
the write cannot drift. An equal statement answers `Unchanged`. The refusals run
before the comparison.

`effective_time` is `stated_day_of(payload)`: the written day, or the start in
`day_zone`. A correction that moves only the end is dated by the start. An end
dates the act; a correction dates the session.

## The description

`DescribeSession` holds `note`, `device`, and `emulated`. `None` is a fact that
the caller does not state. An empty note clears the note. `StatedDevice(None)`
states no device. A command that states no fact is refused.

Each fact that differs from the row is one event: `.note_changed`,
`.device_changed`, `.emulated_changed`. The device is compared before it is
resolved, thus a restated removed device answers `Unchanged`. A new device must
be this library's and live. `.device_changed` holds a `Reference`, because the
reference index reads the annotation. A note that JSONB cannot store is refused,
and the note payloads refuse it and a padded note too.

## The move

`MoveSessionToPlaythrough` holds `session_id` and `playthrough_id`. The target
can be a run at another game, of any kind. A session reaches its game only
through its run, thus this is the remedy for a session logged against the wrong
game. The same run answers `Unchanged` before the target is read. `.moved` holds
a bare `ReferenceId`, as the creation does.

`_live_session` refuses a session under a removed run or game. No read finds
such a session.

## The events and the handlers

Each handler is one `amend`. The timing correction names all eight columns,
thus no value of the old mode stays. Of the five, only `.timing_corrected` holds
an `effective_time`.

## The surfaces

#702 owns the screens. Reset-to-now is `CorrectSessionTiming` with a
`TimedTiming`: start `now`, `started_at_zone` from the browser, `day_zone` from
the row, no end. The screen offers it on a running session; on a finished
session it makes the session run again. The edit of a session is two
acts: timing, then description.
