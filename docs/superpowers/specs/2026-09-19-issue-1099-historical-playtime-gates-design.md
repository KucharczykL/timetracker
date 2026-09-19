# Pass the historical-playtime replay, statistics and budget gates

Issue: [#1099](https://github.com/KucharczykL/timetracker/issues/1099). Last
of the [Historical Playtime wave](2026-09-17-historical-playtime-wave-design.md);
[#704](2026-09-15-issue-704-session-gates-design.md) is the model.

## Purpose

Four gates prove the wave on a production copy: replay, statistics, budget,
pages. `tests/test_projection_replay_gate.py` is the first.

## Statistics

`make verify-reclassification-parity ARGS="--user NAME --confirm NAME"` reads
every statistics scope, converts the review population and reads again.
Without `--confirm` it reads once and prints. It writes, so it runs on a
scratch restore only and names the user twice, as `purge-library` does. Each
conversion dispatches through `reclassify_session`, the confirm page's write,
under one correlation id and an idempotency key of a fresh token and the
row's key. It ends with an `ANALYZE` of the two record tables, so a
benchmark that follows plans on statistics that know the rows.

`games/stats_parity.py` holds one rule per `StatsData` key; a test holds the
mapping equal to `STATS_SOURCES`. A rule reads both readings, the
`ScopeIdentities` behind the session superlatives and the `Converted` rows
in scope, and answers an attribution or `None`.

| group or key | rule |
|---|---|
| `BOTH`, playtime keys | each `PlaytimeBreakdown` keeps its total; `tracked` falls and `historical` rises by the converted hours under its key; order kept |
| `BOTH`, counts and days | equal |
| `PURCHASES` | equal, a queryset as its ordered keys |
| `NOT_A_FIGURE` | equal, except the `*_from_record` flags, which flip only on the play the figure named |
| `total_sessions` | down by the rows in scope, exactly |
| `longest_session_*` | equal, or the row before was converted |
| `highest_session_count*` | equal, or the game before held a converted row |
| `highest_session_average*` | equal, or the game before or after held one |

An unattributed change exits non-zero. A refused conversion stops the run
before the second read.

## Budget

`make bench` dispatches `IMPORT_SHAPE_RECORDS` records between the session
command and the reads: 600, one seeded run each, ten hours at year precision,
cycling the runs. `record command p95` is judged at 100 ms. `--library`
carries the scenario as `None`. `REPORT_SCHEMA` is 4.

## Pages

`make render-pages` runs at the last merge before the wave and at the head
on one restored database, migrated between the runs. Every differing page is
attributed to a wave PR by name.

## Delivered

The 2026-09-19 dump: one library, 2,819 sessions on 861 tracked games, 93
rows in the review population.

- Replay: 7,277 events through six tables, no row differing.
- Statistics: 21 scopes, 199 figures changed, 0 unattributed.
- Budget: `record command p95` 5.0 ms. Six reads inside 20 ms with the
  records present; `game_playtime_sort` 15.9 ms against 8.9 ms without,
  which #1131 owns. Before autovacuum analyzed the record tables it measured
  49.1 ms; hence the command's `ANALYZE`.
- Pages: 1,702 of 1,704 differ, every one attributed; no defect.

Recordings: `docs/event-benchmarks.md` and the wave document.

## Out

The parity command and the page diff stay out of `make check`.
