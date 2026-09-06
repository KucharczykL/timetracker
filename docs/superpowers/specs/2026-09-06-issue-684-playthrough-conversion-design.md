# Convert legacy PlayEvents into Playthrough facts

Issue [#684](https://github.com/KucharczykL/timetracker/issues/684). Parent
phase [#601](https://github.com/KucharczykL/timetracker/issues/601). Wave
review: [Playthrough delivery wave](2026-09-04-playthrough-wave-design.md).
Predecessors: [the Playthrough aggregate](2026-09-04-issue-679-playthrough-aggregate-design.md),
[the preflight report](2026-09-04-issue-686-playthrough-preflight-design.md),
[a start and a completion](2026-09-06-issue-681-playthrough-endpoints-design.md),
[corrections](2026-09-06-issue-1010-playthrough-corrections-design.md), and
[removal](2026-09-06-issue-1011-playthrough-removal-design.md). The model for
the shape is [the PlayerGame baseline
backfill](2026-08-27-issue-676-playergame-baseline-backfill-design.md), whose
module is `games/backfill/playergame.py` and whose migration is
`0033_playergame_baseline_backfill`.

The legacy `PlayEvent` table is the only record of which games a library
played through and when. This run states every one of those rows as Playthrough
events, gives the games #676 tracked before a Playthrough existed the run every
tracked game holds, and pairs each lifecycle fact with the status event #676
already recorded. It writes no legacy row and switches no path.

## What a legacy row means

One rule, total over every shape the table holds:

> Every legacy row in scope becomes one ordinary Playthrough stating both acts.
> Each act takes its day from its column, or no day where that column is null.

The five shapes `games/preflight/playthrough.py` classifies land like this:

| Row | Start | Completion |
|---|---|---|
| both dates (203 rows) | that day | that day |
| neither date (6 rows) | stated, no day | stated, no day |
| start only (0 rows) | that day | stated, no day |
| completion only (0 rows) | stated, no day | that day |
| completion before start (0 rows) | that day | that day, as recorded |

The counts are the ones #686 published for the deployed database, restated
[in the issue](https://github.com/KucharczykL/timetracker/issues/684#issuecomment-5540176486).

### Why an endpoint-less row states two acts and not none

A row carrying neither date is not an empty row. It is the library's record
that a run happened whose days nobody wrote down, and the model has a place for
exactly that: `start_recorded_at` set beside a null `started` is #681's "played
before". A null marker means the act never happened, which is what the default
run of a freshly tracked game says, and it is not what these rows say.

The six such rows in the deployed database were read before this was settled.
They sit on five games, carry no note, and every one of their games has catalog
status `f`. Two are a three-second double submit on Dark Souls 2, which was
played through three times with only one of the three dated. Two are the only
record that the two Witcher games were finished. The library owner states that
the feature was never used for a run that was given up, so the completion each
row implies is a fact about the data rather than a guess.

That decision is not symmetric and the spec says so plainly: #1010's
corrections state a better **day** for an act, and no command un-states the act
itself. A completion stated here in error is repaired by stating a fresh run
beside it and then removing this one — that order, because `RemovePlaythrough`
refuses to take the last live ordinary run off a tracked game, and four of
those five games would hold exactly one. The exposure is those six rows; the
203 dated rows carry `ended` and are unaffected either way.

### Why no bucket

The wave gives the imported-history bucket to #700 and #701, which need one to
hold Sessions they cannot place. This run needs none: every shape above states
a fact, so every run it creates is ordinary.

That settles the verdict two review comments on the issue left open. The blank
name of an `IMPORTED_HISTORY` row has no display number, `display_name()`
raises `UnnumberedPlaythrough` over it, and `DescribePlaythrough` refuses to
take a name away from such a row — so the first creation event with that kind
must supply a name with the row. This run appends no such event, so it incurs
no such obligation, and the obligation stays with the issue that creates the
first bucket. `display_name()` and the refusal are left exactly as they stand.

A run converted from a removed row is ordinary and **not** numbered, because
`with_display_number()` counts numbers across live rows only. That is the
existing removed-row case, not the bucket case: `is_numbered()` answers False
over it, so a caller's `fallback` is honoured and nothing raises.

## Module

`games/backfill/playthrough.py`, shaped like its predecessor:
`PTHROUGH_ISSUE = 684`, `KEY_PREFIX = "backfill:684:playthrough"`, a private
`_append()` taking one event at a time, a summable `ConversionCounts`, then
`convert_game()`, `convert_library()` and `reconcile()`. `convert_library()`
takes its `run_time` defaulted, as `backfill_library()` does, so
`load_sample_data` calls it with the library alone.

One event per append, never one append per row. `LockedStream.append()` stamps
one `recorded_at` across every row of one call, and the events of a single
legacy row carry two different instants where the row was later removed. The
same reason held for #676 and the helper is the same helper.

`dispatch()` is not used, for the reason #676 states and for one more of its
own. A command validates against current state, and every refusal #681 and
#1011 wrote is a refusal this run must pass through: a second start on a run
that has one, a completion that precedes its start, the last live ordinary run
of a tracked game. Those guard what a person states next. This run states what
the library already recorded.

Every query reads through `.only()` over an explicit field tuple, one per model
the module touches — `PlayEvent`, `PlayerGame`, `Game`, `Playthrough` — for the
reason `_BACKFILL_GAME_FIELDS` records in #676's module: 0045 replays this code
against the concrete model long after the schema has moved on, and a bare
queryset selects the columns the model declares today. #770 and #771 both
target these tables.

The classifiers come from `games/preflight/playthrough.py`: `classify_row`,
`legacy_order_key`, `pair_endpoints`, `Endpoint`, `EndpointKind`,
`CandidateEvent` and `CandidateEvents`. Its `_candidate_events` becomes public
as `candidate_events`. Nothing is restated, so the run and the report cannot
answer differently about the same row.

## Events per row

A game's rows are converted in `legacy_order_key` order.

| Event | `effective_time` | `recorded_at` | `correlation_id` |
|---|---|---|---|
| `library.playthrough.created` | — | the row's `created_at` | fresh |
| `library.playthrough.note_changed`, where the note is non-blank | — | the row's `created_at` | fresh |
| `library.playthrough.started` | the row's `started`, or `None` | the row's `created_at` | paired, else fresh |
| `library.playthrough.completed` | the row's `ended`, or `None` | the row's `created_at` | paired, else fresh |
| `library.playthrough.removed`, where the row is removed | — | the row's `removed_at` | fresh |

`effective_time` is the load-bearing field: `Playthroughs._started` and
`._completed` read it onto the row's temporal columns, and `recorded_at`
reaches only the marker beside each.

The creation payload names the `PlayerGame` and `kind: "ordinary"`. A day that
is unknown is `None` rather than `TemporalValue.unknown()`. The column holds
`None` either way — `_normalize_temporal_model_value` answers `None` for any
unknown value — so the choice is about what the event says, and an event that
says nothing about a day is plainer than one that spells out an unknown.

The row's `note` becomes the run's `note`, not an endpoint's. Forty-five of the
209 rows carry one, none longer than 44 characters, and they read as summaries
of the run — "First playthrough", "22h according to endgame screen" — rather
than as remarks about the day an act happened. A blank note appends no event.

### Identity

Every aggregate id this run mints comes from `identity_at(recorded_at)`, never
`uuid.uuid7()`.

`games_playthrough` is in the identity audit's table set and declares
`created_at`, so `check_ordering` holds its primary keys to `created_at` order.
The projector writes `created_at = event.recorded_at`, which here is a day
between 2014 and 2024, and a `uuid7()` minted at run time carries 2026. The
first converted row would break the audit. #676 escaped this only because
`PlayerGame` names its column `tracked_at`, which no order source matches, so
that table is skipped.

`identity_at` also settles the display order. `PlayEvent` is audited the same
way, against its own `created_at`, so the legacy rows' primary keys already
ascend with their `created_at`. Deriving each run's identity from the row's
`created_at` therefore reproduces `legacy_order_key`'s pk tiebreak in
`Playthrough.id` — down to the microsecond, which is the resolution
`identity_at` carries.

Below a microsecond the two orders are peers, not agreed. `created_at` is the
display order's **third** sort field and `Playthrough.id` the fourth; two rows
sharing both a day pair and a `created_at` sort by a random tail. The sample
fixture is exactly that case — its anonymizer stamps every undated row
`2020-01-01 00:00:00+00:00`, and two of those sit on one game — so gate check 4
is written to allow it rather than to fail on it.

## Pairing with the #676 status events

An endpoint with a known day whose `(player_game, kind, day)` triple matches
exactly one #676 status event adopts that event's `correlation_id`. An
ambiguous group, an absent one, and an endpoint with no day each mint a fresh
id. Every other event this run appends mints a fresh one.

`pair_endpoints` is called over this run's own endpoint set, not read off
#686's report. The verdict is a property of the group, so an endpoint the
report did not see — one belonging to a removed row — can move a group from
unambiguous to ambiguous. On the deployed database the two sets are identical,
because it holds no removed row, and the published verdicts stand.

This is the whole of what #685 asked for, and the reason it is here rather than
beside: `correlation_id` is a column on an immutable row, so a pairing is
stated by choosing the id at the moment the lifecycle event is appended, and
this is that append.

A completion that pairs with a `retired` or `abandoned` status event still
adopts that id. The status word decides nothing about what is appended — the
row's `ended` already did — so it decides only which act the id names, and the
act that ended the run is the act that recorded both facts. The deployed
database holds none of these; `pairs_retired_or_abandoned` is 0.

## Idempotency and provenance

Keys, all carrying the issue number: `backfill:684:playthrough:created:{row}`,
and `:note:`, `:started:`, `:completed:`, `:removed:` beside it, plus
`backfill:684:playthrough:default:{player_game}`. Keys are library-scoped
records, so a shared catalog row converted by two libraries is two keys, not a
collision.

**No `command_input` names an aggregate id.** Each is the source row's key and
the fact — `{"fact": "started", "play_event_id": str(row.pk), "day": …}` — so a
second pass over the same row hashes the same fingerprint and replays. An
identity minted fresh in each pass would hash differently, and
`idempotent_append` answers a fingerprint that moved with
`IdempotencyKeyMismatch`; this module calls it bare, as #676 does, so that
conflict would abort the migration in place of the drift report gate check 5
exists to give.

That also removes any need to recover a run's identity from a previous pass.
Both callers are atomic — the migration's `RunPython` and
`load_sample_data`'s block — and `idempotent_append` writes its record in the
transaction that writes its events, so a pass that does not commit leaves
neither. There is no state in which a committed creation event is missing its
endpoints.

Each creation event still carries `source_metadata` of
`{"origin": "backfill", "issue": 684, "play_event_id": str(row.pk)}`, exactly
as #676 stamps `status_change_id`, with the pk spelled as a string because
`canonical_json` refuses a `UUID`. That is provenance for the rehearsal and for
#771, not a lookup: nothing in this run reads it back.

## The default run

Every live `PlayerGame` on a live catalog row that holds no live run once its
rows are converted receives one `library.playthrough.created`, kind ordinary,
dated with the tracked game's own `tracked_at`.

That is 663 games in the deployed database, and it is the half of this issue
that #679 could not deliver: `TrackGame` states the default for a game tracked
through it, the games #676 tracked have none, and `TrackGame` answers
`Unchanged` over a tracked game rather than repairing it.

The rule reads "no live run", not "no legacy row", because a game whose only
row was removed keeps a removed run and still needs the live one every tracked
game holds. A tracked game whose catalog row is removed is skipped and counted
as `tracked_on_removed_game`, the preflight's own meaning for that field. A
removed `PlayerGame` is outside the walk entirely and is counted nowhere.

## Removed legacy rows

A removed row is converted like any other and then marked, by appending
`library.playthrough.removed` dated with the row's own `removed_at`.

Nothing the library removed is destroyed, and #771 destroys the legacy table.
A skipped removed row would therefore be a record that survives this run and
not the next one. The deployed database cannot hold one — `games_playevent`
gained `removed_at` in 0036 and production stands at 0022, so no row can be
marked before this runs — but the sample fixture, a developer database and
every run after #771 can.

Nothing about that append goes through `RemovePlaythrough`, so its refusal over
the last live ordinary run of a tracked game does not fire, and the default
rule above is what keeps the invariant true anyway.

This overrides the wave review and #686's spec, which both say "every **live**
`PlayEvent` becomes a Playthrough". It is a deliberate reversal, and its cost
is the reporting mismatch the next section states.

## Scope

The preflight's walk, with one difference. Per library: keyset-page
`PlayerGame` where `removed_at` is null, skip a game the catalog marks removed,
and take that game's legacy rows — **live and removed alike**, where the
preflight takes live rows only. A row on an untracked game and a row whose game
has no projection are never reached by either.

So the two reports do not diff field for field, and the spec does not claim
they do. `live_rows` is the count of rows both sides see. The preflight's
`rows_removed` is **not** the rest: `_excluded_counts` computes it over every
row on a live catalog game, with no tracking filter, so it also counts removed
rows this walk never reaches. The run therefore emits its own count of the
removed rows it converted, beside the preflight-shaped fields, rather than
claiming a partner field it has none for. Three more of its counts — default
runs, notes, dayless endpoints — have no preflight field either, and are
labelled as its own.

A shared catalog game that two libraries track converts once per library, into
one run each. `audit_library_ownership` reads
`AUDITED_PROJECTION_REFERENCES`, and #1017 registered `Playthrough`, so a run
naming another library's row is reported rather than silent.

## The gate

Every check runs before the transaction commits. Any mismatch is emitted with
its identifier and the whole run is rolled back, exactly as
`0033_playergame_baseline_backfill` does with `Mismatch` and
`_fail_if_mismatched`.

Checks 1 and 2 read **the rows the walk reached**, never `PlayEvent.objects`
whole. A row on an untracked game, on a removed catalog game, or on a game with
no projection row is outside this run by design, and a gate that demanded a run
for it would abort a migration that did nothing wrong. The deployed database
holds none of the four, so this is correctness for every other database.

1. Every live legacy row in scope has exactly one live run whose `started` and
   `completed` equal the row's two days, whose `start_recorded_at` and
   `completion_recorded_at` are both set, and whose `note` equals the row's.
2. Every removed legacy row in scope has exactly one run whose `removed_at` is
   set.
3. Every live tracked game on a live catalog row holds at least one live
   ordinary run.
4. Each game's runs, in display order, carry the same sequence of
   `(started, completed, created_at)` as its rows in `legacy_order_key` order.
   Rows that are peers on all three may come back in either order, because
   nothing the projection carries distinguishes them.
5. A second full pass appends zero events.
6. `check_ordering` reports no violation for `games_playthrough`.

Check 5 is #676's `count_drift` check, unchanged. Checks 1 and 2 are the
row-to-row reconciliation, which compares what was written against the source
rather than against a second count of the source. Check 3 is the wave's
contract that every tracked game holds a run, stated after both #679 and #684.
Check 4 is the ordering rule #679 states, verified over real data rather than
assumed from the append order, and stated over what the projection carries
rather than over a pk it does not. Check 6 is the identity audit, run here
rather than after the deployment, because a backfill stamping a past instant is
the case `identity_at` exists for and the case that breaks it silently.

Beside the mismatches the run emits its counts. What the deployed database
should produce: 872 runs, being 209 converted and 663 default; 203 runs with
both days; 6 with neither; 0 removed rows converted; 45 notes; 296 endpoints
adopting a recorded `correlation_id`, with 110 minting a fresh one and 12 more
dayless endpoints beside them. Of these, `live_rows`, the shape counts and the
pairing counts diff against #686's report by eye; the rest are this run's own.

## Where it runs

Migration `0045_playthrough_conversion_backfill`, one `RunPython` over
`0044_playthrough_endpoint_columns` — the migration that adds the four columns
the endpoint events amend — reversible as `noop` and `elidable=True`. It calls
the live models and the live event machinery for the reason 0033 records:
historical models cannot run a projector or validate a payload, and a backfill
that wrote events and projection rows by hand would be a second event writer.

Production stands behind #676, so the deployment applies 0033 and 0045 in one
run and the rehearsal must be in that order, through `make verify-dump`.

Cost is worth measuring in that rehearsal rather than assuming. Gate check 5
walks the whole library a second time, so the deployed database appends roughly
1290 events and pays roughly 2600 `idempotent_append` calls, each under the
stream lock, inside one migration transaction. 0033's pass is the same order of
magnitude and is the only evidence that this size commits.

`load_sample_data` calls `convert_library()` directly after
`backfill_library()`, inside the same block. `backfill_library()` appends
`library.playergame.created` rather than dispatching `TrackGame`, so a loaded
fixture currently leaves every tracked game without the run every tracked game
holds. The fixture carries 209 legacy rows over 195 of its 858 games — 203 with
both dates, 6 with neither, no notes, none removed — so the added work there is
the same 1290 events, roughly doubling what that block already costs. Seven
test modules load it.

## Rollback

The run appends events and writes no legacy row, so its reversal is the
projection rebuild [#667](2026-08-25-issue-667-shadow-rebuild-design.md)
already provides. The migration itself reverses as `noop`: an event is
appended, not undone, and the projection is rebuilt from what the log holds.

## Tests

`tests/test_playthrough_conversion.py`:

- each of the five row shapes states the endpoints the rule above gives it;
- a row with a note states it as the run's note, and a blank note appends
  nothing;
- a removed row becomes a removed run, and its game still receives a live
  default;
- a tracked game with no rows receives exactly one default, dated `tracked_at`;
- a second pass appends nothing and leaves every row as it stands;
- every converted run's identity sorts by its `created_at`, and
  `check_ordering` passes over `games_playthrough` after a pass;
- three rows on one game, one dated and two not, are numbered 1, 2 and 3, the
  dated one first — the Dark Souls 2 shape;
- two rows sharing a day pair and a `created_at` to the microsecond are
  numbered 1 and 2 in either order, and the gate passes — the sample fixture's
  shape;
- an unambiguous endpoint adopts the #676 `correlation_id`; an ambiguous one,
  an absent one and a dayless one each mint a fresh id;
- a removed row's endpoint joins the pairing set, so a group the preflight
  called unambiguous can be called ambiguous here;
- a library holding a row on an untracked game, on a removed catalog game and
  on a game with no projection converts none of the three and the gate passes;
- each of the six gate checks reports its mismatch when the state it reads is
  tampered with;
- a projection rebuild reproduces every converted row identically, including
  its display number;
- a shared catalog game tracked by two libraries yields one run in each, and
  neither library's run names the other's `PlayerGame`.

## Verification

`make check` in full, including `e2e/`, and `make audit-uuid-identity`. Then
the rehearsal against a restored copy of the deployed database: `make
fetch-dump`, `make verify-dump KEEP=1`, migrate through 0045, diff the emitted
JSON line against the counts published on the issue, and run the identity audit
against the restored copy.

## Out of scope

Every write path and every read path. `PlayEvent` is still written by the add
and edit views until #687, and still read by every filter, statistic, API route
and screen until #1012 through #1015. The legacy storage comes out in #771,
after the parity gate #688. No screen renders a Playthrough until #1012, so
this run's output is visible only through the projection and the log.
