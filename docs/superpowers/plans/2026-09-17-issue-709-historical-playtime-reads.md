# Read historical playtime beside sessions: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> (inline, the default here) or superpowers:subagent-driven-development to
> implement this plan task by task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Every playtime figure sums sessions and historical playtime
records, and every statistic states which sources it takes.

**Architecture:** A shared scope module and a records-sum module sit beside
`player_sessions.py`. `playtime.py` composes both: Python figures return
`PlaytimeBreakdown`, and queryset expressions stay one number. The
classification is a mapping in `stats_data.py`, and a test checks it.

**Tech stack:** Django 6 ORM on PostgreSQL 18, pytest with pytest-django,
Playwright for e2e.

**Spec:** [2026-09-17-issue-709-historical-playtime-reads-design.md](../specs/2026-09-17-issue-709-historical-playtime-reads-design.md).
Read it first. This plan names the work; the spec says why.

## Global constraints

- Run everything through `make`: `make test ARGS="…"` while iterating,
  `make check-fast` between tasks, and full `make check` (e2e included) as
  the only gate before push. Never use `direnv exec`, `uv run` or `pytest`
  directly.
- Containment: a record counts in a period only when `when_lower` and
  `when_upper` both lie inside it. Null bounds count in all-time only.
- `games/reads/historical_playtime_records.py` is the spec's Scope block,
  copied byte for byte. If `main` already has it on rebase, take `main`'s
  copy.
- Sort key: `NullIf(Coalesce(s, 0) + Coalesce(r, 0), 0)`. Never repeat a
  subquery inside one expression.
- The playthrough note reads `.tracked`. Every other caller reads `.total`.
- Nothing outside `games/reads` imports the records sums.
- Use complete-word identifiers, and give every compound type a name
  (`PlaytimeBreakdown`, `PlaytimeParts`).
- Comments explain intent only, with no issue numbers.
- Every test that creates rows uses `@pytest.mark.django_db`.
- Commit messages end with
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Merge with a
  merge commit, never a squash.

## File map

| file | change |
|---|---|
| `games/reads/days.py` | new: `DayInterval` |
| `games/reads/sums.py` | new: `UnscopedSum`, `UnscopedPlaytimeRead`, `PlaytimeSum`, `ZERO`, moved out of `playtime.py` |
| `games/reads/historical_playtime_records.py` | new, shared: the spec's Scope block |
| `games/reads/historical_playtime.py` | new: the record sums |
| `games/reads/playtime.py` | composes both sources; breakdown; renames; deletes the day reader |
| `common/time.py` | deletes `streak`, `streak_bruteforce` |
| `games/views/stats_data.py` | classification mapping, `GamePlaytime`, top-10 parts |
| `games/views/stats_content.py` | `.total` |
| `games/views/game.py` | header `.total`; `games_for_list` alias reuse; column label |
| `games/views/general.py` | navbar `playtime_between_each`; corrected comment |
| `games/views/playthrough.py` | note `.tracked`; `DayInterval` import |
| `games/events/benchmark_reads.py` | follows the new return types |
| `tests/record_rows.py` | new: `record_row`, `record_join` |
| `tests/test_historical_playtime_reads.py` | new |
| `tests/test_playtime_sources.py`, `tests/test_stats.py`, `tests/test_sorting.py`, `tests/test_filters.py` | extended |
| the eight `timedelta` call sites listed in the spec's Callers | `.total` |
| `tests/test_streak.py` | deleted |
| `e2e/test_games_list_projection_e2e.py` | the column shows the composed total |
| `CLAUDE.md`, the wave spec, this issue's spec | docs |

---

### Task 0: Start clean

- [ ] `git fetch origin && git rebase origin/main`. If
  `games/reads/historical_playtime_records.py` is already on `main`, Task 2
  only diffs it against the spec's block.
- [ ] Run `make check-fast` to get a green baseline, and record its time.

### Task 1: Move `DayInterval`; delete the dead readers

**Files:**
- Create: `games/reads/days.py`
- Modify: `games/reads/playtime.py`, `games/views/general.py`,
  `games/views/playthrough.py`, `common/time.py`,
  `tests/test_playtime_sources.py`
- Delete: `tests/test_streak.py`

**Produces:** `from games.reads.days import DayInterval`. The class is
unchanged: `first`, `last`, `single(day)`, `ending(day, *, days)`.

- [ ] Move the class and its docstring verbatim. Update the three
  importers. Drop it from `playtime.__all__`; add no re-export.
- [ ] Delete `playtime_by_day`, `DayPlaytime` and their `__all__` entries,
  and the day assertions in `test_playtime_sources.py` (the `"days"` key
  near line 150, if present).
