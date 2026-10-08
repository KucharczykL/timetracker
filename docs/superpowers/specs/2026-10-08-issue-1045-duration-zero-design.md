# Duration filters: none apart from under an hour

Issue: #1045 (bug). Independent of every wave
([Sessions wave, "#1045 is independent"](2026-09-12-session-wave-design.md)).
Working draft; condense before implementation.

## Problem

A duration filter takes whole hours. `EQUALS h` compiles to the half-open
bucket `[h, h+1)`, so `= 0` returns rows that have a duration under one hour
along with rows that have none. `LESS_THAN 1` has the same problem from the
other side. No modifier separates *none* from *a little*. The issue's
restatement (2026-09-16) lists four fields. Main has five, and the presence
pair is broken on two of them (finding F3).

## Verified findings

Repro: a scratch pytest module run with
`make test ARGS="-c pyproject.toml --rootdir=. <scratch>/test_repro_1045.py -s"`,
and a scratch `conftest.py` that loads `tests/conftest.py`. Data: four tracked
games. *unplayed* has no session. *half_hour* has one 30-minute Timed session.
*running_only* has one Timed session with no end. *two_hours* has one 2-hour
Timed session. Two records: 20 minutes and 3 hours.

### F1. Five fields share the bucket, not four

| field | filter | compiles through | file:line |
|---|---|---|---|
| `playtime_hours` | `GameFilter` | `duration_hours_handler("playtime")` | `games/filters.py:368` |
| `duration_hours` | `PlayerSessionFilter` | `duration_hours_handler("effective_duration")` | `games/filters.py:628-631` |
| `duration_hours` | `HistoricalPlaytimeFilter` | `duration_hours_handler("duration")` | `games/filters.py:1009-1012` |
| `session_average` | `GameFilter` | `AggregateSpec("avg", unit="duration_hours")` | `games/filters.py:1301-1307` |
| `session_playtime_hours` | `GameFilter` | `AggregateSpec("sum", unit="duration_hours")` | `games/filters.py:1318-1324` |

The issue's restatement leaves out `HistoricalPlaytimeFilter.duration_hours`.
All five reach `duration_hours_to_q` (`common/criteria.py:3124-3183`). The
EQUALS bucket is at `:3138-3144`, and NOT_EQUALS negates it at `:3145-3151`.
The aggregate path calls it at `:3663-3666`.

Repro output, `EQUALS 0`:

- `playtime_hours` → unplayed, half_hour, running_only
- session `duration_hours` → the 30-minute session and the running session
- record `duration_hours` → the 20-minute record
- `session_playtime_hours`, `session_average` → half_hour, running_only

`LESS_THAN 1` gives the same set on every field.

### F2. IS_NULL already means "zero duration"

`duration_hours_to_q` compiles `IS_NULL` to `field = timedelta(0)` and
`NOT_NULL` to its negation (`common/criteria.py:3176-3179`). The docstring
states this at `:3130-3131`. So the framework already has an exact-zero
predicate for every duration field. Two problems stop it from working:

- **It is hidden on three fields.** A handler-mapped field has no column, so
  `field_metadata` reads it as not nullable (`common/criteria.py:3025-3026`).
  `_modifiers_for_field` then drops the presence pair (`:2902-2907`). The repro
  shows the vocabulary of `playtime_hours` and both `duration_hours` fields
  without `IS_NULL`/`NOT_NULL`. `tests/test_filters.py:5160-5164` pins
`nullable` False on `playtime_hours`, and its comment states the default.
- **The backend accepts it anyway.** `from_json` does not check the
  vocabulary. `{"playtime_hours":{"modifier":"IS_NULL"}}` returns unplayed and
  running_only. `tests/test_filters.py:1252-1258` pins this, and so does
  `GameFilter.where(playtime_hours__isnull=True)`
  (`tests/test_filter_where.py:52-54`). The quick bar degrades such a filter
  to the pill (`common/components/quick_filter.py:304-305`). `NumberFilter`
  replaces a modifier it does not offer with the first offered one, without a
  notice (`common/components/filters.py:944-946`). In the repro, a
  `playtime_hours` widget given `IS_NULL` renders `EQUALS` selected and no
  `IS_NULL` option.

### F3. On the two aggregates, IS_NULL misses "no sessions"

A sum or avg over no rows is SQL NULL. `field_metadata` offers the presence
pair for that reason (`common/criteria.py:3019-3024`). But the duration unit
sends `IS_NULL` to `_agg = 0`, and NULL is not equal to 0. Repro:

