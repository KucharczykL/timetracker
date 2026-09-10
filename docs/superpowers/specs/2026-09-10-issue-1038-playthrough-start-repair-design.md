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
ran. Every figure below was reproduced twice, once per reviewer. The report
target prints the same figures against any copy.

| Reading | Rows |
|---|---|
| Live tracked `PlayerGame` on a live `Game` | 858 |
| of those, holding no `PlayEvent` row | 662 |
| of those, holding evidence of a start | 542 |
| — a live `Session` | 524 |
| — a status event away from Unplayed | 537 |
| — both | 519 |
| of those, holding neither | 120 |

Status of the 542: abandoned 287, unplayed 137, played 95, retired 21,
completed 2.

The two evidence days agree for 495 of the 519 rows that hold both, read in the
library's own zone. Of the 24 that disagree:

- 2 differ by one day, which is a session that crosses local midnight;
- 14 differ by two to 56 days, and these are batch status sweeps rather than
  play — three games read a status day of 2025-05-01 and a first session on
  2025-05-07, and `games_gamestatuschange` holds four to nine rows stamped with
  that same one day;
- 8 differ by years, which is a status set long after the play it describes.

Read in UTC instead, the same data manufactures 47 further one-day gaps that do
not exist in local time. That is the measurement behind the zone rule below.

## The rule

A run in scope takes one `started`, dated by the earlier of its two evidence
days. A run holding no evidence is left alone. No run takes a `completed`.

### Scope

A `Playthrough` is in scope when all of these hold:

1. `kind` is ordinary;
2. `removed_at` is null;
3. `start_recorded_at` is null;
4. `completion_recorded_at` is null;
5. its `PlayerGame` is live, and names a live `Game`;
6. its `playthrough_created` event carries `source_metadata` naming origin
   `backfill` and issue 684.

Condition 6 carries the weight, and conditions 3 and 4 alone do not. A person
may create a live ordinary run stating neither act — `CreatePlaythrough` allows
it and `tests/completed_runs.py` pins it — and this pass must not date a blank
somebody chose. #679 states a blank run at track time as well, for a game
tracked after the cutover, and what a live status change should say about such
a run is #1034's question. Condition 6 names exactly the runs #684 minted with
no acts (`games/backfill/playthrough.py:384`), which is the debt this pass owes,
and it keeps a second pass stable as the library goes on being used.

A run stating one marker and not the other was stated by a person through #681
or #1010, and this pass does not second-guess it: stating a start beside a
completion a person entered would also risk the reversal `StartPlaythrough`
refuses.

Condition 5 keeps the pass off rows a rebuild would have to explain. It matches
what #684 already skips.

### The two evidence days

**The status day.** The earliest known day among the `LibraryEvent` rows where
all of these hold: the library is the run's, the type is
`PLAYERGAME_STATUS_CHANGED`, the `aggregate_id` is the run's `player_game_id`,
`source_metadata` names origin `backfill` and issue 676, the payload status is
one of played, completed, retired or abandoned, and `effective_time` states a
known day. The day is that value's `lower_bound`.

Those four statuses are the whole list. Legacy `Game.Status` held u, p, f, r and
a, so a #676 event can carry no other word, and shelved in particular cannot
appear. Writing "away from Unplayed" would read as five.

The read is per library, not per run: it reuses `candidate_events(library)` from
`games/preflight/playthrough.py`, which already pays one scan of the unindexed
table for a whole library and reads the day in Python. A per-run query would
pay 858 scans. For the same reason `temporal_has_known_day_q` cannot serve here:
it reads the generated bound columns beside a `TemporalValueField`, and a
`LibraryEvent` payload has none. The known day is read in Python from the
deserialized value, as the preflight already reads it.

The events, not `games_gamestatuschange`. Three reasons, each sufficient: the
events are scoped to one library and a status-change row is not, so a shared
catalog game two libraries track would otherwise hand one library's day to the
other; the events carry the `effective_time` grammar, so a day that was never
known reads as never known rather than as a timestamp; and #771 takes the
table.

Origin `backfill` and issue 676, not every status event. A status change stated
since the cutover was written by a live command under #683, and what a live
status change should say about a run's start is #1034's question, not this
pass's.

**The session day.** The earliest `TruncDate(timestamp_start, tzinfo=zone)`
among live `Session` rows on a live `Game` the run's library owns, where `zone`
is `DISPLAY_TIME_ZONE` resolved for that library's user. The ownership and the
zone are both read the way `games/reads/playthrough_activity.py` reads them, so
a run at a shared catalog game reads no session.

**The two zones do not match, and the status day keeps its own.** A status day
was frozen when #676 ran, by `transition_effective_time` in
`games/backfill/playergame.py:80`, which calls `timezone.localtime()` and so
reads the *server's* `TIME_ZONE` at that moment. The session day is read now, in
the *viewer's* `DISPLAY_TIME_ZONE`. Recomputing the status day in the viewer's
zone is not possible: the event states a day, and the timestamp it came from is
in a legacy table #771 takes. The pass therefore compares a frozen day against a
viewer-zone day, and the report prints both so the mismatch is visible. Where
the two zones differ the comparison may be off by one day, which is the same
size as the smallest real disagreement measured.