- [ ] Delete `streak`, `streak_bruteforce` and `tests/test_streak.py`.
  Before deleting, run `grep -rn "streak\|playtime_by_day\|DayPlaytime"` and
  expect hits only in the files above.
- [ ] Run `make test ARGS="tests/test_playtime_sources.py tests/test_stats.py -x"`.
- [ ] Commit: `refactor: move DayInterval to its own module; drop unread day readers`.

### Task 2: The shared record scope

**Files:**
- Create: `games/reads/historical_playtime_records.py`,
  `tests/record_rows.py`
- Test: `tests/test_historical_playtime_reads.py`

**Produces:**
- `library_records(library)`, `readable_records(library)`,
  `game_records(library, game)` and `RECORD_ORDER`, exactly as in the spec.
- In `tests/record_rows.py`:
  `record_row(run, *, duration, when, provenance=ESTIMATED, **columns) -> HistoricalPlaytime`,
  which writes the row as `a_record` in
  `tests/test_historical_playtime_projection.py` does, with
  `player_game=run.player_game`, and then adds the join for `run`. Also
  `record_join(record, run)`. Reuse `tracked_run` from `session_rows.py`.

- [ ] Write failing tests, one per condition. A record is excluded when:
  - it is in another library;
  - its `PlayerGame` is in another library (build the drift row directly);
  - it is removed;
  - its `PlayerGame` is removed;
  - its catalog game is removed.

  `game_records` narrows to one catalog game. `readable_records` reads
  platform and device with no extra query (`django_assert_num_queries(1)`).
- [ ] Copy the spec's block, then run `make format`. The file must still
  match the spec's block exactly, because the block is already formatted.
- [ ] Run `make test ARGS="tests/test_historical_playtime_reads.py -x"`.
- [ ] Commit: `feat: add the shared historical playtime record scope`.

### Task 3: The record sums

**Files:**
- Create: `games/reads/historical_playtime.py`, `games/reads/sums.py`
- Modify: `games/reads/playtime.py` (imports from `sums.py`)
- Test: `tests/test_historical_playtime_reads.py`

**Consumes:** `library_records`, `game_records`, `DayInterval`.

**Produces:**
- `contained_in(records, days: DayInterval) -> HistoricalPlaytimeQuerySet`
- `historical_total(library, *, within: DayInterval | None = None) -> timedelta`
- `historical_totals(library, windows: Sequence[DayInterval]) -> list[timedelta]`,
  one `aggregate()` with keys `window_0…n`, each a
  `Sum("duration", filter=…)` coalesced to zero
- `historical_summed_by_game(library: UserLibrary | None, *, within=None) -> PlaytimeSum`,
  which returns `UnscopedSum()` with no library.
  `UnscopedSum`, `UnscopedPlaytimeRead`, `PlaytimeSum` and `ZERO` move from
  `playtime.py` to `games/reads/sums.py`, so both modules import them
  without a cycle. `playtime.py` keeps `UnscopedPlaytimeRead` in `__all__`,
  because `tests/test_filters.py:1545` imports it from there.
- `historical_by_platform(library, *, within=None) -> list[PlatformHistorical]`
- `historical_by_month(library, *, year: int) -> list[MonthHistorical]`
- `historical_years(library) -> list[int]`
- `game_historical_playtime(library, game, provenance: HistoricalPlaytimeProvenance | None = None) -> timedelta`

`PlatformHistorical(platform_id, platform_name, playtime)` and
`MonthHistorical(month, playtime)` are `NamedTuple`s. The month filter is
`contained_in(year)` plus `when_lower__month == when_upper__month`, grouped
on `TruncMonth("when_lower")`. `historical_years` reads rows where
`when_lower__year == when_upper__year` and returns the distinct sorted
years.

- [ ] Write a failing parametrized containment test. Each `when` below is
  checked in year 2022, month 2022-06, day window 2022-06-11, and all-time:

  | `when` | counts in |
  |---|---|
  | `2022` | year, all-time |
  | `2022~` | year, all-time |
  | `2022-06` | year, month, all-time |
  | `2022-06-11` | all four |
  | `2020/2022` | all-time |
  | `198X` | all-time |
  | `../2021-09-27` | all-time |
  | `2020/` | all-time |
  | `2020/..` | all-time |
  | `None` | all-time |

- [ ] Write failing tests for the rest:
  - `historical_totals` runs one query (`django_assert_num_queries(1)`);
  - a platform row is reached through the game, and a platformless game
    gives a `None` row;
  - `provenance=` narrows the sum;
  - the per-game subquery equals `game_historical_playtime`;
  - with no library, the per-game subquery raises `UnscopedPlaytimeRead`;
  - a record naming two runs counts once.
- [ ] Implement.
- [ ] Run `make test ARGS="tests/test_historical_playtime_reads.py -x"`.
- [ ] Commit: `feat: sum historical playtime records by containment`.

