# A Playthrough start and a Playthrough completion

Issue [#681](https://github.com/KucharczykL/timetracker/issues/681). Parent
phase [#601](https://github.com/KucharczykL/timetracker/issues/601). Wave
review: [Playthrough delivery wave](2026-09-04-playthrough-wave-design.md).
Predecessor: [the Playthrough aggregate](2026-09-04-issue-679-playthrough-aggregate-design.md).

A Playthrough states two facts: it started, and it completed the main
objective. Each fact carries an optional date at any precision. This issue
states both, and refuses the pair that cannot be true.

## The endpoint has two parts

An endpoint is an act and a date, and the two are independent. "Played before"
is the act with no date: a library states that a run happened and knows nothing
about when. A legacy `PlayEvent` with a null `ended` is the same shape at the
other end.

`TemporalValue.unknown()` serializes to `None`, so a `TemporalValueField`
column holds NULL for an unknown date and NULL for an absent one. The columns
#679 shipped therefore cannot tell "started, date unknown" from "never
started", which is the plainest case the issue names.

Each endpoint is two columns. `started_at` is a nullable `DateTimeField`
holding the event's `recorded_at`; its null is the act that never happened.
`started_date` is the `TemporalValueField`, and its null is a date nobody
knows. The pair follows the naming rule in
[Naming](../../event-retention.md#naming): one act, one verb, and the column is
`<act>_at`.

The temporal columns #679 named `started` and `completed` are renamed to
`started_date` and `completed_date`, with their generated bounds renamed
alongside. `started` beside `started_at` reads as one fact stated twice; the
two columns sit on different time axes, and every query, screen and later
cutover reads both. The incumbent name is the wrong one, and it is two commits
old.

```
started_date                temporal_value
started_date_lower/_upper   date, generated, persisted
started_at                  timestamptz null   -- null: never started
completed_date              temporal_value
completed_date_lower/_upper date, generated, persisted
completed_at                timestamptz null   -- null: never completed
```

The bounds keep the shape #679 gave them, and the display-order index keeps its
name and its four fields under the new column names.

## The migration cannot rename in place

Django 6 refuses to modify a generated field, and detects this exact case:
`django/db/backends/base/schema.py` raises "Modifying GeneratedFields is not
supported" under the branch commented "Field used in a generated field was
renamed". A `RenameField` on `started` repoints the expression of
`started_lower`, so the autodetector's `AlterField` on that generated column
raises.

The migration therefore takes the four generated columns out and puts them back
under their new names:

1. `RemoveIndex` the display-order index, which names two of them;
2. `RemoveField` `started_lower`, `started_upper`, `completed_lower`,
   `completed_upper`;
3. `RenameField` `started` to `started_date` and `completed` to
   `completed_date`, now that nothing generated depends on either;
4. `AddField` the four generated columns under the new names, over the new
   expressions;
5. `AddField` `started_at` and `completed_at`;
6. `AddIndex` the display-order index over the renamed bounds.

A persisted generated column recomputes on add, and the table is small: it
holds one row per game tracked since #679. Production stands at
`0022_external_references`, so there the table does not exist yet and the whole
migration runs against nothing.

`makemigrations --check` must report no drift after the migration is written,
because the state operations and `games/models.py` have to agree on both the
names and the expressions.

## No constraint states the rule

The order rule is not a `CheckConstraint`, and neither is the pairing of
`started_at` with `started_date`. A constraint on a projection table refuses a
rebuild of events that are already recorded, and a rule added after an event is
recorded is exactly the case a rebuild has to survive. The projector is the
only writer, and its tests carry the invariant.

## The events

```
library.playthrough.started     payload {}   effective_time: the endpoint
library.playthrough.completed   payload {}   effective_time: the endpoint
```

The date rides in `effective_time`, which the charter defines as when the
player says the fact occurred, and which the Journal orders by. The status
events state their date the same way, and #686's preflight already reads
`effective_time` back off a recorded event to decide which day a fact landed
on. A date in the payload would give the same value a second home and every
later reader a second code path.

An unknown date is a null `effective_time`. The event's existence is the act,
so the two are never confused.

The payload is empty. `library.playergame.removed` sets the precedent: an
aggregate that already identifies itself states nothing more.

## The commands

```
CommandName.PLAYTHROUGH_START     = "library.playthrough.start"
CommandName.PLAYTHROUGH_COMPLETE  = "library.playthrough.complete"

StartPlaythrough(playthrough_id: UUID, when: TemporalValue | None)
CompletePlaythrough(playthrough_id: UUID, when: TemporalValue | None)
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

Both commands resolve the row the same way, and refuse the same five things.

A private resolver reads the playthrough inside the library, and refuses a row
of another library and a row that does not exist with one sentence, which names
no id. It is a third library-scoped resolver beside `tracked_game` and
`TrackGame._visible_game`, and it is the third caller that #909 merges.

- The `player_game` the run belongs to is removed. `CreatePlaythrough` already
  refuses this, with the same reason: a removed game is restored first.
- The playthrough itself is removed. Nothing stamps `Playthrough.removed_at`
  until #1011, so the refusal is inert; it is written here because the resolver
  both commands share is written here.
- The endpoint already holds the value asked for. The build returns
  `Unchanged`, per [a command that changes
  nothing](2026-08-28-issue-906-no-op-command-semantics-design.md): to do
  nothing is to reach that state. The comparison is over the canonical string,
  so an equal date at equal precision compares equal.
- The endpoint holds a different value. The build raises `CommandRejected`, and
  the sentence names correction. #1010 owns correcting a stated endpoint, and
  its own event is what keeps the earlier value legible in the stream. A second
  `library.playthrough.started` would say a run started twice.
- The two endpoints are certainly reversed. The rule is one function both
  commands call, over the value being stated and the value already recorded.

### The order rule

A completion earlier than a start is refused when the two cannot overlap in
that order:

```
refused when completed_date.upper_bound < started_date.lower_bound
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
    #: Both from the event, so replays agree.
    self.amend(
        Playthrough,
        event.aggregate_id,
        started_date=event.effective_time,
        started_at=event.recorded_at,
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

No note. #681's Scope named an optional note per endpoint. Nothing upstream
asks for one: the charter's Playthrough section states lifecycle facts only,
the wave review gives the row one note, #1010 owns writing and clearing it, and
the "optional note and source reference" in the charter belongs to the
Historical Playtime Record, a different aggregate. The legacy `PlayEvent.note`
is one note per row, so the conversion needs one, and #1010 lands before #684.
The issue text is edited to strike the note and to say this, before
implementation starts.

## Verification

- Both event types register, and their empty payloads round-trip through the
  vocabulary.
- Each command appends its event, with the stated date as `effective_time` and
  with a null `effective_time` for "Played before".
- The projection reads back the act and the date apart: `started_at` set with
  `started_date` null is a run that started on an unknown day.
- Each refusal has a test, and each carries a sentence.
- The order rule is tested over a table of precision pairs: day against day,
  day against month, month against year, a range against an atom, an unknown
  against each, and each pair in both statement orders.
- A repeated dispatch of one command returns `UNCHANGED`, and a repeated
  delivery under one idempotency key returns `REPLAYED`.
- A replay from an empty database reproduces every column of every row, over a
  library holding a started run, a completed run, a run with both, and a run
  with neither.
- The renamed columns leave `games/reads/playthrough_numbering.py` and the
  display-order index reading the same order as before.
- `make check` is green, `makemigrations --check` reports no drift, and
  `make audit-uuid-identity` passes.