- `session_playtime_hours IS_NULL` → running_only (not unplayed)
- `session_playtime_hours NOT_NULL` → half_hour, two_hours (not unplayed)
- the same for `session_average`

*unplayed* matches no modifier on either aggregate. It is not in `= 0`,
`< 1`, `IS_NULL` or `NOT_NULL`. `tests/test_field_widget.py:134-140` says
"is null" on `session_average` "reads as 'never played'". That is false today.
`tests/test_filters.py:5935-5962` pins the true behaviour and asks that a
change to it be a deliberate decision. This spec makes that decision.

### F4. Where zero occurs

- `PlayerSession.effective_duration` is `Coalesce(stated_duration,
  ended_at - started_at, 0)` (`games/models.py:1806-1815`). Zero is a running
  Timed session, or a row whose stated or elapsed time is zero. The CHECK
  admits `stated_duration >= 0` (`:1912-1914`). The command refuses a
  Duration-only zero (`games/commands/playersession.py:357-363`).
- `Game.playtime` is zero when unplayed (`games/reads/playtime.py:167-175`,
  `zero_when_null`), so it is never NULL. A game whose only session is
  running reads zero (running_only above).
- `HistoricalPlaytime.duration` is never zero: CHECK
  `historicalplaytime_duration_positive` (`games/models.py:2064-2066`). A
  presence test on it is vacuous.
- The aggregates are NULL over no sessions in scope and zero when every
  session in scope is zero.

### F5. Precision differs between the two paths

The handler fields take `IntCriterion` (`common/criteria.py:483-487`), and
`_coerce_int` refuses `1.5` (`:256-265`). The aggregates take
`AggregateCriterion` (`:845-861`, `_coerce_number`), which keeps a fraction.
`session_average EQUALS 0.5` compiles to `[0.5 h, 1.5 h)` and returns
half_hour. `tests/test_filters.py:2311-2314` pins fractional parsing.

### F6. The bucket conflicts with the ordering modifiers

`EQUALS 1` matches 1 h 30 min. `LESS_THAN_OR_EQUAL 1` does not
(`common/criteria.py:3158-3159`). `BETWEEN 1 2` is closed on both ends
(`:3160-3166`). Only EQUALS and NOT_EQUALS use the bucket.

### F7. Presentation is per kind and has no unit

- `NUMBER_MODIFIER_LABELS` (`common/components/filters.py:908-919`):
  `is`, `is not`, …, `is null`, `is not null`.
- `MODIFIER_PHRASES` (`ts/elements/filter-tree/summary.ts:50-68`): `IS_NULL`
  "is empty", `NOT_NULL` "is set". This is field-blind.
  `tests/test_summary_modifier_contract.py` pins its keys.
- Builder labels: "Playtime Hours", "Session Average" (no unit), "Session
  Playtime Hours", "Duration (hours)". Quick facets: "Playtime (hrs)"
  (`common/components/quick_filter.py:131-136`) and "Duration (hrs)"
  (`:169-174`, `:212-217`). The two aggregates are not quick facets.
- No `FieldMeta` key says that a number is hours.

### F8. Dead code

`bool_nonzero_duration_handler` (`common/criteria.py:3269-3281`) has no
caller. Only `tests/test_filters.py:71,4702-4711` imports it. The restatement
says it is gone, but it is still on main.

### F9. Callers that pin the current behaviour

Every stored or emitted duration criterion in application code uses an
ordering modifier. The reclassification view uses `duration_hours
GREATER_THAN_OR_EQUAL` (`games/views/session_reclassification.py:151`). No
stats link emits a duration criterion. These tests use EQUALS and keep their
meaning under this design: `tests/test_filters.py:1059,1178,4665,5729,5904`,
`tests/test_rendered_pages.py:795`. The e2e tests use `GREATER_THAN` only
(`e2e/test_quick_filter_e2e.py:104-119,337-347`).

## Prior art

- **In this repo.** A day facet compares an instant at day precision
  (`calendar_day_handler`, `common/criteria.py:3191-3201`). `EQUALS` is the
  whole day, and the field name states the precision. "None" is the presence
  pair. Other number facets (`amount` with `step="0.01"`, `days_to_finish`,
  `year_released`) compare exactly, because their values are discrete. The
  set picker pins presence as `(Any)`/`(None)`
  (`common/components/filters.py:211-216`). That is the one presence wording
  a person sees in a facet today.
- **Stash** (the model for this filter system) casts a duration to whole
  seconds and compares it exactly. `IS_NULL` means the duration is absent
  (`pkg/sqlite/criterion_handlers.go`, `floatIntCriterionHandler`). Exactness
  works there because the input precision (seconds) matches the stored
  precision.
