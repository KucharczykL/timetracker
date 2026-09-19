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

Six keys join the both-sources group: `unique_days`, `unique_days_percent`,
`first_play_*`, `last_play_*`, `total_games`, `total_year_games`. Sessions
alone answer `total_sessions`, `longest_session_*`, `highest_session_count*`
and `highest_session_average*`.

## Day figures

`games/reads/play_figures.py` holds `distinct_days`, `first_play`,
`last_play`, `games_in_scope` and `PlayDay`. The two record scopes,
`records_in_scope` and `one_day_records`, live in
`games/reads/historical_playtime_records.py`, two lines apart. A record
names one day when `when_lower == when_upper`. A day, a qualified day and a same-day range name
one day. A month, a year, a decade, a wider range, an open range and an
unknown `when` name no day. This is narrower than one day-precise endpoint of
a wider range; the table has no precision column, and #1106 widens the rule
when it adds one.

The day count is one `UNION` of both sources' distinct days. The first and
last play read one row from each source and pick in Python. The order is day,
then `sort_name`, then game key, and no row key. A conversion of a session
into a record on the same day at the same game moves no answer. On a tie at
all three levels the session answers. `PlayDay.source` says which source
answered; each is built by a classmethod off its row, so the source cannot
disagree with the columns. The stats row links that game's records in scope
where a record answered, and its sessions otherwise. The Python comparison
of `sort_name` agrees with the SQL order because the database collates in
`C.UTF-8`.

Both reads keep the leading column's index. Measured over 5,000 sessions and
600 records, one end costs under 2 ms and the day count under 4 ms.

## Played-game counts

`games_in_scope` and the purchase count take a session in scope or a record
contained in it, each leg an `id__in` subquery so no join multiplies rows.
`total_year_games` keeps its shape: a purchase count, narrowed per year to
purchases holding a game released that year.

The `games_played` and `games_in_month` links state the same predicate, so
the parity test holds them equal to their figures. Two additions make that
possible:

- `GameFilter.historical_playtime_filter` reaches a game's records through
  `player_game__game__id`.
- `Modifier.WITHIN`, "is wholly within": both bounds of the interval lie
  inside the two given bounds. On a scalar date it compiles as `BETWEEN`.
  Only a field whose handler reads two bound columns offers it; `FilterField`
  reads that off the handler. `BETWEEN` on an interval field stays overlap.
  The date widget carries the modifier in a hidden input, so a stated
  `WITHIN` survives Apply on the builder and the quick bar. A person cannot
  choose it there yet.

A stated empty relation serializes as `{}` and keeps its meaning, "has one",
so the all-time links keep both legs. The game list narrows its Playtime
column by both legs the link states, records summed by containment beside
the sessions. The parity fixture holds a game only a record reaches, so a
divergence fails the test.

## Out

The top-10, platform and navbar links: #1105. A record's session count and a day-precise endpoint of a wider range:
#1106.
