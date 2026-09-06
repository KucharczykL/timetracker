# A Playthrough start and a Playthrough completion

Issue [#681](https://github.com/KucharczykL/timetracker/issues/681). Parent
phase [#601](https://github.com/KucharczykL/timetracker/issues/601). Wave
review: [Playthrough delivery wave](2026-09-04-playthrough-wave-design.md).
Predecessor: [the Playthrough aggregate](2026-09-04-issue-679-playthrough-aggregate-design.md).

A Playthrough states two facts: the run began, and the run met its main
objective. Each fact carries a date at any precision, or no date, and a note.

## The endpoint has three parts

An endpoint is an act, a date and a note. The three are independent. "Played
before" is the act alone: the library states that a run occurred and knows no
day for it.

`TemporalValue.unknown()` serializes to null, so one `TemporalValueField`
column holds null for an unknown date and null for an absent one. A date
column alone cannot tell "started, day unknown" from "never started". A note
has the same problem: an empty string is both "no note" and "no act".

Thus the act takes a column of its own, and that column records the
statement:

```
started                 temporal_value      -- the stated date, null: unknown
started_lower/_upper    date, generated, persisted
start_recorded_at       timestamptz null    -- null: never started
start_note              text not null default ''
completed               temporal_value
completed_lower/_upper  date, generated, persisted
completion_recorded_at  timestamptz null    -- null: never completed
completion_note         text not null default ''
```

`started` and `completed` keep the names #679 gave them. The four generated
bound columns and the display-order index are unchanged. The migration adds
four fields, all nullable or defaulted. A row that exists before the migration
takes the defaults, which read correctly: it states no endpoint.

## The two names of one act

[Naming](../../event-retention.md#naming) gives an act the column `<act>_at`,
because a removal and the record of it are one instant. A start and the record
of it are not. The charter separates `recorded_at`, when timetracker received
the fact, from `effective_time`, when the player says the fact occurred.

Thus the past participle holds the stated date and the act's noun holds the
record: `started` beside `start_recorded_at`, and `start_note`. `started_at`
would put the record instant under a name that reads as the stated date, and
#1013 would offer it as a date facet under that reading.

One verb still runs through the act: `library.playthrough.started`,
`StartPlaythrough`, `start_recorded_at`.

## The two notes

An endpoint note is not the row's `note`, which #1010 states. The row's note
describes the run and belongs to no day. An endpoint note describes one act
within the run, and the
[Player Journal](2026-08-09-player-journal-design.md) places it on the day the
act carries. A legacy `PlayEvent` note keeps that meaning, undated when the
event was undated.

## No constraint states a rule

The order rule is not a `CheckConstraint`, and neither is the pairing of
`start_recorded_at` with `started`. A constraint on a projection table refuses
a rebuild of events that are already recorded, and a rule added after an event
is recorded is the case a rebuild must survive. The projector is the one
writer, and the tests carry the invariant.

## The events

```
library.playthrough.started     payload {"note": str}   effective_time: the date
library.playthrough.completed   payload {"note": str}   effective_time: the date
```

The date rides in `effective_time`. The status events state their date the same
way, and #686's preflight reads it back off a recorded event. A date in the
payload gives one value a second home and every later reader a second path.

An unknown date is a null `effective_time`. The event's existence is the act,
so the two are never confused.

The note is the payload, and it is always present: no note is the empty string.
One `PlaythroughEndpointPayload` serves both specs, under `STRICT_SCHEMA`. They
are two `EventSpec`s, so an issue that gives one of them a field gives it a
type of its own.

Each event takes a builder beside `playthrough_created`. A builder passes the
run's id as `aggregate_id` instead of minting one, because the aggregate
exists.

## The commands

```
CommandName.PLAYTHROUGH_START     = "library.playthrough.start"
CommandName.PLAYTHROUGH_COMPLETE  = "library.playthrough.complete"

StartPlaythrough(playthrough_id: UUID, when: TemporalValue | None, note: str)
CompletePlaythrough(playthrough_id: UUID, when: TemporalValue | None, note: str)
```

`when=None` is "played before": the act, and no day.

No field takes a default. The build compares the whole endpoint, so a default
`note=""` lets a caller restate a date, omit a note it never meant to touch,
and be refused for changing it.

A command names a run, not a game. A tracked game holds many runs, and #684
converts each legacy `PlayEvent` into one of them. #1012 owns the screen that
resolves "the current run of this game" before it dispatches.

`canonical_command_input` keeps a `TemporalValue` whole and
`games/events/idempotency.py` reduces it to its canonical string. Thus two
dispatches of one date fingerprint alike.

Two commands, not one command over an endpoint parameter. Each states one act
and maps to one event type, and the order rule is a function both call.

## The refusals

`library_playthrough()` reads the run inside the library. A row of another
library and a row that does not exist answer with one sentence, which names no
id. It is the third library-scoped resolver, beside `tracked_game` and
`TrackGame._visible_game`, and the third caller #909 merges.

Both commands then refuse:

- The `player_game` the run belongs to is removed. `CreatePlaythrough` refuses
  this for the same reason: a removed game is restored first.
- The run itself is removed. Nothing stamps `Playthrough.removed_at` until
  #1011, so the refusal is inert. It is here because both commands share the
  resolver that states it.
- The endpoint is already stated, and the restatement differs in the date or in
  the note. #1010 owns the correction, and its own event is what keeps the
  earlier value legible. A second `library.playthrough.started` says a run
  began twice.
- The two endpoints are certainly reversed.

A stated endpoint restated identically returns `Unchanged`, per [a command that
changes nothing](2026-08-28-issue-906-no-op-command-semantics-design.md).
Identical is both the date and the note, and the date compares over its
canonical string.

The marker decides which of the three answers applies, and the order is the
reason the marker exists:

```
if row.start_recorded_at is None:                     append the event
elif (when, note) == (row.started, row.start_note):   Unchanged
else:                                                 CommandRejected
```

A null marker is an act that did not occur, so the build appends whatever the
date and the note are. "Played before" on a fresh row is the pair
`when=None, note=""`, and a build that read emptiness as sameness records
nothing.

## The order rule

`endpoints_certainly_reversed()` refuses a pair that cannot overlap in that
order:

```
refused when started.lower_bound is not None
        and completed.upper_bound is not None
        and neither value states a qualifier
        and completed.upper_bound < started.lower_bound
```

Each guard drops a pair the comparison cannot judge, and a bare `<` raises
`TypeError` on the pairs the first two drop.

A bound is unknown for two reasons. The endpoint carries no date, or it is an
open-ended range: `../2024-06` bounds nothing below and `2024-01/..` bounds
nothing above. Both are grammar in [Temporal](../../temporal.md), and
`<temporal-field>` offers both. A window with no edge contradicts nothing.

A qualifier leaves the bounds where the bare value put them, so `2024-05-10~`
bounds to that day exactly, and a completion on the 9th would be refused —
which is what `~` was written to prevent. A range states a qualifier on each
end of its own, so the guard reads the top-level qualifier and both endpoint
qualifiers.

What remains is refused: a run started in May and completed in March. An
imprecise pair that can be consistent passes, so a run started on 10 March and
completed "in March" is permitted, because March ends on the 31st.

The rule reads both columns, which is why both endpoints are one issue. #1010
states the same rule for a correction, whichever endpoint moves.

## The projector

`Playthroughs` gains two handlers. Both amend, and neither projects: a
re-applied creation event must not take an endpoint back out. The endpoint
columns carry model defaults, so `_required_columns` exempts them and would not
report the mistake.

Every written value comes off the event — the date from `effective_time`, the
marker from `recorded_at`, the note from the payload — so a replay from an
empty database writes the row the live append wrote. The projector reads no
clock and no command context.

The two handlers read almost alike, so each handler's test reads the other
endpoint's marker back as null.

## Not in this issue

No screen, no form, no API route, and no `PlayEvent` write path: #687 switches
the writes and #1012 through #1015 switch the reads. No correction and no
removal: #1010 and #1011. No companion status change: #683.

An endpoint note is corrected by #1010 also. This issue states a note with the
act that carries it, and a later change to that note is refused with the
sentence a changed date gets.
