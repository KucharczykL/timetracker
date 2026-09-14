# Read playtime from the Session projection

Issue: [#697](https://github.com/KucharczykL/timetracker/issues/697). Part of the
[session delivery wave](2026-09-12-session-wave-design.md).

## Rule

Playtime is a read. No table stores a playtime total.

## Scope

`library_sessions(library)` in `games/reads/player_sessions.py` is the one scope
for `PlayerSession` rows. It states the library on the session and on its run.
It states four removal marks: the session, the run, the `PlayerGame` and the
catalog game. It does not filter on run kind, so sessions in the
imported-history bucket count. Every reader of `PlayerSession` uses it.

## Interface

Every playtime figure comes from `games/reads/playtime/`. Callers do not sum
sessions.

- `PlaytimeSource` names the figures: per game, all-time, per year, per day
  window, per platform, per month, and the played years.
- `FilteredPlaytimeSource` adds the sum narrowed by a `SessionFilter`.
- `legacy.py` reads `Session`. `projection.py` reads `PlayerSession`.
- `SOURCE` selects one source for all callers.

`projection.py` has no filtered sum, because `SessionFilter` names legacy
fields. `SOURCE` requires both protocols. Thus mypy refuses the projection
source until the filtered sum exists.

No queryset and no `Q` crosses the interface. A `SessionFilter` crosses.

## NULL and zero

A source returns a sum. The sum is NULL for an unplayed game. The package
decides the rest:

| function | unplayed game | reader |
|---|---|---|
| `playtime_by_game` | zero | `playtime_hours` filter, stats top games |
| `playtime_sort_key` | NULL | `playtime` sort |
| `playtime_matching` | NULL | list column, `filtered_playtime` sort |
| scalar figures | zero | detail, stats, navbar |

The sort reads NULL, so an unplayed game sorts last in both directions.
`IS_NULL` and `EQUALS 0` on `playtime_hours` both mean zero, so the filter
reads zero.

Rows with equal playtime order by name, then id.

## Days

The legacy source reads days in the active zone. The projection source reads
`effective_day`, which the row's `day_zone` fixes. The two agree when
`day_zone` comes from the display zone of the library's viewer.

## Parity

`make verify-playtime-parity` compares every figure of both sources through
`PlaytimeSource`. It uses the library's display zone or `--day-zone`. A
different figure makes the command fail.

## Removed

`Game.playtime`, its `Session` signal and the `Session` entry of
`_AFTER_STAMP`. The sample fixture has no `playtime` key. The loader refuses
unknown fields.

## Statistics classification

| `StatsData` field | Sessions | Historical Playtime |
|---|---|---|
| `total_hours` | yes | all-time: estimated; year: only inside the year |
| `top_10_games_by_playtime` | yes | estimated |
| `total_playtime_per_platform` | yes | only with a recorded Release or device |
| `month_playtimes` | yes | only inside the month |

The Historical Playtime column is a further `PlaytimeSource` member.

## Limits

- Each per-game read is a correlated subquery. A materialised total is a
  further source, not a caller change.
- A read between two instants is not possible for a Duration-only row.
- The alias `playtime` on `Game` blocks a column of that name.
