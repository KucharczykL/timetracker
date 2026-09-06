# A Playthrough start and a Playthrough completion

Issue [#681](https://github.com/KucharczykL/timetracker/issues/681). Parent
phase [#601](https://github.com/KucharczykL/timetracker/issues/601). Wave
review: [Playthrough delivery wave](2026-09-04-playthrough-wave-design.md).
Predecessor: [the Playthrough aggregate](2026-09-04-issue-679-playthrough-aggregate-design.md).

A Playthrough states two facts: it started, and it completed the main
objective. Each fact carries an optional date at any precision and an optional
note. This issue states both, and refuses the pair that cannot be true.

## The endpoint has three parts

An endpoint is an act, a date and a note, and the three are independent.
"Played before" is the act alone: a library states that a run happened and
knows nothing about when. A legacy `PlayEvent` with a null `ended` is the same
shape at the other end, and one with a note and no date is the shape #684 has
to carry over.

`TemporalValue.unknown()` serializes to `None`, so a `TemporalValueField`
column holds NULL for an unknown date and NULL for an absent one. The columns
#679 shipped therefore cannot tell "started, date unknown" from "never
started", which is the plainest case the issue names. A note has the same
problem in a milder form: an empty string is both "no note" and "the act never
happened".

The act therefore gets a column of its own, and it is the record of the
statement rather than the date of the fact:

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

`started` and `completed` keep the names #679 gave them, and their four
generated bound columns are untouched, as is the five-field display-order
index.

The marker is named for what it holds. [Naming](../../event-retention.md#naming)
gives an act the column `<act>_at`, because a removal's act and the record of
it are one instant. A start's are not: the charter separates `recorded_at`,
when timetracker received the fact, from `effective_time`, when the player says
the fact occurred. `started_at` beside `started` would put the record instant
under a name that reads as the stated date, and #1013 would then offer it as a
date facet under that reading. So the past participle holds the stated date and
the act's noun carries everything about the statement: `start_recorded_at`,
`start_note`. The docs sweep adds that sentence to the Naming section, because
every later endpoint faces the same split.

The two notes sit beside the row's own `note`, which #1010 states. They are not
the same note. The row's note describes the run; an endpoint note describes one
act within it, and the Journal needs it dated to place it on a day. The
[Player Journal design](2026-08-09-player-journal-design.md) already reads it
that way: a lifecycle fact carries an optional note, a completion renders
`Finished in 12 days with a note: "…"`, and a legacy `PlayEvent` note keeps its
meaning as the note of a fact, undated when the event was undated. A row-level
note has no date and can be placed on no day.

## The migration

Four `AddField` operations, all nullable or defaulted, over a table holding one
row per game tracked since #679:

```
start_recorded_at, completion_recorded_at   DateTimeField(null=True, default=None, editable=False)
start_note, completion_note                 TextField(blank=True, default="")
```

Nothing generated is touched, so Django 6's refusal to modify a generated field
never comes up, and the autodetector writes the whole migration. Existing rows
take the defaults, which read correctly: a row created before this issue has
stated neither endpoint.

`makemigrations --check` must report no drift once it is written.

## No constraint states the rule

The order rule is not a `CheckConstraint`, and neither is the pairing of
`start_recorded_at` with `started`. A constraint on a projection table refuses a
rebuild of events that are already recorded, and a rule added after an event is
recorded is exactly the case a rebuild has to survive. The projector is the
only writer, and its tests carry the invariant.

## The events

```
library.playthrough.started     payload {"note": str}   effective_time: the endpoint
library.playthrough.completed   payload {"note": str}   effective_time: the endpoint
```

The date rides in `effective_time`, which the charter defines as when the
player says the fact occurred, and which the Journal orders by. The status
events state their date the same way, and #686's preflight already reads
`effective_time` back off a recorded event to decide which day a fact landed
on. A date in the payload would give the same value a second home and every
later reader a second code path.

An unknown date is a null `effective_time`. The event's existence is the act,
so the two are never confused.

The note is the payload, and it is always present: no note is the empty string.
An optional key would make the projector ask whether a value is absent or
empty, and the two mean the same thing here. The aggregate identifies itself,
so the payload states nothing else. One `PlaythroughEndpointPayload` TypedDict
serves both specs, under the same `STRICT_SCHEMA` as the creation payload; the
two are separate `EventSpec`s, so a later issue that gives one of them a field
gives it its own type.

Each event gets a module-level builder beside `playthrough_created`, and the
builders are where the difference from creation shows: they take the
playthrough's id as `aggregate_id` rather than minting one, because the
aggregate already exists.

```python
def playthrough_started(
    playthrough_id: uuid.UUID, *, when: TemporalValue | None, note: str
) -> NewEvent:
    return PLAYTHROUGH_STARTED.new(
        aggregate_id=playthrough_id,
        effective_time=when,
        payload={"note": note},
    )
```

## The commands

```
CommandName.PLAYTHROUGH_START     = "library.playthrough.start"
CommandName.PLAYTHROUGH_COMPLETE  = "library.playthrough.complete"

StartPlaythrough(playthrough_id: UUID, when: TemporalValue | None, note: str = "")
CompletePlaythrough(playthrough_id: UUID, when: TemporalValue | None, note: str = "")
```

`when=None` is "Played before": the act, no date, no Session and no duration.

A command names a playthrough, not a game. A tracked game has many runs, and
#684 converts each legacy `PlayEvent` into its own row. The screen that resolves
"the current run of this game" arrives with #1012, and resolves it before it
dispatches.

`canonical_command_input` keeps a `TemporalValue` field whole and
`games/events/idempotency.py` reduces it to its canonical string, so two
dispatches of one date fingerprint alike.

Two commands rather than one command over an endpoint parameter: each states
one act, each maps to one event type, and the shared rule below is a function
both call rather than a branch inside one build.

## The refusals

Both commands resolve the row the same way, and answer the same list.

A private resolver reads the playthrough inside the library, and refuses a row
of another library and a row that does not exist with one sentence, which names
no id. It is a third library-scoped resolver beside `tracked_game` and
`TrackGame._visible_game`, and it is the third caller that #909 merges.

- The `player_game` the run belongs to is removed. `CreatePlaythrough` already
  refuses this, with the same reason: a removed game is restored first.
- The playthrough itself is removed. Nothing stamps `Playthrough.removed_at`
  until #1011, so the refusal is inert; it is written here because the resolver
  both commands share is written here.
- The endpoint is already stated. The marker column decides this, never the
  date and never the note: a null `start_recorded_at` is an act that has not
  happened, so the build appends the event whatever the date and note are.
  "Played before" on a fresh row is exactly the pair `when=None, note=""`, and
  reading emptiness as sameness would record nothing at all.
- A stated endpoint is restated identically. The build returns `Unchanged`, per
  [a command that changes
  nothing](2026-08-28-issue-906-no-op-command-semantics-design.md): to do
  nothing is to reach that state. Identical means both the date and the note
  match, the date over its canonical string, so an equal date at equal
  precision compares equal.
- A stated endpoint is restated differently, in either the date or the note.
  The build raises `CommandRejected`, and the sentence names correction. #1010
  owns correcting a stated endpoint, and its own event is what keeps the
  earlier value legible in the stream. A second `library.playthrough.started`
  would say a run started twice.
- The two endpoints are certainly reversed. The rule is one function both
  commands call, over the value being stated and the value already recorded.

### The order rule

A completion earlier than a start is refused when the two cannot overlap in
that order:

```
refused when completed.upper_bound < started.lower_bound
```

Both bounds must be known. An endpoint with no date has no bound and is never
refused, and neither is an imprecise pair that could be consistent: a run
started on 10 March and completed "in March" passes, because March ends on the
31st. A run started in May and completed in March is refused, because the
completion's last possible day precedes the start's first possible day.

This is why the two endpoints are one issue. The rule reads both columns, and a
rule stated in one issue and enforced in another is a rule with two homes.
#1010 states the same rule for a correction, whichever endpoint the correction
moves.

## The projector

`Playthroughs` gains two handlers. Both amend, and neither projects: the
comment #679 left at `games/projectors/playthrough.py` says why. A re-applied
creation event must not take an endpoint back out.

```python
def _started(self, event: RecordedEvent) -> None:
    #: Every value from the event, so replays agree.
    self.amend(
        Playthrough,
        event.aggregate_id,
        started=event.effective_time,
        start_recorded_at=event.recorded_at,
        start_note=event.payload["note"],
    )
```

Every written value comes off the event, so a replay from an empty database
writes the row the live append wrote. The projector reads no clock and no
command context.

The endpoint columns keep their model defaults, so `_required_columns` exempts
them and the creation handler stays as #679 wrote it.

## What this issue does not do

No screen, no form, no API route, and no `PlayEvent` write path: #687 switches
writes and #1012 through #1015 switch reads. No correction and no removal:
#1010 and #1011. No companion status change: #683.

No correction of an endpoint note either. #681 states a note with the act that
carries it; changing or clearing one afterwards is the same correction #1010
owns, and it is refused here with the same sentence as a changed date.

## Verification

- Both event types register, and their payloads round-trip through the
  vocabulary, with a note and with the empty string.
- Each command appends its event, with the stated date as `effective_time` and
  with a null `effective_time` for "Played before".
- The projection reads back the act, the date and the note apart:
  `start_recorded_at` set with `started` null is a run that started on an
  unknown day, and it keeps its note.
- Each refusal has a test, and each carries a sentence.
- The order rule is tested over a table of precision pairs: day against day,
  day against month, month against year, a range against an atom, an unknown
  against each, and each pair in both statement orders.
- A repeated dispatch of one command returns `UNCHANGED`, and a repeated
  delivery under one idempotency key returns `REPLAYED`.
- A replay from an empty database reproduces every column of every row, over a
  library holding a started run, a completed run, a run with both, and a run
  with neither.
- A fresh row takes `StartPlaythrough(when=None, note="")` and comes back
  started, and the same command a second time answers `UNCHANGED`.
- `make check` is green, `makemigrations --check` reports no drift, and
  `make audit-uuid-identity` passes.