- **Conclusion.** Exact equality on a measured length is useful only at zero.
  A bucket is acceptable when the UI names it. "None" belongs to the presence
  pair, not to a magic value of EQUALS.

## Directions evaluated

1. **Relabel the bucket.** Needed: it stops the filter from lying. But alone
   it gives no way to ask for none. Taken, as presentation only (U2).
2. **None/any predicate on every duration field.** Taken. The framework
   already has the predicate (F2). The fix exposes it, defines it correctly
   on the aggregates (F3), and states where it is vacuous (F4).
3. **Sub-hour input.** Rejected for this issue. It changes `IntCriterion`
   to a fractional or minutes value on three filters, the TS reader, the URL
   grammar and saved presets, to gain exact equality at sub-hour precision.
   The only exact value anyone asks for is zero, and direction 2 already
   answers that. F5 records an inconsistency that already exists; see the
   follow-ups.
4. **EQUALS 0 means exactly zero, for 0 only.** Rejected. It is a jump in
   one value (`= 0` is `{0}`, `= 1` is `[1, 2)`). It silently changes every
   saved preset and bookmarked URL that holds `= 0`. It leaves "under an
   hour, none included" expressible only as an AND of two criteria, which
   the quick bar cannot hold.
5. **Floor every modifier, like the day facet.** Rejected. `> 2` would mean
   "at least 3 h". A person who asks for more than two hours expects 2 h 30
   min.
6. **Take EQUALS/NOT_EQUALS off duration fields.** Not decided here, because
   it is a visible vocabulary change; the user did not take it (U2). The wire keeps compiling
   either way.

## Design (decided)

### D1. The field metadata states the unit

The vocabulary needs no unit: D3 uses `FilterField.nullable`. The decided
presentation (U1–U2) does need one. The presence labels and the bucket hint
are for duration fields only, while `year_released` and `session_count` keep
"is null" and plain "is". The TS summary reads only `FieldMeta`. So:

- `FieldMeta` gets `unit: NotRequired[DurationUnit]`. `DurationUnit`
  (`common/criteria.py:1358`) is today on `AggregateSpec.unit` alone. The key
  is set on the five duration fields and absent on every other field.
  `ts_codegen` already emits `NotRequired` keys as optional
  (`common/components/ts_codegen.py:171-178`).
- A handler field states it through a mark on `duration_hours_handler`'s
  handler, read by a `FilterField.unit` property. This is the pattern
  `temporal_interval_handler` uses for `interval_bounds`
  (`common/criteria.py:3356`, read at `:1059`). An aggregate reads
  `AggregateSpec.unit`.
- The key is optional so the hand-written `FieldMeta` objects in TS tests
  still compile: `ts/elements/filter-group.test.ts`,
  `ts/elements/filter-tree/summary.test.ts`,
  `ts/elements/filter-tree/operations.test.ts`,
  `ts/elements/filter-tree/test-support.ts`, and any partial metadata in
  `ts/elements/filter-summary.test.ts` and `client-errors.test.ts`.

### D2. The presence pair means "no duration" and "some duration"

`duration_hours_to_q` becomes the one definition:

- `IS_NULL` → `Q(field=timedelta(0)) | Q(field__isnull=True)`
- `NOT_NULL` → `Q(field__gt=timedelta(0))`

On a non-null column the `isnull` arm is vacuous. `_not_in_q` uses the same
pattern (`common/criteria.py:700-709`). On an aggregate, the arm brings a game
with no sessions in scope into "none", and `NOT_NULL` keeps it out. For every
duration field, the two modifiers now partition the rows. `> 0` replaces
`~(= 0)`, because a negated equality on a NULL aggregate is unknown and drops
the row again.

*Why "none" includes NULL on `session_average`*: an average over no sessions
is not a number, but "this game has no session time" is true. The widget test
already claims this reading (F3). The alternative, NULL only, would make
"none" miss a game whose only session is running, while `playtime_hours`
"none" includes that game.

`EQUALS`, `NOT_EQUALS`, `LESS_THAN` and the others keep their SQL. A NULL
aggregate still matches none of them, so `= 0` and `!= 0` do not split an
aggregate into two complete sets: `!= 0` leaves out a game with no sessions
in scope (follow-up 3).

**The "none" sets differ between the game fields.** `Game.playtime` adds
historical playtime to session time (`games/reads/playtime.py:171-175`).
A game whose only playtime is a record is "some" on `playtime_hours` and
"none" on `session_playtime_hours` and `session_average`. This is correct,
because the aggregates count sessions alone. The partition test pins it.

