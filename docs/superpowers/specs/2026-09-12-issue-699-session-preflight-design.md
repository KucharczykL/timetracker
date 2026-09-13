# Report what the legacy Session rows hold

Issue [#699](https://github.com/KucharczykL/timetracker/issues/699), in epic
[#601](https://github.com/KucharczykL/timetracker/issues/601), first in the
[Session delivery wave](2026-09-12-session-wave-design.md).

`games/preflight/session.py` reads the legacy `Session` rows. The
`preflight_sessions` command prints the result, and `make preflight-sessions`
runs it. The code only reads. It appends no event and writes no row.

#689 states the three timing modes, and #700 converts each legacy row into one
of them and assigns it to a run. This report says what those two will meet.
#700 imports the classifier and the assignment rule, thus the report and the
run agree.

Every number below was measured against the production dump of 2026-09-12,
restored locally. It holds one library, one user, 859 games and 2,807 Session
rows. Where the anonymized sample fixture answers differently, the difference
is named.

## What a preflight is here

A preflight reports. What it finds never fails the run, and the command exits
zero whatever it counts. Only a scope it cannot resolve is an error, which is
[#686's contract](2026-09-04-issue-686-playthrough-preflight-design.md)
unchanged.

The issue text says the unholdable rows "block the cutover". They are reported
as their own counts and nothing more: production holds none, and it is the only
database that will ever be converted, so a gate would be machinery guarding an
empty set. #700 refuses such a row at write time, which is where a refusal
belongs.

The wave design states the gate as well, and is amended alongside this spec.

## The zone finding

The wave design says day grouping is seeded from `settings.TIME_ZONE` because
"every day-grained read today groups in it". That premise is false.

`TimezoneActivationMiddleware` (`common/middleware.py:37`, installed at
`timetracker/settings.py:102`) wraps every request in
`timezone.override(DISPLAY_TIME_ZONE)`. So the navbar's midnight range
(`games/views/general.py:59`), `TruncDate` and `TruncMonth`
(`games/views/stats_data.py:190,360`), `timestamp_start__year` (`:148,:157`),
the `__date` lookups (`games/filters.py:280`) and the dormancy clock
(`games/reads/playthrough_activity.py:75`) all group in the **viewer's** zone.
Production's one user holds `display_time_zone = Europe/Prague`, while
`TIME_ZONE` resolves to `UTC`.

Measured on the dump, between those two zones: **124** sessions fall on a
different day, **10** in a different month, **5** in a different year — the
wave design's own numbers, now with both sides named. Seeding `day_zone` from
`TIME_ZONE` therefore *moves* those rows rather than holding them still, and
#704's strict-equality gate would fail by that amount.

The census takes no position. Every zone-dependent figure is reported under
both zones, and `--day-zone` names a third. Which zone #689 seeds is #689's
decision; this report is the evidence it reads.

## The scope of a row

A Session carries no library column. Every live read reaches it as
`game__library` — `SessionQuerySet.for_library` filters `game__library=library`
(`games/models.py:1149`), and no read disagrees — so the census reads ownership
too, and one row is counted for exactly one library.

A Session on a shared game (`Game.library IS NULL`) belongs to no library. A
walk over the games a library owns cannot reach one, so it is counted in the
shared-catalog section of the report and never in a per-library category.
Production has no shared games.

The classified population is every row #700 converts: live rows and removed
rows alike, each given a timing verdict and an assignment outcome, with
`removed` counted as a separate axis beside them. #700 converts a removed row
and states the removal as a fact, and the two removed rows are the only rows in
the database exercising the running branch — classifying live rows alone would
report that branch as empty when it is not.

## What the report partitions

Two partitions, over two populations, and the report states which is which:

- **Rows in scope** — every Session whose game this library owns — partition
  into the not-converted ladder below and the **classified rows**, which is
  everything the ladder does not claim.
- **Classified rows** partition twice over: once by timing verdict, once by
  assignment outcome. Each of those sums to the classified count, not to the
  rows in scope.

The report prints the difference between rows in scope and the two sets, and
the difference is zero.

## The timing taxonomy

`TimingVerdict` is a `StrEnum` of six words. `classify_timing(row)` reads one
row and answers one of them:

| verdict | rule | live | removed |
|---|---|---|---|
| `negative_elapsed` | end earlier than start | 0 | 0 |
| `negative_manual` | `duration_manual < 0` | 0 | 0 |
| `timed` | end set, `duration_manual = 0` | 2,663 | 0 |
| `duration_only` | no end, `duration_manual > 0` | 142 | 0 |
| `corrected` | end set, `duration_manual > 0` | 0 | 0 |
| `running` | no end, `duration_manual = 0` | 0 | 2 |

The two refused words are tested first, in the order listed, so a row that is
both reversed and negative is named by the first thing no mode can hold rather
than by the mode it would otherwise take. The six counts sum to the classified
rows.

An end equal to its start is `timed`. A zero elapsed interval is a duration,
not a contradiction, and #689's CHECK constraints admit it.

`negative_manual` exists because nothing forbids the value: `duration_manual`
carries no CHECK constraint (`games/models.py:1197`) and `forms.DurationField`
accepts Django's leading-minus syntax. Without the word, such a row would be
called `timed` or `duration_only` and #689's constraints would refuse it at
write time, which is the surprise a preflight exists to prevent.

**Every rule tests `duration_manual > timedelta(0)`, never presence.** The
column is `null=True, default=timedelta(0)` and only the default was ever
taken: no row holds NULL, `Session.save()` coerces one away
(`games/models.py:1255`), and the dump confirms zero. Read as a presence test,
the same taxonomy calls all 2,805 live rows `timed`, which is the trap this
issue exists to name. A NULL would raise on the comparison rather than
misclassify, so `classify_timing` reads NULL as zero — matching both
`Session.save()` and the acceptance query — and the report counts such rows in
a `manual_duration_null` observation beside the verdicts.

`running`, `negative_elapsed` and `negative_manual` are verdicts, not modes.
#689 states `PlayerSessionTimingMode` with three members spelled exactly as
`timed`, `duration_only` and `corrected`, and the test asserting the spellings
agree is #689's to write — this issue ships first and cannot enforce it. #700
imports `classify_timing`, maps the three, and refuses the other three. The
enum lives here rather than in the model because this module ships first, and
the model's vocabulary must not outlive #772 inside a migration-support module.

**The sample fixture disagrees, and usefully.** Replayed,
`games/fixtures/sample.yaml.gz` answers `duration_only` 141 and `corrected` 1:
it was generated before the wave review corrected two rows by hand. So the
fixture keeps a `corrected` specimen the production dump no longer has, and a
test reading sample data sees that branch populated. The dump's numbers are the
acceptance figures; the fixture's are stated so the difference is never read as
a defect.

## The assignment rule

`assign_run` answers one of three outcomes per row, reading the live ordinary
runs of the game the row names:

1. **`sole_run`** — the game holds exactly one live ordinary run. It takes the
   row whatever the dates say. Under the rule below, 164 sessions in UTC and
   113 in Europe/Prague fall outside their sole run's interval, and bucketing
   them would put a game's whole history in a sorting tray because #1038 dated
   that run from a status day.
2. **`contained`** — the game holds more than one, and exactly one of them
   claims the row's day.
3. **`bucket`** — every other case: no run claims the day, more than one does,
   or the game holds no live ordinary run at all. These rows need the
   "Imported history — needs sorting" run #700 mints.

A run claims a day when at least one of its bound columns is set and the day
lies within the interval they state:

- `started_lower` bounds it on the left when set;
- `completed_upper` bounds it on the right when set;
- a run whose two bound columns are both NULL claims nothing.

The rule reads **bound columns, not days**. `started` and `completed` are
`TemporalValueField` values admitting month, year and decade precision and
open-ended ranges, so a decade start bounds ten years early and a range with an
unknown start leaves `started_lower` NULL while the act was still recorded.
Every run in the dump carries a plain day value, so production never exercises
the wider readings.

A run with both bounds NULL reads as an unbounded interval and would claim
every session, which is what produced the bucket in production.

Measured on the dump, per zone:

| population | UTC | Europe/Prague |
|---|---|---|
| games with one live ordinary run | 2,743 live + 2 removed | same |
| multi-run games, exactly one run claims the day | 60 | 61 |
| multi-run games, no run claims it | 2 | 1 |
| multi-run games, more than one claims it | 0 | 0 |

**The half-open reading is unexercised by production.** On the eight multi-run
games every run is either fully dated (13 runs) or states no day at all (4
runs), so a both-endpoints-closed reading returns the same split in either
zone. The 541 start-only runs all sit on single-run games, where rule 1 answers
before containment is consulted. The rule was chosen on principle: it is the
literal reading of "a run with no stated endpoint", it places strictly more
rows than the closed reading, and where a half-bounded run overlaps a dated one
the row gets two claimers and reaches the bucket, which is the genuine
ambiguity the bucket exists for. #704 covers the branch synthetically, as it
already must for two overlapping dated intervals.

### Which runs the rule reads

`live_ordinary_runs(library, player_game)` from
`games/reads/playthrough_runs.py:44` — the run's own `removed_at` and its
`kind`, and no other mark. `library_runs` additionally reads the two parents'
marks; this walk counts those parents' marks as their own ladder categories
instead, so a row on a removed game is reported as such rather than losing its
run silently. Production holds no such row.

### The day

`(timestamp_start AT TIME ZONE zone)::date`, computed for both candidate zones
per the finding above. A Duration-only row has no end and its start is still an
instant, so one rule dates every row.

## The rows no mode converts

Three per-library categories, checked in this order so each row is counted
once. A removed game whose `PlayerGame` is also removed is counted by the first
that claims it:

| category | production |
|---|---|
| the game is removed | 0 |
| the library holds no `PlayerGame` for the game | 0 |
| the `PlayerGame` is removed, thus the game is untracked | 0 |

The shared-game count lives in the shared-catalog section, not here: the walk
reads the games the library owns and cannot reach an unowned one.

Distinguishing the second category from the third needs the `PlayerGame` rows
themselves — a game whose tracking row is removed holds no live run, exactly
like a game that was never tracked — which is why the walk reads them in their
own query.

## The zone delta

Three counts per library, reported and blocking nothing: rows whose day differs
between `settings.TIME_ZONE` and `resolve_str_for_user(library.user,
"DISPLAY_TIME_ZONE")` (`timetracker/settings_resolver.py:290`, reached as
`activity_clock(library).zone` in `games/reads/playthrough_activity.py:34`),
and of those, how many cross a month boundary and how many cross a year. The
dump answers 124, 10 and 5 between `UTC` and `Europe/Prague`. Both zone names
are printed beside the counts, because with both at their defaults the delta is
zero and a bare number would mean nothing.

Fifteen rows also carry a per-row `timestamp_start_timezone` of
`Europe/Prague`, which `games/formatting.py:58` reads under the
`SESSION_TIME_ZONE_DISPLAY` setting. The census reports how many rows carry a
committed zone at all and does not date anything by it; #689 decides whether
`day_zone` inherits it.

## The output

Name the scope: `--user`, `--library` or `--all-libraries`. The first line is
`SESSION_PREFLIGHT_JSON=` and a payload carrying a `schema_version`, a
`generated_at`, the zone names it read, the summary, one entry per library, and
the shared-catalog counts. The time follows on its own readable line, then a
section per library. `--sample-size` limits the identifiers printed beside a
count; the default is 20, and `0` prints none. `--day-zone` names a zone to
report beside the two defaults. Two runs over the same data print the same
bytes, except for the time they state.

Samples are the first identifiers in key order, never random: the
`negative_elapsed` rows, the `negative_manual` rows, the `running` rows, the
bucket rows, the rows more than one run claimed, and the games whose sessions
need a bucket.

A scope naming no library is not an error, because a deployment can hold none.
The report says it read nothing, so a row of zeros is not read as a clean
result.

## The walk

One walk per library, over the games the library owns, paged with
`keyset_pages` keyed on `("id",)` — which yields rows, so `itertools.batched`
re-chunks them, as the deleted sibling did. Each batch makes three queries: the
batch's sessions, the batch's `PlayerGame` rows, and the live ordinary runs
under them. No code opens a server-side cursor, which
`tests/test_iterator_guard.py` already enforces over `games/`.

`Game` declares no composite index, so the walk's `library` filter rides along
with a primary-key sort unindexed together. At 859 games it costs nothing, and
no index is added for a command run by hand.

## Testing

`tests/test_session_preflight.py`:

- one test per verdict, plus an end equal to its start reading `timed`, a
  reversed interval carrying a manual duration reading `negative_elapsed`, a
  negative manual duration reading `negative_manual`, a zero `duration_manual`
  never reading as absent, and a NULL reading as zero;
- the counts sum field by field, and the empty counts are an identity;
- a sole run takes a session outside its interval;
- containment on a multi-run game: claimed from the left by a start-only run,
  from the right by a completion-only run, by both bounds of a dated run; a run
  with two NULL bounds claims nothing; zero claimers and two claimers both
  reach the bucket; a game with no live ordinary run reaches the bucket;
- each ladder category counted once, a game both removed and untracked counted
  by the first, and the unaccounted difference zero;
- the zone delta counts a day, a month and a year crossing, and reports both
  zone names;
- samples capped by `--sample-size`, and `0` printing none;
- one library never counts another, and a shared game reaches no per-library
  category;
- the payload renders itself and two runs print the same bytes;
- **the walk writes nothing**: a context manager around the census call
  installs `connection.execute_wrapper` and raises on any statement whose
  `write_targets()` is non-empty, reusing the parser
  `games/events/rebuild.py:82` already ships for `only_shadow_writes()`. It
  must wrap the call and not the test: `tests/conftest.py:233`'s autouse
  `_track_created_games` and the `owned_library` fixtures insert rows while the
  test arranges its data, so a fixture-scoped guard fails on the arrange step.
  Keying on write keywords rather than on "not a SELECT" is what makes the
  guard stable against savepoints. A row-count comparison, which is what #686
  used, would pass an `UPDATE`.

## Acceptance against the dump

`make restore-dump` restores the newest dump; the command runs against the
`DATABASE_URL` it prints. Note that `TIME_ZONE` resolves to `Europe/Prague`
under `DEBUG` and `UTC` otherwise (`timetracker/settings.py:173`), so the run
states the zones it read and the comparison is made against the matching
column. The hand-written comparison is one query per reported category; the
timing one is:

```sql
SELECT CASE
         WHEN timestamp_end IS NOT NULL AND timestamp_end < timestamp_start
           THEN 'negative_elapsed'
         WHEN COALESCE(duration_manual, interval '0') < interval '0'
           THEN 'negative_manual'
         WHEN timestamp_end IS NOT NULL
              AND COALESCE(duration_manual, interval '0') > interval '0'
           THEN 'corrected'
         WHEN timestamp_end IS NOT NULL THEN 'timed'
         WHEN COALESCE(duration_manual, interval '0') > interval '0'
           THEN 'duration_only'
         ELSE 'running'
       END AS verdict,
       count(*) FILTER (WHERE removed_at IS NULL) AS live,
       count(*) FILTER (WHERE removed_at IS NOT NULL) AS removed
FROM games_session GROUP BY 1 ORDER BY 1;
```

Expected on the dump: `duration_only` 142/0, `timed` 2,663/0, `running` 0/2,
and nothing else. Assignment: 2,743 live and 2 removed `sole_run`; then 60
`contained` and 2 `bucket` in UTC, 61 and 1 in Europe/Prague, with zero rows
claimed by more than one run in either. Ladder and shared-catalog categories
all zero. Zone delta 124 / 10 / 5.

## What this issue also does

- **Amends the wave design.** Its zone premise is false, its "blocks the
  cutover" line is reversed here, its 113 figure is a Europe/Prague number
  beside a UTC table, and it names the third assignment outcome "ambiguous"
  where this spec says "bucket" and means strictly more.
- **Comments on #689 and #704**, because the seeding rationale one of them
  inherits is void and the gate the other states depends on the answer.
- **Adds the `make preflight-sessions` row** to the commands table in
  `CLAUDE.md`, where the removed `preflight-playthroughs` row used to sit. The
  target depends on `ensure-postgres`, as every sibling does.

## Out of scope

The `PlayerSession` model and its modes (#689), any event (#689 onward), the
conversion itself (#700), the bucket run (#700), choosing the seeded zone
(#689) and moving day grouping to the viewer's zone (its own issue), and any
change to the legacy `Session` table.