### Task 4: Compose figures computed in Python

**Files:**
- Modify: `games/reads/playtime.py`, `games/views/stats_data.py`,
  `games/views/stats_content.py`, `games/views/game.py` (header only),
  `games/views/general.py`, `games/views/playthrough.py`,
  `games/events/benchmark_reads.py`, and the eight test call sites in the
  spec's Callers section
- Test: `tests/test_playtime_sources.py`

**Consumes:** Task 3.

**Produces:**
- `PlaytimeBreakdown(tracked, historical)`, a frozen dataclass with slots
  and a `total` property, exported.
- These return `PlaytimeBreakdown`: `total_playtime`, `game_playtime`,
  `playtime_between`, `game_playtime_between`.
- `playtime_between_each(library, windows) -> list[PlaytimeBreakdown]`
  runs two queries in total.
- `PlatformPlaytime.playtime` and `MonthPlaytime.playtime` hold a
  `PlaytimeBreakdown`.
- `played_years` returns the union of both sources.
- `summed_by_game` is renamed `tracked_summed_by_game`, and
  `summed_by_game_matching` is renamed `tracked_summed_by_game_matching`.

The platform merge is a dict keyed on `(platform_id, platform_name)`, then
`sorted` by `(-total, name is None, name or "", id is None, id or 0)`.
Compare UUIDs as `UUID` values: their ordering matches PostgreSQL's
byte-wise `uuid` ordering.

- [ ] Move the existing assertions to `.total` or to breakdown values.
  Add failing tests for:
  - each function with one contained and one non-contained record beside
    sessions;
  - `playtime_between_each` in two queries;
  - a platform and a month that only records reach;
  - the unspecified bucket last on a tie;
  - `played_years` including a record's year.
- [ ] Implement. Update every caller: `.total` everywhere except the
  playthrough note, which reads `.tracked`. `StatsData.total_hours` is typed
  `PlaytimeBreakdown`.
- [ ] The navbar in `model_counts` calls
  `playtime_between_each(library, [today, last_seven_days])`. Rewrite the
  comment at `general.py:46-47` to say the link lists the tracked part.
- [ ] Playthrough test: a record contained in the note's window leaves the
  note unchanged. Put it in the note's existing test file, found with
  `grep -rn NO_SESSIONS_NOTE tests`.
- [ ] Run `make typecheck`, then
  `make test ARGS="tests/test_playtime_sources.py tests/test_stats.py tests/test_removal.py tests/test_api.py tests/test_retention.py tests/test_rendered_pages.py tests/test_library_reconciliation.py tests/test_library_api_isolation.py -x"`.
- [ ] Commit: `feat: return tracked and historical playtime from every figure`.

### Task 5: Compose the expressions and the game list

**Files:**
- Modify: `games/reads/playtime.py`, `games/views/game.py`
  (`games_for_list`, `list_games`)
- Test: `tests/test_playtime_sources.py`, `tests/test_sorting.py`,
  `tests/test_filters.py`, and the game list view tests (find them with
  `grep -rln "filtered_playtime" tests`)

**Produces:**
- `playtime_by_game(library, *, year)` returns
  `Coalesce(tracked, 0) + Coalesce(historical, 0)`.
- `playtime_sort_key(library)` returns `NullIf(<that>, ZERO)`.
- `playtime_matching(library, session_filter: PlayerSessionFilter)` no
  longer accepts `None`.
- `PlaytimeParts(tracked, historical, total)` is a `NamedTuple` of
  expressions, and `playtime_parts_by_game(library, *, year) -> PlaytimeParts`
  builds it.
- `games_for_list`: `filtered_playtime` is `F("total_playtime")` when there
  is no `session_filter`, and `playtime_matching(...)` otherwise.
  `total_playtime` becomes an `annotate` so that `F()` can read it; check
  that `?sort=playtime` still works.
- `list_games`: the Playtime column label is `"Playtime (matching sessions)"`
  when `game_filter` carries a `session_filter`.

- [ ] Write failing tests:
  - the sort key is NULL for an unplayed game and for a game whose only
    session is running, and both sort last in both directions;
  - a record-only game sorts by its record;
  - `playtime_hours` matches a game whose composed total crosses the
    threshold only with its record;
  - under a session filter, `playtime_matching` ignores records;
  - an unscoped composed sum raises when executed, and
    `annotated_for_filtering`'s second-library refusal still holds;
  - with no filter, the list queryset's SQL names
    `games_historicalplaytime` once and `games_playersession` once
    (count in `str(sort.queryset.query)`);
  - the column label under a session filter.
- [ ] Implement.
- [ ] Run `make test ARGS="tests/test_playtime_sources.py tests/test_sorting.py tests/test_filters.py -x"`.
- [ ] Commit: `feat: sort and filter the game list on composed playtime`.