### D3. Every duration field where none can occur offers the pair

`FilterField.nullable` (`common/criteria.py:1053`, read at `:3013-3014`)
already states the presence pair for a field that names no column. Five
fields use it: `games/filters.py:242,383,389,935,1225`. Set `nullable=True`
on `playtime_hours` and on session `duration_hours`. Leave the record
field at the default.

| field | offers the pair | why |
|---|---|---|
| `playtime_hours` | yes, new (`nullable=True`) | unplayed, or running only |
| session `duration_hours` | yes, new (`nullable=True`) | running, or a zero-length row |
| record `duration_hours` | no (default) | CHECK > 0 (`games/models.py:2064-2066`) |
| `session_average` | yes, as now (reducer) | NULL or zero |
| `session_playtime_hours` | yes, as now (reducer) | NULL or zero |

No change to `_modifiers_for_field`. For these handlers, `nullable` means
"has a presence test", and D2 defines that test.

Once the two fields offer the pair, the quick bar admits them
(`is_quick_editable` reads `meta["modifiers"]`), and the F2 rewrite stops
for these fields.

### D4. EQUALS stays the hour bucket on the wire

`{"modifier":"EQUALS","value":h}` keeps `[h, h+1)`, and NOT_EQUALS keeps its
complement. That applies to fractional aggregate values too (F5). Saved
presets and URLs keep their meaning, and no data migration is needed.

One stored meaning does change: a stored `IS_NULL` on `session_average` or
`session_playtime_hours` (`FilterPreset.object_filter`,
`games/models.py:1063`) now also matches games with no sessions in scope
(D2). That is the fix for F3, so no migration is needed. No fixture or
migration in the repo stores such a preset: `games/fixtures` and
`games/migrations` name neither field, and the sample fixture dumps no
`FilterPreset`. Production presets are unknown; the release note says so. Only
presentation changes (U2). The docstring of `duration_hours_to_q` states
both rules (bucket, presence) as current behaviour.

### D5. Delete `bool_nonzero_duration_handler`

