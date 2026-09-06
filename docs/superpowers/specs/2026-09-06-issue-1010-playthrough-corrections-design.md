# Correct and rename a Playthrough

Issue [#1010](https://github.com/KucharczykL/timetracker/issues/1010). Parent
phase [#601](https://github.com/KucharczykL/timetracker/issues/601). Wave
review: [Playthrough delivery wave](2026-09-04-playthrough-wave-design.md).
Predecessor: [a Playthrough start and a Playthrough
completion](2026-09-06-issue-681-playthrough-endpoints-design.md).

A Playthrough carries four values a player writes: the name, the row's note,
and each endpoint's date and note. #679 gave the row the first two columns and
stated neither. #681 states an endpoint once and refuses a second statement.
This issue states all four again, after the first time.

## A correction is an ordinary command

The projection carries the current value. The stream carries what the value
was, and when the library said so. Nothing reads the earlier value yet; the
event is what keeps it legible, and `games/reads/playergame_history.py` is the
precedent for the reader that comes later.

Thus a correction adds an event type. It does not re-send the event #681
appends. A second `library.playthrough.started` says the run began twice, which
is the sentence #681 already refuses.

## No schema change

Every column this issue writes exists. `name` and `note` came with the row in
#679; #681 added the six endpoint columns and the four generated bounds beside
them. This issue adds no migration, no field and no index. A projection rebuild
is its whole reversal, which is what [the shadow
rebuild](2026-08-25-issue-667-shadow-rebuild-design.md) already provides.

## Two descriptive facts, one command

The name and the note are one act to a person: both are free text about the
whole run, neither carries a day, and one form saves them together. The name
and the note are two facts to the stream: an issue that later gives the note a
structure gives it its own type, and a reader that wants the renames reads one
event type instead of filtering a merged one.

`RecordPlayerGameFacts` settled this shape. One command carries both values,
`None` states no fact, and `build()` decides under the lock which value already
holds:

```
CommandName.PLAYTHROUGH_DESCRIBE = "library.playthrough.describe"

DescribePlaythrough(playthrough_id: UUID, name: str | None, note: str | None)
```

`None` and `""` are different answers. `None` leaves the stored value alone;
`""` clears the value, and a cleared name is how a player asks for
`Playthrough N` back. A command that states neither fact raises `ValueError` in
`__post_init__`, as `RecordPlayerGameFacts` does: a command that asks for
nothing would still claim an idempotency key.

`__post_init__` also strips each stated value. A name of three spaces is a
cleared name, not a name that reads as three spaces and silently costs the row
its number, and a note of one newline is no note.

The command carries no `expected` value and refuses no stale write. The form is
the last writer, and one library has one writer.

## The endpoint correction restates the pair

An endpoint is an act, a date and a note, and #681 states the three together. A
correction states the same pair the same way:

```
CommandName.PLAYTHROUGH_CORRECT_START      = "library.playthrough.correct_start"
CommandName.PLAYTHROUGH_CORRECT_COMPLETION = "library.playthrough.correct_completion"

CorrectPlaythroughStart(playthrough_id: UUID, when: TemporalValue | None, note: str)
CorrectPlaythroughCompletion(playthrough_id: UUID, when: TemporalValue | None, note: str)
```

No field takes a default, for the reason #681 gives: the build compares the
whole endpoint, so a default `note=""` lets a caller correct a date, omit a
note it never meant to touch, and be refused for changing it.

`when=None` after a correction is still "played before": the act stands, and
the day is unknown again. Both commands call `stated_date()` in
`__post_init__`, so `TemporalValue.unknown()` and `None` fingerprint alike and
compare alike, exactly as the lifecycle commands do.

Two commands, not one over an endpoint parameter. Each corrects one act and
maps to one event type, and the order rule is a function both call.

### The two readings of `None`

`None` means "state no fact" on `DescribePlaythrough` and "no day" on a
correction. One module, one word, two meanings, and a call site cannot see the
difference.

The pair is kept because each side is the honest reading of its own field. A
name is a value a command may decline to touch, and the command states which of
two independent facts it carries. A date is a value the domain itself calls
unknown: "played before" is the act with no day, `TemporalValueField` stores it
as null, and `stated_date()` exists to make the two spellings of it one. Giving
the correction a "leave the date alone" answer would need a third value beside
`None` and `unknown()`, for a form that always posts both parts of the
endpoint.

What keeps it legible is that neither command has both readings. The
correction's `note` is a plain `str` with no default, so no field of a
correction ever means "leave this alone".

## The marker does not move

A correction writes the date and the note. It does not write
`start_recorded_at` or `completion_recorded_at`.

The marker says the act occurred, and it holds the instant the library first
recorded it. A correction records a better value for a fact the library already
held; it does not record the act a second time. Moving the marker would say the
run started when the player fixed a typo, and #1013 would offer that instant as
a facet under that reading.

The correction's own instant is on the event, which is where the record of a
statement belongs when no column names it.

## The events

```
library.playthrough.name_changed         payload {"name": str}
library.playthrough.note_changed         payload {"note": str}
library.playthrough.start_corrected      payload {"note": str}  effective_time: the date
library.playthrough.completion_corrected payload {"note": str}  effective_time: the date
```

The two descriptive types follow `library.playergame.mastered_changed`: a value
column stated anew takes `<column>_changed`, and the event carries no
`effective_time`. A rename happens on no day in the world. Its sibling
`library.playergame.status_changed` does state one, because a status is a fact
about the player and the game that the Journal places on a day; the row's name
and its note are not.

The two endpoint types name the act this issue adds, and the verb runs through
the type, the command and nothing else — a correction touches no column of its
own. The corrected date rides in `effective_time`, as it does on the event it
corrects. A date in the payload would give one value a second home and every
later reader a second path. An unknown date is a null `effective_time`, and the
event's existence is not the act here — the marker written earlier is.

Four specs, three payload types, all under `STRICT_SCHEMA`. The two corrections
reuse `PlaythroughEndpointPayload`, for the reason #681 states: they are
separate `EventSpec`s, so an issue that gives one of them a field gives it a
type of its own. The two descriptive types take `PlaythroughNamePayload` and
`PlaythroughNotePayload`. `note_changed` does **not** reuse the endpoint
payload, though the shape is identical: that type's docstring binds its note to
an act whose date is the `effective_time`, and this note describes a run and
has no day. The harder reason is that a payload is a recorded schema, validated
on the way in and on the way out over rows already written. One type across two
families couples their futures: a key added to `PlaythroughEndpointPayload`
would change `note_changed`'s schema too, and under `STRICT_SCHEMA` every
`note_changed` row already written would then fail to read back. A second type
is the only way to keep the two free to move apart.

Each event takes a builder beside `playthrough_started`, and each passes the
run's id as `aggregate_id`.

## The refusals

`library_playthrough()` reads the run inside the library and answers a row of
another library exactly as it answers a row that does not exist. Every command
here goes through it.

`_endpoint_subject()` was the wrong name for the second resolver: it refuses a
removed run and a removed tracked game, and a rename is not an endpoint. Its
name is now `_live_run()`, which says what it returns — the run, when neither
mark is set — and both #681 commands read it under that name. The name was the
incumbent's mistake, not the newcomer's, and the rename cost two call sites and
the definition. #909 merges `library_playthrough()` with the
two other library-scoped resolvers; it does not merge this one, which states a
removal rule the other two have no column for.

Every command refuses:

- the run is outside the library, or is not a row;
- the `player_game` the run belongs to is removed;
- the run itself is removed. Nothing stamps `Playthrough.removed_at` until
  #1011, so the refusal stays inert.

`DescribePlaythrough` also refuses:

- a name longer than the column. Nothing else bounds it: pydantic validates a
  `str` with no length, the projector's `amend()` issues a raw `UPDATE`, and
  Postgres raises `DataError` inside a projector, which is a refusal with no
  sentence. The bound is a module constant taken from the field, in the shape
  `EVENT_TYPE_MAX_LENGTH` and `IDEMPOTENCY_KEY_MAX_LENGTH` already use, because
  django-stubs types `max_length` as `int | None`. The bound is deliberately a
  command-layer rule and not a `MaxLen` on the payload: a recorded schema is
  validated over rows already written, so a length it states can never be
  loosened. It lives in `build()` rather than `__post_init__` for the same
  reason the "no fact" check does not — a refusal a person reads carries a
  `sentence`, and `__post_init__` can only raise `ValueError`;
- a name being taken away from a run whose `kind` is not `ORDINARY`. The
  display number is counted over live ordinary rows only, so a blank name on
  the imported-history bucket leaves a row that has no name and no number, and
  `display_name()` raises `UnnumberedPlaythrough` on the one read that renders
  it. The refusal reads `run.name`, so it fires only where a name is actually
  taken away: a row is born blank, and a save that repeats that blank still
  states its note. This is the single place a kind refuses anything, and it
  refuses one value of one field: an imported-history run's endpoints, note and
  non-blank names are corrected like any other run's. Nothing gives such a row
  a name at creation, so the invariant is #684's to hold when it writes one.

Both corrections also refuse:

- the endpoint is not stated. `stated_start(run)` returns `None`, so there is
  nothing to correct, and the sentence names the act that states one. This is
  the distinction the marker exists for: correcting a stated endpoint is not
  the act of stating an endpoint that never happened;
- the two endpoints are certainly reversed, judged by the moved value against
  the stored one.

Neither correction can take an endpoint back out. Clearing a date leaves the
act; the act itself has no retraction, and none is stated anywhere in this
wave. #1011 removes the whole run, which is the only act that withdraws one.

## The order of the branches

[A command that changes
nothing](2026-08-28-issue-906-no-op-command-semantics-design.md) asks whether
the state already holds before it asks whether the state can be reached. A
correction inverts that pair, and only that pair:

1. the resolver's refusals — the library, then the two removal marks. #681's
   commands already answer these before they compare anything;
2. **the marker.** An unstated endpoint is refused here, ahead of `Unchanged`;
3. the value comparison. Equal is `Unchanged`; different is the event.

Step 2 is ahead of step 3 because an unstated endpoint holds exactly the values
a "played before" correction states. `started` is null and `start_note` is `""`
on a row that never started, so `CorrectPlaythroughStart(when=None, note="")`
compares equal to both columns. Under #906's order that dispatch answers
`UNCHANGED` and claims an idempotency key for a correction of an act that never
happened, and the player is told nothing is wrong.

`DescribePlaythrough` has no marker, so it has no inversion to state. Its two
refusals stand ahead of the comparison, and neither is excused by the row
holding a value the command repeats. The length refusal reads the command
alone: a column 255 characters wide cannot hold the name whatever the row says.
The kind refusal reads the row as well, because what it forbids is a name being
taken away, and only a row that has one can lose it. Both facts already holding
is then `Unchanged`; a save that moved the note alone appends one event.

A correction compares the whole pair — `(when, note)` against
`(stated.when, stated.note)` — and equality is `Unchanged`. The date compares
over its canonical string, which `stated_date()` in `__post_init__` and
`TemporalValueField` on the column make one spelling. The note compares over a
stripped string, for the same reason and in the same place: `__post_init__` is
the last point that can reach the fingerprint, which `dispatch()` takes from
the constructed command before `build()` runs. All four endpoint commands strip
it, so `"blind "` and `"blind"` are one statement and claim one key.

## The order rule

`endpoints_certainly_reversed(started=…, completed=…)` is called with the
moved value in its own slot and the stored value from the row in the other:

```
CorrectPlaythroughStart       started=self.when, completed=run.completed
CorrectPlaythroughCompletion  started=run.started, completed=self.when
```

The function is unchanged. #681 wrote it keyword-only for this call site: the
two arguments share a type, and a swap here is silent on every pair but the one
it exists to catch.

A correction that clears a date passes `None` and is never refused, because a
day nobody knows contradicts nothing.

A pair already stored reversed is not repaired by this rule. #681 refuses the
statement that would create one, so the pair can only arrive from a backfill,
and #684 owns what it writes.

## The name states no uniqueness

Two runs of one game may carry the same name, and a player may name a run
`Playthrough 2` while a different row derives that number. Nothing refuses
either. A display number is a read-time derivation over live ordinary rows, and
a name is what the player wrote; a rule that reconciled them would refuse a
name for what a sibling row does.

A blank name on an ordinary run is not a hole. `display_name()` reads the
number, and clearing a name is the way back to it.

## The projector

`Playthroughs` gains four handlers:

```
_name_changed          name = payload["name"]
_note_changed          note = payload["note"]
_start_corrected       started = effective_time, start_note = payload["note"]
_completion_corrected  completed = effective_time, completion_note = payload["note"]
```

All four `amend()`. None may `project()`: `project()` instantiates the model
and refuses a column no handler filled, so a correction event — which knows
nothing of `player_game`, `kind` or `created_at` — raises `TypeError` there.
What keeps a re-applied creation event from taking a correction back out is a
separate fact, and one #679 and #681 already hold: `_created` names four
columns, `project()` writes only the columns it is given, and `name`, `note`
and the endpoint columns all carry model defaults, so `_required_columns`
exempts them.

Every written value comes off the event, so a replay from an empty database
writes the row the live append wrote. No handler reads a clock, a command
context or the row it writes.

The two correction handlers name no marker column, which is what keeps the
first statement's instant across a rebuild: `project()` inserts the field
default, `replay()` walks the stream in sequence order, the `started` event
stamps the marker, and every correction after it leaves that column alone.

## Verification

Focused tests, beside the ones #681 wrote:

- `tests/test_playthrough_events.py` — the four specs are registered under
  their names, each payload validates strictly and refuses an extra key, and
  each builder passes the run's id through as `aggregate_id`;
- `tests/test_playthrough_command.py` — one refusal per bullet above; a
  rename, a note, and both together; `None` leaving the other value alone; a
  whitespace-only name reading as cleared; a cleared name on an ordinary run
  read back through `with_display_number()` as `Playthrough N`; a corrected
  date, a corrected endpoint note, a date cleared to unknown; `Unchanged` for
  each command; the reversed pair refused from either side; the marker
  unchanged across a correction;
- idempotency, which the acceptance block requires and #681 tests by name: a
  repeat under one key records nothing further, for one command of each shape;
  `unknown()` and `None` fingerprint alike on a correction, which is the
  regression `stated_date()` prevents; `name=None` and `name=""` fingerprint
  apart, which is what makes them two answers;
- `tests/test_playthrough_projection.py` — each handler over a recorded event,
  a replay from an empty database reproducing a row that was created, started,
  completed, renamed, noted and corrected on both endpoints, and a shadow
  rebuild of that row swapping with an empty diff. The marker is read off the
  `started` event's `recorded_at`, never off the row the correction has
  already amended: a row read afterwards agrees with a handler that moved the
  marker, and the test would pass with the defect it exists to catch.

The gate is the full `make check`, including `e2e/`. No screen changes, so no
e2e test is added.

Five places named this issue in the future tense: the comments on
`Playthrough.name` and `Playthrough.note`, the two refusal messages in
`games/commands/playthrough.py` that sent a reader to #1010 — the messages a
log carries, not the `sentence` a person reads — and the `Playthrough` bullet
in `CLAUDE.md`. Each now names the command a person uses.

## Not in this issue

No screen, no form, no API route: #1012 through #1015 switch the reads, and
#687 switches the legacy writes. No removal and no restoration: #1011. No
history reader over the correction events: nothing reads
`playergame_history.py` for Playthroughs yet either.

No repair of a pair already stored reversed, and no retraction of a stated
endpoint. No uniqueness over the name. No change to
`endpoints_certainly_reversed()`, to `stated_date()`, or to
`games/reads/playthrough_endpoints.py`, all three of which #681 shipped in the
shape this issue needs.
