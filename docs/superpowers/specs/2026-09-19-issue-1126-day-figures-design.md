# Records in the day figures and the played-game counts

Issue: [#1126](https://github.com/KucharczykL/timetracker/issues/1126). Part
of the
[Historical Playtime wave](2026-09-17-historical-playtime-wave-design.md).

## Rule

The [charter](2026-08-09-timetracker-overhaul-design.md)'s contribution table
governs. A record counts in the days played and in the first and last play
when it names one day. A record counts a game as played when it lies wholly
inside the scope. A record never counts in the session count, the longest
session or the averages.

Six keys read both sources: `unique_days`, `unique_days_percent`,
`first_play_*`, `last_play_*`, `total_games`, `total_year_games`. Four keys
read sessions only: `total_sessions`, `longest_session_*`,
`highest_session_count*`, `highest_session_average*`.

## Day figures

`games/reads/play_figures.py` holds `distinct_days`, `first_play`,
`last_play` and `PlayDay`. A record names one day when
`when_lower == when_upper`. A day, a qualified day and a same-day range name
one day. A month, a year, a decade, a wider range, an open range and an
unknown `when` name no day. This is narrower than one day-precise endpoint of
a wider range; the table has no precision column, and #1106 widens the rule
when it adds one.

The day count is one `UNION` of both sources' distinct days. The first and
last play read one row from each source and pick in Python. The order is day,
then `sort_name`, then game key, and no row key. A conversion of a session
into a record on the same day at the same game moves no answer. On a tie at
all three levels the session answers. `PlayDay.from_record` says a record
answered; the stats row then prints no session link. The Python comparison
of `sort_name` agrees with the SQL order because the database collates in
`C.UTF-8`.

Both reads keep the leading column's index. Measured over 5,000 sessions and
600 records, one end costs under 2 ms and the day count under 4 ms.

## Played-game counts

`games_in_scope` and the purchase count take a session in scope or a record
contained in it. `total_year_games` keeps its shape: a purchase count,
narrowed per year to purchases holding a game released that year.

The `games_played` and `games_in_month` links state the same predicate, so
the parity test holds them equal to their figures. Two additions make that
possible:

- `GameFilter.historical_playtime_filter` reaches a game's records through
  `player_game__game__id`.
- `Modifier.WITHIN`, "is wholly within": both bounds of the interval lie
  inside the two given bounds. On a scalar date it compiles as `BETWEEN`.
  Only a field with `FilterField(interval=True)` offers it. `BETWEEN` on an
  interval field stays overlap.

The parity fixture holds a game only a record reaches, so a divergence fails
the test.

## Out

The top-10, platform and navbar links and the narrowed Playtime column:
#1105. A record's session count and a day-precise endpoint of a wider range:
#1106.
