# Report the legacy lifecycle rows before converting them

Issue [#686](https://github.com/KucharczykL/timetracker/issues/686). Parent
epic [#601](https://github.com/KucharczykL/timetracker/issues/601), placed
second in the
[Playthrough delivery wave](https://github.com/KucharczykL/timetracker/blob/main/docs/superpowers/specs/2026-09-04-playthrough-wave-design.md).

The code is a new `games/preflight/` package, one management command, and one
Makefile target. It reads. It appends no event, writes no row, and changes no
schema.

#684 converts every live `PlayEvent` into a Playthrough. This runs first and
says what that conversion will meet: how many rows convert without a question,
which ones carry a question, which display numbers are decided by nothing a
player stated, and which #676 status events the conversion is expected to pair
with. #699 sets the precedent for the Sessions wave — a preflight runs before
the migration it describes, and its counts are what the migration is measured
against.

## It does not depend on #679

The issue body lists #679 as a dependency. That line is wrong, and this
document is where it is corrected.

The preflight reads `PlayEvent.started` and `PlayEvent.ended`, which are plain
`DateField`s, and `PlayerGame`, which #671 and #676 already delivered. It
applies the wave's numbering rule to those legacy columns. #679 applies the
same rule to a Playthrough's `TemporalValueField` bounds. Neither imports the
other; #684 is the one place the two meet, and #684 depends on both.

So this issue is buildable against `main` as it stands, which is what the wave
document meant by "#679 and #686 have no unmet dependency and may start
together". The cost of the two implementations is named under
[The handoff to #684](#the-handoff-to-684), which is where it is paid.

## The aggregate is the anchor, not the catalog row

#684 converts a `PlayEvent` into a Playthrough of a `PlayerGame`. So the walk
is over live `PlayerGame` rows, not over `Game.objects.filter(library=…)`.

The difference is not cosmetic. `TrackGame._visible_game`
(`games/commands/playergame.py:89-95`) resolves
`Q(library=context.library) | Q(library__isnull=True)`, so a library may track
a shared catalog game whose `library` is NULL. A walk anchored on the catalog
would miss that game, miss its rows, and still count its `PlayerGame` under
"tracked" — the arithmetic would not close. Anchoring on the projection makes
the report's universe the same universe #684 writes into.

`PlayerGame` is a `ProjectionModel` and declares no manager of its own
(`games/models.py:1508-1526`), so there is no `for_library()` and no `.alive()`
to call. Liveness is spelled out: `filter(library=…, removed_at__isnull=True)`.

## Two axes, not one list

A row's convertibility and its position in the display order are independent
properties. A row that converts without a single question can still land on a
display number that no recorded date chose. Reporting them as one partition
would put one row in two buckets and make the totals lie.

So the report carries two classifications over the same set of rows, plus a
population section that says which rows the conversion sees at all, a pairing
section about the #676 events, and a short global section for the catalog rows
no library owns.

### Convertibility

One verdict per live row. The five are mutually exclusive and sum to the live
row count.

| Verdict | The row | What #684 states |
|---|---|---|
| `clean_both` | `started` and `ended`, with `started <= ended` | a start and a completion |
| `clean_start_only` | `started`, no `ended` | a start |
| `clean_end_only` | `ended`, no `started` | a completion, and a start whose date is unknown |
| `no_known_endpoint` | both null | a Playthrough that states neither fact |
| `reversed_endpoints` | `ended < started` | undecided — see below |

A row with `started == ended` is `clean_both`. The legacy `days_to_finish`
already treats that as one day rather than zero
(`games/models.py:1347-1367`), and #681 refuses only a completion *earlier*
than its start.

`clean_end_only` is clean because the conversion knows what to write. The wave
gives it "Played before": a start with an unknown temporal value. It is counted
apart from `clean_both` because it is the shape that produces a Playthrough
whose start nobody recorded, and the count of those is worth knowing before the
run rather than after it.

`reversed_endpoints` is the one verdict that names an unresolved decision.
#681 refuses a completion earlier than its start, so #684 cannot state the pair
as recorded. Whether it swaps the endpoints, drops the completion, or appends
without the refusal a live command would apply, is #684's call. The preflight's
job is to say how many rows force that call, and to name them. A production
count of zero would let #684 decide nothing at all, which is a legitimate
outcome of running this first.

### Ordering

The wave's rule numbers a PlayerGame's live ordinary Playthroughs by known
start bound NULLS LAST, then known completion bound NULLS LAST, then creation
time. Over legacy columns that reads: order by `started` NULLS LAST, then
`ended` NULLS LAST, then the row's primary key.

**The tiebreak is the primary key, not `created_at`.** `created_at` is
`auto_now_add` (`games/models.py:1370`), so `loaddata` rewrites it at load time
and a fixture-loaded database has a `created_at` order unrelated to the order
the rows were originally written in. The primary key is a `UUIDv7Field`
preserved verbatim by the dump, so it is the only stable statement of insertion
order. `games/backfill/playergame.py:296-300` keys on `id` for the same reason
and says so.

The tiebreak always resolves — every `PlayEvent` has a primary key. So the
order is never *undecidable*; it is sometimes *unstated*, decided by when a row
was inserted rather than by anything a player recorded. The issue body says
"undecidable", and this is the honest reading of it.

Three per-game counts, over tracked games holding at least one live row:

- `ordered_by_date` — every row's `(started, ended)` pair is distinct, so the
  dates alone fix the order;
- `tie_broken` — two or more rows share one `(started, ended)` pair, including
  the `(NULL, NULL)` pair, so the primary-key order decides their display
  numbers;
- `date_order_differs_from_insertion` — the numbering rule puts the rows in a
  different order than their primary keys do. A player reading today's list top
  to bottom will see the numbers renumber under them, and this count says for
  how many games.

The last two overlap and are reported as two independent counts, not as parts
of a partition. The report says so on its own face.

### Population

The conversion's universe is the live `PlayEvent` rows of the games behind a
library's live `PlayerGame` rows. Everything the conversion will not see is
counted anyway, so the arithmetic closes and a surprising exclusion is visible
rather than silently absent.

Per library:

- `tracked` — live `PlayerGame` rows. Each one gets at least a default
  Playthrough.
- `tracked_without_rows` — of those, the ones whose game holds no live
  `PlayEvent`. Each receives the ordinary default and nothing else.
- `live_rows` — the convertible universe.
- `rows_removed` — the row's own `removed_at` is set.
- `rows_on_removed_game` — the game's `removed_at` is set.
- `rows_untracked` — a live row on a live library-owned game whose `PlayerGame`
  row exists with `removed_at` set.
- `rows_without_projection` — a live row on a live library-owned game with no
  `PlayerGame` row at all.

A row matching more than one exclusion is counted once, in the order listed.
The order is stated in the code and pinned by a test.

**The last two are different findings and must not be one count.**
`rows_without_projection` is the #676 signal: no projection row means the
baseline backfill has not run against this database, and #684 would have no
aggregate to attach a Playthrough to. `rows_untracked` is ordinary.
`remove_game_for_request` (`games/views/playergame_writes.py:60-75`) untracks
and then removes, deliberately without a transaction around the pair, because
dispatch refuses to nest — and its own docstring says a failure between the two
"leaves a game no list shows". That state is a live `Game` with live
`PlayEvent`s and a removed `PlayerGame`. A healthy database that ran 0033 can
hold it, so reporting it as a backfill failure would send whoever reads the
output after the wrong thing.

### The catalog rows no library owns

Three global counts, outside every library heading, following the
`shared_games` count `0033_playergame_baseline_backfill.py:86` already reports
for the same blind spot:

- `shared_games` — catalog games with a null `library`;
- `shared_game_rows` — live `PlayEvent` rows on them;
- `contested_rows` — of those, the rows on a shared game that more than one
  library tracks.

A contested row belongs to no single Playthrough: two libraries track the game,
and each library's walk reaches the same row. #684 decides what that means —
one Playthrough per tracking library, or none. This issue only says how many
there are.

All three are expected to be zero. `GameForm.__init__` always stamps
`instance.library`, so the production catalog holds no shared game, and the
#676 design says the same. They are counted because "expected to be zero" and
"verified zero" are different statements, and this command exists to make the
second one.

### Pairing with the #676 status events

#684 appends an unambiguous lifecycle and status pair under the
`correlation_id` of the status event #676 already recorded. This section says
how many such pairs exist to find.

An endpoint is one known date on one live row: a `started`, or an `ended`. A
candidate for that endpoint is a `library.playergame.status_changed` event
where:

- `source_metadata` carries `origin == "backfill"` and `issue == 676`;
- `aggregate_id` is the `PlayerGame` of the row's game;
- the payload status is `played` for a `started` endpoint, or `completed` for
  an `ended` endpoint;
- the effective time's day equals the endpoint's date.

#### The day comparison happens in Python

The event's `effective_time` is a `TemporalValueField`, and unlike
`Release.release_date` it carries no generated `_lower`/`_upper` companion
columns. Every use of `TemporalLowerBound` in the tree today is inside a
`GeneratedField` definition; there is no `annotate()` or `filter()` precedent
for it, and `LibraryEvent` declares no index on `aggregate_id`, on
`event_type`, or on `source_metadata` (`games/models.py:1765-1791`). Comparing
the bound in SQL would therefore be a per-row function call over an unindexed
scan, and it would be the first of its kind in the repository.

So the SQL filter is the ordinary part — `event_type`, the two JSON keys, the
payload status, and the library — and the day is read in Python from the
deserialized `TemporalValue`. #676 wrote these with `TemporalValue.from_day`,
so lower and upper are one day and either bound answers.

The candidate set is fetched **once per library**, not once per batch of games,
and held as a dictionary keyed by `(aggregate_id, status, day)`. One
unindexed scan of that library's events per run is acceptable; one per batch
against a restored production copy is not. The memory cost is one entry per
dated #676 status event of the library, which is bounded by its
`GameStatusChange` history.

#### One rule for ambiguity, with no iteration order in it

Endpoints and candidates form a bipartite graph: an edge joins an endpoint to
each event that matches it. The verdict is a property of the connected
component, not of a scan:

- a component holding exactly one endpoint and exactly one candidate →
  `unambiguous`;
- any larger component → **every** endpoint in it is `ambiguous`, and no
  candidate is claimed;
- an endpoint with no edge → `absent`;
- a candidate in no component → counted under `unclaimed_events`.

The greedy alternative — walk the endpoints, let each one with a single
candidate claim it — gives different answers depending on the walk order. If
endpoint A matches only event X while endpoint B matches X and Y, walking A
first makes A unambiguous and B ambiguous; walking B first can leave A absent.
A component rule has no such freedom, so the output is a function of the data
alone, which is what the determinism requirement below needs.

The components need no graph traversal to find. An endpoint's four match
conditions reduce to one key — `(aggregate_id, status, day)` — and every
endpoint has exactly one. So two endpoints share a candidate only by sharing
that key, and each component *is* one key's group. The implementation is a
group-by, and the asymmetric case above cannot arise: if A and B both match X
they hold the same key, so B's second candidate Y is A's as well. The rule is
still written as a statement about components, because that is what makes it
order-free; the key grouping is how it is computed.

Two rows of one game that ended on the same day sit in one component with the
single `completed` event, and both are ambiguous. Neither may adopt that
correlation id without the other losing it, and a one-directional count would
have called both of them unambiguous.

`unclaimed_events` is expected to be large: most status transitions have no
`PlayEvent` behind them.

## Two things the operator must know before reading a run

**The pairing section reads zero before migration 0033.** #676's backfill is
`0033_playergame_baseline_backfill`, and the deployed database is believed to
stand at `0022_external_references` — an observation from a dump inspection,
recorded in the wave document and in the #937 design, not a fact this
repository stores. There is no `showmigrations` artifact and no deployment
manifest to check it against. So the rehearsal order is `make verify-dump` to
restore, then `migrate`, then the preflight; and the operator's real check is
the command's own `#676 status events found` line, which reads zero when the
backfill has not run.

**The exit code says nothing.** The command always exits 0, because a preflight
reports and does not gate. `audit_library_ownership` raises `CommandError`
(`games/management/commands/audit_library_ownership.py:143`) because a
cross-library link violates an invariant. An undated `PlayEvent` violates
nothing — it is the input #684 exists to handle, and a command that failed on
real data would be run with its exit code ignored, which is worse than not
failing. What is read is the JSON line.

## Where the code lives

`games/preflight/playthrough.py`, with `games/preflight/__init__.py` opening the
package. It sits beside `games/backfill/playergame.py` and follows its shape:
frozen slotted dataclasses with an `__add__`, so a per-library result sums into
a total without a second structure.

The module holds pure classification and query helpers, and knows nothing about
printing:

- `legacy_order_key(row)` — the wave's ordering rule over legacy columns;
- `classify_row(row)` — one of the five verdicts;
- `pair_endpoints(...)` — the component rule over one library's endpoints and
  candidates;
- `preflight_library(library, *, sample_size)` — the whole per-library result,
  as a dataclass carrying an `as_dict()`.

The management command is a printer over that result and holds no rule of its
own.

### The handoff to #684

#684 imports `legacy_order_key`, `classify_row` and `pair_endpoints`. Sharing
them makes the two issues agree on every *verdict* by construction.

It does not, by itself, discharge the wave's fourth verification requirement,
that every preflight count matches the conversion's own report. Verdicts are
not counts. So this issue also ships the counting structure — `PreflightCounts`
and `LibraryPreflight` — and #684 reports its population through the same
dataclass. **The cross-check is #684's to write**: a test that runs
`preflight_library()` and the conversion against one database and asserts the
population counts equal. This document names that obligation so #684 inherits
it in writing rather than by memory.

One duplication is accepted and must not be silent. `legacy_order_key` states
the wave's numbering rule over `DateField`s; #679 states the same rule over a
Playthrough's bound columns. Two implementations of one rule. Neither issue can
avoid it — the legacy columns and the projection columns are different types on
different models — so #684, the one issue that holds both, owns the test that
pins them equal: convert a set of rows, then assert the Playthroughs' display
order matches `sorted(rows, key=legacy_order_key)`.

## How it reads the database

Live `PlayerGame` rows are paged with `keyset_pages` over
`filter(library=…, removed_at__isnull=True)` keyed on `("id",)` — a
`UUIDv7Field` primary key, answered by the primary-key index. Nothing opens a
server-side cursor.

`keyset_pages` yields rows rather than pages
(`common/keyset.py:30-50`), so the preflight groups its output with
`itertools.batched` and issues one query per batch for that batch's `Game` and
`PlayEvent` rows. A game's rows are never split across batches, because the
batch is a batch of aggregates and a `PlayerGame` is unique per
`(library, game)`. The grouping the ordering axis needs therefore happens in
Python, over one batch.

The candidate events are the exception: one query per library, before the walk,
as described above.

Three further queries per library, each an aggregate rather than a walk: the
excluded-row counts, which are `COUNT(*)`s with the exclusion in the `WHERE`
clause. The three global counts are one more each. A keyset over `PlayEvent`
keyed on `("game_id", "id")` would need an index no migration has created, and
this issue adds no schema.

## Output

Two things on every run: one machine line, then a readable section per library.
That is the order `0033_playergame_baseline_backfill.py:32-37` prints in, and
the reason to keep it is that the machine line is what a deploy log is grepped
for.

The line follows the reconciliation precedent's construction —
`json.dumps(payload, sort_keys=True, separators=(",", ":"))`, and a
`schema_version` — but not its name or its shape. The prefix is
`PLAYTHROUGH_PREFLIGHT_JSON=` rather than `…_RECONCILIATION_JSON=`, because
this command reconciles nothing: it has no expected state to compare against
and emits no mismatch list. The payload is
`{"schema_version": 1, "summary": {…}, "libraries": [{…}]}`, where `summary`
holds the flat totals in the manner of `_summary()` and `libraries` holds one
entry per library. `schema_version` is bumped when a key changes meaning, so a
line captured from the rehearsal stays readable against the deploy's.

The human section, per library:

```text
Playthrough preflight - library 0199... (lukas)
  tracked games: 412
    holding no play events: 380
  live play events: 44
    clean, both endpoints: 28
    clean, start only: 9
    clean, completion only: 4
    no known endpoint: 2
    completion before start: 1
      019a1b2c-...
  not converted:
    removed rows: 3
    on a removed game: 1
    on an untracked game: 2
    with no projection row: 0
  ordering, over 12 tracked games holding rows:
    ordered by date alone: 9
    display number decided by insertion order: 2
      0199aaaa-... 0199bbbb-...
    date order differs from insertion order: 1
      0199cccc-...
  #676 status events found: 118
    endpoints with one unambiguous pair: 12
    endpoints with an ambiguous pair: 2
      019a2222-... 019a3333-...
    endpoints with no candidate: 30
    status events no endpoint claimed: 106
```

Then, once, outside every library:

```text
Shared catalog games: 0
  live play events on them: 0
  rows more than one library tracks: 0
```

### Samples are capped and deterministic

Every list of identifiers is capped at `--sample-size`, default 20. `0` omits
the identifiers and keeps the counts. A capped list always prints beside its
own full count, so the cap can never be mistaken for the number.

The sample is the first N in the report's own order — library primary key, then
`PlayerGame` id, then row id — not a random draw. Two runs against an unchanged
database produce byte-identical output, and a test pins that. A random sample
would make the JSON line undiffable across the rehearsal and the deploy, which
is the one thing it is for. The component rule for pairing carries the same
requirement, which is why it is stated without an iteration order.

## The command

`games/management/commands/preflight_playthroughs.py`, and
`preflight-playthroughs: ensure-postgres` in the Makefile beside
`audit-uuid-identity`, taking `ARGS`. CLAUDE.md's Commands table gains the row,
as it carries one for `make audit-uuid-identity`.

Its scope arguments mirror `audit_library_ownership`: a required mutually
exclusive group of `--user USERNAME`, `--library UUID`, and `--all-libraries`
(`games/management/commands/audit_library_ownership.py:27-36`). Naming a scope
is deliberate rather than defaulted, because the totals of a multi-library run
mean something different from one library's counts. Plus `--sample-size N`.

## Verification

The gate is the full `make check`. New tests in
`tests/test_playthrough_preflight.py`:

- each of the five verdicts, one row each, including `started == ended` landing
  in `clean_both`;
- a game whose rows tie on `(started, ended)`: counted as tie-broken, the game
  named in the sample;
- a game with two `(NULL, NULL)` rows: the same, since that pair ties too;
- a game whose date order differs from its primary-key order: counted, and not
  also counted as tie-broken;
- the tiebreak is the primary key: two rows whose `created_at` order is the
  reverse of their pk order are ordered by pk;
- each exclusion — a removed row, a row on a removed game, a row whose
  `PlayerGame` is removed, a row with no `PlayerGame` — counted in its own
  category, and a row matching two counted once;
- a tracked game with no rows: counted as receiving the ordinary default;
- a shared game tracked by one library: its rows walked under that library; a
  shared game tracked by two: its rows counted as contested;
- an unambiguous pair; two rows ending on one day sharing one `completed`
  event, both ambiguous; one endpoint with two candidate events of the same
  day and status, ambiguous; and both of those asserted from either insertion
  order, so no walk order can change the answer;
- an endpoint with no candidate; a #676 status event no endpoint claimed;
- a status event whose `source_metadata` lacks the #676 origin: not a
  candidate; likewise one whose effective time is unknown;
- two libraries: no count and no sampled identifier crosses;
- the command writes nothing — the `LibraryEvent` count, every removable
  model's row count, and the maximum stream sequence are equal before and
  after;
- `--sample-size 1` truncates a list while its count stays whole, and
  `--sample-size 0` omits the identifiers;
- a run over data holding every anomaly exits 0;
- the JSON line parses, its keys are sorted, and its `summary` equals the sum
  of its `libraries` entries;
- two consecutive runs produce identical stdout.

### The sample fixture proves the walk, not the pairing

A run after `make loadsample` is a smoke test over production-shaped data — 858
games, 209 play events — and it belongs in the suite. It cannot cover the
pairing section, and the test says so rather than asserting a zero that looks
like a working query.

`anonymize_sample.py:35-36` omits `GameStatusChange` from the dump, so the
fixture holds none. `load_sample_data.py:153` runs the #676 backfill, which
without legacy status rows appends only the corrective current-status event —
and that one is written with `TemporalValue.unknown()`
(`games/backfill/playergame.py:261`), so it has no day and can never be a
candidate. Every endpoint in a fixture-loaded database is therefore `absent`.

The fixture test asserts exactly that: the walk completes, the population
counts are nonzero and internally consistent, and the pairing section is
`unambiguous: 0` with `#676 status events found: 0`. Pairing coverage comes
from the unit tests above, which build `GameStatusChange` rows and run
`backfill_library` themselves.

### Before #684

This command runs against a restored production copy through
`make verify-dump`, after `migrate`, and its output is recorded on #684. That
output is the evidence #684's reconciliation is measured against, and producing
it is the whole reason this issue precedes that one.

## Reversibility

Nothing to reverse. The command writes no row and appends no event, the package
is new, and the Makefile target is additive. A revert is the commits.

## Out of scope

- The Playthrough model, its events and its projector, which are #679.
- The conversion itself, which is #684, and the cross-check test named under
  [The handoff to #684](#the-handoff-to-684), which #684 owns.
- Any schema change, including an index that would make a `PlayEvent` keyset or
  the candidate scan cheaper.
- Any reasoning about Sessions. #699 preflights those, and #700 assigns them.
- Any change to the `PlayEvent` write path, screens, filters or API, which are
  #687 and #1012 through #1015.
