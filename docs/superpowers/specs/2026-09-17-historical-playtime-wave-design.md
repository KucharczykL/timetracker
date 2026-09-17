# Historical Playtime delivery wave

Date: 2026-09-17

Parent epic: [#601](https://github.com/KucharczykL/timetracker/issues/601)

## Purpose

This document is the wave review #601 requires before the Historical Playtime
group begins. It replaces the placeholder ordering of #705 through #710 with a
dependency-ordered sequence, states the issue boundaries, and names the legacy
surface this wave turns out to own.

The six placeholders carry an outcome line and the shared acceptance block.
Two of them each describe half of one act, one is a table in another issue's
specification, and none of them knows that production already holds the data
this wave is about. This review merges two, opens four, and reorders the rest,
leaving eight issues, one of which is a follow-up placed outside the wave.

The Session wave is the model. Its topology is reused where the shapes match
and departed from where they do not: this wave has no deployment window and no
stack, because nothing here converts data behind a live write path.

Every empirical claim below was checked against a production dump taken on
2026-09-16, after #770 closed, and against the code.

## Product boundary

A Historical Playtime Record states a duration a person did not track as
sittings: hours from before tracking began, a figure read off a launcher, a
guess. This wave makes it an event-sourced aggregate, gives it an entry form
and a list, admits it to the statistics the charter allows it into, and gives
a person the act that turns a mis-recorded session into one.

It does not import anything, does not let a record name a Release, does not
merge the session and record lists into one, and does not touch the Journal.

## What the data says

The charter wrote this wave assuming no legacy data: "Historical or aggregate
playtime is not represented as fake Sessions" describes the target, and the
Session wave's census classified every legacy row as a session of one of three
modes. The production copy says otherwise.

Live sessions, 2,810 in one library:

| shape | rows |
|---|---|
| Timed | 2,668 |
| Duration-only | 142 |
| Duration-only, 8 hours or longer | 93 |
| Duration-only, 24 hours or longer | 49 |
| longest Duration-only row | 46 days 8 hours (World of Warcraft, note "561 hours") |

Of the 93 rows of 8 hours or longer, 61 are the sole session their game holds,
91 carry a device, 27 sit on games that also hold Timed sessions, and their
stated days are 89 distinct real-looking dates rather than a default. They
sum to about 4,700 of the library's 9,300 hours. Half of all recorded playtime
is a historical estimate stored as a session.

Every session-derived statistic is wrong because of them today: the longest
session, the highest per-game average, the unique-day count and the day chart
all read those rows as sittings. The playtime totals are right, because a
record and a session contribute to totals alike.

No rule tells an estimate from a session: a 9-hour sitting exists and so does
a 4-hour estimate. Duration alone suggests; a person decides. That is why the
reclassification below is an act a person performs, with a threshold to shape
the list and a bulk form to apply the decision to what the list shows.

## Aggregate and storage

### The record

A record carries:

- **duration**, whole seconds, positive;
- **when**, a `TemporalValue` at any precision the grammar admits, `unknown`
  allowed, required;
- **provenance**: `Estimated` (a guess), `Manually entered` (a figure the
  person read somewhere), `Externally measured` (written by an importer; the
  manual form never offers it);
- **playthroughs**, one or more, all of one PlayerGame, the whole duration
  belonging to them collectively and never divided among them;
- **device**, optional; **release**, reserved in the payload as `null`, no
  column and no control until ACCESS (#719–#724) ships the selector;
- **emulated**, as sessions carry, because conversion carries it over;
- **note**, free text;
- **source**, reserved in the payload as `null`, for the observation an
  importer reconciled against (provider, provider key, observation id,
  observed at). #798 defines the shape, adds the column and the list filter,
  and the event type does not change. A person's "48 h per Steam" is a note.

"One or more playthroughs, required" was chosen over "zero or more" so that a
game's playtime always flows through its runs and the per-run figures on Game
detail add up, and over "exactly one" so that "two playthroughs in the 2000s,
about 100 hours" stays one record naming two runs rather than two records with
a guessed split, which the charter forbids.

### Events

Aggregate `HistoricalPlaytime`; `aggregate_id` is the record id, a UUIDv7;
library from the event. Four types, registered in `DEFAULT_EVENT_TYPES` with
payload validation:

- `library.historicalplaytime.created` — the whole statement:
  `duration_seconds`, `when` (canonical temporal text), `provenance`,
  `playthroughs` (captured run references, at least one), `device` (captured
  reference or null), `emulated`, `note`, `release: null`, `source: null`.
- `library.historicalplaytime.restated` — the same shape. A record is one
  fact, so any change is a new statement of the whole fact. The projector
  overwrites every column.
- `library.historicalplaytime.removed` and `.restored` — the mark, as
  sessions.

Field-grained events (`duration_corrected`, `runs_changed`, …) were considered
and rejected: sessions needed the split because timing, description and run
are corrected at different times for different reasons; a record is corrected
as a unit. Storing records as `PlayerSession` rows under a `kind` was rejected
because it is the charter's named non-goal and would put a kind filter on
every session-derived figure forever.

### Commands

`RecordHistoricalPlaytime`, `RestateHistoricalPlaytime`,
`RemoveHistoricalPlaytime`, `RestoreHistoricalPlaytime`, in
`games/commands/historical_playtime.py`. Runs resolve through `library_row`.
The command refuses: runs of two different PlayerGames, the imported-history
bucket, a removed run or a run under a removed game, zero runs, a duration
under one second, a `when` the grammar refuses. The command admits every
provenance; the form offers two, and `Externally measured` is the importer's.
`Restate` answers `Unchanged` when the statement equals the row.

`ReclassifySessionAsHistoricalPlaytime`, in `games/commands/playersession.py`:
`RecordHistoricalPlaytime`, then a fifth session event,
`library.playersession.reclassified`, carrying the record's reference; two
dispatches under one correlation id, the pairing #683 established. The record
carries the session's duration, its `stated_day` (a Timed row's effective day)
as a day-precision `when`, its device, emulated flag, note and run, and
provenance `Manually entered` unless the caller states `Estimated`. Only
Duration-only rows are offered on screen; the command admits any live session
that has a duration, and refuses a running Timed row.

The event is not `removed`, because a removed session can be restored:
`RestoreSession` exists, #695's Undo reaches it, and the Trash (#795) will.
Restoring a reclassified session would count its hours twice while the record
stands. The projector marks `removed_at` and a new `reclassified_into` column
on the session row, so every `alive()` read excludes it as before, and
`RestoreSession` refuses a row whose `reclassified_into` names a live record,
with a sentence naming it. The undo of the pair is `RemoveHistoricalPlaytime`
then `RestoreSession`, which the refusal then admits, under one correlation id;
`restored` clears both columns.

### Projections

Both `ProjectionModel`, family `CURRENT_STATE`, projector `HistoricalPlaytimes`
in `games/projectors/historical_playtime.py`:

- `HistoricalPlaytime`: id, library, player_game (RESTRICT), duration, `when`
  as `TemporalValueField` with generated `when_lower` and `when_upper` (the
  `Playthrough.started_*` pattern), provenance, device (RESTRICT, null),
  emulated, note, created_at, removed_at. CHECK: duration positive.
- `HistoricalPlaytimeRun`: record (RESTRICT), playthrough (RESTRICT), library;
  unique on (record, playthrough). Its queryset declares
  `ancestor_marks = ("record",)`, so the referrer check reads the record's mark
  through it, as `PlayerSessionQuerySet` reads its parents'.

Both foreign-key pairs join `AUDITED_PROJECTION_REFERENCES`; #1017's audit
test enumerates them. The run side joins `BLOCKING_REFERRERS`, so
`RemovePlaythrough` refuses while a live record names the run, with a sentence
naming the remedy: restate the record onto another run, or remove it. Both
tables join the rebuild registry and the replay gate. `REMOVABLE_MODELS` does
not gain the record: removal is a command, as for sessions.

## Reads and statistics

`games/reads/historical_playtime.py` is the twin of `playtime.py`: records of
a library, narrowed to a year by containment, summed per game, per platform,
per month. Year scope is containment: a record counts in year Y when
`when_lower ≥ Y-01-01` and `when_upper ≤ Y-12-31`; month likewise; null bounds
(an `unknown` when) count in all-time only. A range or a decade therefore
contributes to all-time and to nothing narrower, which is the charter's
granularity rule.

`playtime.py` stops meaning "sessions" and starts meaning "playtime":

- totals and per-game figures return `PlaytimeBreakdown(tracked, historical)`
  with `total` derived, so every caller that shows a figure can show the
  split;
- the game list's `playtime_by_game`, `playtime_sort_key` and the
  `playtime_hours` filter compose `Coalesce(sessions, 0) + Coalesce(records,
  0)` into one number, because a column sorts one way;
- `playtime_matching`, which narrows the sum by a `PlayerSessionFilter`, stays
  sessions-only: a session filter cannot narrow records. Its label says so.

`game_historical_playtime(library, game, provenance=None)` is added beside
`game_playtime`, so an importer can compute the untracked remainder from
existing reads.

### Per platform

The charter admits records to platform totals only through a Release or a
Device. Today's per-platform figure groups sessions by the *game's* platform
column, and sessions reach it with no Release either. Records take the same
path, so the two sources agree; when #889 retires the column and the figure
moves to Release, both move together. This is a deviation from the charter's
letter, recorded here and in #709.

### Classification

#708 merges into #709: the classification is the table in the
specification of the issue that implements it, as #697's specification already
carries for four fields. Stated once, in `stats_data.py`:

| `StatsData` figure | sessions | records |
|---|---|---|
| `total_hours`, `total_playtime`, `top_10_games_by_playtime` | yes | yes, by containment |
| `total_playtime_per_platform` | yes | yes, through the game's platform |
| `month_playtimes` | yes | only when `when` lies inside the month |
| `total_sessions`, `unique_days`, `longest_session_*`, `highest_session_*`, `first_play_*`, `last_play_*`, streaks, the day chart | yes | never |

### Presentation

One `PlaytimeSplit` component renders `242 h · 142 h tracked · 100 h
historical`, omitting the split when the historical part is zero. The
charter's example says "~100h estimated"; the word is amended, because a
`Manually entered` figure read off a launcher is not an estimate and the bulk
conversion writes that provenance by default. Provenance shows per record, not
in the sum. It appears on
the Game detail headline, the stats totals, the navbar figure and the top-10
rows. The game list column shows the total alone. The Playthroughs table on
Game detail adds record durations to the run they name; a record naming two
runs shows under both with a "shared" mark and is never divided, so the column
may sum past the game's total, which the mark explains.

## Screens

**Game detail.** A "Historical playtime" section between Sessions and
Playthroughs: when, duration, provenance badge, runs, device; Edit and Remove
per row; Add. Its header is the `PlaytimeSplit`. Empty: "No historical
playtime."

**Entry and edit form**, a standalone page like add-session: run picker
(multi-select among the game's live ordinary runs, the default run
preselected), duration in hours and minutes, when (`temporal-field`, default
`unknown`), provenance (Estimated, Manually entered), device
(`<search-select>`), emulated, note. Edit dispatches `Restate`; an unchanged
submit shows the success toast and appends nothing. Remove goes through the
confirm page and offers Undo through `<toast-stack>` as #695 does, over
`RestoreHistoricalPlaytime`.

**Playtime page.** The nav entry "Sessions" becomes "Playtime" with two tabs.
Sessions is today's list, same route, same presets. Historical is a new list
over `HistoricalPlaytime`: `HistoricalPlaytimeFilter` (game, provenance, device,
emulated, duration hours, when, note, created; not run, because a record's
runs are a to-many hop and `check_comparison_through` refuses one — a run's
records are read from Game detail), a quick bar with
provenance and duration facets, sortable table, saved presets, the filter
builder, `GET /api/historical-playtime/` and `/{id}`, and the TypeScript
contract. Provenance is prominent in columns and facets because import will
lean on it.

One list over both aggregates, which would let the review convert rows in
place, was considered and deferred: it needs a read-side union view whose row
shape depends on what bulk actions (TABLE-01–03) and the imported row (#798)
must carry. It is filed as a follow-up placed after both. Two tabs lose
nothing meanwhile.

**Review facet** on the Sessions tab: a quick facet "Duration only, ≥ N h", N
editable, default 8. Each Duration-only row gains "Was an estimate", which
opens the entry form prefilled from the session with the run fixed. The
facet's toolbar gains "Convert all shown": every row matching the current
filter, not the page; a confirm page listing them; then `Reclassify` per row at
day precision, provenance Manually entered, one correlation id per row, in one
request, and a count when done. The population is bounded (142 rows exist);
chunking and retry are TABLE-03's if a later population outgrows one request. There is no stored "suggested"
state: the threshold is the suggestion, and a row a person does not convert
stays a session.

**Undo of a single conversion** from its toast reverses the pair under one
correlation id: remove the record, restore the session.

## Delivery order

1. **#705** — the aggregate: events, four commands, two projections, the
   projector, the replay-gate leg, the audit pairs, the `BLOCKING_REFERRERS`
   entry and `RemovePlaythrough`'s sentence.
2. **#706** — entry: the form for record and restate, the Game detail
   section, remove with Undo.
3. **#709** — reads and statistics: `historical_playtime.py`,
   `PlaytimeBreakdown`, the composed `playtime.py`, the game list column,
   sort and filter, the classification table.
4. **#1097** — the Playtime page: nav entry, two tabs, `HistoricalPlaytimeFilter`,
   quick bar, presets, API router, TypeScript contract.
5. **#710** — presentation: `PlaytimeSplit` on the headline, the stats, the
   navbar, the top-10 rows; the per-run column.
6. **#1098** — reclassification: the `Reclassify` command, the review facet,
   "Was an estimate", "Convert all shown", Undo of the pair.
7. **#1099** — gates: replay parity with a record in every leg, the `make bench`
   records workload and budgets, the `render_pages` diff attributed, the
   rehearsal on the production copy.

`#705 → {#706, #709, #1097} → #710 → #1098 → #1099`. #706, #709 and #1097
may start together after #705. #710 waits on #709. #1098 waits on #706, whose
form it prefills, and on #1097, whose tab it lives on.

No deployment window. Each issue leaves `main` incomplete rather than
inconsistent: #705 leaves tables nothing writes, #706 a form that records
rows no statistic reads yet, #709 figures that change nothing while no record
exists. Every issue merges alone. No stack.

Merged:

- **#707** — correction and deletion: the commands are #705's, the screens are
  #706's; a record is corrected as a unit, so there is no third act.
- **#708** — the classification is #709's table, not a separate act.

Opened: #1097 the Playtime page, #1098 the reclassification, #1099 the gates,
and #1100 the union list as a follow-up outside the wave.

## Cross-wave handoffs

### Release moves to ACCESS

A record naming a Release means something only once `LibraryEntry` says the
library has that Release, the reasoning that moved Release-on-Session there.
The payload reserves `release: null`; #719–#724 inherit the selector for
records as they did for sessions.

### The importer's affordances

#798 finds, from this wave: one write path (the same commands the form
dispatches), provenance `Externally measured` in the enum, column, filter and
badge, `source: null` reserved on `created` and `restated`, idempotency keys
the importer derives from provider, game key and observed-at, a default run on
every tracked game to hang a record on, `game_historical_playtime` by
provenance for the remainder, a bench workload shaped like an import, and
`Restate` as the sync verb so a counter never counts twice. The observation
store, a sync-run record and the reconciliation screen are #798's own tables
and screens; "when was the last import" is answered by them, not by a record.
`source_metadata` on the event envelope (#660, validated by #920) is where a
sync run stamps its id.

### Per platform through Release

#889 owns moving the per-platform figure off the game's platform column; when
it does, records and sessions move together.

### The union Playtime list

Filed as #1100. A read-side view `games_playtime_entry` over both
projections, an unmanaged model, one list, one filter vocabulary, row actions
by kind. Placed after TABLE-01–03, which decide what a bulk action needs on a
row, and after the #798 design, which decides what an imported row carries.
Not a projection: derived, no shadow, one `RunSQL` migration that changes
whenever either projection's columns do.

## Verification contract

- Replay from an empty stream reproduces both tables exactly; the replay gate
  has a record in every leg, one of them naming two runs.
- Every command's refusals are proven directly, including two PlayerGames in
  one statement, the bucket, and a removed run.
- `RemovePlaythrough` refuses a run a live record names and admits it after
  the record is restated away or removed.
- Statistics parity on the production copy, before and after "Convert all
  shown" over the 93 rows of 8 hours or longer: every playtime total equal to
  the second in every scope; `total_sessions` down by 93; the longest session,
  the highest average, the unique-day count and the day chart restated and
  each change attributed to a converted row.
- The Undo of one conversion leaves the stream one pair longer and both
  tables as they were; `RestoreSession` alone refuses a reclassified session
  while its record is live and admits it once the record is removed.
- `make bench` appends 600 records through 600 dispatches in one workload
  run, an import's shape, and meets the append and read budgets recorded in
  `docs/event-benchmarks.md`.
- `render_pages` before and after, every differing file attributed.
- Full `make check` green at every merged commit.

## What was applied

Merged: #707 into #705 and #706; #708 into #709.

Opened: #1097 the Playtime page; #1098 the reclassification act and review;
#1099 the gates; #1100 the union list, as a follow-up outside the wave.

Reordered: #709 stays reads and #710 stays presentation, with the page
between them and #710 behind #709; #705 first, as before.

Amended in the charter's assumptions, on the evidence of the production copy:
this wave owns legacy data after all, 142 Duration-only sessions of which 93
are estimates by any reasonable threshold, and the act that reclassifies them
is part of the wave rather than a follow-up.

Deviation recorded: records reach the per-platform figure through the game's
platform column, as sessions do, until #889.
