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
9. #1012 — read cutover: Game detail
10. #1013 — read cutover: the list page, its filters, sorts, quick facets, and
    saved presets
11. #1014 — read cutover: statistics and the stat links
12. #1015 — read cutover: the API router and the row element
13. #1026 — read cutover: the purchase Finished column and the `finished` sorts
14. #683 — the companion status change beside a lifecycle action
15. #1033 — Playing and Dormant runs
16. #688 — the PlayerGame and Playthrough replay-parity gate

Required orderings and the reason for each:

- `#679 → everything`. Nothing states a fact about a row no projector writes.
- `#686 → #684`. A preflight that runs after the conversion reports on events
  the conversion already wrote.
- `#681 → #684`. The conversion appends the same event types a live start and a
  live completion append, and the payload has to exist first.
- `#681 → #1010, #1011`. A correction corrects a stated fact.
- `#684 → #687`. A write cutover leaves the legacy table as the only record of
  facts it no longer writes, so every legacy row must already be an event.
- `#687 → #1012 … #1015, #1026`. A read switched before the write is switched
  reads a projection two writers disagree about.
- `#1012 → #683`. The companion action is an affordance beside a lifecycle
  control, and that control is on the surface #1012 delivers.
- `#1012 → #1013`. The split below leaves the list page reading legacy rows
  under a detail page that reads runs. #1012 leaves the scaffolding that holds
  the two together — a second row builder and the link translation — and #1013
  removes it. Either order needs a bridge; this one puts it where it is already
  specified.
- `#1013 → #1033`. The badge and the facet render on the list page, which reads
  legacy rows until #1013.
- `#1013, #1014, #1015, #1026 → #688`. The gate proves parity for surfaces that
  have all moved.
- `#688 → #771`. Legacy storage comes out after the gate is green.

Free to start together: #679 and #686. #686 reads legacy rows only, and has no
unmet dependency.

Free to run in parallel: #1012, #1014, #1015, and #1026 after #687, with #1013
behind #1012; #909 any time after #681. #1033 appends no event, so it neither
gates #688 nor waits on it, and it may run beside #683.

## Issue boundaries

### #679 — the Playthrough aggregate

Delivers the model, the migration, `library.playthrough.created`, the
`Playthroughs` projector, the `TrackGame` edit that states the default, the
display-number rule, and the system kind. Absorbs #680: a number decided after
the projection ships is a second migration over the same column.

Also relaxes `ProjectorRegistry` so one family holds many projectors, with the
ownership guard on the `(family, event type)` pair. It belongs here because
nothing else can consume it: no second `CURRENT_STATE` projector can exist
until it lands.

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

What shipped: `RemovePlaythrough` and `RestorePlaythrough` in
`games/commands/playthrough.py`, over the `library.playthrough.removed` and
`library.playthrough.restored` events, whose handlers write `removed_at` from
each event's own `recorded_at` so a replay reproduces the instant. The refusal
reads `BLOCKING_REFERRERS`, a tuple of `BlockingReferrer` beside its one
reader, empty until #700 and #701 give a Session its reference to a run. It is
a local tuple rather than a registry with a system check because `games.E009`
already refuses an unregistered reference *out of* a projection, and a second
registry for references *into* one would restate it. Each entry carries the
sentence a person is shown, because "move the sessions first" is advice only
its own referrer can give.

Beside it, the rule the wave did not state: a tracked game keeps one run, so
removal is refused where no other live ordinary run of the same `PlayerGame`
remains. It counts ordinary rows only — removing the bucket #700 creates takes
no ordinary run away — and it is scoped on the library explicitly, because a
row may name another library's `PlayerGame`, the drift
`audit_library_ownership` reports. Both commands answer `Unchanged` for state
that already holds, ahead of every refusal, so a repeat still succeeds after
the game itself was removed.

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
edit views, the form, and the API. The inline "+1" creation on Game detail goes
away rather than moving, because a tracked game already holds a run (#1024 owns
stating a count). The legacy table is still read. The rename of every
identifier that does not derive from the model's own name travels here too,
saved presets included.

### #1012 through #1015 and #1026 — switch reads

Split by surface, following #946, #947, #951, and #953:

- #1012 — the Game detail Playthrough section;
- #1013 — the paginated list page, `PlayEventFilter` and its relations,
  `playthrough_count`, the sort keys, the quick facets, and the saved presets
  that name them. #687 renamed every one of those identifiers and rewrote the
  stored presets; #1013 moves what they read onto the projection;
- #1014 — every read of `games__playevents__ended` in
  `games/views/stats_data.py` and `games/views/stats_links.py`, moved onto the
  generated bound columns, with the parity test each stat link already has;