**The earlier of the two.** A status set years after the play should not
outrank a session that proves the play, and a game marked Played with no
session should still state a day.

The rule is wrong for the batch-sweep case, and knowingly so. Fourteen of 519
rows take a status day two to 56 days before any recorded play, because that day
is a bulk status review rather than play — STASIS: BONE TOTEM reads status
played on 2025-03-22 and its first live session on 2025-05-17. Preferring the
session day instead would be wrong for the 8 years-apart rows, which is the
larger error on the same data. A person corrects any one of them with
`CorrectPlaythroughStart`.

### Why no completion

Legacy abandoned, retired and completed each say a run ended, and
`_KIND_FOR_STATUS` already maps all three onto a completion. That is 310 of the
542 in scope: 287 abandoned, 21 retired, 2 completed. This pass states none of
them.

The 287 abandoned were never counted as finished on any screen. Stating a
completion for them would invent 287 finishes no reading of the library ever
showed.

The other 23 are counted as finished today, on the all-time statistics page
alone. `PurchaseQueryset.finished()` (`games/models.py:933`) ORs
`tracked__status__in=DONE_STATUSES` into its condition, and
`games/views/stats_data.py:248` still calls it; `purchases_finished()`
(`games/views/stats_links.py:159`) mirrors the same OR so the drill-down link
matches the number. The Purchase list read the same way until #1026 moved it to
the projection, so those 23 now read finished on one screen and unfinished on
the other. That split is live on `main` today and this pass does not cause it.
Stating a completion for the 23 would settle it in one direction without a
person's word, so this pass leaves it, and naming the right answer for
`finished()` belongs to its own issue.

Every year-scoped finish number always required a dated finish, and a status
carries no day beyond the one #676 recorded, so none of the 310 was ever counted
in a year.

## What moves on the screens

Stating a start is not only the Started cell. Each of these follows from the
same event, and the plan carries a test for each:

- **The blank run stops being adoptable.** `run_to_adopt`
  (`games/reads/playthrough_runs.py:86`) answers nothing once the run states an
  act, so **Add playthrough** on those 542 games creates a *second* run rather
  than filling in the first. That is the intended reading — the run is no longer
  blank — but it changes what one press does on 542 games.
- **The green one-press button changes act.** `games/views/playthrough_rows.py:201`
  offers `start` while no start is stated and `complete` afterwards, so the
  button title goes from `Started today` to
  `Completed today, also marks the game Completed`.
- **18 runs read Dormant where they read Never played.** `activity_day_expression`
  coalesces the latest session day with `started_lower`, so the 18 runs holding a
  status day and no live session gain a non-null day, and every one of those days
  is older than the 30-day default threshold. The 524 runs holding a session
  already read Playing or Dormant from the session alone and do not move.
- **The Started column, the started filters, the `IS_NULL` modifier, the started
  sort, the edit form's prefill, the four API keys and any saved preset naming
  a started criterion** all read the stated value from this day forward.
- **`Playthrough N` does not move.** Numbering is derived at read time from the
  runs a game holds, and this pass adds no run.

The condition word for a dropped run stays wrong: `activity` is null only where
a completion is stated, so an abandoned run goes on reading Playing or Dormant.
That is true on `main` today for 524 of these 662 runs and becomes true for 18
more. Naming the right word is out of scope here and filed separately.

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
  an inferred day from a recorded one without recomputing the inference, and it
  is what the amendment below reads. #920 revisits the shape of that mapping;
  a third key is accepted today.

Both reads pin their columns by name, as `_PLAYEVENT_FIELDS` does in #684 and
for the same reason: a `.only()` list written out fails loudly when a column is
renamed, where a bare query would quietly read a migrated model.

The pass appends events. It does not dispatch. `games/backfill/playthrough.py`
states the reason and it holds here: a command's refusals guard what a person
states next, and this states what the library already recorded. The two
refusals that would have applied — a start already stated, and a completion
before the start — are covered by scope conditions 3 and 4, which admit neither
case.

No new aggregate is minted. The identity ordering audit reads event rows rather
than aggregates, so nothing new enters it either way; `recorded_at` is now, so
the keys this pass appends sort after every key already in the stream. The gate
runs `ordering_violations()` regardless, because that argument is the kind a
check should carry rather than a paragraph.

## What #684 must change

`reconcile()` fails on every repaired game unless it is amended, and that is not
an edge case.

`_rows_for_games` (`games/backfill/playthrough.py:425`) seeds `{game_id: []}`
for every live tracked game, so the `rows is None` skip at `:699` never fires
for a game holding no `PlayEvent`. `_reconcile_game` therefore runs with an
empty row list, and a repaired run trips three codes at once: `RUN_DISAGREEMENT`
(`:594`), because the rows say nothing and the runs now say one shape;
`MISSING_MARKER` (`:611`), because the run states a start and no completion; and
`DISPLAY_ORDER_DISAGREEMENT` (`:663`), because the run orders against an empty
list. `load_sample_data` calls `reconcile()`, so `make check` goes red for all
542.