### Task 6: The classification and the stats top 10

**Files:**
- Modify: `games/views/stats_data.py`, `games/views/stats_content.py`
- Test: `tests/test_stats.py`

**Produces:**
- `StatsSource`, a `StrEnum` with values `BOTH`, `SESSIONS_NO_SITTINGS`,
  `SESSIONS_NO_YEAR_OF_PLAY`, `PURCHASES` and `NOT_A_FIGURE`.
- `STATS_SOURCES: Mapping[str, StatsSource]`, keyed exactly as the spec's
  table.
- `GamePlaytime` gains `tracked_playtime` and `historical_playtime`.
- The top 10 annotates the three `PlaytimeParts` members under those names,
  plus `total_playtime`.

- [ ] Write failing tests:
  - `STATS_SOURCES.keys() == StatsData.__required_keys__ | StatsData.__optional_keys__`;
  - a record contained in 2022 moves `total_hours`, the top 10, the
    platform rows and `month_playtimes` for 2022, and nothing for 2021;
  - a snapshot of every `SESSIONS_*` key before and after the record is
    equal;
  - a `2020/2022` record moves only the all-time figures;
  - a record-only game enters the 2022 top 10 with its tracked part zero.
- [ ] Implement. `stats_content.py` renders `.total` on month and platform
  rows (Task 4 may already have done this); the top 10 keeps reading
  `total_playtime`.
- [ ] Run `make test ARGS="tests/test_stats.py tests/test_stats_links.py -x"`.
  Use whatever the stats-link parity file is actually named
  (`grep -rln stats_links tests`).
- [ ] Commit: `feat: classify every statistic by its playtime sources`.

### Task 7: e2e, docs, parity, gate

**Files:**
- Modify: `e2e/test_games_list_projection_e2e.py`, `CLAUDE.md`,
  `docs/superpowers/specs/2026-09-17-historical-playtime-wave-design.md`,
  this issue's spec

- [ ] e2e: a game with one session and one record shows the sum in the
  Playtime column, and `?sort=playtime` orders it above a sessions-only game
  with less time.
- [ ] `CLAUDE.md`:
  - In the HistoricalPlaytime entry, replace "Nothing reads or writes it
    from a page yet." with one sentence: "`games/reads/historical_playtime.py`
    sums it by containment beside sessions." If `main` changed that
    sentence, keep `main`'s and append ours.
  - Rewrite the Playtime reads paragraph: both sources, `PlaytimeBreakdown`,
    containment, the sort key's NULL rule, the note's `.tracked`, the two
    record modules, and "no caller outside `games/reads` imports the record
    sums".
- [ ] Wave spec Classification table: remove "streaks, the day chart" from
  the "never" row, and add the sentence "Streaks and the day chart had no
  caller, and #709 removed the read."
- [ ] Docs sweep of this issue's spec: rewrite it to describe the current
  design only (drop "Parallel work", keep the rest), then delete this plan
  file.
- [ ] Parity rehearsal on the newest dump:
  - `make fetch-dump` if the newest dump is older than 2026-09-16;
  - `make restore-dump`, `DATABASE_URL=<printed> make migrate`;
  - `git switch --detach origin/main`, then
    `DATABASE_URL=… make render-pages ARGS="--user <name> --out $SCRATCH/main"`;
  - switch back, and run the same with `--out $SCRATCH/branch`;
  - `diff -r` must be empty;
  - `DATABASE_URL=… make bench ARGS="--library <id> --gate"` must pass;
  - `make drop-dump`.

  Put the diff result and the bench table in the PR body.
- [ ] Run the full `make check`, logged to a file. Read its exit code, not
  a grep of its output.
- [ ] Commit, push, open the PR (title
  `feat: read historical playtime beside sessions (#709)`, body `Closes #709`,
  the parity evidence, and `Refs #1105 #1106`). Do not merge until the user
  says so.

## Self-review

- **Spec coverage:**
  - rule and qualifiers: Task 3;
  - modules and scope: Tasks 2 and 3;
  - `DayInterval` move: Task 1;
  - breakdown, `between_each`, merge order, `played_years`: Task 4;
  - deletions: Task 1;
  - expressions, sort key rule, game list: Task 5;
  - classification and top 10: Task 6;
  - Game detail classification: Task 4 (header `.total`; the metrics stay
    as they are) and Task 7 (docs);
  - known gap comment: Task 4;
  - callers: Task 4;
  - verification: Tasks 2–7;
  - parallel rules: Tasks 2 and 7;
  - wave amendment: Task 7.
- **Shared names:** `UnscopedSum`, `ZERO` and `PlaytimeSum` move to
  `games/reads/sums.py` in Task 3, and Task 4 onward imports them from
  there. The file map lists that module under Task 3's work.
