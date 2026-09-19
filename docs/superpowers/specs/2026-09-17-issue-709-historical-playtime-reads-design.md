# Read historical playtime beside sessions

Issue: [#709](https://github.com/KucharczykL/timetracker/issues/709).
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md).
Coordination: [the parallel review](../../review/2026-09-17-historical-playtime-parallel-specs.md).

## Rule

A playtime figure is the sum of two sources: sessions and historical
playtime records. A record counts in a period only when its `when` lies
wholly inside the period: `when_lower` and `when_upper` are both inside.
A null bound is never inside. Thus these count in all-time only:

- an unknown `when`;
- a range with an open or unknown end;
- a range or a decade wider than the period.

A qualifier does not move a bound. `DayInterval` in `games/reads/days.py`
states every period, for both sources.

## Modules

- `games/reads/historical_playtime_records.py` holds the record scope.
- `games/reads/historical_playtime.py` holds the record sums, for
  `games/reads` only.
- `games/reads/playtime.py` composes the two sources.
- `games/reads/sums.py` holds what both sum modules share.

Both scopes refuse a missing library with `UnscopedRead`.

## Figures

A figure computed in Python returns `PlaytimeBreakdown(tracked,
historical)`, and `total` is their sum. The platform rows and the month rows
merge one query per source. Platform rows merge on the platform id and sort
as PostgreSQL did: total descending, then name, then id, with `None` last.

The note the Add Playthrough page fills in reads sessions only, through
`game_tracked_between`, because a record is not a sitting.

## Expressions

A queryset sorts and filters on one number:

| expression | value | no playtime |
|---|---|---|
| `playtime_by_game` | `Coalesce(s, 0) + Coalesce(r, 0)` | zero |
| `playtime_sort_key` | the same, `NullIf` zero | NULL |
| `playtime_matching` | matching sessions only | NULL |

The sort key is NULL for a game whose only playtime is a running session.
Telling the two apart runs each subquery twice.

Django compiles an annotation again wherever `F()` names it. Thus a page
annotates a half beside a total only where it renders the half.

Without a session filter, the game list's sort reuses the column's
subqueries. Under a session filter, the column header reads "Playtime (matching
sessions)", because a session filter cannot narrow records.

## Classification

`STATS_SOURCE_GROUPS` in `games/views/stats_data.py` lists each `StatsData`
key under one `StatsSource`. A test compares the keys with `StatsData`.

- **Both sources:** `total_hours`, the top 10, the platform rows, the month
  rows, the played-game counts, and -- since #1126 -- the unique days and
  the first and last play. A playtime figure and a played-game count take a
  record wholly inside the scope; a day figure takes only a record naming
  one day. Records reach a platform through the game's platform column until
  #889.
- **Sessions only, a record states no sittings:** the session count, the
  longest session, the highest count and the highest average.
- **Purchases**, and **not a figure**, for the rest.

As first delivered, this section put the unique days, the first and last play
and the two played-game counts under sessions only, against the charter's
contribution table, and recorded no deviation. #1126 restored the table's
answer, and gave the `games_played` and `games_in_month` links the records
relation and the containment word they needed to stay equal to their figures.

Game detail's hours read both sources. Its other figures read sessions.

## Known gap

These links open lists that show sessions only:

- the per-year "View all" link and the month links;
- the top-10 row links;
- the platform row links;
- the navbar links.

#1105 repairs the stats links. #710 decides the navbar's link target.
#1106 adds a stated session count to a record.