The amendment: `reconcile()` reads the repaired set for the library — one query
for `playthrough_started` events whose `source_metadata` names issue 1038,
collecting their `aggregate_id` — and `_reconcile_game` reads a run in that set
as stating no act. All three checks then pass, and check 7 still counts the run
as the one actless default a game may hold, so it keeps its teeth.

Ordering the two passes around each other in `load_sample_data` is not an
alternative. It would leave `reconcile()` false for any later call, including
one a test makes, and the check that is only true when run in one order is not a
check.

`load_sample_data` calls this pass after `convert_library()` and refuses the
load on any mismatch, as it already does for #684.

## The gate

A migration `0048_playthrough_start_repair` runs the pass, checks it, then
commits, in the shape of `0045_playthrough_conversion_backfill`: one
`RunPython` with `migrations.RunPython.noop` as its reverse and
`elidable=True`. Any mismatch rolls the whole run back. It prints one
machine-readable line to stderr and a human summary to stdout, and names the
first three mismatches in the exception itself.

The number is free today. #770 and #771 both take a table and both land in this
wave, so the plan re-reads the highest applied number before writing the file.

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
7. `reconcile()` and `ordering_violations()` from #684 both answer clean for
   every library the pass touched.

Replay parity is proven separately by `make verify-replay-parity`, which reads
every library and fails on a differing row. The projector already writes
`started` and `start_recorded_at` from this event type
(`games/projectors/playthrough.py:44`), so the pass introduces no projector
change to prove.

## The report

`make report-playthrough-starts` runs `manage.py report_playthrough_starts`,
read-only, in the shape of `make preflight-playthroughs`. It takes the same
three-way flag group — one of `--user`, `--library` or `--all-libraries` — plus
`--sample-size`, and prints, per library and in total:

- runs in scope;
- runs holding a status day, a session day, both, neither;
- of the runs holding both, how many agree, and the distribution of the gap in
  days for the rest, with the zone each day was read in named beside it;
- which source won, counted;
- runs left stating no act, counted, so a clean report does not read as full
  coverage;
- a sample of runs by identity, each naming the game, the day and the winning
  source, capped by `--sample-size`, which defaults as `preflight_playthroughs`
  does.

Deterministic: sorted by identity, never sampled at random, so two runs over
unchanged data print the same bytes. The report is the thing to run against a
restored copy before a deployment carries the migration.

## Reversibility

The stream is append-only and a projection rebuild replays what the stream
holds, so a rebuild does not take these events back. This pass therefore has no
rollback after it commits, and this specification does not claim one. The
migration's reverse is a no-op, stated rather than implied.

What stands in its place:

1. the report, run against a restored copy, before the deployment;
2. the gate, which rolls the run back before it commits on any mismatch;
3. `CorrectPlaythroughStart` from #1010, which states a better day for any one
   run afterwards, and is the same affordance a person has for a day they typed
   wrong themselves.

The deployment rehearsal is the existing one: `make verify-dump` restores,
migrates and drops a copy.

## What this reports and does not repair

**120 runs go on reading `-`.** They hold neither a session nor a status day.
After this pass, `-` no longer separates a game never played from a game whose
evidence did not survive, so the report prints that count per library.

**131 runs read Unplayed beside a live session.** The status is wrong and the
session is evidence, so those runs are in scope and do take a start; their
status is left as it stands. God of War Ragnarök holds 23 live sessions from
November 2022 to February 2024 and still reads Unplayed. Repairing a status is a
different act on a different aggregate, and it belongs to its own issue.

**The shared-catalog case is unmeasured.** The dump holds one library and every
`Game` names it, so nothing in the measurement exercises the ownership scoping
the two evidence reads carry. Tests cover it; production data does not.

**The `finished()` split is left alone**, as the completion section says.

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

- a run whose creation names no backfill origin is left alone, whether a person
  created it through `CreatePlaythrough` or #679 stated it at track time;
- a run stating a completion and no start is left alone;
- a run stating a start is left alone;
- an `imported_history` run is left alone;
- a removed run, a run under a removed `PlayerGame`, and a run at a removed
  `Game` are each left alone.

The pass:

- a second call appends nothing and reports the same counts;
- a run holding no evidence still states no act;
- no completion is stated, for any legacy status;
- `reconcile()` answers clean after the pass, over a library holding a repaired
  run, a converted run and a game with no legacy row alike;
- `reconcile()` still reports `SURPLUS_ACTLESS_RUN` where a second actless run
  exists beside a repaired one, so the amendment took no teeth out.

The screens:

- **Add playthrough** on a repaired game creates a second run;
- the one-press button on a repaired run posts to the completion route;
- a run repaired from a status day older than the threshold reads Dormant.

The migration follows `tests/test_playthrough_conversion.py`, which calls the
`RunPython` function against a library built in the test rather than running
`migrate`: a library built to hold each case is converted, the gate passes, and
each check fails when the condition it names is broken.

## Dependencies

- #684, whose `reconcile()` this amends
- #1010
