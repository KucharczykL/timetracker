# Pass the historical-playtime replay, statistics and budget gates

Issue: [#1099](https://github.com/KucharczykL/timetracker/issues/1099). Last
member of the
[Historical Playtime wave](2026-09-17-historical-playtime-wave-design.md);
[#704](2026-09-15-issue-704-session-gates-design.md) is the model.

## Purpose

Four gates prove the wave on a production copy: replay, statistics, budget,
pages. The replay gate is `tests/test_projection_replay_gate.py`, which
records a record in every leg. This design adds the other three instruments.

## Statistics

`make verify-reclassification-parity ARGS="--user NAME --confirm NAME"` reads
every statistics scope, converts the review population and reads every scope
again. Without `--confirm` it reads once and prints. It writes, so it runs on
a scratch restore only, and it names the user twice, as `purge-library`
does. Each conversion dispatches through `reclassify_session`, the write the
confirm page calls, under one correlation id and an idempotency key of a
fresh token and the row's key. It ends with an `ANALYZE` of the two record
tables, so a benchmark that follows plans on statistics that know the rows.

`games/stats_parity.py` holds the rules, one per `StatsData` key, and a test
holds the mapping equal to `STATS_SOURCES`. A rule reads both values, the
whole readings, the `ScopeIdentities` behind the session superlatives, and
the `Converted` rows narrowed to the scope. It answers an attribution or
`None`. The judge reports every changed key and every refusal.

| group or key | rule |
|---|---|
| `BOTH`, playtime keys | each `PlaytimeBreakdown` keeps its total; `tracked` falls and `historical` rises by the converted rows' hours under its key; row order kept |
| `BOTH`, counts and days | equal |
| `PURCHASES` | equal, a queryset as its ordered keys |
| `NOT_A_FIGURE` | equal, except the two `*_from_record` flags, which flip only where a converted row is the play the figure named |
| `total_sessions` | down by the rows in scope, exactly |
| `longest_session_*` | equal, or the row before was converted |
| `highest_session_count*` | equal, or the game before held a converted row |
| `highest_session_average*` | equal, or the game before or after held one |

A change no rule attributes exits non-zero. A refused conversion stops the
run before the second read.

## Budget

`make bench` dispatches `IMPORT_SHAPE_RECORDS` records after the session
command and before the reads: 600, one seeded run each, ten hours at year
precision, cycling the runs when they run out. `record command p95` is judged
at 100 ms. `--library` dispatches nothing and carries the scenario as `None`.
`REPORT_SCHEMA` is 4.

## Pages

`make render-pages` runs at the last merge before the wave and at the head,
against one restored database migrated between the runs. Every differing
page is attributed to a wave PR by name.

## Delivered

On the 2026-09-19 dump, one library of 2,819 sessions on 861 tracked games,
93 rows in the review population:

- Replay: 7,277 events through six tables, no row differing.
- Statistics: 21 scopes, 199 figures changed, 0 unattributed.
- Budget: `record command p95` 5.0 ms. Six reads inside 20 ms with the
  records present; `game_playtime_sort` 15.9 ms against 8.9 ms without them,
  which #1131 owns. A run before autovacuum had analyzed the record tables
  measured 49.1 ms, which is why the command analyzes them.
- Pages: 1,702 of 1,704 differ, every one attributed; no defect.

The recordings are in `docs/event-benchmarks.md` and the wave document.

## Out

The parity command and the page diff stay out of `make check`. The review
population converts in one pass.
