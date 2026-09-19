# Records in the day figures and the played-game counts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The days played, the first and last play and the two played-game
counts count a historical playtime record, as the charter states, and the
`games_played` link compiles the same predicate as its figure.

**Architecture:** Member 1: three readers move out of
`games/reads/session_figures.py` into `games/reads/play_figures.py`, each with
a records leg scoped by `contained_in` narrowed to `when_lower == when_upper`,
under a source-blind tie-break. Member 2: `games_in_scope` and the purchase
count gain a containment leg; `GameFilter` gains `historical_playtime_filter`
and the criteria algebra gains `Modifier.WITHIN`, so `games_played` and
`games_in_month` state "a session in scope or a record within it". One
`gh stack` of two members.

**Tech Stack:** Django 6, PostgreSQL 18, Python 3.14, pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-09-19-issue-1126-day-figures-design.md`

## Global Constraints

- Every command goes through `make`. No `direnv exec .`, no raw `uv run` or
  `pytest`. Focused runs: `make test-fast ARGS="tests/test_play_figures.py -x"`.
- Wrap every pytest target in the shared lock:
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS=...`.
- `make check-fast` while iterating. The full `make check` runs once, at the end,
  and only when the user says so.
- Never write to a `GeneratedField`: `effective_day`, `effective_duration`,
  `sort_instant`, `when_lower`, `when_upper`.
- Read playtime and records only through `games/reads/`. No new
  `Sum("duration")` call site.
- Complete words in identifiers: `record` not `rec`, `session` not `sess`.
- `make vale` after every prose change. A projector *replays*; the row is a
  *projection*. Never "delete" for a removal.
- Rebase onto `origin/main` before the first edit.
- Scope: six keys and two links. The top-10, platform and navbar links and the
  narrowed Playtime column stay #1105's.
- Two members, one stack: `gh stack init` after Task 6, `gh stack add` for
  member 2, `gh stack submit`, merge with `gh stack merge` (merge commits).
  Never retarget a PR base by hand.

---

### Task 1: Move the three readers into `play_figures.py`

A pure move, so a later task's diff shows only behaviour.

