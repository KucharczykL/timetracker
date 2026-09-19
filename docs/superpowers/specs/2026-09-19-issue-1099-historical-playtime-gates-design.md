# Pass the historical-playtime replay, statistics and budget gates

Issue: [#1099](https://github.com/KucharczykL/timetracker/issues/1099). Last
member of the
[Historical Playtime delivery wave](2026-09-17-historical-playtime-wave-design.md);
[#704](2026-09-15-issue-704-session-gates-design.md) is the model.

## Purpose

The wave is proven on a production copy and measured. Four gates: replay,
statistics, budget, pages. The replay gate already holds: the stream in
`tests/test_projection_replay_gate.py` records a record in every leg, one
naming two runs, one restated, one removed and one restored, a reclassified
session and one reclassified and undone. This design adds the other three
instruments and runs all four on a dump fetched on the day of the run.

## Statistics

`make verify-reclassification-parity ARGS="--user NAME --confirm NAME"` is
one command over one library. It reads every statistics scope, converts the
review population, reads every scope again, and judges each figure by the
rule its source group states. Without `--confirm` it reads once and prints
the figures and the population's count; with it, it converts. It writes, so
it runs on a scratch restore only, and it names the user twice, as
`purge-library` does. It opens no transaction of its own: every conversion
dispatches through `run_in_transaction`, which refuses to nest.

The scopes are all-time and every year `played_years` answers, read before
the conversion. `games/stats_parity.py` holds the pure half: the rules, over
two `StatsData` per scope and a `ScopeIdentities` beside each -- the longest
session's row, the first and last play's rows, the highest-count and
highest-average games, the distinct days, the games and purchases the two
count keys count. `PlayDay` gains the session it was read from, so first and
last play name a row; every other identity the readers already answer. The
command holds the reads and the conversion: `compute_stats` and the
`session_figures` readers a scope, then `reviewable_sessions(library)`, each
row through `reclassify_session`, the write the confirm page calls, under
one correlation id with an idempotency key of a fresh token and the row's
key, so a second run against one database converts nothing and says so
rather than replaying. `statement_from_session` states day precision and
provenance Manually entered. The converted rows' ids, days, games and the
games' purchases, narrowed to each scope, are the `Converted` fact every rule
reads.

One rule per member of `STATS_SOURCE_GROUPS`, so a key added to the mapping
without a rule fails the test that walks it:

| group or key | rule |
|---|---|
| `BOTH` | every `PlaytimeBreakdown` keeps its `total`; `tracked` falls and `historical` rises by the converted seconds its row's key holds in scope; row order kept |
| `PURCHASES` | equal, a queryset compared as its ordered keys |
| `NOT_A_FIGURE` | equal |
| `total_sessions` | down by the converted rows in scope, exactly |
| `unique_days` | down by the days only converted rows held in scope, exactly |
| `unique_days_percent` | equal to the page's formula over the after values of `unique_days`, `first_play_date` and `last_play_date` |
| `longest_session_*`, `first_play_*`, `last_play_*` | unchanged, or the row before was converted |
| `highest_session_count*` | unchanged, or the game before held a converted row in scope |
| `highest_session_average*` | unchanged, or the game before or the game after held a converted row in scope, because taking a short row away raises an average |
| `total_games` | the games that left are exactly those with a converted row in scope and no session left in it |
| `total_year_games` | the purchases that left are exactly those none of whose games keeps a session in scope; a purchase count, not a game count, in every scope |

Longest session, first and last play sit under a total order that ends on the
row's key, and a session count only falls, so no tie flips those without a
converted row.

The last two rules name a change the wave did not: both keys count through a
session in scope, so a game whose sole session becomes a record leaves "games
played" and takes its purchase with it. The gate attributes the change and
passes; whether a contained record should count a game as played is a
question for the read, filed as its own issue.

The verdict prints one line per changed figure with its attribution and
exits non-zero on a change no rule attributes. `CommandFailed` from any row's
conversion is its sentence on stdout and a non-zero exit before the second
read: a population partly converted has no parity to judge.

## Budget

`make bench` gains a records workload between the session command and the
reads: `IMPORT_SHAPE_RECORDS = 600` dispatches of `RecordHistoricalPlaytime`,
one seeded run each, ten hours at year precision, Estimated, no device, with
the same warmup the other commands take. Six hundred dispatches in one run is
an import's shape, which is why the count is a constant the command passes
and not `--iterations`; `run_benchmark` takes it as a parameter, so the tests
pass a small one. A run takes many records, so the scenario walks the seeded
runs and starts over when they run out, and the count holds under `--seed 0`
as well. The estimate the command prints before it seeds counts the 600
dispatches. The scenario ends with an `ANALYZE` of the two record tables,
through the seed's helper given the tables to name, for the same reason the
seed analyzes what it wrote: the reads that follow plan against statistics
that know the rows exist.

`record command p95` is judged at the charter's 100 ms beside the other two,
placed after the session budget and before the reads. The six reads are
unchanged and now run with 600 records present on the scratch library; under
`--library` they run with the records the parity command converted.
`--library` dispatches nothing, as before, so its report carries
`record_command` as `None` and its seven budgets stay. `REPORT_SCHEMA` moves
from 3 to 4.

Both recordings are pasted into `docs/event-benchmarks.md` under one
heading, the scratch run and the production-shape run, the way every
recording before them was.

## Pages

`make render-pages` runs twice against one restored database: at
`855c276f`, the last merge before the wave's code, from a second worktree
with its own `uv sync`, and at the head that carries this issue, the
database migrated forward between them, each run given the restore's
`DATABASE_URL`. The base commit holds migrations through 0008 and the head
adds 0009 to 0011; the dump must stand at 0008 or earlier, which
`django_migrations` says after the restore. A dump the deployment took after
running the wave holds the new tables already and the base render would run
over them; that is a different rehearsal and is not this one.

The directories diff on content. Every differing file is attributed by name:
a wave PR, or one of the two merges inside the wave that touched rendering
(#1115, #1120). A page nothing explains gets a third render at the
intermediate merge that separates the candidates; a page still unexplained
is a defect.

## Rehearsal

One scratch database, in this order: `make fetch-dump`, `make restore-dump`,
render at the base commit, migrate, render at the head, diff and attribute,
`verify-reclassification-parity`, `make bench ARGS="--library <id> --gate"`,
`make verify-replay-parity` over six tables. The parity command prints the
population it converts; the issue's 93 was counted before the review kept the
bucket out, so the count is read, not assumed. The numbers land where #704's
did: a Delivered block under the wave's delivery order, the benchmarks
document, and this specification's Delivered section. The wave's "What was
applied" gains the `total_games` finding.

## Out

The parity command and the page diff stay out of `make check`. No read of
the Historical list joins the six. The review population converts in one
pass with no chunking. Nothing here changes a figure; the follow-up issue
owns `games_in_scope`.
