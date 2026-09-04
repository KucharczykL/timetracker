# Playthrough delivery wave

Date: 2026-09-04

Parent epic: [#601](https://github.com/KucharczykL/timetracker/issues/601)

## Purpose

This document is the wave review #601 requires before the Playthroughs group
begins. It replaces the placeholder ordering of #679 through #688 with a
dependency-ordered, cycle-free sequence, states the issue boundaries, and names
every legacy surface and its owner.

The ten placeholder issues carry an outcome line and the shared acceptance
block. They identify real outcomes, but three of them cannot be built in the
stated order, two describe one act each and belong together, one describes five
subsystems, and three outcomes the cutover needs are absent. This review keeps
every surviving outcome, merges three, adds six, and moves two.

The delivered PlayerGame wave is the model. Its topology — one issue for the
aggregate and its creation, one per fact, one for removal and restoration, a
backfill, a write cutover, then read cutovers split by surface — is reused here
rather than invented again.

## Product boundary

Every PlayerGame has `Playthrough 1` from the moment the library tracks the
game. A Playthrough states two facts and no more: whether it started, and
whether it completed the main objective, each with an optional effective date.
It carries a name, a note, and nothing that resembles a status.

The wave replaces `PlayEvent` as the record of playthrough starts and
completions. It does not assign Sessions to Playthroughs, does not build the
Session organizer, and does not add ratings, reviews, or per-Playthrough
mastery.

## Aggregate and storage

`Playthrough` is the second projection model and the second command family. It
follows `PlayerGame`:

- the primary key is the creation event's `aggregate_id`, so both `UUIDv7Field`
  defaults are opted out;
- the projector `Playthroughs` is the only writer, in the `CURRENT_STATE`
  family;
- `removed_at` is the projector's, stated by a command.

Both endpoints are `TemporalValueField`, with generated lower- and upper-bound
columns beside each, exactly as `Release.release_date` carries
`release_date_lower` and `release_date_upper`. Three consumers need that shape:

1. "Played before" states a start whose date is unknown, which a `DateField`
   cannot express without a second flag;
2. the Sessions wave assigns a legacy Session by asking which interval contains
   its effective date, and an indexed bound column is what makes that query
   answerable;
3. the statistics that read `PlayEvent.ended` today read a bound column after
   the cutover, and the Journal reads the precision.

`PlayEvent.days_to_finish` is a `GeneratedField` over two `DateField`s. Its
replacement is derived from the two bound columns and is only defined when both
endpoints are precise enough to give one; the read cutover states the rule.

### The default Playthrough

A projector cannot mint an identity. Replaying an event twice must write the
same row, so the default Playthrough's `aggregate_id` cannot come from
`uuid.uuid7()` inside a handler, and it cannot come from a second projector
family reading the first one's rows.

The identity therefore comes from the command. `TrackGame` appends its
`library.playergame.created` event and a `library.playthrough.created` event
together, under one `correlation_id`. The library's first act on a game states
both facts, which is what "mandatory" means.

Two consequences the first issue owns:

- `TrackGame` is a shipped command; the change is an edit to it, and its
  existing idempotency key covers both events;
- every game already tracked by the #676 backfill has a `PlayerGame` row and no
  Playthrough, so the conversion issue backfills a default for each of them.

### Numbering and the imported-history bucket

A blank name displays as `Playthrough N`. `N` is a display number over the
live, ordinary Playthroughs of one PlayerGame, ordered by known start bound
NULLS LAST, then known completion bound NULLS LAST, then creation time.

The bucket named "Imported history — needs sorting" is an ordinary
Playthrough row with a system kind. It holds no lifecycle fact, and it is
excluded from the display numbering, so a removed or system row never shifts
the number a player learned.

This wave defines the kind and the numbering rule. It creates no bucket: the
wave that assigns Sessions is the wave that needs one.

## Delivery order

1. #679 — the Playthrough aggregate, its creation event, its projector, the
   default at `TrackGame`, the display numbering, and the system kind
2. #686 — the read-only preflight report over legacy `PlayEvent` rows
3. #681 — state a start and state a completion
4. #1010 — correct and rename a Playthrough
5. #1011 — remove and restore a Playthrough
6. #909 — the shared library-scoped reference resolver
7. #684 — convert legacy `PlayEvent` rows and backfill the missing defaults
8. #687 — switch lifecycle writes to commands
9. #1012 — read cutover: Game detail and the list page
10. #1013 — read cutover: filters, sorts, quick facets, and saved presets
11. #1014 — read cutover: statistics and the stat links
12. #1015 — read cutover: the API router and the row element
13. #683 — the companion status change beside a lifecycle action
14. #688 — the PlayerGame and Playthrough replay-parity gate

Required orderings and the reason for each:

- `#679 → everything`. Nothing states a fact about a row no projector writes.
- `#686 → #684`. A preflight that runs after the conversion reports on events
  the conversion already wrote.
- `#681 → #684`. The conversion appends the same event types a live start and a
  live completion append, and the payload has to exist first.
- `#681 → #1010, #1011`. A correction corrects a stated fact.
- `#684 → #687`. A write cutover leaves the legacy table as the only record of
  facts it no longer writes, so every legacy row must already be an event.
- `#687 → #1012 … #1015`. A read switched before the write is switched
  reads a projection two writers disagree about.
- `#1012 → #683`. The companion action is an affordance beside a lifecycle
  control, and that control is on the surface #1012 delivers.
- `#1013, #1014, #1015 → #688`. The gate proves parity for surfaces that
  have all moved.
- `#688 → #771`. Legacy storage comes out after the gate is green.

Free to start together: #679 and #686. #686 reads legacy rows only, and has no
unmet dependency.

Free to run in parallel: #1012, #1013, #1014, and #1015 after #687;
#909 any time after #681.

## Issue boundaries

### #679 — the Playthrough aggregate

Delivers the model, the migration, `library.playthrough.created`, the
`Playthroughs` projector, the `TrackGame` edit that states the default, the
display-number rule, and the system kind. Absorbs #680: a number decided after
the projection ships is a second migration over the same column.

Out: every other event type, every screen, the backfill.

### #686 — the preflight report

A read-only management command over legacy `PlayEvent` rows. It appends no
event and writes no row. It reports, per library: rows that convert without a
question, rows with no known endpoint, rows whose order is undecidable, games
with no rows at all, and the status events the conversion is expected to pair
with. #699 sets this precedent for the Sessions wave.

Moved ahead of the conversion. Its original position, after the conversion,
would have reported on the run's own output.

### #681 — state a start and state a completion

Two commands, two event types, one issue. They are one issue because a single
refusal spans both endpoints: a completion earlier than a start is refused, and
a rule stated in one issue and enforced in another is a rule with two homes.
Absorbs #682.

Includes "Played before": a start whose temporal value is unknown, with no
Session and no duration.

### #1010 — correct and rename

The name, the note, and either endpoint. A correction is an ordinary command
with its own event; the projection carries the current value and the stream
carries what it was.

### #1011 — remove and restore

Mirrors #675 for this family. It owns the question the other issues do not:
what a removed Playthrough means for the Sessions that will point at it. The
answer this wave commits to is that removal is refused while any Session names
the row, and the refusal is inert until the Sessions wave creates the reference.

### #909 — the shared resolver

#601 gives this wave the decision. `_tracked_game` in
`games/commands/playergame.py` is a private library-scoped resolver, and
`TrackGame._visible_game` is a second, wider one beside it. The Playthrough
commands need a third: resolve a Playthrough within the library, and refuse a
reference from another one. Three callers is the evidence one family could not
give.

### #684 — convert the legacy rows

One backfill, in the shape of `games/backfill/playergame.py`:

- every live `PlayEvent` becomes a Playthrough with its recorded endpoints,
  ordered by the rule #679 states;
- every tracked game with no `PlayEvent` receives the ordinary default;
- an unambiguous lifecycle and status pair is appended under the
  `correlation_id` of the status event #676 already recorded.

That last clause is why #685 cannot be a separate issue. `correlation_id` is a
column on an immutable row. The pairing is expressed by choosing the id at the
moment the lifecycle event is appended, which is this issue's append.
`games/backfill/playergame.py` anticipated exactly this and recorded a fresh id
per event so that one existed to adopt.

The run reports its counts and its evidence, and #686 has already published
what the run should find.

### #687 — switch writes

Every path that writes a `PlayEvent` dispatches a command instead: the add and
edit views, the form, and the inline creation on Game detail. The legacy table
is still read.

### #1012 through #1015 — switch reads

Split by surface, following #946, #947, #951, and #953:

- #1012 — the Game detail Playthrough section and the list page;
- #1013 — `PlayEventFilter` and its relations, `playevent_count`, the sort
  keys, the quick facets, and the saved presets that name them;
- #1014 — every read of `games__playevents__ended` in
  `games/views/stats_data.py` and `games/views/stats_links.py`, moved onto the
  generated bound columns, with the parity test each stat link already has;
- #1015 — the `/api/playevent` router and the `play-event-row` custom
  element with its registered props.

### #683 — the companion status change

The checked "Also mark Game Played" beside a first start, the checked "Also
mark Game Completed" beside a completion, and the optional action beside the
compact status selector. One command appending a lifecycle event and a status
event under one `correlation_id`.

Moved after #1012. Its affordance sits beside a control that does not exist
until the read cutover renders one.

### #688 — the gate

Unchanged. Empty-database replay, current-state parity, and idempotency across
both families together.

## Cross-wave handoffs

### Sessions own the assignment

The charter describes assigning legacy Sessions to Playthroughs, the
imported-history bucket, and the organizer in one passage. This wave splits
that passage by what each half needs:

- this wave defines the bucket's kind and the numbering rule that skips it;
- #700 and #701 assign Sessions, create the bucket where a library needs one,
  and record the interval reasoning;
- #714 through #717 deliver the organizer and reconcile what the assignment
  left ambiguous.

The reason is that `Session` has no reference to a Playthrough and is not
evented yet. Adding the column to the legacy row now means writing it twice:
once as an ordinary field, and again when #701 makes it a projection.

### Catalog follow-ups do not block this wave

The open catalog follow-ups sit in catalog write paths and catalog screens that
this wave does not touch:

- #979
- #980
- #981
- #990
- #991
- #993
- #994
- #997
- #998
- #999

One is inherited rather than blocking: #977 offers `removed_at` as a filter
operand on every model, and #1013 adds a model. It stays owned by the filter
audit, #765 through #767.

### Cleanup

- #771 removes the legacy `PlayEvent` and `GameStatusChange` storage, after
  #688.

## Migration, rollback, and reconciliation

The conversion appends events and writes no legacy row, so its reversal is the
projection rebuild #667 already provides. Its idempotency keys carry the issue
number, as #676's do, so a partial run resumes rather than duplicating.

Production stands at `0022_external_references`, which is behind the #676
backfill. The conversion therefore runs after that backfill in the same
deployment and must be verified in that order against a restored copy, through
`make verify-dump`.

## Verification contract

Each issue keeps the standing acceptance block. The wave adds:

1. the default Playthrough exists for every tracked game, stated by an event,
   after both #679 and #684;
2. the display number is stable across a projection rebuild;
3. an unambiguous legacy pair shares one `correlation_id` with the status event
   #676 recorded;
4. every preflight count in #686 matches the conversion's own report in #684;
5. the statistics that read a finish date report the same values before and
   after #1014, for a restored production copy;
6. the empty-database replay in #688 reproduces both families together.

## What was applied

Three issues closed as merged, each with the reason on the closing comment:

- #680, into #679
- #682, into #681
- #685, into #684

Six opened:

- #1010
- #1011
- #1012
- #1013
- #1014
- #1015

Seven were retitled to the delivery order above, because the new slices would
otherwise collide with the `PLAY-05`, `PLAY-09` and `PLAY-10` labels the
placeholders held:

- #679
- #686
- #681
- #684
- #687
- #683
- #688

#601's Playthroughs section now carries the order, the merges, the additions
and the deferral. Its Sessions section carries the other half of the deferral,
and the #909 line names its placement inside this wave.
