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
rule its source group states. It writes, so it runs on a scratch restore
only, and it names the user twice, as `purge-library` does.

The scopes are all-time and every year `played_years` answers, read before
the conversion; a year no session or record touches has no figure to compare.
`games/reads/stats_parity.py` holds the pure half: a `ScopeSnapshot` of
`compute_stats` beside the identities the rules need -- the longest session's
row, the first and last play's rows, the highest-count and highest-average
games, the set of distinct days -- and the rules. The command holds the
conversion: `reviewable_sessions(library)`, each row through
`reclassify_session`, the write the confirm page calls, under one correlation
id with one idempotency key a row, day precision, provenance Manually entered.
The converted rows' ids, days and games, narrowed to each scope, are the
`Converted` fact every rule reads.

One rule per member of `STATS_SOURCE_GROUPS`, so a key added to the mapping
without a rule fails the test that walks it:

| group | rule |
|---|---|
| `BOTH`, `PURCHASES` | equal in every scope |
| `total_sessions` | down by the converted rows in scope, exactly |
| `unique_days` | down by the days only converted rows held in scope, exactly |
| `unique_days_percent` | derived; equal to the value recomputed from the attributed inputs |
| `longest_session_*`, `first_play_*`, `last_play_*` | unchanged, or the row before was converted |
| `highest_session_count*`, `highest_session_average*` | unchanged, or the game before held a converted row in scope |
| `total_games`, `total_year_games` | down by the games whose every session in scope was converted, exactly |

The last rule names a change the wave did not: `games_in_scope` counts a game
with a session in scope, so a game whose sole session becomes a record leaves
"games played". The gate attributes it and passes; whether a contained record
should count a game as played is a question for the read, filed as its own
issue.

The verdict prints one line per changed figure with its attribution and
exits non-zero on a change no rule attributes. A refusal from any row's
conversion is a sentence on stdout and a non-zero exit before the second
read: a population partly converted has no parity to judge.

## Budget

`make bench` gains a records workload between the session command and the
reads: `IMPORT_SHAPE_RECORDS = 600` dispatches of `RecordHistoricalPlaytime`,
one seeded run each, ten hours at year precision, Estimated, no device, with
the same warmup the other commands take. Six hundred dispatches in one run is
an import's shape, which is why the count is a constant and not
`--iterations`. The scenario ends with an `ANALYZE` of the two record tables,
for the same reason the seed analyzes what it wrote: the reads that follow
plan against statistics that know the rows exist.

`record command p95` is judged at the charter's 100 ms beside the other two.
The six reads are unchanged and now run with 600 records present on the
scratch library; under `--library` they run with the records the parity
command converted. `--library` dispatches nothing, as before. The report
carries `record_command`, `None` under `--library`, and `REPORT_SCHEMA`
moves.

Both recordings are pasted into `docs/event-benchmarks.md` under one
heading, the scratch run and the production-shape run, the way every
recording before them was.

## Pages

`make render-pages` runs twice against one restored database: at
`855c276f`, the last merge before the wave's code, and at the head that
carries this issue, the database migrated forward between them. The
directories diff on content. Every differing file is attributed by name: a
wave PR, or one of the merges that landed inside the wave (#1115, #1118,
#1120). A page nothing explains gets a third render at the intermediate merge
that separates the candidates; a page still unexplained is a defect.

## Rehearsal

One scratch database, in this order: `make fetch-dump`, `make restore-dump`,
render at the base commit, migrate, render at the head, diff and attribute,
`verify-reclassification-parity`, `make bench ARGS="--library <id> --gate"`,
`make verify-replay-parity` over six tables. The numbers land where #704's
did: a Delivered block under the wave's delivery order, the benchmarks
document, and this specification's Delivered section. The wave's "What was
applied" gains the `total_games` finding.

## Out

The parity command and the page diff stay out of `make check`. No read of
the Historical list joins the six. The 93 rows convert in one pass with no
chunking. Nothing here changes a figure; the follow-up issue owns
`games_in_scope`.
