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
states every period.

## Modules

- `games/reads/historical_playtime_records.py` holds the record scope. Its
  text is shared with #706 and #1097.
- `games/reads/historical_playtime.py` holds the record sums. Only
  `games/reads` imports it.
- `games/reads/playtime.py` composes the two sources.
- `games/reads/sums.py` holds what both sum modules share.

## Figures

A figure computed in Python returns `PlaytimeBreakdown(tracked,
historical)`, and `total` is their sum. The platform rows and the month rows
merge one query per source. The platform rows keep the database order:
total, then name, then id, with `None` last.

The playthrough note reads `tracked` only, because a record is not a
sitting. Every other caller reads `total`.

## Expressions

A queryset sorts and filters on one number:

| expression | value | no playtime |
|---|---|---|
| `playtime_by_game` | `Coalesce(s, 0) + Coalesce(r, 0)` | zero |
| `playtime_sort_key` | the same, `NullIf` zero | NULL |
| `playtime_matching` | matching sessions only | NULL |

The sort key is NULL for a game whose only session is running. Telling
the two apart runs each subquery twice.

`playtime_parts_by_game` gives the two halves for the stats top 10. It has
no total, because a total runs both subqueries again.

When no session filter is set, the game list annotates the sort key as the
column and aliases the sort to it. PostgreSQL then evaluates each subquery
once. Under a session filter, the column header reads "Playtime (matching
sessions)", because a session filter cannot narrow records.

## Classification

`STATS_SOURCES` in `games/views/stats_data.py` gives each `StatsData` key a
`StatsSource`. A test compares its keys with the `StatsData` keys.

- **Both sources:** `total_hours`, the top 10, the platform rows, the month
  rows. Records reach a platform through the game's platform column until
  #889.
- **Sessions only, a record states no sittings:** the session count, the
  unique days, the longest session, the highest count, the highest average,
  and the first and last play.
- **Sessions only, a record states no year of play:** `total_games` and
  `total_year_games`.
- **Purchases**, and **not a figure**, for the rest.

Game detail's hours read both sources. Its other figures read sessions.

## Known gap

These links open lists that show sessions only:

- the per-year "View all" link and the month links;
- the top-10 row links;
- the platform row links;
- the navbar links.

#1105 repairs the stats links. #710 decides the navbar's link target.
#1106 adds a stated session count to a record.
