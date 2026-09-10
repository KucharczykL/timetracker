# State a start for the runs the conversion left empty

Issue [#1038](https://github.com/KucharczykL/timetracker/issues/1038). The model
is [the legacy PlayEvent
conversion](2026-09-06-issue-684-playthrough-conversion-design.md), whose
default branch this repairs.

#684 states a Playthrough from a legacy `PlayEvent` row. A tracked game that
never had one receives the ordinary default, and that default states `created`
alone. Most tracked games never had a row: a person who marked a game Played,
logged a session and moved on wrote a `GameStatusChange` and a `Session`, and
no `PlayEvent`. Their Game detail reads `Playthrough 1` with `Started` as `-`,
beside the session list and a History pane naming the day the status changed.

This pass states that day.

## What the numbers are

Measured against a production dump restored at 2026-09-09, taken before 0045
ran. The report target below prints the same figures against any copy.

| Reading | Rows |
|---|---|
| Live tracked `PlayerGame` on a live `Game` | 858 |
| of those, holding no `PlayEvent` row | 662 |
| of those, holding evidence of a start | 542 |
| — a live `Session` | 524 |
| — a status event away from Unplayed | 537 |
| of those, holding neither | 120 |

The two sources agree on the day for most rows that hold both. Where they
differ they differ by one day in the common case, which is a session that
crosses local midnight, and by years in the rare one, which is a status set
long after the play it describes.

## The rule

A run in scope takes one `started`, dated by the earlier of its two evidence
days. A run holding no evidence is left alone. No run takes a `completed`.

### Scope

A `Playthrough` is in scope when all of these hold:

1. `kind` is ordinary;
2. `removed_at` is null;
3. `start_recorded_at` is null;
4. `completion_recorded_at` is null;
5. its `PlayerGame` is live, and names a live `Game`.

Conditions 3 and 4 together are the default run and nothing else. #684 states
both acts for every row it converts, including a row that knew only one day, so
a converted run always states two markers. A run stating one marker and not the
other was stated by a person through #681 or #1010, and this pass does not
second-guess it: stating a start beside a completion a person entered would
also risk the reversal `StartPlaythrough` refuses.

Condition 5 keeps the pass off rows a rebuild would have to explain. It matches
what #684 already skips.

### The two evidence days

**The status day.** The earliest known day among the `LibraryEvent` rows where
all of these hold: the library is the run's, the type is
`PLAYERGAME_STATUS_CHANGED`, the `aggregate_id` is the run's `player_game_id`,
`source_metadata` names origin `backfill` and issue 676, the payload status is
one of played, completed, retired or abandoned, and `effective_time` states a
known day. The day is that value's `lower_bound`.

The events, not `games_gamestatuschange`. Three reasons, each sufficient: the
events are scoped to one library and a status-change row is not, so a shared
catalog game two libraries track would otherwise hand one library's day to the
other; the events carry the `effective_time` grammar, so a day that was never
known reads as never known rather than as a timestamp; and #771 takes the
table.

Origin `backfill` and issue 676, not every status event. A status change stated
since the cutover was written by a live command under #683, and what a live
status change should say about a run's start is #1034's question, not this
pass's. Restricting the filter keeps this pass to legacy data and keeps a
second run of it stable as the library goes on being used.

**The session day.** The earliest `TruncDate(timestamp_start, tzinfo=zone)`
among live `Session` rows on a live `Game` the run's library owns, where `zone`
is `DISPLAY_TIME_ZONE` resolved for that library's user. The ownership and the
zone are both read the way `games/reads/playthrough_activity.py` reads them, so
a run at a shared catalog game reads no session and the day never depends on
the server's zone.

**The earlier of the two.** A status set years after the play should not
outrank a session that proves the play, and a game marked Played with no
session should still state a day.

### Why no completion

Legacy abandoned, retired and completed each say a run ended, and
`_KIND_FOR_STATUS` already maps all three onto a completion. This pass states
none of them.

Before the cutover a finish was a `PlayEvent.ended`. These games had no row, so
no screen ever counted them as finished. `playthrough_count`, the Purchase list
Finished column and every statistics finish number read a stated completion
today, so stating 310 of them would invent 310 finishes that no reading of the
library ever showed. Parity with what the person saw before the wave outranks
the word the status uses.

The visible cost is that a run the person dropped goes on reading `Playing` or
`Dormant`, because `activity` is null only for a run whose completion is
stated. That is the wrong word for a dropped run, and it is already the wrong
word today for every one of these 662 runs. Naming the right one is out of
scope here and filed separately.

## Events

`games/backfill/playthrough_start.py`, in the shape of
`games/backfill/playthrough.py`, appends one `playthrough_started` per run in
scope that holds evidence, with `when` the day as a `TemporalValue` and `note`
blank.

- `recorded_at` is the instant the pass runs. Nothing recorded this before, and
  a past `recorded_at` would say something did. #684 could use a row's
  `created_at` because the row was the record; here the record is being made
  now.
- `correlation_id` is fresh per event. #685 paired an endpoint with a status
  event because both described one recorded act; this pass infers a day from an
  event rather than pairing with it.
- The idempotency key is `backfill:1038:playthrough-start:<playthrough_id>`. The
  identity is the run's, stable and not minted by this pass, so it may also be
  named in `command_input`.
- `source_metadata` is origin `backfill`, issue 1038, and the source that won,
  spelled `status` or `session`. The third key is what lets a later reader tell
  an inferred day from a recorded one without recomputing the inference.

The pass appends events. It does not dispatch. `games/backfill/playthrough.py`
states the reason and it holds here: a command's refusals guard what a person
states next, and this states what the library already recorded. The two
refusals that would have applied — a start already stated, and a completion
before the start — are covered by scope conditions 3 and 4, which admit neither
case.

No new aggregate is minted, so the identity ordering audit has nothing new to
hold.

## The gate

A migration `0048_playthrough_start_repair` runs the pass, checks it, then
commits, in the shape of `0045_playthrough_conversion_backfill`. Any mismatch
rolls the whole run back. It prints one machine-readable line to stderr and a
human summary to stdout, and names the first three mismatches in the exception
itself.

1. Every run in scope holding evidence states a start, whose day equals the
   evidence day the reader computes for it.
2. Every run in scope holding no evidence still states no act.
3. No run outside scope changed: every run stating a start after the pass
   either stated one before it or was in scope, and every run that stated one
   before still states the same day.
4. This pass stated no completion: the count of runs stating one is unchanged.
5. A second pass appends nothing.
6. The count of live ordinary runs stating no act falls by exactly the number
   of runs this pass repaired.

Replay parity is proven separately by `make verify-replay-parity`, which reads
every library and fails on a differing row. The projector already writes
`started` and `start_recorded_at` from this event type, so the pass introduces
no projector change to prove.

`load_sample_data` calls the pass beside `convert_library()` and refuses the
load on any mismatch, as it already does for #684.

## The report

`make report-playthrough-starts` runs `manage.py report_playthrough_starts`,
read-only, in the shape of `make preflight-playthroughs`. It takes `--user` or
`--all-libraries` and prints, per library and in total:

- runs in scope;
- runs holding a status day, a session day, both, neither;
- of the runs holding both, how many agree, and the distribution of the gap in
  days for the rest;
- which source won, counted;
- a sample of the first twenty runs by identity, each naming the game, the day
  and the winning source, the cap taken from the report's own `--sample-size`,
  which defaults as `preflight_playthroughs` does.

Deterministic: sorted by identity, never sampled at random, so two runs over
unchanged data print the same bytes. The report is the thing to run against a
restored copy before a deployment carries the migration.

## Reversibility

The stream is append-only and a projection rebuild replays what the stream
holds, so a rebuild does not take these events back. This pass therefore has no
rollback after it commits, and this specification does not claim one.

What stands in its place:

1. the report, run against a restored copy, before the deployment;
2. the gate, which rolls the run back before it commits on any mismatch;
3. `CorrectPlaythroughStart` from #1010, which states a better day for any one
   run afterwards, and is the same affordance a person has for a day they typed
   wrong themselves.

The deployment rehearsal is the existing one: `make verify-dump` restores,
migrates and drops a copy.

## What this reports and does not repair

The pass counts, and the report prints, runs whose `PlayerGame` states Unplayed
while a live session exists on the game. There are 131 in the measured dump.
The status is wrong and the session is evidence, so those runs are in scope and
do take a start; their status is left as it stands. Repairing a status is a
different act on a different aggregate, and it belongs to its own issue.

Also out: what `activity` should read for a retired or abandoned run, and the
count affordance #1024 owns.

## Testing

The evidence reader, over a built library:

- a session at 23:30 in a library reading `Europe/Prague` states that local day,
  not the UTC day before it;
- a removed session, a session on a removed game, and a session on a game the
  library does not own are each read as no session;
- a status event whose `effective_time` states no known day is read as no
  status day, and one stating a month states that month's `lower_bound`;
- a status event written by a live command, rather than the #676 backfill, is
  not read;
- where both days exist, the earlier wins, and the winning source is recorded.

The scope:

- a run stating a completion and no start is left alone;
- a run stating a start is left alone;
- an `imported_history` run is left alone;
- a removed run, a run under a removed `PlayerGame`, and a run at a removed
  `Game` are each left alone.

The pass:

- a second call appends nothing and reports the same counts;
- a run holding no evidence still states no act;
- no completion is stated, for any legacy status.

The migration, in the shape of `tests/test_playthrough_conversion.py`: a
library built to hold each case migrates, the gate passes, and each check fails
the migration when the condition it names is broken.

## Dependencies

- #684
- #1010