**Files:**
- Create: `games/reads/play_figures.py`
- Modify: `games/reads/session_figures.py` (remove `PlayDay`, `_play_day`,
  `distinct_days`, `first_play`, `last_play`; keep `scoped_sessions`,
  `games_in_scope`, `session_count`, the three superlatives, `has_sessions`,
  `SORT_NAME`, `GAME_KEY`, the three other NamedTuples, and the module
  docstring's tie-break sentence, which describes the three superlatives)
- Modify: `games/views/stats_data.py:56-65` (split the import)
- Modify: `games/events/benchmark_reads.py:22-30` (split the import)
- Create: `tests/test_play_figures.py`
- Modify: `tests/test_session_figures.py` (move the day-figure cases out)

**Interfaces:**
- Consumes: `library_sessions`, `scoped_sessions` (imported from
  `session_figures`), `YearScope`.
- Produces: `PlayDay(day: date, game: Game)`,
  `distinct_days(library: UserLibrary, year: YearScope) -> int`,
  `first_play(library, year) -> PlayDay | None`, `last_play(...) -> PlayDay | None`.

- [ ] **Step 1: create the module with the three readers unchanged**

Module docstring states the sources it will take once Task 3 lands; write it
for the end state, since Task 3 is the same PR:

```python
"""The day figures, counted over sessions and day-precision records.

A record counts on its day when it names exactly one, so a month,
a year and a range wider than a day count in no figure here. The
tie-break names no source, so restating a session as a record
cannot move an answer.
"""
```

Copy `PlayDay`, `_play_day`, `distinct_days`, `first_play`, `last_play` across
verbatim. Import `SORT_NAME`, `GAME_KEY`, `scoped_sessions` from
`session_figures` and `GAME` from `games/reads/player_sessions.py`, which the
readers' `select_related(GAME)` names.

- [ ] **Step 2: move the tests**

Move `test_distinct_days_*`, `test_first_play_on_a_shared_day_picks_the_lower_key`
and the day-figure assertions of `test_an_empty_library_answers_none_and_zero`
into `tests/test_play_figures.py`, with the `at`, `timed` and `games` fixtures
that serve them. Keep a copy of the fixtures in `test_session_figures.py` for
the readers that stay. Do not change an expected value in this task.

- [ ] **Step 3: run both files**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_play_figures.py tests/test_session_figures.py -x"
```

Expected: PASS, same count as before the move.

- [ ] **Step 4: run the two call sites' tests**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_stats.py tests/test_event_benchmark.py -x"
```

- [ ] **Step 5: commit**

```bash
git add -A && git commit -m "refactor: move the day figures to their own module (#1126)"
```

---

### Task 2: The source-blind, mirrored tie-break

**Files:**
- Modify: `games/reads/play_figures.py`
- Modify: `tests/test_play_figures.py`

**Interfaces:**
- Produces: the two order tuples later tasks reuse —
  first `("effective_day", SORT_NAME, GAME_KEY)`,
  last `("-effective_day", f"-{SORT_NAME}", f"-{GAME_KEY}")`.

- [ ] **Step 1: rewrite the shared-day test to state the new answer**

The `games` fixture gives `beta` the sort name `"a beta"` and `alpha` the sort
name `"b alpha"`. One session a game on one day, so:

```python
def test_a_shared_day_answers_by_sort_name_at_each_end(owned_library, games):
    beta, alpha = games
    day = date(2024, 1, 1)
    duration_only_row(tracked_run(owned_library, alpha), day, timedelta(hours=1))
    timed(tracked_run(owned_library, beta), day, 8, 1)

    earliest = first_play(owned_library, None)
    latest = last_play(owned_library, None)

    assert earliest is not None and latest is not None
    assert (earliest.day, earliest.game) == (day, beta)
    assert (latest.day, latest.game) == (day, alpha)
```

Remove `test_first_play_on_a_shared_day_picks_the_lower_key`, whose
`sorted(..., key=lambda row: row.pk)` construction states the rule this task
replaces.

- [ ] **Step 2: run it and watch it fail**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_play_figures.py -x -k shared_day"
```

Expected: FAIL. Today's order is the day, then the row key, so both ends
answer by insertion order within the day.

- [ ] **Step 3: order on the three levels**

`first_play` orders `("effective_day", SORT_NAME, GAME_KEY)`; `last_play`
mirrors every level with a `-` prefix. Both keep `.select_related(GAME)`.

- [ ] **Step 4: run the file**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_play_figures.py -x"
```

- [ ] **Step 5: run the pages and stats that print the figures**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_stats.py tests/test_rendered_pages.py -x"
```

Fix an expected game name in those files where a shared day makes one move; the
value is now the lower, or higher, sort name.

- [ ] **Step 6: commit**

```bash
git add -A && git commit -m "fix: order the day figures by the game, not the row key (#1126)"
```

---

### Task 3: The day count counts a record

**Files:**
- Modify: `games/reads/days.py` (add `year_days`)
- Modify: `games/reads/playtime.py:86-87` (use it, drop the private copy)
- Modify: `games/reads/play_figures.py`
- Modify: `tests/test_play_figures.py`

**Interfaces:**
- Consumes: `library_records` from `games/reads/historical_playtime_records.py`,
  `contained_in` from `games/reads/historical_playtime.py`, `DayInterval`.
- Produces: `year_days(year: YearScope) -> DayInterval | None` in
  `games/reads/days.py`, where `type YearScope = int | None` now lives (moved
  from `games/reads/playthrough_completions.py`, which re-exports it, because
  `days.py` is a leaf and must not import `games.filters`); a private
  `_day_records(library, year) -> HistoricalPlaytimeQuerySet` in
  `play_figures.py`, which every reader in that module shares.

- [ ] **Step 1: write the failing tests**

Use `record_row` from `tests/historical_playtime_rows.py` and `tracked_run`
from `tests/session_rows.py`. The `when` strings are canonical temporal text.

```python
@pytest.mark.parametrize(
    "when",
    ["2024-03-05", "2024-03-05~", "2024-03-05?", "2024-03-05/2024-03-05"],
)
def test_a_record_naming_one_day_raises_the_day_count(owned_library, games, when):
    beta, _alpha = games
    record_row([tracked_run(owned_library, beta)], when=when)

    assert distinct_days(owned_library, 2024) == 1
    assert distinct_days(owned_library, None) == 1


@pytest.mark.parametrize(
    "when", ["2024", "2024-03", "2024-03-05/2024-03-06", "2024-03-05/..", None]
)
def test_a_record_naming_no_single_day_raises_nothing(owned_library, games, when):
    beta, _alpha = games
    record_row([tracked_run(owned_library, beta)], when=when)

    assert distinct_days(owned_library, 2024) == 0
    assert distinct_days(owned_library, None) == 0


def test_a_record_on_a_day_a_session_holds_counts_once(owned_library, games):
    beta, _alpha = games
    run = tracked_run(owned_library, beta)
    day = date(2024, 3, 5)
    timed(run, day, 10, 1)
    record_row([run], when="2024-03-05")

    assert distinct_days(owned_library, 2024) == 1


def test_a_day_outside_the_year_leaves_that_year(owned_library, games):
    beta, _alpha = games
    record_row([tracked_run(owned_library, beta)], when="2023-12-31")

    assert distinct_days(owned_library, 2024) == 0
    assert distinct_days(owned_library, None) == 1
```

- [ ] **Step 2: run them and watch them fail**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_play_figures.py -x -k record"
```

Expected: FAIL, every count one short.

- [ ] **Step 3: add `year_days` to `games/reads/days.py`**

```python
def year_days(year: YearScope) -> DayInterval | None:
    """The year's days; None is all-time, which bounds nothing."""
    return None if year is None else DayInterval.year(year)
```

Have `games/reads/playtime.py` import it and take its private `_year_days` out,
so one function answers the question.

- [ ] **Step 4: write the records leg and the union count**

```python
def _day_records(library: UserLibrary, year: YearScope) -> HistoricalPlaytimeQuerySet:
    """Records naming exactly one day, that day inside the scope."""
    records = library_records(library).filter(when_lower=F("when_upper"))
    days = year_days(year)
    return records if days is None else contained_in(records, days)


def distinct_days(library: UserLibrary, year: YearScope) -> int:
    """One query: UNION is distinct, so a day both sources hold counts once."""
    session_days = (
        scoped_sessions(library, year).values_list("effective_day").distinct()
    )
    record_days = _day_records(library, year).values_list("when_lower").distinct()
    return session_days.union(record_days).count()
```

`values_list` without `flat=True` on both legs, so the two selects have one
shape. Neither model declares `Meta.ordering`, so no leg carries an `ORDER BY`
the union would refuse.

- [ ] **Step 5: run the file, then the empty-library case**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_play_figures.py tests/test_playtime_sources.py -x"
```

- [ ] **Step 6: commit**

```bash
git add -A && git commit -m "feat: count a day-precision record in the days played (#1126)"
```

---

### Task 4: The first and last play read both sources

**Files:**
- Modify: `games/reads/play_figures.py`
- Modify: `tests/test_play_figures.py`

**Interfaces:**
- Produces: `PlayDay(day: date, game: Game, from_record: bool)`. Every consumer
  of the third field is Task 5.

- [ ] **Step 1: write the failing tests**

```python
def test_a_record_earlier_than_every_session_answers_the_first_play(
    owned_library, games
):
    beta, alpha = games
    timed(tracked_run(owned_library, beta), date(2024, 6, 1), 10, 1)
    record_row([tracked_run(owned_library, alpha)], when="2024-01-02")

    earliest = first_play(owned_library, 2024)

    assert earliest == PlayDay(date(2024, 1, 2), alpha, True)


def test_a_record_later_than_every_session_answers_the_last_play(owned_library, games):
    beta, alpha = games
    timed(tracked_run(owned_library, beta), date(2024, 6, 1), 10, 1)
    record_row([tracked_run(owned_library, alpha)], when="2024-09-09")

    latest = last_play(owned_library, 2024)

    assert latest == PlayDay(date(2024, 9, 9), alpha, True)


def test_a_session_and_a_record_at_one_game_on_one_day_answer_the_session(
    owned_library, games
):
    beta, _alpha = games
    run = tracked_run(owned_library, beta)
    timed(run, date(2024, 3, 5), 10, 1)
    record_row([run], when="2024-03-05")

    earliest = first_play(owned_library, 2024)

    assert earliest == PlayDay(date(2024, 3, 5), beta, False)


def test_a_record_naming_no_single_day_answers_neither_end(owned_library, games):
    beta, _alpha = games
    record_row([tracked_run(owned_library, beta)], when="2024-03")

    assert first_play(owned_library, 2024) is None
    assert last_play(owned_library, 2024) is None


def test_a_record_and_a_session_on_one_day_answer_by_sort_name(owned_library, games):
    beta, alpha = games
    day = date(2024, 3, 5)
    timed(tracked_run(owned_library, alpha), day, 10, 1)
    record_row([tracked_run(owned_library, beta)], when="2024-03-05")

    assert first_play(owned_library, None) == PlayDay(day, beta, True)
    assert last_play(owned_library, None) == PlayDay(day, alpha, False)
```

- [ ] **Step 2: run them and watch them fail**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_play_figures.py -x"
```

- [ ] **Step 3: implement one ordered read a source, picked in Python**

Each leg answers its own end, then one comparison picks between them. Keep both
legs in one private function per direction so the tie-break is written once:

- the session leg reads `(effective_day, SORT_NAME, GAME_KEY)` with the game
  selected, `LIMIT 1`;
- the record leg reads `(when_lower, RECORD_SORT_NAME, RECORD_GAME_KEY)` over
  `_day_records`, where the two constants spell `player_game__game__sort_name`
  and `player_game__game_id`, `LIMIT 1`;
- the comparison key is `(day, game.sort_name, game.pk)`, ascending for the
  first play and descending for the last, and a tie on all three answers the
  session, which is the `from_record=False` row.

Reach the game through `player_game__game` for a record and through
`playthrough__player_game__game` for a session. Neither scope selects it:
the session leg keeps its `.select_related(GAME)`, and the record leg adds
`.select_related("player_game__game")`, so the pick reads no further query.
The Python comparison of `sort_name` and the SQL orders agree only because
the database collation is `C.UTF-8` (`docs/database.md`); say so in one
comment at the comparison.

- [ ] **Step 4: run the file and the stats page**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_play_figures.py tests/test_stats.py -x"
```

- [ ] **Step 5: measure the two reads before keeping the plan**

The budget cell `stats_superlatives` measured 20.4 ms against 20 ms once
before, and the remedy then was to stop sorting joined rows whole. This task
adds a joined sort key under an indexed leading column, so measure rather than
assume. `make bench` has no records workload until #1099, so use a scratch
script in the session scratchpad (not committed):

1. `make restore-dump` for a real library, or seed a scratch library with 5,000
   sessions and 600 records naming one day each;
2. `EXPLAIN (ANALYZE, BUFFERS)` each of the four reads;
3. confirm the session leg stops inside the first day's group, as an
   incremental sort over `playersession_day_order` should, rather than sorting
   every joined row.

Where the planner sorts whole, keep the fallback the spec names: read the
earliest or latest day off the index first, then order only the rows on that one
day by the game's two columns. Record the numbers in the commit message.

- [ ] **Step 6: commit**

```bash
git add -A && git commit -m "feat: answer the first and last play from both sources (#1126)"
```

---

### Task 5: The row links only where the link works

**Files:**
- Modify: `games/views/stats_content.py:219-243`
- Modify: `games/views/stats_data.py` (carry the two flags into `StatsData`)
- Modify: `tests/test_rendered_pages.py` or `tests/test_stats_content_links.py`

**Interfaces:**
- Consumes: `PlayDay.from_record` from Task 4.
- Produces: two `StatsData` keys, `first_play_from_record: bool` and
  `last_play_from_record: bool`, both always present. This task also lists them
  under `StatsSource.NOT_A_FIGURE`, because
  `test_every_stats_key_states_its_sources_once` compares the mapping with
  `StatsData` and goes red the moment a key exists without a source.

- [ ] **Step 1: write the failing test**

A library whose only play is a day-precision record renders the First play row
with the game's name and the date, and no link to that game's sessions. Assert
on the rendered HTML of the stats page: the game's detail link is present, the
session-list link for that game is not.

- [ ] **Step 2: run it and watch it fail**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_stats_content_links.py -x"
```

- [ ] **Step 3: carry the flag and omit the link**

`compute_stats` writes `first.from_record` and `last.from_record` into the two
new keys, `False` where the figure is absent. `_playtime_table`'s two rows build
the `Fragment` without `_session_link(...)` when the flag is set. Nothing else
in the row changes. Declare both keys on `StatsData` and list both under
`StatsSource.NOT_A_FIGURE`, or the classification walk goes red.

- [ ] **Step 4: run the rendered pages and the links**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_stats_content_links.py tests/test_rendered_pages.py tests/test_stats_links.py -x"
```

- [ ] **Step 5: commit**

```bash
git add -A && git commit -m "feat: drop the session link where a record answers the play (#1126)"
```

---

### Task 6: The classification states the charter for the day keys

**Files:**
- Modify: `games/views/stats_data.py:116-190`
- Modify: `tests/test_stats.py:220-262`

- [ ] **Step 1: state the reversal in the tests**

Two changes in `tests/test_stats.py`:

- `_session_figures` selects keys by source group, so moving six keys would
  drop them out of the comparison in silence. Give the helper the key names it
  compares, so the sessions-only set is stated rather than derived.
- Keep `test_a_contained_record_moves_only_the_playtime_figures` as it is: its
  record is `when="2022-06"`, month precision, which moves no day figure. Add a
  case beside it for a day-precision record, asserting the day count, the
  percent, and the first and last play all move, and that the session count,
  the longest session, the two highest-session keys, `total_games` and
  `total_year_games` do not (member 2 moves those two).

- [ ] **Step 2: run and watch it fail**

Keep one derived assertion so the step is red: `STATS_SOURCES["unique_days"]
is StatsSource.BOTH`, and the same for the five siblings. Without it nothing
fails here, because Tasks 3 and 4 already made the readers count records.

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_stats.py -x"
```

- [ ] **Step 3: move the six keys**

`unique_days`, `unique_days_percent`, `first_play_game`, `first_play_date`,
`last_play_game`, `last_play_date` move from `SESSIONS_NO_SITTINGS` to `BOTH`.
Task 5's two flag keys join `NOT_A_FIGURE`. Then:

- `StatsSource.BOTH`'s member comment states both record rules: a playtime
  figure counts a record wholly inside the scope, a day figure counts only a
  record naming one day. Member 2 adds the third.

- [ ] **Step 4: run the stats tests and the classification walk**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_stats.py tests/test_stats_links.py -x"
```

- [ ] **Step 5: commit**

```bash
git add -A && git commit -m "feat: classify the day figures as both sources (#1126)"
```

- [ ] **Step 6: open the stack**

```bash
gh stack init
```

Member 1 ends here. Every task below is member 2: `gh stack add` before Task 7's
first commit.

---

### Task 7: `games_in_scope` and the purchase count take a records leg

**Files:**
- Modify: `games/reads/session_figures.py` (`games_in_scope`)
- Modify: `games/views/stats_data.py:343-350` (`played_purchases`)
- Test: `tests/test_session_figures.py`, `tests/test_stats.py`

**Interfaces:**
- Consumes: `library_records`, `contained_in`, `year_days` (Task 3).
- Produces: `records_in_scope(library, year) -> HistoricalPlaytimeQuerySet`
  in `session_figures.py` (live records, contained in the year; all-time takes
  every one); `games_in_scope` unchanged in signature; `played_purchases(library_purchases, sessions, records, year)`
  as a small function in `stats_data.py` so the count states its predicate
  once.

- [ ] **Step 1: write the failing tests**

```python
def test_a_game_only_a_contained_record_reaches_is_in_scope(owned_library, games):
    beta, _alpha = games
    record_row([tracked_run(owned_library, beta)], when="2024-03")

    assert list(games_in_scope(owned_library, 2024)) == [beta]
    assert list(games_in_scope(owned_library, None)) == [beta]


def test_a_record_wider_than_the_year_enters_all_time_alone(owned_library, games):
    beta, _alpha = games
    record_row([tracked_run(owned_library, beta)], when="2023/2024")

    assert list(games_in_scope(owned_library, 2024)) == []
    assert list(games_in_scope(owned_library, None)) == [beta]
```

In `tests/test_stats.py`, the month-precision case
`test_a_contained_record_moves_only_the_playtime_figures` now expects
`total_games` and `total_year_games` to rise by one in 2022 and all-time (the
recorded game holds a purchase there; add one to the fixture), and every
other sessions-only key unchanged.

- [ ] **Step 2: run and watch them fail**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_session_figures.py tests/test_stats.py -x -k 'record'"
```

- [ ] **Step 3: state the two legs as one `Q`**

```python
def records_in_scope(
    library: UserLibrary, year: YearScope
) -> HistoricalPlaytimeQuerySet:
    """Live records wholly inside the year; None is all-time."""
    records = library_records(library)
    days = year_days(year)
    return records if days is None else contained_in(records, days)


def games_in_scope(library: UserLibrary, year: YearScope):
    """Played: a session in scope, or a record contained in it."""
    return Game.objects.filter(
        Q(**{f"{GAME_SESSIONS}__in": scoped_sessions(library, year)})
        | Q(player_games__historical_playtime__in=records_in_scope(library, year))
    ).distinct()
```

`played_purchases` states the same two through `games__`, and the per-year
`games__year_released` filter stays as it is.

- [ ] **Step 4: run the two files, commit**

```bash
git add -A && git commit -m "feat: a contained record makes a played game (#1126)"
```

---

### Task 8: `Modifier.WITHIN`

**Files:**
- Modify: `common/criteria.py` (`Modifier`, `_SUFFIX_MODIFIER`,
  `DateCriterion.to_q`, `temporal_interval_handler`, `FilterField`,
  `_modifiers_for_field`, the `FieldMeta` builder)
- Modify: `games/filters.py` (the three temporal `FilterField`s: Playthrough
  `started`, `completed`, HistoricalPlaytime `when` set `interval=True`)
- Test: `tests/test_filters.py`, `tests/test_filter_paths.py`,
  `tests/test_playthrough_filter.py`

**Interfaces:**
- Produces: `Modifier.WITHIN = "WITHIN"`; suffix `within`;
  `FilterField(interval: bool = False)`; `_modifiers_for_field(kind, nullable, interval)`
  appends `WITHIN` after `NOT_BETWEEN` for a date field with `interval`.

- [ ] **Step 1: write the failing tests**

- `DateCriterion(value="2024-01-01", value2="2024-12-31", modifier=WITHIN).to_q("day")`
  equals the `BETWEEN` `Q`.
- On `HistoricalPlaytimeFilter.where(when__within=("2024-01-01", "2024-12-31"))`:
  a record `2024-03` matches, `2023-12/2024-01` does not, `2024` matches,
  `../2024-06` does not, `None` does not; `when__between` over the same bounds
  matches the overlapping one.
- `field_metadata(HistoricalPlaytimeFilter)`'s `when` lists `WITHIN`;
  `PurchaseFilter`'s `date_purchased` does not.
- A missing `value2` raises `FilterError` naming `WITHIN`.

- [ ] **Step 2: run and watch them fail**

- [ ] **Step 3: implement**

`temporal_interval_handler`: beside the `BETWEEN` branch,

```python
if modifier == Modifier.WITHIN:
    low, high = min(value, value2), max(value, value2)
    return (
        stated & Q(**{f"{lower_field}__gte": low}) & Q(**{f"{upper_field}__lte": high})
    )
```

`DateCriterion.to_q` treats `WITHIN` as `BETWEEN`. `for_dates()` does not
list it; `_modifiers_for_field` appends it when `interval` is set, and the
`FieldMeta` builder passes the flag through. `where()` learns `within` through
`_SUFFIX_MODIFIER`, consuming a 2-tuple like `between`.

- [ ] **Step 4: run the three test files, commit**

```bash
git add -A && git commit -m "feat: a wholly-within modifier for interval-valued dates (#1126)"
```

---

### Task 9: `WITHIN` on the client

**Files:**
- Modify: `ts/elements/filter-tree/summary.ts` (`MODIFIER_PHRASES`:
  `WITHIN: "is wholly within"`)
- Modify: `ts/elements/filter-tokens.ts` (`RANGE_MODIFIERS` gains `WITHIN`)
- Modify: `ts/elements/filter-widgets.ts` (`writeDateWidget`: `case "WITHIN"`
  beside `BETWEEN`; the reader that serialises a date range keeps emitting
  `BETWEEN` from the widget, since the widget cannot choose; the modifier
  dropdown is where a person picks `WITHIN`)
- Test: `ts/elements/filter-tree/summary.test.ts`,
  `ts/elements/filter-tokens.test.ts`; the two contracts
  `tests/test_summary_modifier_contract.py`, `tests/test_filter_tokens_contract.py`

- [ ] **Step 1: write the failing vitest cases** (a `WITHIN` phrase; `isRangeModifier("WITHIN")`)
- [ ] **Step 2: `make test-ts`**, watch them fail
- [ ] **Step 3: implement, `make test-ts`**, then the two contracts:

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_summary_modifier_contract.py tests/test_filter_tokens_contract.py tests/test_filter_tree_contract.py -x"
```

- [ ] **Step 4: `make ts-check`, commit**

```bash
git add -A && git commit -m "feat: the client phrases and writes WITHIN (#1126)"
```

---

### Task 10: `GameFilter.historical_playtime_filter`

**Files:**
- Modify: `games/filters.py:136-139,208-215` (the field and its `relation_to_q`
  through `HistoricalPlaytime`, `related_lookup="player_game__game__id"`)
- Test: `tests/test_filters.py`, `tests/test_filter_paths.py`,
  `tests/test_filter_cross_entity.py`

- [ ] **Step 1: write the failing tests**

- `GameFilter.from_json({"historical_playtime_filter": {"provenance": {...}}})`
  parses and selects the games whose records match; `match: "none"` selects
  the others.
- `resolve_path_kind(GameFilter, ["historical_playtime_filter", "when"]) == "date"`.
- A blob nesting `game_filter` and `historical_playtime_filter` past
  `MAX_FILTER_DEPTH` raises `FilterError`.
- `model_field_registry("game")` reaches `historicalplaytime`.

- [ ] **Step 2: run, watch them fail; implement; run**

The field metadata derives the relation from the annotation, so no builder
template is written. Run `make gen-element-types` and `make ts-check` in case
a generated prop lists relations.

- [ ] **Step 3: commit**

```bash
git add -A && git commit -m "feat: a game filter reaches its historical playtime records (#1126)"
```

---

### Task 11: The two links state the figure's predicate

**Files:**
- Modify: `games/views/stats_links.py` (`games_played`, `games_in_month`, a
  `_records_within(year)` / month helper beside `_session_bounds`)
- Modify: `tests/test_stats_links.py` (`world` fixture; parity cases)
- Modify: `games/views/stats_data.py` (the classification: `total_games`,
  `total_year_games` to `BOTH`; `SESSIONS_PLAYED_GAMES` removed; `BOTH`'s
  comment states the third rule; the `StatsSource` docstring)
- Test: `tests/test_stats.py` (`_session_figures` names its keys; the walk)

- [ ] **Step 1: seed the divergence**

In `world`: a fourth tracked game `Recorded` with one record `when=f"{YEAR}-05"`
and no session, and a fifth `Recorded elsewhere` with a record
`when=f"{YEAR - 1}-05"`. `test_games_played_matches_total_games` and
`test_games_in_month_matches_that_month` now fail, because the figure counts
`Recorded` and the link does not.

- [ ] **Step 2: state the links**

```python
def games_played(year) -> GameFilter:
    """Games with a session in scope or a record within it (matches `total_games`)."""
    return GameFilter(
        OR=[
            GameFilter(session_filter=all_sessions(year)),
            GameFilter(historical_playtime_filter=all_records(year)),
        ]
    )


def all_records(year) -> HistoricalPlaytimeFilter:
    return HistoricalPlaytimeFilter.where(**_record_bounds(year))


def _record_bounds(year) -> dict:
    if not _is_year(year):
        return {}
    return {"when__within": _year_range(year)}
```

`games_in_month` takes the same `OR` with the month's two bounds. Confirm
`GameFilter(OR=[...])` with an empty top level compiles to the disjunction
alone (read `OperatorFilter.to_q`).

- [ ] **Step 3: move the two keys and remove the empty group**

`total_games`, `total_year_games` join `BOTH`; `StatsSource.SESSIONS_PLAYED_GAMES`
is removed with its docstring line; `BOTH`'s comment states all three record
rules; the class docstring's claim about a count of games now holds.
`_session_figures` in `tests/test_stats.py` names its keys.

- [ ] **Step 4: run parity, stats and filters**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_stats_links.py tests/test_stats.py tests/test_filters.py -x"
```

- [ ] **Step 5: commit**

```bash
git add -A && git commit -m "feat: the played-game links count a contained record (#1126)"
```

---

### Task 12: The documents and the sibling issues

**Files:**
- Modify: `docs/superpowers/specs/2026-09-17-issue-709-historical-playtime-reads-design.md:61-77`
- Modify: `docs/superpowers/specs/2026-09-17-historical-playtime-wave-design.md:210-221`
- Modify: `docs/superpowers/specs/2026-09-15-issue-704-session-gates-design.md:32`
- Modify: `CLAUDE.md:403-412`

- [ ] **Step 1: amend #709's Classification section**

The day figures read both sources at day precision; the two played-game
counts read a record by containment; the link machinery they needed is named.

- [ ] **Step 2: amend the wave document's classification table**

Split the "never" row: the session count, the longest session and the two
highest-session keys keep it; the unique days and the first and last play take
"only a record naming one day". Add the rows the table never had —
`unique_days_percent` (derived), `total_games` and `total_year_games` (yes, by
containment).

- [ ] **Step 3: follow the readers in `CLAUDE.md` and #704's specification**

`CLAUDE.md:403-412` and #704's line 32 both name `session_figures.py` as the
home of the distinct days and the first and last play. Both name
`play_figures.py` for those three, and `CLAUDE.md` states the module's rule in
one clause: a record counts on its day when it names exactly one.

- [ ] **Step 4: `make vale`**

```bash
make vale
```

Expected: no findings.

- [ ] **Step 5: commit**

```bash
git add -A && git commit -m "docs: state the day figures' record leg (#1126)"
```

- [ ] **Step 6: state the cut on the three issues**

With `gh issue comment`:

- **#1105** — its scope loses the `GameFilter` records relation, the
  containment modifier and the `games_played`/`games_in_month` links, which
  landed here; it keeps the top-10 and platform row links, the narrowed
  Playtime column and the navbar.
- **#1099** — the two `NOT_A_FIGURE` flags need their rule: a flag flips only
  where the row that answered was converted.

---

### Task 13: The gate

- [ ] **Step 1: rebase onto `origin/main`**

```bash
git fetch origin && git rebase origin/main
```

- [ ] **Step 2: `make check-fast`**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check-fast
```

- [ ] **Step 3: the full gate, on the user's word**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check 2>&1 | tee /tmp/check.log; echo "exit=$?"
```

Read the exit code, never a grep of the output. Then `gh stack submit`, and
merge with `gh stack merge` when the user says merge.
