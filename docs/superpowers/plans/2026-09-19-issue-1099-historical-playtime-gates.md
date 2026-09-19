# Historical-playtime gates implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three instruments -- a statistics-parity command, a records
workload in `make bench`, a render_pages rehearsal -- and one run of all four
gates on a fresh production dump, recorded.

**Architecture:** A pure rules module over two `StatsData` per scope plus the
identities the readers answer; one management command that reads, converts
through the confirm page's write, reads again and judges; one more scenario in
the benchmark between the session command and the reads. No model, no
migration, no event.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pytest + pytest-django.

**Spec:** [docs/superpowers/specs/2026-09-19-issue-1099-historical-playtime-gates-design.md](../specs/2026-09-19-issue-1099-historical-playtime-gates-design.md)

## Global constraints

- Run everything through `make`; never `uv run pytest` directly, never
  `direnv exec .`. Focused runs: `make test ARGS="tests/test_stats_parity.py -x"`.
- The gate before the PR is one full `make check`, e2e included, on the
  user's word. `make check-fast` while iterating.
- Python 3.14 only; `except A, B:` bare form is PEP 758, not a bug.
- No dispatch inside `transaction.atomic` -- `run_in_transaction` refuses to
  nest. Tests that dispatch need `@pytest.mark.django_db(transaction=True)`.