- #1015 — the `/api/playthrough` router. #687 moved the router prefix and took
  the `play-event-row` custom element away, so what was left was the handlers
  that still read the legacy row. The path id moved onto the run there rather
  than in #771, because a list of runs can state no row id, and
  `games/reads/playthrough_provenance.py` went with it; #771 keeps the table;
- #1026 — the purchase list's Finished cell, `PURCHASE_SORTS["finished"]` and
  `GAME_SORTS["finished"]`, all three reading
  `Max("games__playevents__ended")`.

Two surfaces left #1012 while it was planned, and both carry the verdict on
their issues.

The **list page** went to #1013. This document gave #1012 the page and #1013
everything that orders and narrows it, and the two halves block each other:
`list_playthroughs` sorts on every request and filters whenever `?filter=` is
set, so a page switched to the projection under legacy sort keys answers a 500,
and a filter switched to the projection under a legacy queryset narrows one
model by another's fields. Game detail carries no sort, no filter and no quick
bar, so it is the half that moves alone.

The **purchase Finished column** went to #1026, opened for it. It reads as one
cell and is three reads: the cell, a purchase sort key `apply_sort` runs on
every request, and a Game sort key reachable through `?sort=` and through a
saved preset. Moving the cell alone leaves the column's own header ordering the
page by a number the column no longer shows. It also asks what one aggregate
over many games reports for a completion stated at less than day precision, a
question no other surface in this wave asks and that a cell cannot answer on the
way past.

### #683 — the companion status change

The "Also mark Game Played" box beside a first start, the "Also mark Game
Completed" box beside a completion, and the act each run row allows: Start on a
run with no start, Complete on a started one. Each surface appends its
lifecycle event and its status event under one `correlation_id`.

Moved after #1012. Its affordance sits beside a control that does not exist
until the read cutover renders one.

Its planning on 2026-09-09 settled three things the charter left open.

**The status is the strongest thing stated.** A game completed once stays
Completed, and a second run does not walk it back. So "Also mark Game Played"
renders only where the status is `Unplayed`, rather than rendering checked
beside every status as the charter's line reads. On any other status a checked
box would demote the game, which the charter forbids two paragraphs earlier.

**The act sits on the run, not beside the selector.** The charter describes an
optional action beside the compact status selector, and it was written before a
run had an editor of its own. #1012 renders every run four sections below that
metadata row, each with its actions. The lifecycle act belongs there, where the
row states which run it acts on. The selector is untouched and stays immediate.

**Two dispatches, not one command.** `record_run` is already one to three
dispatches, because a restatement states each endpoint separately. A single
command over both aggregates would have to replace that path and could not
serve the form at all. The pair shares a `correlation_id`, which is what
`_record_completed` shipped for.

### #1033 — Playing and Dormant runs

An unfinished run reads Playing or Dormant, from how long it has been since the
game was played, against a user-scoped threshold. Both sides filter. Neither is
stored, and neither touches a status.

Opened by #683's planning, from the question its status model raises: with the
high-water rule, a Completed game with a second run in flight reads plain
Completed, and nothing says a run is live.

Three answers were weighed, and the reasoning is recorded because the charter
rejected the last of them:

1. **a stated `stopped` endpoint on the run.** Refused. Stopping is not an act
   and carries no day — a person does not decide they have stopped playing a
   game, it becomes true quietly some months later. A field filled only when
   someone remembers is a field that is mostly wrong;
2. **a stored `playing` flag on `PlayerGame`.** Refused, and the charter's
   non-goal stands. It copies a fact the runs already state, so the two can
   disagree, and with several runs it sits one level above the thing it is
   about;
3. **a read over session recency, against a setting.** Taken. The app already
   knows the last day a game was played. Nothing is written, so nothing can
   drift, and the only matter of taste — how long is too long — is a display
   preference the person owns.

A third word joined the two this section names. #679 gives every tracked game a
run at track time, so a run at a game nobody has played is the common case, and
calling it Dormant would say a game tracked this morning went quiet. #1033
spells it `Never played` rather than `Unplayed`, because
`PlayerGameStatus.UNPLAYED` already spells that and Game detail prints a status
beside these rows.

`Session` holds no reference to a run, so the recency #1033 reads is the game's.
#700 and #701 narrow it to the run, recorded in the Sessions handoff below.

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

One more piece of this wave waits on the same reference. #1033 reads how long
it has been since a game was played, and answers that for the game rather than
for one of its runs, because no Session names a run. #700 and #701 narrow the
read to the run, inside the module #1033 adds. A game with one unfinished run
reads the same either way, so nothing #1033 renders is wrong meanwhile — it is
less specific than it will be.

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

Eight opened, the last of them while #683 was planned:

- #1010
- #1011
- #1012
- #1013
- #1014
- #1015
- #1026
- #1033

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