D2 replaces it. Delete the factory, its import and
`TestFilterFieldHandlers.test_bool_nonzero_duration_handler`. Update the
`FieldHandler` comment at `common/criteria.py:1014-1017`, which names the bool
presence/zero case, the `FilterField` docstring at `:1027-1032`, and the
section comment above the handler factories at `:3184-3187` ("bool
presence/zero fields").

### D6. Correct the tests that state the old reading

- `tests/test_filters.py:5935-5962`
  (`test_scoped_sum_is_null_when_no_row_matches_the_scope`): with D2, the
  NULL sum matches `IS_NULL`, and `EQUALS 0` still does not. Rename the test
  and flip the IS_NULL assertion.
- `tests/test_filters.py:5160-5164` (`test_handler_field_defaults_not_nullable`)
  pins `playtime_hours` `nullable` False, and its comment says a handler
  field is never nullable. Move it to the record `duration_hours` (still the
  default), and add a test that `playtime_hours` states `nullable` True and
  offers the pair.
- `tests/test_field_widget.py:134-140`: the comment becomes true. Keep it and
  add a DB assertion that proves it.

## Presentation (decided by the user, 2026-10-08)

### U1. Presence labels on a duration field

`IS_NULL` reads **"is 0 (none)"** and `NOT_NULL` reads **"is more than 0"**,
both in the number picker and in the builder summary ("Playtime (hrs) is 0
(none)"). They stay at the end of the picker list, where
`_modifiers_for_field` puts them now. Non-duration number fields keep "is
null"/"is not null" and "is empty"/"is set".

### U2. The hour bucket keeps "is" and shows a hint

`EQUALS`/`NOT_EQUALS` keep the labels "is"/"is not". Under the inputs, a
duration field shows the bucket for the typed value: **"0 h up to 1 h"** for
`is 0`, and "outside 0 h up to 1 h" for `is not 0`. A fractional aggregate
value gives "0.5 h up to 1.5 h". There is no hint for any other modifier or
for an empty value. The server renders the first state, and the widget's TS
updates it on input and on a modifier pick, so it never flashes. The builder
summary writes the same range: "Duration (hrs) is 0 h up to 1 h".

### U3. Field labels

Every duration field ends in "(hrs)", as the quick facets already do:
"Playtime (hrs)", "Duration (hrs)" (session and record), "Session average
(hrs)", "Session playtime (hrs)". The handler fields set `FilterField.label`,
and the aggregates set `GameFilter.labels`. No test pins the old labels.

### Options not taken

- Q1: `(None)`/`(Any)` ("(Any)" reads as "zero included") and "is none" /
  "is more than none".
- Q2: static "is (whole hours)" labels, and taking EQUALS/NOT_EQUALS off
  duration pickers (it needed follow-up 1 first).
- Q3: "(hours)" everywhere, or no change.

## Test plan

Python (`tests/test_filters.py` unless named):

1. `duration_hours_to_q` compiles `IS_NULL` to the `= 0 | IS NULL` Q and
   `NOT_NULL` to `> 0`. EQUALS keeps the bucket
   (`test_duration_hours_equals_bucket` unchanged).
2. A partition test, parametrised over the five fields, uses the repro's
   world: unplayed, half-hour, running-only, two-hours, a records-only game
   (`hist_only`, one 20-minute record and no session), and a 3-hour record.
   Assert that `IS_NULL` and `NOT_NULL` are disjoint and cover the scope.
   Expected "none" sets: `playtime_hours` {unplayed, running_only};
   `session_playtime_hours` and `session_average` {unplayed, running_only,
   hist_only}; the running session on sessions; no record on records. Also
   pin that `NOT_EQUALS 0` on an aggregate leaves out unplayed and
   hist_only (follow-up 3).
3. `EQUALS 0` keeps `[0, 1)` on every field (a regression pin for D4).
4. `field_metadata`: `modifiers` matches the D3 table, `unit` is present on
   the five fields and absent elsewhere, and labels follow U3.
5. `is_quick_editable` admits `{"playtime_hours":{"modifier":"IS_NULL"}}`
   and the session `duration_hours` equivalent
   (`tests/test_quick_filter_bar.py`).
6. `field_widget(GameFilter, "playtime_hours")` renders the pair with the
   U1 labels and the U2 hint (`tests/test_field_widget.py`).
   `purchase_price_total` keeps "is null" and has no hint.
7. The `test_scoped_sum…` flip and the comment fixes from D6.
8. `bool_nonzero_duration_handler` is deleted together with its test. No
   guard is needed against it coming back.

TypeScript (vitest):

9. `summary.test.ts`: a duration presence leaf and an EQUALS leaf phrase per
   U1/U2 when `unit` is set. A non-duration number field keeps today's
   phrases.
10. Contract: add a `fixtures.json` case `playtime_hours IS_NULL` on
    `game`. vitest regenerates `ts/elements/filter-tree/fixtures.canonical.json`
    (gitignored), and `tests/test_filter_tree_contract.py:32` reads it to
    prove the TS output is `to_q()`-equivalent.
11. The bucket hint text for `is 0`, `is not 1`, `0.5`, empty, and `>`,
    the same cases in Python and TS.

E2E (`e2e/test_quick_filter_e2e.py`):

12. Open Playtime (hrs), pick the "none" modifier, and Apply. The URL holds
    `{"playtime_hours":{"modifier":"IS_NULL"}}`, the list shows the unplayed
    game and not a 30-minute one, and the facet reopens with the modifier
    still held.

Gate: full `make check` under the shared lock.

## Follow-up issues to file

1. **The number and string widgets rewrite a modifier they do not offer
   without a notice** (`common/components/filters.py:944-946`, and the
   `StringFilter` equivalent). A builder row hydrated from a stored filter
   should refuse or degrade, as the quick bar does, and not save a different
   filter. This is general, not specific to durations.
2. **Duration aggregate values accept fractions; handler fields do not**
   (F5). Decide one precision for "hours" across `IntCriterion` and
   `AggregateCriterion` on duration units, or adopt direction 3
   (minute/decimal input) everywhere at once.
3. **A sum over no sessions is NULL, not zero.** So `session_playtime_hours
   < 1` leaves out a game with no sessions, while `playtime_hours < 1`
   includes it (it is zero-coalesced). Likewise `= 0` and `!= 0` do not split
   an aggregate into complete sets: `!= 0` leaves out unplayed and
   records-only games. Decide whether duration sums coalesce. D2 fixes only
   the presence pair.
4. **Bucket vs ordering** (F6): `= 1` includes 1 h 30 min and `≤ 1` does
   not. After the U2 hint ships, see whether people still find this
   confusing before changing any semantics.
5. **The issue's restatement is out of date**: it lists four fields (five
   exist) and says `bool_nonzero_duration_handler` is gone (it is still on
   main until D5). Correct the issue when this lands.

## Wave notes

None of this blocks a wave. The Sessions wave already removed the three
legacy fields. `effective_duration` is the projection's generated column, so
D2 needs no write. D1's `FieldMeta` key is optional, so branches in flight
that build `FieldMeta` by hand in TS tests still compile.
