# Read historical playtime beside sessions

Issue: [#709](https://github.com/KucharczykL/timetracker/issues/709).
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md).
Aggregate: [#705](2026-09-17-issue-705-historical-playtime-aggregate-design.md).
Coordination: [the parallel review](../../review/2026-09-17-historical-playtime-parallel-specs.md).

## Purpose

Every playtime figure is the sum of two sources: the sessions a library
records and the historical playtime records it states. Every statistic
states which sources it takes. Presentation of the split is #710's.

## Rule

A record counts in a period when its `when` lies wholly inside the period:
`when_lower` and `when_upper` are both inside. This is containment. A null
bound is never inside, so these count in all-time only:

- `unknown`;
- a range with an open or unknown end, such as `../2021-09-27` or `2020/`;
- a range or a decade wider than the period, such as `2020/2022` in 2022.

A qualifier (`2022~`, `2022?`) does not move a bound, so `2022~` counts in
2022. A period is always a `DayInterval`: a year is 1 January to
31 December, a month is its first to its last day, and the navbar's windows
are days. Every narrowed read uses one containment filter.

`DayInterval` moves from `playtime.py` to a new leaf module,
`games/reads/days.py`, because both read modules take it and `playtime.py`
imports the records module. Its importers (`games/views/general.py`,
`games/views/playthrough.py`, `tests/test_playtime_sources.py`) import it
from there. `playtime.py` does not re-export it.

## The records modules

Two modules, as for sessions: `player_sessions.py` holds the scope and
`playtime.py` the sums.

| module | owner | contents |
|---|---|---|
| `games/reads/historical_playtime_records.py` | shared with #706 and #1097 | `library_records`, `readable_records`, `game_records`, `RECORD_ORDER` |
| `games/reads/historical_playtime.py` | this issue | the record sums |

### Scope

The shared module is this text, fixed by the parallel review (D1, D2). The
first of the three branches to merge adds it. The others take `main`'s copy
on rebase and add nothing to it.

```python
"""The records a library counts, and the row path a page reads."""

from django.db.models import F

from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeQuerySet,
    UserLibrary,
)

#: Newest first; an unknown `when` last; then newest recorded.
RECORD_ORDER = (F("when_lower").desc(nulls_last=True), "-created_at", "id")


def library_records(library: UserLibrary) -> HistoricalPlaytimeQuerySet:
    """Every live record this library counts.

    A copy of this breaks quietly. The record's and its tracked
    game's libraries are both stated: either can name another
    library's row. `alive()` alone keeps the records of a removed
    catalog game.
    """
    return HistoricalPlaytime.objects.filter(
        library=library,
        player_game__library=library,
        removed_at__isnull=True,
        player_game__removed_at__isnull=True,
        player_game__game__removed_at__isnull=True,
    )


def readable_records(library: UserLibrary) -> HistoricalPlaytimeQuerySet:
    """The row path the list, the section and the API share."""
    return library_records(library).select_related(
        "player_game__game__platform", "device"
    )


def game_records(library: UserLibrary, game: Game) -> HistoricalPlaytimeQuerySet:
    """The counted records at one catalog game."""
    return library_records(library).filter(player_game__game=game)
```

The run join is not in the scope. `RemovePlaythrough` refuses a run that a
live record names, so a live record never names a removed run.

### Sums

`games/reads/historical_playtime.py` imports `library_records` and
`game_records`. Each function reads records only. A scalar returns zero,
never NULL.

- `contained_in(records, days)`: the containment filter.
- `historical_total(library, *, within=None) -> timedelta`.
- `historical_totals(library, windows) -> list[timedelta]`: one aggregate
  with one filtered sum per window, in the order given.
- `historical_summed_by_game(library, *, within=None)`: a correlated
  subquery on `OuterRef("pk")` of a `Game`, NULL when the game has no
  record in scope.
- `historical_by_platform(library, *, within=None)`: grouped on
  `player_game__game__platform`.
- `historical_by_month(library, *, year)`: a record counts in a month only
  when both bounds lie in that month.
- `historical_years(library) -> list[int]`: every year that wholly
  contains some record's `when`.
- `game_historical_playtime(library, game, provenance=None) -> timedelta`:
  the importer's remainder read (#798).

A record reaches the per-platform figure through its game's platform
column, as a session does. The charter admits a record only through a
Release or a Device. This deviation lasts until #889 moves both sources to
Release.

## The composed module

`games/reads/playtime.py` stops meaning "sessions". It imports the records
sums and composes them. No reader outside `games/reads` imports the records
sums: a new figure is a function in `playtime.py`, as before.

The session-only halves are renamed so that their names say "sessions":
`summed_by_game` becomes `tracked_summed_by_game`, and
`summed_by_game_matching` becomes `tracked_summed_by_game_matching`. Their
only callers are `playtime.py` and `tests/test_playtime_sources.py`.

### The breakdown

```python
@dataclass(frozen=True, slots=True)
class PlaytimeBreakdown:
    tracked: timedelta
    historical: timedelta

    @property
    def total(self) -> timedelta:
        return self.tracked + self.historical
```

Every figure computed in Python returns one:

| function | tracked | historical |
|---|---|---|
| `total_playtime(library, *, year)` | sessions in the year | records contained in the year |
| `game_playtime(library, game)` | the game's sessions | the game's records |
| `playtime_between(library, days)` | sessions on those days | records contained in the days |
| `playtime_between_each(library, windows)` | likewise, one per window | likewise |
| `game_playtime_between(library, game, days)` | likewise, one game | likewise, one game |
| `PlatformPlaytime.playtime` | per platform | per platform, through the game |
| `MonthPlaytime.playtime` | per month | records contained in the month |

`playtime_between_each` runs one aggregate per source, with one filtered
sum per window. The navbar calls it with today and the last seven days, so
it runs two queries, as it does today.

The platform and month readers run one grouped query per source and merge
the two in Python. A platform or a month that only records reach gets a
row. The merged platform rows sort by this key, which reproduces the
database order the reader states today under the `C.UTF-8` collation:

1. total, descending;
2. platform name, ascending, where the unspecified bucket's `None` sorts
   last;
3. platform id, ascending, where `None` sorts last.

`played_years` returns the union of the years with sessions and
`historical_years`, in ascending order.

`playtime_by_day` and `DayPlaytime` are deleted, because nothing calls
them. `common/time.py`'s `streak` and `streak_bruteforce` are deleted with
`tests/test_streak.py`, for the same reason. The stats page has no streak
and no day chart.

### The expressions

A queryset sorts and filters on one number, so the expressions do not
split. Here `s` is the tracked subquery and `r` is the historical subquery.

| expression | value | no playtime |
|---|---|---|
| `playtime_by_game(library, *, year)` | `Coalesce(s, 0) + Coalesce(r, 0)` | zero |
| `playtime_sort_key(library)` | `NullIf(Coalesce(s, 0) + Coalesce(r, 0), 0)` | NULL |
| `playtime_matching(library, filter)` | `s` narrowed by the filter | NULL |
| `playtime_parts_by_game(library, *, year)` | `PlaytimeParts(tracked, historical, total)` | zero each |

`PlaytimeParts` is a `NamedTuple` of three expressions. The first two are
`Coalesce(s, 0)` and `Coalesce(r, 0)`, and the third is their sum. The stats
page's top 10 annotates all three, so `stats_data.py` imports nothing from
the records module.

The sort key is NULL when the game has no playtime. A game whose only
session is running has zero playtime, so it sorts with the unplayed games,
last in both directions, until the session ends. The column prints 0 for it
either way. This rule keeps two subqueries per row. Each form that
distinguishes "no rows" from "zero" repeats a subquery, and PostgreSQL runs
a repeated subquery again: `Coalesce(s + r, s, r)` runs four per row. The
20 ms read budget is the reason for the rule.

With no library, both halves compile as `UnscopedSum` and refuse to execute.

`GameQuerySet.annotated_for_filtering` keeps its `playtime` alias through
`playtime_by_game`, so the `playtime_hours` filter reads the composed total.
`session_playtime_hours` names sessions and stays sessions-only.

## The game list

`games_for_list` aliases `total_playtime` to the sort key. The
`filtered_playtime` column then reads:

- `F("total_playtime")` with no session filter, which is the composed total
  with no second pair of subqueries;
- `playtime_matching(library, session_filter)` under a session filter,
  which is the matching sessions alone, because a session filter cannot
  narrow records. The column header then reads "Playtime (matching
  sessions)".

