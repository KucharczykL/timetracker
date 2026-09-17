# Read historical playtime beside sessions

Issue: [#709](https://github.com/KucharczykL/timetracker/issues/709).
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md).
Aggregate: [#705](2026-09-17-issue-705-historical-playtime-aggregate-design.md).

## Purpose

Every playtime figure is the sum of two sources: the sessions a library
records and the historical playtime records it states. Every statistic
states which sources it takes. Presentation of the split is #710's.

## Rule

A record counts in a period when its `when` lies wholly inside the period:
`when_lower` and `when_upper` are both inside. This is containment. A null
bound is never inside, so these count in all-time only:

- `unknown`;
- a range with an open end, such as `../2021-09-27` or `2020/`;
- a range or a decade wider than the period, such as `2020/2022` in 2022.

A qualifier (`2022~`, `2022?`) does not move a bound, so `2022~` counts in
2022. A period is always a `DayInterval`: a year is 1 January to
31 December, a month is its first to its last day, and the navbar's windows
are days. Every narrowed read uses one containment filter.

## The records module

`games/reads/historical_playtime.py` is the records twin of
`games/reads/player_sessions.py` and holds the record sums.

### Scope

The scope text is fixed. #706 and #1097 add the same two functions to the
same file, so the second branch to merge takes `main`'s copy on rebase.

```python
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


def game_records(library: UserLibrary, game: Game) -> HistoricalPlaytimeQuerySet:
    """The counted records at one catalog game."""
    return library_records(library).filter(player_game__game=game)
```

The run join is not in the scope. `RemovePlaythrough` refuses a run that a
live record names, so a live record never names a removed run.

### Sums

All of these read records only and return zero, not NULL, for a scalar:

- `contained_in(records, days)`: the containment filter;
- `historical_total(library, *, within=None) -> timedelta`;
- `historical_summed_by_game(library, *, within=None)`: a correlated
  subquery on `OuterRef("pk")` of a `Game`, NULL when the game has no
  record in scope;
- `historical_by_platform(library, *, within=None)`: grouped on
  `player_game__game__platform`;
- `historical_by_month(library, *, year)`: a record counts in a month only
  when both bounds lie in that month;
- `historical_years(library) -> list[int]`: every year that wholly contains
  some record's `when`;
- `game_historical_playtime(library, game, provenance=None) -> timedelta`:
  the importer's remainder read (#798).

A record reaches the per-platform figure through its game's platform
column, as a session does. The charter admits a record only through a
Release or a Device. This deviation lasts until #889 moves both sources to
Release.

## The composed module

`games/reads/playtime.py` stops meaning "sessions". It imports the records
module and composes.

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
| `game_playtime_between(library, game, days)` | likewise, one game | likewise, one game |
| `PlatformPlaytime.playtime` | per platform | per platform, through the game |
| `MonthPlaytime.playtime` | per month | records contained in the month |

The platform and month readers run one grouped query per source and merge
the two in Python. The platform rows keep today's order: total descending,
then platform name, then platform id. A platform or a month that only
records reach gets a row.

`played_years` returns the union of the years with sessions and
`historical_years`, in ascending order.

`playtime_by_day` never reads records. `summed_by_game` and
`summed_by_game_matching` stay sessions-only, because they are the tracked
half that the expressions below compose.

### The expressions

A queryset sorts and filters on one number, so the expressions do not
split:

| expression | value | unplayed game |
|---|---|---|
| `playtime_by_game(library, *, year)` | `Coalesce(s, 0) + Coalesce(r, 0)` | zero |
| `playtime_sort_key(library)` | `Coalesce(s + r, s, r)` | NULL |
| `playtime_matching(library, None)` | as `playtime_sort_key` | NULL |
| `playtime_matching(library, filter)` | `s` narrowed by the filter | NULL |

Here `s` is the session subquery and `r` is the record subquery. The sort
key is NULL only when both are NULL, so a game whose only session is
running still reads zero and sorts before unplayed games, as it does today.
With no library, both halves compile as `UnscopedSum` and refuse to execute.

`GameQuerySet.annotated_for_filtering` keeps its `playtime` alias through
`playtime_by_game`, so the `playtime_hours` filter reads the composed total.
`session_playtime_hours` names sessions and stays sessions-only.

## The game list

The Playtime column and its sort read `filtered_playtime`. With no session
filter it equals the composed total. With a `session_filter` it is the
matching sessions alone, because a session filter cannot narrow records,
and the column header reads "Playtime (matching sessions)".

## Classification

The table is in `stats_data.py`, stated once, next to `StatsData`. A test
reads every `StatsData` key and fails on a key the table does not classify.

| `StatsData` figure | sessions | records |
|---|---|---|
| `total_hours` | yes | yes, contained in the year; all in all-time |
| `top_10_games_by_playtime` | yes | yes, likewise |
| `total_playtime_per_platform` | yes | yes, through the game's platform |
| `month_playtimes` | yes | contained in the month |
| `total_sessions`, `unique_days`, `unique_days_percent`, `longest_session_*`, `highest_session_*`, `first_play_*`, `last_play_*` | yes | never: a record states no sittings |
| `total_games`, `total_year_games` | yes | never: a record states hours, not a year of play |
| purchase, spending, finished, dropped and backlog figures | no | no |

The streaks and the day chart read `playtime_by_day`, which never reads
records.

`total_hours` becomes a `PlaytimeBreakdown`. The top-10 queryset annotates
`tracked_playtime`, `historical_playtime` and `total_playtime`, where the
total is their sum. It still keeps rows with a total above zero and orders
by total, then sort name, name and key.

Every page renders `.total`. No page changes while no record exists.

### Known gap

The "View all" link under Games by playtime and each month row's link
reach the game list through a session filter. A game whose only 2022
playtime is a record appears in the 2022 top 10 but not in the list behind
the link. Under that filter, the list's column shows sessions only. The
repair is a `GameFilter` relation to records, which needs #1097's
`HistoricalPlaytimeFilter`. It is filed as a follow-up.

## Callers

- `stats_data.py` and `stats_content.py` render `.total` for the totals,
  the platform rows and the month rows;
- Game detail's header reads `game_playtime(...).total`;
- the navbar reads `playtime_between(...).total`;
- the playthrough note reads `game_playtime_between(...).total`;
- `benchmark_reads.py` calls the same functions, so the bench times the
  composed plan.

## Verification

- `tests/test_historical_playtime_reads.py`:
  - the scope refuses a foreign library on the record and on its
    `PlayerGame`, and each of the three marks;
  - containment for `2022`, `2022~`, `2022-06`, `2022-06-11`,
    `2020/2022`, `198X`, `../2021-09-27`, `2020/` and `unknown`, in a year,
    a month, a day window and all-time;
  - the platform through the game, and `provenance=`.
- `tests/test_playtime_sources.py`:
  - each breakdown;
  - the platform and month merge, including a row only records reach;
  - the sort key's NULL rule, including a running session;
  - `playtime_hours` over a composed total;
  - `playtime_matching` under a filter ignoring records;
  - an unscoped read still refusing.
- `tests/test_stats.py`:
  - a record moves the four "yes" figures in its year and none of the
    "never" figures;
  - the classification covers every key.
- Game list: a record moves the sort and the filter; the header names
  matching sessions under a session filter.
- Parity on a restored production dump with no records: `make render-pages`
  at `main` and at the branch, `diff -r` empty; `make bench ARGS="--library
  <id> --gate"` inside the 20 ms read budget with the second subquery.
- Full `make check`.

## Parallel work

#706 and #1097 run beside this issue. The scope functions above are posted
on both issues. Expected textual conflicts: `CLAUDE.md` and
`games/views/game.py`, where the Game detail header call sits next to
#706's new section. The issue merges alone, with no stack.

## Follow-up issues

1. A `GameFilter` relation to historical playtime records, so the stats
   links find a game that only records reach. Placed after #1097.
2. A stated session count on a record: an optional `session_count` in the
   payload and the form. With it, `total_sessions` and
   `highest_session_count` sum the count, `highest_session_average` divides
   by sessions plus counts over records that state one, and `last_play_*`
   reads a day-precision `when_upper`. The worked example is a PS Tracker
   row: 87 hours, 28 sessions, last played 2021-09-27. Placed after the
   wave, as input to #798.