- No `QuerySet.iterator()`; page with `keyset_pages` from `common/keyset.py`.
- Unabbreviated identifiers; compound types named (`NamedTuple`, `type`
  alias); primitive roles aliased (`type ScopeKey = int | None  # a year, or None for all-time

class ScopeIdentities(NamedTuple):
    longest_session_id: UUID | None
    highest_count_game_id: UUID | None
    highest_average_game_id: UUID | None

class ConvertedRow(NamedTuple):
    session_id: UUID; day: date; game_id: UUID; platform_id: UUID | None
    seconds: int

class Converted(NamedTuple):           # already narrowed to the scope
    rows: tuple[ConvertedRow, ...]

class FigureChange(NamedTuple):
    key: StatsKey; before: object; after: object
    attribution: str | None   # None is unattributed

def judge_scope(before: StatsData, after: StatsData,
                identities: ScopeIdentities, converted: Converted) -> tuple[FigureChange, ...]
```

`RULES: Mapping[StatsKey, Rule]` where `type Rule = Callable[[object, object, ScopeIdentities, Converted], str | None]`
answers the attribution sentence or `None`. Keys absent from a scope
(`total_games`, `month_playtimes` all-time) are skipped when absent from
**both** `StatsData`; present in one only is a change with no attribution.

Rules, one each, named after the spec's table:

- `BOTH`, playtime keys: `PlaytimeBreakdown` values -- `total` equal;
  `tracked` down and `historical` up by the converted seconds the row's key
  holds (`total_hours`: all rows; `games_by_playtime`: per game, order kept,
  compare as a list of `(game_id, breakdown)`; `total_playtime_per_platform`:
  per platform id; `month_playtimes`: per month of a row's day).
- `BOTH`, counts and days (`games_by_playtime_count`, `total_games`,
  `total_year_games`, `unique_days`, `unique_days_percent`, `first_play_*`,
  `last_play_*`): equal. A change is unattributed by design: it means the
  read disagrees with the charter.
- `PURCHASES`: `list(queryset.values_list("pk", flat=True))` equal, ints equal.
- `NOT_A_FIGURE`: equal.
- `total_sessions`: `before - after == len(rows)`.
- `longest_session_*`: equal, or `identities.longest_session_id` in
  `{row.session_id}`. The `_game` and `_time` siblings share one rule bound
  to the same identity.
- `highest_session_count*`: equal, or `highest_count_game_id` in `{row.game_id}`.
- `highest_session_average*`: equal, or before's or after's game id in
  `{row.game_id}`; after's is `after["highest_session_average_game"].pk`.

- [ ] Tests, pure, no database: one passing and one failing case per rule
  above, built from two dict literals typed `StatsData` and hand-made
  `ScopeIdentities`/`Converted`. A `PlaytimeBreakdown` case where `total`
  moves by one second fails. A `games_by_playtime` case with equal totals in
  another order fails. A `unique_days` case that falls by one is unattributed.
- [ ] Guard: `test_every_stats_key_has_a_rule` asserts
  `set(RULES) == set(STATS_SOURCES)`.
- [ ] Implement; `make test ARGS="tests/test_stats_parity.py -x"`; commit
  `feat: judge each statistics figure by its source's rule`.

---

### Task 1: The command

**Files:** create `games/management/commands/verify_reclassification_parity.py`;
modify `Makefile` (after `verify-replay-parity`), `CLAUDE.md` commands table;
test `tests/test_stats_parity.py`.

**Consumes:** Task 1's names; `compute_stats`, `played_years`,
`longest_session`, `most_sessions_game`, `highest_average_game`, `reviewable_sessions`,
`reclassify_session`, `statement_from_session`, `new_correlation_id`,
`CommandFailed`.

Shape:

1. `--user NAME` required, `--confirm NAME` optional. Resolve `User`, library.
2. `scopes = [None, *played_years(library)]`; for each, `before[scope] = compute_stats(library, scope)` and `identities[scope]` through the three readers (`longest_session(...).session.pk`, `most_sessions_game(...).game.pk`, `highest_average_game(...).game.pk`, each `None` where the reader answers `None`).
3. `population = list(reviewable_sessions(library).select_related("playthrough__player_game__game"))`; print its count. Without `--confirm`: print every scope's figures and stop, exit 0. `--confirm` not matching `--user`: `CommandError`.
4. Convert: `token = uuid.uuid7()`, `correlation_id = new_correlation_id()`, per row `reclassify_session(user, row, statement_from_session(row), idempotency_key=f"reclassify-{token}-{row.pk}", correlation_id=correlation_id)`; catch `CommandFailed` → print sentence, `CommandError`. Collect `ConvertedRow` per row before converting (platform id off the game, seconds off `effective_duration`).
5. `after[scope]` as in 2; `converted[scope]` narrows rows by the year of `row.day` (all-time takes all).
6. `judge_scope` per scope; print `scope: key before → after [attribution | UNATTRIBUTED]` for each change; summary `N unattributed of M changed across S scopes; P rows converted`. Unattributed > 0 → `CommandError`.

Makefile:

```make
# Converts the review population and judges every figure. Scratch restore only.
# Usage: make verify-reclassification-parity ARGS="--user NAME --confirm NAME"
verify-reclassification-parity: ensure-postgres
	uv run --frozen python manage.py verify_reclassification_parity $(ARGS)
```

- [ ] Tests (`transaction=True`): seed a library with `create_tracked_game`
  and `CreateSession` rows -- two Duration-only rows over 8 h on different
  games (one the game's sole session, one beside a Timed row), one Timed row,
  one Duration-only row under 8 h. `call_command` with `--confirm`: exit clean,
  output names two converted rows, `total_sessions` down by 2 in the year,
  `longest_session_*` attributed to the converted row, `total_games`,
  `unique_days`, `first_play_date` and `total_hours` unchanged. Without `--confirm`: no event appended. Mismatched `--confirm`:
  `CommandError`. A second `--confirm` run: population 0, nothing changes,
  exit clean.
- [ ] Unattributed path: monkeypatch `RULES["total_sessions"]` to answer
  `None`; expect `CommandError` naming `total_sessions`.
- [ ] `make test ARGS="tests/test_stats_parity.py -x"`; commit
  `feat: verify statistics parity across the reclassification`.

---

### Task 1: The records workload

**Files:** modify `games/events/benchmark_workload.py`, `benchmark.py`,
`benchmark_run.py`, `games/management/commands/benchmark_events.py`; test
`tests/test_event_benchmark.py`.

**Produces:**

```python
# benchmark_workload.py
def run_record_command_scenario(library, *, actor, runs: Iterator[Playthrough],
                                records: int, warmup: int) -> Timings
def _analyze(tables: Sequence[type[Model]] = _SEEDED_TABLES) -> None
# benchmark.py
def record_command_budget(timings: Timings) -> Budget   # "record command p95", 100 ms
REPORT_SCHEMA = 4
BenchmarkReport.record_command: Timings | None          # after session_command
# benchmark_run.py
def run_benchmark(*, seed, iterations, warmup, records: int, library=None, keep=False, ...)
# benchmark_events.py
IMPORT_SHAPE_RECORDS = 600
SECONDS_PER_RECORD_DISPATCH = 5 / 1000
```

Scenario body: `_record_playtime(library, actor=actor, run=run)` dispatches
`RecordHistoricalPlaytime(statement=HistoricalPlaytimeStatement(duration=timedelta(hours=10), when="2005", provenance=HistoricalPlaytimeProvenance.ESTIMATED, playthrough_ids=(run.pk,), device_id=None, emulated=False, note=""))`
with `idempotency_key=str(uuid.uuid7())`. Runs cycle: wrap the iterator so
exhaustion re-opens `seeded_runs(library)`; a library with no run raises
`ValueError("The records scenario needs a run to name.")`. Ends with
`_analyze((HistoricalPlaytime, HistoricalPlaytimeRun))`. Placed in
`_measure_scratch` after the session scenario, before `run_read_scenario`;
budget after `session_command_budget`. `_measure_existing` sets
`record_command=None`. `_write_estimate` adds `records * SECONDS_PER_RECORD_DISPATCH`
and names the count in the notice. `_write_report` prints
`Record command: ...` after the session line.

- [ ] Tests: `test_the_record_command_scenario_records_on_the_seeded_runs`
  (seed 5 games, `records=3, warmup=1` → 4 `HistoricalPlaytime` rows, 3
  samples); `test_the_record_scenario_cycles_the_runs` (seed 2 games,
  `records=5` → 5 rows); `test_the_report_carries_every_scenario_and_a_schema`
  asserts schema 4 and `record_command` present; `test_library_mode_reads_without_dispatching`
  keeps 7 budgets and asserts `record_command is None`; scratch budget count
  10 with `"record command p95"` between `"session command p95"` and the first
  read; `test_the_record_command_budget_is_the_charters`; the estimate test
  names the record count. Every existing `run_benchmark` call in tests gains
  `records=2`.
- [ ] `make test ARGS="tests/test_event_benchmark.py -x"`; commit
  `feat: a records workload in the benchmark, an import's shape`.

---

### Task 1: The rehearsal

Manual, on this machine, no code. Each step's output goes into the
recordings; nothing is edited by hand.

- [ ] `make fetch-dump`; `make restore-dump` → note the printed
  `DATABASE_URL` as `$URL`. Check the migration state:
  `psql "$URL" -c "select name from django_migrations where app='games' order by id desc limit 1"`
  must answer `0008_...` or earlier. If it answers 0009+, stop and report:
  the spec's Pages section says why.
- [ ] Base render: `git worktree add ../base 855c276f`, in it `uv sync --frozen`,
  `make migrate DATABASE_URL=$URL`, `make render-pages DATABASE_URL=$URL ARGS="--user <name> --out /tmp/…/before"`.
- [ ] Head render, in this worktree: `make migrate DATABASE_URL=$URL`,
  `make render-pages DATABASE_URL=$URL ARGS="--user <name> --out /tmp/…/after"`.
  `diff -rq before after | wc -l`; then attribute every differing file,
  grouping by route and by the wave PR or #1115/#1120. A file no group
  explains: render at the merge between candidates and split.
- [ ] `make verify-reclassification-parity DATABASE_URL=$URL ARGS="--user <name> --confirm <name>"`;
  keep the whole output.
- [ ] `make bench DATABASE_URL=$URL ARGS="--library <id> --gate"` and, on the
  development database, `make bench ARGS="--gate"`; keep both outputs.
- [ ] `make verify-replay-parity DATABASE_URL=$URL`.
- [ ] `make drop-dump`; `git worktree remove ../base`.

---

### Task 1: Record it

**Files:** `docs/event-benchmarks.md` (new heading "The #1099 recording",
scratch run then production-shape run, the machine block if it changed),
the wave doc (Delivered block after item 7 of the delivery order, in the
session wave's shape; "What was applied" gains the `total_games` finding
and #1126), this spec (a `## Delivered` section with the four gates' numbers).

- [ ] Paste, do not edit, the three outputs. Attribution list for the pages
  in the wave doc's block, one line per group with its count.
- [ ] `make vale`; commit `docs: record the historical-playtime gates`.
- [ ] Full `make check` once, on the user's word; open the PR.

## Follow-up issues

- #1126 (filed, lands first): the reads restored to the charter's table.
