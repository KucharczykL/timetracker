# Count a record in the day figures and the played-game counts

Issue: [#1126](https://github.com/KucharczykL/timetracker/issues/1126). Parent
phase: #601. Ahead of
[#1099](https://github.com/KucharczykL/timetracker/issues/1099), whose parity
gate judges the classification this issue restores.

## Purpose

The [overhaul charter](2026-08-09-timetracker-overhaul-design.md)'s
contribution table gives Historical Playtime a day-precision leg in "Day
totals, unique days, streaks, first/last play", a leg in every playtime total,
and no leg at all in the session count, the averages and the longest session.
[#709](2026-09-17-issue-709-historical-playtime-reads-design.md) put the
unique days, the first and last play and the two played-game counts under
"sessions only" and recorded no deviation. This issue restores the charter's
answer for all six keys.

Why it matters now: #1098's "Move all N to historical playtime" writes every
record at day precision. Converting a session dated D into a record dated D
must leave the days played, the first and last play and the games played
exactly as they were, and move only the session count, the longest session
and the per-game averages. #1099's parity gate proves that, so this lands
first.

Two members, one stack: the day figures, then the played-game counts with the
filter machinery their link needs. Each member leaves `main` consistent.

## The day rule

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

This is narrower than the charter's "day precision only" read per endpoint: a
range `2021-09-01/2021-09-27` has two day-precise ends, and #1106 wants the
last play to read such a record's `when_upper`. The table generates no
precision column, so an endpoint's precision cannot be read in SQL today.
This issue takes the one-day predicate the two bound columns can state and
records the narrowing; #1106 widens it when it adds the columns it needs.

Both sources reach the day figures through the scopes the playtime sums
already use, `library_sessions` and `library_records`, so a figure and a total
never disagree about which rows exist. The two scopes read different marks: a
session's scope reads the run's, a record's does not, because a record names
its runs through a join. Nothing can drift, since a run holding a record is a
blocking referrer and a record under a removed run cannot be restored.

`unique_days_percent` is derived from the day count and, all-time, from the
first and last play. It follows the two without a leg of its own.

## The module

`games/reads/play_figures.py` holds `distinct_days`, `first_play`, `last_play`
and `PlayDay`, and states in its docstring that it counts sessions and
day-precision records. `games/reads/session_figures.py` keeps `session_count`,
the three superlatives, `has_sessions` and `games_in_scope`, and its docstring's
tie-break sentence, which describes the three superlatives that stay.

## The tie-break

The first play is the earliest day any counted row states; within that day, the
game with the lower sort name, then the lower game key. The last play mirrors
it: the latest day, then the higher sort name, then the higher game key, which
is how the two readers already mirror each other on the row key. A day holding
two games therefore still answers two games, one at each end.

The order names no source and no row key, so converting a session into a record
on the same day at the same game cannot move either answer. That is what
#1099's gate needs.

The current `first_play` and `last_play` order on the day, then the row key,
and skip the sort name and the game key the module's other readers honour. The
day figures take those two levels and drop the row key on purpose: the row key
is the one column a conversion changes, and the figure the page prints is a
day and a game, which the first three levels already decide. `sort_name` is
entered by hand and usually empty, so on real data the second level is often
the game key; that matches the three superlatives, which read the same
column.

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
in name and the record leg carries a second predicate. Each leg selects its
game, so the pick reads no further query. The Python comparison of
`sort_name` agrees with the two SQL orders because the database's collation
is `C.UTF-8`, which [Database contract](../../database.md) pins; a UUID key
orders the same way on both sides by construction.

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

## The played-game counts

`total_games` counts games with a session in scope through `games_in_scope`;
`total_year_games` counts purchases through the same session join, narrowed
per year to purchases holding a game released that year. The charter names no
row for either, but a game with a per-Game total is a played game, and the
same page already counts it as one in `games_by_playtime_count`. Both keys
mean "a game this library played", so they move together.

Both gain a records leg by containment, the predicate the totals use: a game
is in scope when a session of it is, or when a record naming it lies wholly
inside the scope's days. `games_in_scope` states the two as one `Q` over
`player_games__playthroughs__sessions` and `player_games__historical_playtime`;
the purchase count states the same two through `games__`. A year's record leg
narrows on `when_lower` and `when_upper` against the year's `DayInterval`;
all-time takes every live record. `total_year_games`'s second `games__` join
per year is kept as it is, because this issue moves the source, not the
shape.

### The link states the same predicate

`total_games` links to `games_played` in `games/views/stats_links.py`, and
`tests/test_stats_links.py` holds each link's count equal to its figure. Today
a `GameFilter` cannot say "a record contained in scope": its relations are
sessions, purchases, playthroughs and platforms, and the temporal criterion's
`BETWEEN` on an interval-valued field reads overlap. Two things are added so
the link and the figure compile one predicate:

- **`GameFilter.historical_playtime_filter`**, a relation to
  `HistoricalPlaytimeFilter` through `player_game__game__id`, the way
  `playthrough_filter` reaches the game. The field metadata derives the
  relation from the annotation, so the builder offers it and its child group
  without a template of its own. `HistoricalPlaytimeFilter.game_filter`
  already points the other way; the depth guard bounds the cycle as it bounds
  the session one.
- **`Modifier.WITHIN`**, "is wholly within": two bounds, the interval both
  columns state lies inside them, both bounds known. On a scalar date it
  compiles as `BETWEEN`, so the algebra stays total. The temporal handler
  states it as `lower >= low AND upper <= high`, beside `BETWEEN`'s overlap.
  Only an interval-valued field offers it in the builder: `FilterField` gains
  an `interval` flag the two temporal handlers' fields set, and
  `_modifiers_for_field` appends `WITHIN` for a date field carrying it, so a
  purchase date never lists a synonym of `BETWEEN`. The summary phrases it,
  the token module lists it as a range modifier, and the date widget writes
  its two bounds as it writes `BETWEEN`'s. The two cross-language contracts
  regenerate. `where()` spells it `when__within=(start, end)`.

`games_played(year)` becomes an `OR` of two `GameFilter`s: sessions in scope,
records within the year's days; all-time takes any session or any record.
`games_in_month` takes the same shape, because the month row's figure already
counts a record by containment and its link is one line away from agreeing.
The parity fixture gains a game only a record reaches, in-year, and one whose
record lies outside the year, so the parity test holds the divergence it
could not hold before.

The `HistoricalPlaytimeFilter.when` facet keeps `BETWEEN` as overlap; a person
narrowing a list wants the records that touch a period. `WITHIN` is the
statistic's word.

## Classification

`STATS_SOURCE_GROUPS` moves `unique_days`, `unique_days_percent`,
`first_play_game`, `first_play_date`, `last_play_game`, `last_play_date`,
`total_games` and `total_year_games` to `StatsSource.BOTH`.
`SESSIONS_NO_SITTINGS` keeps the session count, the longest session, the
highest count and the highest average, which the charter gives no record leg
ever. `SESSIONS_PLAYED_GAMES` empties and is removed.

`BOTH` now holds three record rules, so its comment states them: a playtime
figure and a played-game count take a record wholly inside the scope; a day
figure takes only a record naming one day. The `StatsSource` docstring's claim
that a count of games reads both sources becomes true.

The two `PlayDay` source flags the stats row reads, `first_play_from_record`
and `last_play_from_record`, join `NOT_A_FIGURE`: they steer a link, not a
number.

## Documents

#709's Classification section and the wave document's classification table
state the corrected split. The wave's table has no row for
`unique_days_percent`, `total_games` or `total_year_games`, so those are added
rather than corrected. `CLAUDE.md` and #704's specification both name
`session_figures.py` as the home of the first and last play, and follow the
readers to the new module. #1105's scope loses the relation, the containment
word and the two game-list links, which land here, and keeps the top-10 and
platform row links, the narrowed Playtime column and the navbar.

#1099's rule table already states equality for the six keys. Its two
`NOT_A_FIGURE` flags need a rule of their own there: a flag flips only where
the row that answered was converted.

## Tests

- `tests/test_play_figures.py` takes the moved cases and adds: a day-precision
  record on a day no session holds raises the day count; one on a day a session
  already holds does not; a same-day range and a qualified day raise it; a
  month, a year, a wider range, an open range and an unknown `when` raise
  nothing; a record earlier than every session answers the first play and
  carries its source; a session and a record on one day at one game answer the
  session; a shared day answers two games, one at each end.
- `tests/test_session_figures.py`: a game only a contained record reaches
  enters `games_in_scope` for its year and all-time; a record wider than the
  year enters all-time alone.
- `tests/test_stats.py` states the reversal in the open. Its `_session_figures`
  helper selects keys by source group, so the moved keys would leave the
  comparison silently; the helper names the keys it compares. The existing
  case records a month-precision record, which moves the two played-game
  counts and no day figure; a day-precision case beside it moves the day
  figures as well. Neither moves the session count, the longest session or the
  two highest-session keys.
- `tests/test_stats_links.py`: `games_played` and `games_in_month` equal their
  figures with a record-only game in the fixture; `WITHIN` on
  `historical_playtime_filter.when` finds a record inside the year and not one
  overlapping it.
- `tests/test_filters.py`, `tests/test_filter_paths.py`: the relation parses,
  resolves its path kinds, and refuses a cycle at the depth guard; `WITHIN` on
  a scalar date equals `BETWEEN`; a scalar date field lists no `WITHIN`.
- The two cross-language contracts pass with `WITHIN` in both vocabularies.
- The rendered stats page covers a first play a record alone answers, which
  prints no session link.

## Out

- The top-10 row links, the platform row links, the navbar figures' links and
  the game list's narrowed Playtime column: #1105.
- A stated session count on a record, which would give a record a leg in the
  session count: #1106 decides, and the charter says never. Reading a
  day-precise endpoint of a wider range: #1106 as well.
- `total_year_games` counts a purchase, not a game, and its two `games__`
  filters join twice per year, so a bundle holding a played game and a game
  released that year counts. The shape stays; only the source moves.
- A `NOT_WITHIN` modifier: nothing asks for one.
- Streaks: the charter's row names them, and the wave removed the helpers with
  no caller. Nothing prints a streak today.
