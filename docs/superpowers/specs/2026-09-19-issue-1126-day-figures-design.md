# Count a day-precision record in the day figures

Issue: [#1126](https://github.com/KucharczykL/timetracker/issues/1126). Parent
phase: #601. Ahead of
[#1099](https://github.com/KucharczykL/timetracker/issues/1099), whose parity
gate judges the classification this issue restores.

## Purpose

The [overhaul charter](2026-08-09-timetracker-overhaul-design.md)'s
contribution table gives Historical Playtime a day-precision leg in "Day
totals, unique days, streaks, first/last play" and no leg at all in the session
count, the averages and the longest session.
[#709](2026-09-17-issue-709-historical-playtime-reads-design.md) put the unique
days and the first and last play under "sessions only" and recorded no
deviation. This issue restores the charter's answer for those four keys.

Why it matters now: #1098's "Move all N to historical playtime" writes every
record at day precision. Converting a session dated D into a record dated D
must leave the days played and the first and last play exactly as they were,
and move only the session count, the longest session and the per-game
averages. #1099's parity gate proves that, so this lands first.

## The rule

A record counts on its day when it names exactly one:
`when_lower == when_upper`. For a single day, containment in a scope and "the
day lies in the scope" are the same predicate, so the day leg is
`contained_in(records, days)` narrowed to rows whose two bound columns agree.

Four shapes name one day and count: a day, a day the person marked approximate,
a day the person marked uncertain, and a range whose two endpoints are the same
day. A qualifier states how sure the person is, never which day. A month, a
year, a decade, a range wider than a day, an open range and an unknown `when`
name no single day and count in no day figure, exactly as they count in no month
total today. An open range carries one NULL bound, which the containment
predicate already excludes.

Both sources reach the day figures through the scopes the playtime sums
already use, `library_sessions` and `library_records`, so a figure and a total
never disagree about which rows exist. The two scopes read different marks: a
session's scope reads the run's, a record's does not, because a record names
its runs through a join. Nothing can drift, since a run holding a record is a
blocking referrer and a record under a removed run cannot be restored. These
figures are the first read to put both scopes in one number, which is why the
asymmetry is stated here.

`unique_days_percent` is derived from the day count and, all-time, from the
first and last play. It follows the two without a leg of its own.

## The two played-games keys are #1105's

`total_games` and `total_year_games` count a game with a session in scope. The
charter names no such row, and the same page already counts a game with a
per-Game total as played in `games_by_playtime_count`. Both keys mean "a game
this library played", so they move together or not at all.

`total_games` carries the one count link a parity test judges, `games_played`
in `games/views/stats_links.py`. Correcting the figure means that builder must
state the same predicate, which needs a `GameFilter` relation to records and a
containment word on the temporal criterion.
[#1105](https://github.com/KucharczykL/timetracker/issues/1105) already scopes
both, along with the month, top-10 and platform links, so it takes the two keys
with the link in one change and the link parity never holds a divergence.
`total_year_games` carries no link at all; it travels with `total_games`
because the page must not answer "games played" two ways.

The four keys here carry no count link, so they need none of that machinery.

## The module

`games/reads/play_figures.py` holds `distinct_days`, `first_play`, `last_play`
and `PlayDay`, and states in its docstring that it counts sessions and
day-precision records. `games/reads/session_figures.py` keeps `session_count`,
the three superlatives and `has_sessions`, so each module's name answers which
sources it takes. Its docstring's tie-break sentence moves with the readers it
describes. `games_in_scope` stays where it is until #1105 moves it.

## The tie-break

The first play is the earliest day any counted row states; within that day, the
game with the lower sort name, then the lower game key. The last play mirrors
it: the latest day, then the higher sort name, then the higher game key, which
is how the two readers already mirror each other on the row key. A day holding
two games therefore still answers two games, one at each end.

The order names no source and no row key, so converting a session into a record
on the same day at the same game cannot move either answer. That is what
#1099's gate needs.

`session_figures.py` claims the tie-break is "value first, then the game's sort
name, then the game's key, then the session's". The day figures keep the first
three levels and drop the fourth on purpose: the row key is the one column a
conversion changes, and the figure the page prints is a day and a game, which
the first three levels already decide. The current `first_play` and `last_play`
honour none of the three, ordering on the row key alone, so
`tests/test_session_figures.py`'s shared-day case answers by sort name in both
directions rather than by row key.

The figure names the day, not the hour. Neither source is ordered by an
instant: a session's row key is its creation order rather than its play order,
and a record states no instant at all. No ordering over the two tables could do
better while a record states no time of day.

`PlayDay` carries which source answered, preferring the session where a session
and a record state the same day at the same game. The stats row prints the
game, the date and a link to that game's sessions in scope; it omits that link
only when a record alone answered, so the page offers no link to an empty list.
#1105 replaces the omission with a link that reaches records.

## The query shape

The day count is one query: each source's distinct days as a `values_list`,
combined with `union()`, counted. `UNION` is distinct, so a day both sources
hold counts once.

The first and last play read each source separately and pick between the two in
Python by the tie-break, because no order spans both tables: the columns differ
in name and the record leg carries a second predicate.

Each of those reads orders on a joined game column under an indexed leading
key, `effective_day` or `when_lower`. That is a plan the budget has already
been burned by once: #704 records `stats_superlatives` first measuring 20.4 ms
against 20 ms, and the remedy was to stop sorting joined rows whole. So the
plan measures this one before it is kept. Ordering by the three levels with
`LIMIT 1` is the shape to try first, since the leading key is the index's. Where
the planner sorts the joined rows whole instead of stopping inside the first
day's group, the fallback is two reads a source: the earliest day off the index,
then the rows on that one day ordered by the game's columns.

`make bench` records both cells, `stats_totals` and `stats_superlatives`, and
judges them at 20 ms under `ARGS="--library <id> --gate"` on a real library.
The record table's size is #1098's review population, which #1099 measures with
600 records; the plan's measurement uses that count rather than a guess.

## Classification

`STATS_SOURCE_GROUPS` moves `unique_days`, `unique_days_percent`,
`first_play_game`, `first_play_date`, `last_play_game` and `last_play_date` to
`StatsSource.BOTH`. `SESSIONS_NO_SITTINGS` keeps the session count, the longest
session, the highest count and the highest average, which the charter gives no
record leg ever.

`BOTH` now holds two record rules, so its comment states both: a playtime
figure counts a record wholly inside the scope, and a day figure counts only a
record naming one day. The `StatsSource` docstring claims a count of games
reads both sources, which the code contradicts; it states what the code does
and names #1105 as the issue that makes the claim true.

## Documents

#709's Classification section and the wave document's classification table
state the corrected split and name #1105 for the two played-games keys. The
wave's table has no row for `unique_days_percent`, `total_games` or
`total_year_games`, so those are added rather than corrected. `CLAUDE.md` and
#704's specification both name `session_figures.py` as the home of the first
and last play, and follow the readers to the new module. #1126's own body
records the cut, and #1105's scope gains the two keys.

#1099's rule table states that the day count falls by the converted days and
that the first and last play change or are attributed. Both rules are wrong
after this issue. #1099's specification is not on `main`, and nothing orders
#1105 before it, so whoever rebases #1099 states strict equality for these four
keys, keeps the attributed rule for the two played-games keys, and names #1105
as the issue that makes those two strict as well.

## Tests

- `tests/test_play_figures.py` takes the moved cases and adds: a day-precision
  record on a day no session holds raises the day count; one on a day a session
  already holds does not; a same-day range and a qualified day raise it; a
  month, a year, a wider range, an open range and an unknown `when` raise
  nothing; a record earlier than every session answers the first play and
  carries its source; a session and a record on one day at one game answer the
  session; a shared day answers two games, one at each end.
- `tests/test_stats.py` states the reversal in the open. Its `_session_figures`
  helper selects keys by source group, so the six keys would leave the
  comparison silently; the helper names the keys it compares, and a second case
  asserts the four day keys move. The existing case records a month-precision
  record, which never pinned the day figures at all, so it keeps its answer and
  a day-precision case is added beside it.
- The rendered stats page covers a first play a record alone answers, which
  prints no session link.

## Out

- The two played-games keys, `games_played`, `games_in_month`, the top-10,
  platform and navbar links, and the `GameFilter` records relation: #1105.
- A stated session count on a record, which would give a record a leg in the
  session count: #1106 decides, and the charter says never.
- `total_year_games` counts a purchase, not a game, and its two `games__`
  filters join twice, so a bundle holding a played game and a game released
  that year counts. Both are #1105's to keep or correct with the key.
- Streaks: the charter's row names them, and the wave removed the helpers with
  no caller. Nothing prints a streak today.
