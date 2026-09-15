# Session delivery wave

Date: 2026-09-12

Parent epic: [#601](https://github.com/KucharczykL/timetracker/issues/601)

## Purpose

This document is the wave review #601 requires before the Sessions group
begins. It replaces the placeholder ordering of #689 through #704 with a
dependency-ordered sequence, states the issue boundaries, and names every
legacy surface and its owner.

The sixteen placeholder issues carry an outcome line and the shared acceptance
block. They identify real outcomes, but one of them is the entire read layer in
a single issue, four pairs each describe one act, one is not an act at all, two
belong to owners outside this wave, one asks for a projection the wave should
not build, and the preflight is listed eleventh when its whole purpose is to
inform the first issue. This review merges five, moves three out, drops one,
and reorders the rest, leaving ten.

The delivered Playthrough wave is the model, and its topology is reused rather
than invented again. It is not copied wholesale, and one departure needs
stating plainly: this review names "the entire read layer in a single issue" as
a defect and then merges the read cutover into #702 anyway. The justification
is not that the surfaces are uncoupled — they are as coupled as Playthrough's
were — but that the coupling is handled by the stack rather than by the issue
split. #702's stack members are the review boundaries, one per surface, and
they merge atomically because production is one library deploying the wave as
one release. A wave with more than one reader should split the issues instead.

Every empirical claim below was checked against a production dump taken on
2026-09-12 and against the code, and three of the charter's own rules did not
survive that check.

## Product boundary

A Session records that a game was played, for how long, on what device. This
wave makes it event-sourced, gives it the three explicit timing modes the
charter defines, and attaches every session to a Playthrough.

It does not add Historical Playtime Records, does not let a Session name a
Release, does not build the Session organizer or any bulk action, and does not
touch the Journal.

## What the data says

Every decision below was checked against a production dump taken on
2026-09-12, after two rows were corrected by hand during the review. The
shape of the real data is not what the charter's migration rules assume, and
two of those rules are amended here because of it.

Live sessions, 2,805 in one library:

`duration_manual` is never NULL in any of the 2,807 rows — the column is
`null=True, default=timedelta(0)` and only the default was ever taken — so
every rule below tests `duration_manual > INTERVAL '0'`, never presence. Read
as a presence test, the same table classifies all 2,805 live rows as Timed.

| shape | rows | becomes |
|---|---|---|
| end set, `duration_manual = 0` | 2,663 | Timed |
| no end, `duration_manual > 0` | 142 | Duration-only |
| no end, `duration_manual = 0` | 0 | would be running Timed |
| end set, `duration_manual > 0` | 0 | would be Corrected |
| zero elapsed, negative interval, zero total | 0 | — |

Two removed rows exist, both with no end and a zero manual duration. They are
the only rows in the database that exercise the running-session branch, and
they are removed.

Three findings follow, and each changes an issue:

**The charter's blocking preflight rule is wrong about this data.** It says a
preflight "reports every running legacy Session with a non-zero manual addition
and blocks the cutover", requiring the player to finish it, correct it, or
strip the manual value. But a legacy row with no end and a manual duration is
not a running session — it is the ordinary manual-entry flow, which posts a
start and a duration and never sets an end. That is 142 rows, 5% of the table,
and it is precisely the population Duration-only mode exists for. Applying the
rule literally would demand hand-repair of the wave's own happy path. The rule
is amended: these rows convert to Duration-only by rule, and the preflight
blocks only on rows no mode can hold.

**Corrected mode has no production instances.** Not one row has both an
elapsed interval and a manual duration. The mode is still built, because the
charter defines it and corrections must be expressible, but its migration
branch will convert nothing, so the parity gate carries synthetic cases for it
rather than relying on real data to exercise it.

**Mode and provenance are the same word.** The charter states three timing
modes and, separately, three duration provenances — Measured, Manually
entered, Corrected — which map one-to-one onto Timed, Duration-only and
Corrected. Storing both would be storing one fact twice. Provenance as an
independent axis belongs to Historical Playtime Records, whose values
(Estimated, Externally measured) have no Session equivalent. A Session states
one word.

## Aggregate and storage

`PlayerSession` is the third projection model and the third command family. It
follows `PlayerGame` and `Playthrough`: the primary key is the creation event's
`aggregate_id`, both `UUIDv7Field` defaults are opted out, the projector is the
only writer, and `removed_at` is the projector's, stated by a command, so the
model is absent from `REMOVABLE_MODELS`.

It is a new table rather than the legacy `Session` made event-sourced, for two
reasons in this order. First, `removed_at` means the player's mark on a legacy
Session and the projector's mark on a projection, and converting in place flips
that meaning midway through the wave on a table eight surfaces are reading.
Second, the run reference is non-null, and there is no in-place migration that
adds a non-null foreign key to 2,807 existing rows without the conversion
having already run — which is the conversion this wave writes.

The generated-column argument is weaker than it looks and is not the deciding
one: dropping a stored generated column is metadata-only, and the table rewrite
comes from the *additions* (`timing_mode`, `stated_day`, `day_zone`,
`effective_day`, the run reference), which a new table pays on an empty table
instead. Nothing holds a foreign key to `Session` — confirmed against
`pg_constraint` — so nothing has to be repointed.

The name `PlayerSession` is permanent. It reads beside `PlayerGame` and needs
no rename when legacy storage goes.

### The three modes

`timing_mode` is a stated enum column, not a shape read off the row, and
database CHECK constraints bind each word to the columns it admits:

- **Timed** — an exact start instant, an optional end instant while running, no
  override. Duration is elapsed time.
- **Duration-only** — a day and a stated duration. No instants.
- **Corrected** — an exact start and end, plus an override that *replaces*
  elapsed time rather than adding to it.

The constraints exist because the migration is the code most likely to write an
impossible row, and it runs once over years of data.

### The effective day

Every day-grained read keys on one non-null `effective_day`: the navbar's today
and last-seven-days figures, the stats page's day and month grouping and its
year scope, the list sort, `get_latest_by`, and the dormancy clock in
`games/reads/playthrough_activity.py`. A Duration-only row has no instant to
derive one from, so the day must be available as a column rather than computed
per read.

It is a **generated** column, over a zone the row carries:

```sql
effective_day date GENERATED ALWAYS AS
  (COALESCE(stated_day, (started_at AT TIME ZONE day_zone)::date)) STORED
```

The review expected this to be impossible, on the grounds that a generated
expression must be IMMUTABLE while a zone conversion is only STABLE. That is
wrong, and was checked rather than assumed: `timezone(text, timestamptz)` is
marked immutable in `pg_proc`, so PostgreSQL 18 accepts the column, generates
it, and regenerates it on an `UPDATE` of `day_zone`. Both were confirmed in a
throwaway table.

The shape matches what the Journal already specifies for the same facts: a
Duration-only Session takes its "written effective calendar day, without
timezone conversion", while a timed Session takes "the configured
display-timezone date of exact `timestamp_start`". That is the `COALESCE`
above, and a CHECK forbids `stated_day` on a Timed or Corrected row so the
branch is never ambiguous.

**Which zone seeds `day_zone` is open, and #689 decides it.** *(Decided: the
viewer's display zone, stated by the caller rather than resolved by the command.
See [the #689 design](2026-09-13-issue-689-playersession-aggregate-design.md).)* This review
stated that it is seeded from `settings.TIME_ZONE` because "every day-grained
read today groups in it". [#699's
census](2026-09-12-issue-699-session-preflight-design.md) checked that premise
against the code and it is false: `TimezoneActivationMiddleware`
(`TimezoneActivationMiddleware.__call__`, installed at `timetracker/settings.py:102`) wraps
every request outside `/api/settings/` in
`timezone.override(DISPLAY_TIME_ZONE)`, so `TruncDate`,
`TruncMonth`, `timestamp_start__year`, the navbar's midnight range and the
`__date` filter lookups all group in the **viewer's** zone. Production's one
user holds `display_time_zone = Europe/Prague` while `TIME_ZONE` resolves to
`UTC`.

The delta between those two zones, measured on production, is 124 sessions on
a different day, 10 in a different month, and 5 in a different **year** — so
seeding from `TIME_ZONE` *moves* that many rows rather than holding them
still, and #704's strict-equality gate would fail by exactly that. Seeding
from the display zone holds today's grouping still and makes the zone a
per-viewer fact the row cannot carry alone. #689 states the choice and its
reason; #699 reports both and takes no position.

Seeding from the display zone leaves two answers to one question. The stored
`day_zone` freezes a session's day when it is recorded; #1033's
`ActivityClock` resolves the viewer's zone on every read, and
`default_activity_clock()` reads UTC with no viewer. They agree until a viewer
changes zone, and then disagree about the same session's day. #1047 decides
the one zone a library counts days in, whose fact it is, and the one act that
changes it; it lands before #702, whose dormancy-clock member reads its answer.
#1054 restates recorded session days on that act and #748 rebuilds the
Journal's day projections on it — one trigger, two registrants. The
restatement is an event, never an `UPDATE` of `day_zone`: `PlayerSession` is a
projection, so a bulk `UPDATE` is drift that `rebuild_projections` reports and
reverts.

One limit worth stating: `timezone(text, timestamptz)` is marked immutable but
its answer depends on the interpreter's tzdata, so a tzdata update that changes
a historical rule will not regenerate stored values. Determinism holds within a
tzdata generation.

### The mandatory run reference and the bucket

Every `PlayerSession` names a Playthrough, non-null. Unknown has exactly one
spelling — the "Imported history — needs sorting" bucket, the system-kind run
#679 specified and deliberately did not create. This wave creates one where a
library needs one, which is what fills `BLOCKING_REFERRERS`, the registry
#1011 shipped empty.

`CreateSession` takes a run explicitly and never infers one. Nothing is derived
from the game, the day, or another session, which is the rule the charter
already applies to Release. The four creation surfaces that name a game today —
the add form, add-for-game, the purchase form's Submit & Create Session, and
Game detail's link — each gain a run picker, and #702 owns them.

The conversion is the one place a run is chosen by rule, because there is no
person to ask. Two rules, and **both amend the charter**:

1. **A sole live ordinary run wins regardless of dates.** The charter buckets a
   Session "outside the only interval"; 164 production sessions in UTC, and 113
   in Europe/Prague, are outside their sole run's interval, and bucketing them
   would put a game's entire history in a sorting tray because #1038 dated its
   one run from a status day.
2. **An undated run does not claim containment.** Read as `(-∞, +∞)`, a run
   with no stated endpoint contains everything and manufactures ambiguity on
   contact — which is the *only* thing that produced ambiguity in production.

Measured outcome on the real library. The split moves with the zone the day
is read in, so both candidates are named:

| population | UTC | Europe/Prague | lands |
|---|---|---|---|
| sessions on games with one live ordinary run | 2,743 | 2,743 | that run |
| on the 8 multi-run games, exactly one dated run contains the day | 60 | 61 | that run |
| …no dated run contains it | 2 | 1 | the bucket |
| …more than one dated run contains it | 0 | 0 | the bucket |

The whole migration produces **one bucket holding one or two sessions**. Without rule
2 the bucket holds ten and the containment rule is never genuinely exercised;
without rule 1 it holds over a hundred. Note the consequence for #704: no
production row arbitrates between two dated overlapping intervals, so that
branch is covered synthetically.

### Reaching the game

`PlayerSession` holds no `game` foreign key. The game is reached through
`playthrough → player_game → game`, so a session and its run can never name
different games.

The cost was measured rather than assumed. The game list's playtime sort, the
heaviest read that grows, runs in 1.07 ms today and 1.65 ms through the two
extra joins, whole-library. The list and the API also `select_related` the
game, its platform and the device, which becomes a four-join row; #704 states
that path as the budgeted one, not the two-join one.

Its registered references are therefore the Playthrough — a second
projection-to-projection key, after the one #1017 registered — and the Device.

## Playtime, read at query time

Nothing materialises playtime. `Game.playtime`, its `post_save`/`post_delete`
signal and the `_AFTER_STAMP` recalculation `games/removal.py` runs after a
removal stamp all go with the legacy table, and no column replaces them.

The wave review reached for a `PlaytimeTotal` projection first and the
justification did not survive checking. The game list does not read
`Game.playtime`: `GAME_SORTS["playtime"]` is already `Sum("sessions__duration_total")`,
a read-time aggregate on every page load. Only two reads use the column at all
— the Game-detail figure and the `playtime_hours` filter.

A materialised total also cannot be complete here. `GAME_SORTS["filtered_playtime"]`
restricts playtime to the active session sub-filter, and the five `GameFilter`
aggregates over `Game.sessions` each carry a `scope` sub-filter — arbitrary
boolean predicates over thirteen fields and two cross-entity relations. No key
enumerates that, so the read-time path must exist and be correct regardless;
anything materialised is an optimisation of a subset that must then agree with
it.

Measured on restored production data, that optimisation buys about a
millisecond:

| read | time |
|---|---|
| game list playtime sort, today | 1.07 ms |
| the same through the two extra joins | 1.65 ms |
| stats totals, session count, distinct days | 1.79 ms |
| per-platform playtime | 1.70 ms |
| monthly chart | 0.77 ms |

Against that it would cost a projector, a rebuild path, and — once HIST lands —
conditional write logic, because the charter admits an estimated record to a
year total only at a granularity its effective value justifies ("a decade fact
may contribute to a decade or all-time total, but never to an invented year").

The future does not rescue it either. The Journal materialises its own
durations — `JournalDayProjection` stores each day's session count and total —
so the largest downstream reader of session durations never consults a totals
table. And a Historical record's optional Release and Device are not in any key
a per-game table would carry, so #710's tracked-versus-estimated split composes
at read time in every scope except the two such a table would serve.

So the wave ships no projection and #704 ships a **stated budget** instead: a
named per-read threshold, measured on restored production data, with
materialisation of exactly the breaching cells as the remedy. The cube becomes
a condition with a trigger rather than a refusal, which is the shape #909 and
#913 already use.

## Delivery order

1. #699 — the read-only preflight census over legacy Sessions
2. #689 — the `PlayerSession` aggregate, its modes, its projector, its creation
3. #691 — finish a running Timed session
4. #692 — the three correction commands
5. #694 — removal and restoration
6. #697 — read playtime from the projection
7. #700 — convert legacy Sessions, assign runs, mint the bucket
8. #1047 — the one zone a library counts days in, and the act that changes it
9. #702 — the cutover: writes, the run pickers, and every read surface
10. #704 — replay, statistics, and performance gates
11. #772 — remove legacy Session storage

Required orderings and the reason for each:

- `#699 → #689`. A preflight that runs after the schema exists reports on
  decisions already made. Its census is what the mode taxonomy is checked
  against — and in this wave it already overturned three charter rules.
- `#689 → everything`. Nothing states a fact about a row no projector writes.
- `#691, #692, #694 → #700`. The conversion appends the same event types the
  live commands append, so every payload must exist first.
- `#692 → #694`. #694 makes #1011's refusal live — a run with sessions naming
  it cannot be removed — and the sentence that refusal shows says to move the
  sessions first. `MoveSessionToPlaythrough` is #692's. Shipping #694 first
  ships a refusal with no remedy.
- `#700 → #702`. A write cutover leaves the legacy table as the sole record of
  facts nothing writes any more, so every legacy row must already be an event.
- `#1047 → #702`. The dormancy clock and `effective_day` are two answers to
  which zone counts a day; #702's clock member reads the one #1047 states
  rather than choosing a zone inside a cutover.
- `#702 → #704`. The gate proves parity for surfaces that have all moved.
- `#704 → #772`. Legacy storage comes out after the gate is green.

Free to run in parallel: #691 and #692 after #689, with #694 behind #692; #697
and #1047 any time after #689.

Outside the delivery order, #1047 also blocks #1054 and #748, the two
registrants of its trigger.

## Issue boundaries

### #699 — the preflight census

Delivered as `make preflight-sessions`, over
`games/preflight/session.py`. A read-only management command over legacy
`Session` rows, appending no event and writing no row. Per library it reports:
a timing verdict per row, the assignment outcome in three buckets (sole run,
contained, bucket), games whose sessions would need a bucket, the rows no mode
converts, and the day-zone delta. Every count is taken in both candidate zones,
side by side.

It gates nothing. This review stated a block on that last category — a
negative elapsed interval — and #699 reports it as a count instead: production
holds none, it is the only database that will ever be converted, and #700
refuses such a row at write time, which is where a refusal belongs. It
certainly does **not** block on a no-end row with a manual duration, for the
reason stated above.

#699 also names two rows no mode can hold rather than one, because nothing
forbids a negative `duration_manual` either, and reports the third assignment
outcome as the **bucket** — a broader word than "ambiguous", since a game with
no live ordinary run at all reaches it too.

`classify_timing` and `assign_run` are the deliverable #700 imports, so the
report and the conversion can never name one row differently. The six verdicts
it states are `timed`, `duration_only` and `corrected` — the modes #689 admits
— beside `negative_elapsed`, `negative_manual` and `running`, which no mode
holds and #700 refuses.

Follows #686's shape.

### #689 — the PlayerSession aggregate

Delivers the model and its migration, the three modes and their CHECK
constraints, `stated_day`, `day_zone`, the generated `effective_day`, the
mandatory Playthrough reference, the Device reference, the creation command and
its event, the projector, the queryset, and both entries in
`AUDITED_PROJECTION_REFERENCES`.

Two constraints the boundary must name, because the obvious precedent is wrong
for each:

- `PlayerSessionQuerySet` **states `alive()`**. `BlockingReferrer.on` refuses a
  model whose manager lacks it, and #694 registers one — but the queryset this
  model would otherwise copy, `PlaythroughQuerySet`, deliberately states neither
  `alive()` nor `for_library()`. Following that precedent raises `TypeError` at
  import.
- a CHECK forbids `stated_day` on a Timed or Corrected row, so the `COALESCE`
  in `effective_day` has exactly one live branch per mode.

Absorbs #690, which described the creation command alone: a projection table
with no creation event is a table nothing writes. Absorbs #693 as well — a note
is a field on the creation payload, not an act with an event of its own.

`CreateSession` takes a run, a duration statement, and the descriptive fields.
It never infers a run.

Out: every other event type, every screen, the backfill, and any Release
reference beyond an unused optional field reserved in the payload.

**Delivered.** The design is
[The PlayerSession aggregate and its three timing modes](2026-09-13-issue-689-playersession-aggregate-design.md);
what it settled, and what the rest of this wave inherits:

- **`day_zone` seeds from the viewer's display zone**, and the caller states it
  inside the timing statement. Inside a request that is
  `timezone.get_current_timezone_name()`, already activated by the middleware,
  so #702 adds no zone control for it.
- **Restating a library's days is an act that needs an event.** The rebuild
  diffs whole rows, so the bulk `UPDATE` this review imagined would be drift
  `--check` reports and `swap_in` reverts. The deferred issue ships an event.
- **Corrected replaces; legacy `duration_manual` added.** A converted Corrected
  row's `stated_duration` is the legacy row's `duration_total`, never its
  manual component, and #700's test asserts that arithmetic rather than a
  spelling. #702 owns the form combination that still means "add".
- **Three zone columns, not one**, and `day_zone` is NULL on a Duration-only
  row, whose written day no restatement moves. Production holds 56 rows with an
  end zone and no start zone, which #700 must decide about.
- **Three generated columns**, not one: `effective_day`, `effective_duration`,
  and `sort_instant`, which is what #702 keys the navbar's keyset read on —
  `effective_day` would have demoted intra-day order to conversion order.
- **The event namespace is `library.playersession.*`**, following the model
  name as `playergame` and `playthrough` do.
- **No CHECK can guard `day_zone`.** A generated column is computed before any
  constraint, so a blank or unknown zone answers `DataError`, which
  `answers.py` can only answer with "nothing was saved"; the command refusing
  an unknown zone is the only guard that can name the zone. It validates against `pg_timezone_names` as well as `zoneinfo`,
  because the two tzdata sets arrive in different images.
- **`alive()` reads two ancestor marks**, not the catalog game's: a catalog
  mark would hide sessions from `blocking_referrer` and make a run with live
  sessions removable. #702 states the catalog mark in the read layer.
- **#700 reuses the legacy `Session.id`** as the aggregate id, so every
  bookmarked URL keeps working and parity needs no mapping table.

### #691 — finish a running session

One command, one event: state the end instant of a Timed session that has none.
Refuses an end before the start, and refuses a session that is not Timed.

**Delivered.** The design is
[End a running Timed session](2026-09-13-issue-691-session-end-design.md). What
the rest of the wave inherits:

- A partial act carries its own payload, and states no `day_zone`. The row
  holds that zone.
- The event dates the act; the row dates the session. An end's
  `effective_time` reads the end, and `effective_day` reads the start.
- `_live_session` is the resolution that #692 and #694 reuse. It calls
  `_live_run` for scope as well as marks, then refuses a removed session. That
  last rule stays inert until #694 states the mark.
- `_timed_start` refuses the mode before it reads a value. A Corrected row
  learns what it is, because the remedy differs.
- `_check_aware` is module-level, shared with `CreateSession`.
- An end equal to the start is recorded. An identical restatement answers
  `Unchanged`; the same instant in another zone is refused.

### #692 — the three correction commands

`CorrectSessionTiming` states one whole `TimingStatement` again. The statement
is the transition law: each is complete by its shape, so every mode may follow
every other, and an override with no end cannot be stated because
`CorrectedTiming` holds both instants. It shares every value refusal with
`CreateSession`. `DescribeSession` states note,
device and the emulated flag, `None` meaning not stated, following
`DescribePlaythrough`. `MoveSessionToPlaythrough` states the run.

They are three rather than one so that #714's bulk move is the bulk form of a
single command rather than a second way to reassign, and so that a bulk
reassignment is not one field away from a bulk timing rewrite.

`reset_session` — "set the start to now" — is a timing act with no command in
the placeholder set. It is `CorrectSessionTiming` with a `TimedTiming`: start
`now`, `started_at_zone` the browser's, `day_zone` the row's, no end. Offered
only on a running session; on a finished one it runs the session again. Contract
is [Correct a session](2026-09-14-issue-692-session-corrections-design.md).

### #694 — removal and restoration

Mirrors #675 and #1011 for this family. Its removal is the projector's mark,
stated by `RemoveSession`, so `PlayerSession` is absent from `REMOVABLE_MODELS`.

This is also what makes #1011's refusal live: a Playthrough with sessions
naming it cannot be removed, a rule #1011 shipped inert.

Delivered as [Remove and restore a session](2026-09-14-issue-694-session-removal-design.md).
Two things it decided beyond the commitment above. `RemovePlaythrough` now
runs the last-ordinary-run rule ahead of the referrer check, so a sole run
with sessions hears "remove the game itself instead", the one remedy that
works for it; the referrer's sentence, which names a move, answers only a run
with a live ordinary sibling. And #1048 closed on its option 2: the gap
between this issue and #714 is accepted, because after the swap it touches
only the 62 legacy sessions at games with more than one live ordinary run.

### #697 — read playtime from the projection

Absorbs #698. Both placeholders asked for a projection; the wave ships read
modules instead, for the reasons stated above. It delivers the per-Game and
all-time reads over `PlayerSession`, the yearly read that #698 asked for as the
same query with a year, and the removal of `Game.playtime`, its signal, and the
`_AFTER_STAMP` recalculation in `games/removal.py`. Its
[design](2026-09-14-issue-697-playtime-reads-design.md) puts every playtime
figure behind one interface with a legacy and a projection source, moves every
playtime caller onto it; #702 binds `SOURCE` once the filtered sum exists.

**Delivered.** The design is
[Read playtime from the Session projection](2026-09-14-issue-697-playtime-reads-design.md);
what it settled, and what the rest of this wave inherits:

- **One scope.** `library_sessions()` in `games/reads/player_sessions.py` states
  which `PlayerSession` rows a library counts: four removal marks, the library
  on both the session and its run, every run kind. #702's readers state it and
  `PlayerSession` gains no `for_library()`.
- **One interface.** `games/reads/playtime/` answers every playtime figure from
  `SOURCE`, bound to the legacy table. #702 binds it to the projection, and mypy
  refuses that line until the projection source implements
  `summed_by_game_matching`, which needs `SessionFilter` restated in the
  projection's fields.
- **The parity instrument.** `make verify-playtime-parity` compares every figure
  of both sources through the protocol. #700 reconciles against it and #704
  gates on it.
- **Rehearsed on the 2026-09-12 dump.** Of 883 rendered pages, 879 were
  identical before and after. Portal's detail figure moved from the stored
  16 h to the 7 h its sessions sum to, the one change made on purpose. Three
  stats pages reordered rows that share a playtime, which `main` left
  unordered and which now fall back to name and id. No shared catalog game
  holds a session.

`ProjectorFamily.STATS` therefore still has no projector behind it after this
wave, and #913's reopen condition is untouched — it asks for a family that must
write one aggregate row per action, which this wave no longer has.

### #700 — convert the legacy rows

One pass: classify each legacy Session into a mode, append its migration event
carrying the legacy evidence — the original instants, both duration components,
the recorded zones — assign it to a run by the stated rule, and mint the bucket
where a library needs one.

Absorbs #701. Classification and the event are one act: the classification *is*
the payload, and there is no state in which a row is classified but unwritten.
The mandatory run reference forces the assignment into the same pass, since a
row cannot be written without one.

Converts removed rows too, stating the removal as a fact.

**Delivered.** Design in
[Convert legacy Sessions](2026-09-14-issue-700-session-conversion-design.md).
Four decisions the later issues inherit: a running row converts as a Timed
row with no end only when it is removed, and refuses the migration while
live; the bucket is one imported-history run per game, minted at the
migration's instant, and `MoveSessionToPlaythrough` is the only way out of
it; a row whose game has no live tracking row refuses the migration by name
rather than being skipped; and the migration is member 1 of the wave's
`gh stack` (#700 → #1047 → #702 → #704), never merged alone.

### #1047 — the zone a library counts days in

One statement of the zone every day-grained reader reads — `effective_day`, the
dormancy clock, the Journal's day projections, and the statistics built on
them — replacing today's two: the `day_zone` stored per session and the zone
`ActivityClock` resolves per read. It decides whether that zone is a library's
fact or a viewer's preference, and names the one act that changes it, including
whether changing the display-zone setting offers that act or it stays separate
and explicit. #1054 (the restatement event's shape) and #748 (the Journal
rebuild) register on that act and do not choose their own trigger. Where a
figure moves under the decision, the delta is enumerated against restored
production data rather than asserted equal.

**Delivered.** The design is
[The zone a library counts days in](2026-09-15-issue-1047-library-calendar-design.md);
what it settled, and what the rest of this wave inherits:

- **The stored row zone is the library's answer.** `effective_day` is the day;
  no reader computes one from a zone of its own. `default_activity_clock()` is
  gone, and `activity_clock` reads `calendar_day_zone(library)`.
- **The setting is the act, and it is automatic.** Changing `DISPLAY_TIME_ZONE`
  appends `library.calendar.day_zone_changed` in the same transaction as the
  preference row and reports the delta after. The projector rewrites every
  Timed and Corrected row: one library-wide event, which answers #1054's open
  question. #748 registers as a Journal projector handling the same event.
- **The delta on the 2026-09-12 dump** is 9 of 2,663 Timed and Corrected sessions to another
  day under Prague→UTC, none to another month or year; the round trip is
  exact and the replay check clean.
- **#702's surfaces seed `day_zone` from `calendar_day_zone(library)`**, and a
  statement off the calendar is refused, so a wrong seed is loud.

### #702 — the cutover

Absorbs #703. One issue, delivered as a stack, one pull request per surface
below; `gh stack merge` lands them atomically so `main` never carries a
half-cutover. The stack members are the review boundaries the placeholder split
would have provided — the difference is that they merge together, because
production is a single library deploying the whole wave as one release and no
intermediate state ever runs anywhere real.

The surfaces, each one a stack member:

1. **The run pickers and the write path.** The four creation surfaces — the add
   form, add-for-game, the Add Game and Add Purchase forms' Submit & Create
   Session, Game detail's link — each name a run. `clone_session_by_id` and
   `new_session_from_existing_session` copy the source's run. `mark_as_played`
   stays a companion dispatch beside creation under its own `correlation_id`,
   the shape #683 settled for Playthrough. `returns.py` classifies every route
   that changes, or its completeness guard fails.
2. **The session list**: filters, quick facets, sorts, the row element. Four
   `SessionFilter` fields change meaning (`duration_manual_hours`,
   `duration_calculated_hours`, `is_manual`, `is_active`), `timestamp_end`
   becomes meaningless for Duration-only rows, and `game`, `search` and
   `device_filter` all reach the game through the run now.
   `QUICK_FACETS["sessions"]` moves with them.
3. **The Game list and Game detail.** The list's playtime column and both
   `playtime` and `filtered_playtime` sorts, then detail's session table,
   playtime figure and `without_manual()` average — whose name describes
   `duration_calculated`, not manual time, and which needs restating in mode
   terms.
4. **`GameFilter`'s session aggregates**: `session_count`, `session_average`,
   `manual_playtime_hours`, `calculated_playtime_hours`, and
   `QUICK_FACETS["games"]`'s `playtime_hours`. Three of those sources are
   columns #772 deletes, and `Game.sessions` as a reverse accessor ceases to
   exist — the replacement path crosses `player_games__playthroughs__sessions`
   and must stay library-scoped on a shared catalog Game.
5. **Statistics**: `stats_data`, `stats_content`, and `stats_links`, whose
   builders emit `timestamp_start__between` and are parity-tested against the
   stat they link from, so both move together or the parity test is what breaks.
6. **The navbar and layout**: `model_counts`'s today and last-seven-days
   figures, and `recent_session_resumes` in `common/layout.py` — the only
   `keyset_pages` read of Session, keyed on `(timestamp_start, id)` behind
   `session_start_id_idx`. The new table needs the equivalent index and keyset
   key.
7. **The API**: `GET /api/session/`, `GET /{id}`, `PATCH /{id}/device`,
   `PATCH /{id}` — all four write through `session.save()` today — plus
   `/api/devices/search`'s `Max("session__timestamp_start")` ordering and
   `/api/timezones/search`, which feeds the per-session zone picker. The router
   keys on the session and refuses unknown body keys, following #1015, so the
   dying field names cannot pass unread.
8. **The TypeScript contract**: `ts/elements/filter-tree/fixtures.json` is
   session-saturated — a `session_filter` relation, a `session_count` scope, and
   two field-comparison cases on the session model — and
   `tests/test_filter_tree_contract.py` maps `"session"` to `SessionFilter`.
   The serializer and its fixtures move with the vocabulary or the
   cross-language contract test fails.
9. **The dormancy clock** in `games/reads/playthrough_activity.py`, which reads
   `Session` directly. This member also owns the narrowing the Playthrough wave
   deferred here: the clock currently asks when the *game* was last played and
   must ask when the *run* was. Its zone is #1047's to decide, not this
   member's: the clock computes its day with `TruncDate(..., tzinfo=clock.zone)`
   from the viewer's preference while `default_activity_clock()` uses UTC, and
   `effective_day` is frozen in the `day_zone` #689 seeds from the viewer's
   display zone. This member reads the answer #1047 states.
10. **`audit_library_ownership`**, whose session count and hand-written
    `Session.device` cross-library check both read the `game` foreign key the
    new table does not have. The registry-driven `cross_library_violations`
    replaces the second; the derived count needs a successor.
11. **e2e**: `test_session_finish_e2e.py`, `test_session_reset_e2e.py`,
    `test_time_zone_row_e2e.py`, `test_datetime_field_e2e.py`,
    `test_duration_format_e2e.py`, `test_quick_filter_e2e.py`.

The read scope is settled: `library_sessions()` (#697) hides a `PlayerSession`
under all four removal marks and states the library on the session, its run and
its tracked game. Every read-layer reader this issue adds states it.

No temporary compatibility writer is built in either direction, so this wave
adds nothing for #774 to remove.

Saved presets are not migrated. Production holds three, all `mode='playthroughs'`,
none naming a session field — so the conclusion holds, but the reason is "none
names a dying field", not "the table is empty". #767 keeps the versioned
registry if a later wave wants one.

**Delivered.** The design is
[Switch Session writes and every read surface](2026-09-15-issue-702-session-cutover-design.md);
three members (#1075, #1076, #1077), what they settled, and what
#704 inherits:

- **The form derives the mode from what is filled.** No mode control; two
  shapes are refused naming the shapes that work. A duration beside two
  instants replaces elapsed time, which is what Corrected means.
- **The filter is `PlayerSessionFilter`, in projection words**, under model
  key `playersession`; the four dying fields are replaced, not aliased, and a
  key no field answers is refused rather than dropped.
- **The bucket takes no new session.** Clone and resume name the game's
  latest live ordinary run, keyed on the game, never the source's run. A
  session on a game nothing tracks is refused on the run.
- **Aggregates always take the context scope**, so a shared catalog game
  counts one library's rows whether or not a scope filter is stated.
- **Superlatives read `effective_duration`**, so a Corrected row enters at its
  override and a Duration-only row at its stated duration. #704's equality
  gate measures against that, not against elapsed time alone.
- **The dormancy clock asks when the run was last played**, so a run whose
  play sits in the bucket reads Never played until the sessions are moved.
- **A foreign device on the API answers 404**, ahead of the command's 409.
- **The legacy table has one guard**: `tests/test_session_import_guard.py`
  fails on an import outside the conversion, the census, the legacy playtime
  source, the removal registry and the fixture commands. #772 empties its
  list.

### #704 — the gates

Replay parity for the projections, statistics parity against the legacy reads,
and determinism of replay under a stated zone.

Statistics parity is a **strict equality** gate: every figure on the stats
page, the navbar, the Game list and Game detail is equal before and after, on
restored production data.

#689 seeds `day_zone` from the viewer's display zone, the zone today's reads
group days in, which is what makes strict equality reachable; seeding from
`settings.TIME_ZONE` would have moved 124 sessions to another day, 10 to another
month and 5 to another year, and this gate would have failed by exactly that
amount. Equality holds while the viewer's zone is the one the rows were seeded
in, and #704 states the zone each of its figures was measured in. #697 ships
the gate's instrument, `make verify-playtime-parity`.

The performance gate states a **budget** rather than a verdict. It names a
per-read threshold measured on restored production data for the reads that grow
— the list and API row path, which is four joins after `select_related` becomes
`playthrough__player_game__game__platform`, the game list's playtime sort, and
the stats aggregate set — and names materialisation of exactly the breaching
cells as the remedy if one is exceeded. Today's figures, recorded in this
document, are the baseline.

Two branches have no production data and are covered synthetically: Corrected
mode, which no legacy row converts into, and arbitration between two dated
overlapping run intervals, which no production session encounters.

### #772 — remove legacy Session storage

Rewritten from "remove legacy Session generated fields and signals". The table
goes whole, as #771 took `PlayEvent`; removing two generated columns from a
table that is itself being retired is not a separate act. Pulled into this wave
from #602, as #771 was pulled into the Playthrough wave.

It also takes `Session` out of `REMOVABLE_MODELS` and out of the builder table
in `tests/test_removable_models.py`, which fails until the two agree, and
removes the `_AFTER_STAMP` entry in `games/removal.py`.

The sample fixture is converted with it: `games/fixtures/sample.yaml.gz` holds
2,807 `games.session` records and no `games.playergame` or `games.playthrough`
records, because those already replay from its 4,244 `games.libraryevent` rows.
Sessions must replay the same way, which means `anonymize_sample` shifts event
payloads rather than columns, and `LOADABLE_MODELS`/`FIXTURE_RELATIONSHIPS` in
`load_sample_data` lose their session entries. `make loadsample`, `make init`,
`entrypoint.sh LOAD_SAMPLE_DATA` and `tests/test_anonymize_sample.py` all ride
on that, and the fixture becomes unloadable the moment the table goes — the
same class of trap that killed two CLEAN-02 attempts.

## Cross-wave handoffs

### Release on a Session moves to ACCESS

#690 carried both event-sourced creation and the reusable Release selector the
catalog wave deferred to it. A Session naming a Release is only meaningful once
`LibraryEntry` exists to say the library has that Release, which is #719–#724.
The selector and its UI ship there, with their real consumer. The creation
payload reserves an optional Release field from day one, so nothing is
retrofitted into an event type later.

### #909's `visible_row` stays closed, and its reopen moves

#601 records the reopen candidate as "an evented Session names a Device and a
Platform". Session names no Platform today, and with Release deferred the
question rests entirely on what `CreateSession` takes. It takes a **run**,
explicitly — a strictly scoped resolve, like the Device beside it — so this
wave produces no second caller of a `visible_to` model and `visible_row` stays
closed.

Had the command taken a Game and derived the run, it would have been that
second caller and #909 would reopen here. The reopen moves to ACCESS.

### #696 becomes part of #908

A "temporary operator Session-recovery command" is the capability #664's
`library.user_id == actor.pk` predicate makes inexpressible, which is #908.
#908's hard part is not the predicate but who may call it, what is audited, and
how the events present — which is why it already waits on Audit History
(#740–#743) and #794. Answering it temporarily here answers it twice. #696
closes, its outcome recorded in #908.

### #695 leaves the wave

Undo for a removed session is a toast affordance over `RestoreSession`, which
#694 ships. It carries no parity obligation and blocks no gate, so it lands any
time after the cutover.

### ORG inherits one command and two rows

#714's bulk Session-to-Playthrough move is the bulk form of
`MoveSessionToPlaythrough`, not a second mechanism. The organizer (#715–#717)
inherits one bucket holding two sessions.

Worth costing, because this wave creates it: between #694 and #714 the only
remedy for #1011's refusal is moving sessions one at a time, and the busiest
production run holds 47. A sole run at a well-played game is effectively
unremovable for that whole gap.

### HIST composes at read time

With no totals projection, a Historical Playtime Record contributes to a total
by being summed beside the sessions, in whichever scope the charter's
granularity rule admits it to. #710's tracked-versus-estimated split is two
read-time sums. Historical records never contribute to session count, average,
longest, or streaks, so no Session-derived statistic changes shape.

### The Journal keeps its own day rules

#748 rebuilds Journal day projections when a library's day zone changes; that
rebuild stays the Journal's, but its trigger is #1047's, shared with #1054's
restatement of session days. This wave stores a day computed in one stated
zone — the viewer's display zone, per #689 — and ships no restatement path.

The Journal's stated day rules already match this model's columns exactly — a
Duration-only Session takes its written calendar day without conversion, a
timed one takes the display-timezone date of its instant — so `stated_day` and
`started_at` are the two fields its projector will read.

### #1045 is independent

The hour-bucket duration filter bug, found while taking the census for this
review, affects seven filter fields and can land at any time. Three of those
fields die in this wave; it is recorded as one reason they are replaced rather
than aliased forward.

## The deployment window

**Nothing deploys between #700 and #704.** The wave ships as one release.

This is a constraint, not a preference. #700 converts every legacy row into an
event and populates the projection, but writes do not switch to commands until
#702. In that window the legacy write path is still the live one, so a session
created through it lands in the legacy table and in no event — the projection
silently stops keeping up, and every read cut over after it would be short a
row.

On `main` that is harmless, because the intermediate states are only ever built
and tested, never served. It becomes wrong the moment someone deploys mid-wave.

The issues before #700 carry no such constraint: #689 leaves a table nothing
writes, #691, #692 and #694 leave commands nothing calls, and #697 changes a
read whose answer is unchanged. Each is incomplete rather than inconsistent, so
each merges on its own like any other issue. Only #702's own members are
mutually broken halfway — writes through commands while reads still read a
legacy table nothing updates — which is why that issue alone is delivered as an
atomically merged stack.

#704 is what lifts the constraint: once parity is green, the projection is the
record and the legacy table is inert.

## Migration, rollback, and reconciliation

The conversion is one pass over 2,807 rows, appending one event each, at the
scale #676 and #684 already ran. It is reversible by discarding the projection
and the appended events while legacy storage stands, which it does until #772.

The reconciliation report states, per library: rows converted per mode, the
three assignment outcomes, bucket size, playtime totals before and after in
each scope, and session counts before and after. A differing row fails the
migration rather than being reported and accepted.

`make verify-replay-parity` and `make verify-dump` are the rehearsals, and the
pre-deploy dump restore is a prerequisite of shipping as it was for the catalog
wave.

## Verification contract

- The preflight's census matches a hand-written query over the production dump,
  for every category it reports, and every rule is expressed as
  `duration_manual > INTERVAL '0'` rather than as a presence test.
- Every mode's CHECK constraint refuses the rows it should, proven directly,
  including `stated_day` on a Timed or Corrected row.
- Replay from an empty stream reproduces `PlayerSession` and the affected
  `Playthrough` rows exactly.
- Statistics parity is strict equality: every figure on the stats page, the
  navbar, the Game list and Game detail is equal before and after, on restored
  production data.
- The cross-language filter contract test passes with the rewritten fixtures.
- The performance budget is measured with `make bench` against the four-join row
  path, not asserted, and compared against the baseline recorded here.
- The sample fixture loads after conversion, and `make loadsample` works from an
  empty database.
- `make check` is green at every merged commit, and the cutover stack is merged
  atomically.

## What was applied

Merged, because each states one act:

- #690 into #689 — a creation command and the table it writes are one issue
- #693 into #689 — a note is a field on a payload, not an act
- #698 into #697 — a yearly figure is the same read with a year
- #701 into #700 — the classification is the event payload
- #703 into #702 — stated above, and delivered as a stack whose members are the
  boundaries the split would have given

Moved out:

- #695 — after the wave
- #696 — closed, its outcome moved into #908
- Release on a Session — to ACCESS (#719–#724)

Pulled in:

- #772 — from #602, rewritten to take the storage, the fixture, and the
  `REMOVABLE_MODELS` entry

Dropped from the plan during review:

- `PlaytimeTotal` — measured at roughly a millisecond of benefit, unable to
  serve the sub-filtered aggregates at all, and with the Journal materialising
  its own durations. #704 states a budget instead

Reordered:

- #699 from eleventh to first
- #694 behind #692, which owns the remedy for the refusal #694 makes live

Amended in the charter, on the evidence of the production census:

- the preflight's blocking rule, which misreads 142 manual-entry rows as
  running sessions
- the separate mode and provenance vocabularies, collapsed to one word on a
  Session
- the assignment rule, twice: a sole run wins regardless of dates (164 sessions
  in UTC, 113 in Europe/Prague, sit outside their sole run's interval), and an
  undated run does not claim containment (without which every ambiguous row in
  production is an artifact and the bucket holds ten instead of two)

## Follow-up issues

Filed from this review, and restated on 2026-09-14 once #699 and #689 had
overturned the zone premise the first version carried:

- #1047 — the one zone a library counts days in, reconciling the stored
  `day_zone` with #1033's `ActivityClock`, and the one act that changes it.
  Joins the delivery order before #702. A change of zone moves 124 production
  sessions to a different day, 10 to a different month and 5 to a different
  year; that delta is evidence for the decision, not a parity failure
- #1054 — the restatement of recorded session days on #1047's act, as an event
  whose shape (per session or per library) it decides. Never an `UPDATE` of
  `day_zone`
- #748 — the Journal's day-projection rebuild, the second registrant of the
  same act
- #1048 — bulk move before the organizer, or accept the gap: between #694 and
  #714 a run with many sessions cannot be removed without moving each session
  by hand