Under a session filter, `?sort=playtime` still orders by the composed total
while the column shows the matching sessions. Only a URL written by hand
reaches this, because the header sorts by `filtered_playtime`.

## Classification

The table is in `stats_data.py`, stated once, next to `StatsData`, as a
mapping from each key to its class. A test compares the mapping's keys
with every `StatsData` key, required and not required, and fails on any
difference.

| class | `StatsData` keys |
|---|---|
| both sources, contained in the scope | `total_hours`, `top_10_games_by_playtime`, `total_playtime_per_platform` (through the game's platform), `month_playtimes` (contained in the month) |
| sessions only: a record states no sittings | `total_sessions`, `unique_days`, `unique_days_percent`, `longest_session_time`, `longest_session_game`, `highest_session_count`, `highest_session_count_game`, `highest_session_average`, `highest_session_average_game`, `first_play_game`, `first_play_date`, `last_play_game`, `last_play_date` |
| sessions only: a record states hours, not a year of play | `total_games`, `total_year_games` |
| neither: purchases | `this_year_finished_this_year_count`, `total_spent`, `total_spent_currency`, `spent_per_game`, `all_purchased_this_year_count`, `all_purchased_refunded_this_year`, `all_purchased_refunded_this_year_count`, `refunded_percent`, `dropped_count`, `dropped_percentage`, `purchased_unfinished_count`, `unfinished_purchases_percent`, `backlog_decrease_count`, `all_finished_this_year`, `all_finished_this_year_count`, `this_year_finished_this_year`, `purchased_this_year_finished_this_year`, `purchased_unfinished`, `all_purchased_this_year` |
| not a figure | `year`, `title`, `stats_dropdown_year_range` |

`total_hours` becomes a `PlaytimeBreakdown`. `GamePlaytime`, the annotation
type of the top 10, gains `tracked_playtime` and `historical_playtime`. The
top 10 keeps the rows whose total is above zero and orders by total, then
sort name, name and key.

Game detail's header has its own figures:

| figure | sources |
|---|---|
| hours played | both, through `game_playtime` |
| session count, average session, play range (`_game_overview_metrics`) | sessions only |

The wave document's Classification table names streaks and the day chart.
This issue's PR removes them from that row and adds one sentence: "Streaks
and the day chart had no caller, and #709 removed the read."

Every page renders `.total`. No page changes while no record exists.

### Known gap

These links reach a list that shows sessions only:

- per year, the "View all" link under Games by playtime, and each month
  row, reach the game list through a session filter. A game whose only
  2022 playtime is a record is in the 2022 top 10 but not in the list
  behind the link, and the list's column shows sessions only. The all-time
  link has no filter and shows the composed total;
- each top-10 row links to that game's sessions;
- each platform row links to that platform's sessions, so a platform that
  only records reach links to an empty list;
- the two navbar figures link to the session list.

#1105 repairs the first three. #710 decides the navbar's link target. The
comment in `model_counts` that says the navbar total matches its link's list
is corrected to say that the link lists the tracked part.

## Callers

These change with the return types:

- `games/views/stats_data.py`: `StatsData.total_hours`, `GamePlaytime`,
  and the top 10's annotations;
- `games/views/stats_content.py`: renders `.total` for the totals, the
  platform rows and the month rows;
- `games/views/game.py`: the Game detail header reads
  `game_playtime(...).total`, and `games_for_list` as above;
- `games/views/general.py`: the navbar calls `playtime_between_each` and
  reads `.total`;
- `games/views/playthrough.py`: the note reads
  `game_playtime_between(...).tracked`. The note seeds a run's text from the
  sessions after its last finish, and its window comes from session days.
  A record is not a sitting. This is the one day-window read that leaves
  records out;
- `games/events/benchmark_reads.py`: calls the same functions, so the bench
  times the composed plan;
- tests that compare a plain `timedelta` and move to `.total`:
  - `tests/test_removal.py:62,66`;
  - `tests/test_rendered_pages.py:396`;
  - `tests/test_api.py:501,512`;
  - `tests/test_retention.py:261,315`;
  - `tests/test_library_reconciliation.py:308`;
  - `tests/test_library_api_isolation.py:402`;
  - every scalar, `MonthPlaytime` and `PlatformPlaytime` assertion in
    `tests/test_playtime_sources.py`.

## Verification

- `tests/test_historical_playtime_reads.py`:
  - the scope refuses a foreign library on the record and on its
    `PlayerGame`, and each of the three marks;
  - containment for `2022`, `2022~`, `2022-06`, `2022-06-11`,
    `2020/2022`, `198X`, `../2021-09-27`, `2020/`, `2020/..` and `unknown`,
    in a year, a month, a day window and all-time;
  - `historical_totals` over two windows in one query;
  - the platform through the game, and `provenance=`.
- `tests/test_playtime_sources.py`, which exists, moves to the breakdown
  and gains:
  - each breakdown, and `playtime_between_each` in two queries;
  - the platform and month merge, including a row only records reach and
    the unspecified bucket's order;
  - the sort key's rule: NULL for no playtime and for a running session
    alone, both last in both directions;
  - `playtime_hours` over a composed total;
  - `playtime_matching` under a filter ignoring records;
  - an unscoped read still refusing.
- `tests/test_stats.py`:
  - a record moves the four "both" figures in its year and nothing in any
    other class;
  - the classification's keys equal the `StatsData` keys.
- Game list: a record moves the sort and the filter; the column under no
  filter equals the sort key; the header names matching sessions under a
  session filter; the query runs two playtime subqueries per row with no
  filter.
- Playthrough note: a contained record does not move it.
- Parity on a production dump with no records:
  - `make restore-dump`, then `make migrate` when the dump predates #705;
  - `make render-pages` at `main` and at the branch, `diff -r` empty;
  - `make bench ARGS="--library <id> --gate"` inside the 20 ms budget.

  The dump holds no records, so the bench proves the session half and the
  plan shape, not the cost at record scale. That budget is #1099's.
  `render_pages` renders each list only with its default sort, so the
  `playtime` sort and a session-filtered header are proved by the tests
  above, not by the diff.
- Full `make check`.

## Parallel work

#706 and #1097 run beside this issue. The parallel review is the only
agreement between the three branches. This issue's comment links it.

- **Shared module.** See Scope above.
- **`CLAUDE.md`.** In the HistoricalPlaytime entry, this branch replaces
  "Nothing reads or writes it from a page yet." with one sentence of its
  own. If a sibling merges first, this branch keeps `main`'s sentence and
  appends its own. Nothing else in that entry changes. The Playtime reads
  paragraph is this issue's alone. It names both sources, the containment
  rule and the sort key's rule.
- **`games/views/game.py`.** This issue changes the header call and
  `games_for_list`. #706 adds a section nearby. The lines are adjacent and
  do not overlap.
- **The wave document.** This issue's PR carries its one-row amendment.

The issue merges alone, with no stack and no required order.

## Follow-up issues

1. #1105: a `GameFilter` relation to historical playtime records, with a
   containment modifier or a second `when` field. #1097's `when` filter
   reads overlap, as Playthrough's endpoints do, and this issue's sums read
   containment. With the relation, a stats link and its stat compile one
   predicate, and the links in Known gap find a game or a platform that
   only records reach. Placed after #1097.
2. #1106: a stated session count on a record: an optional `session_count`
   in the payload and the form. With it, `total_sessions` and
   `highest_session_count` sum the count, `highest_session_average` divides
   by sessions plus counts over records that state one, and `last_play_*`
   reads a day-precision `when_upper`. The worked example is a PS Tracker
   row: 87 hours, 28 sessions, last played 2021-09-27. Placed after the
   wave, as input to #798.
