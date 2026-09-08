# The Playthrough list page

The Playthrough list page reads the `Playthrough` projection. The filter, the
sorts, the quick facets and the saved presets read it too. No screen reads
`games_playevent`.

## The filter

`PlaythroughFilter` filters `Playthrough`. The mode word stays `playthroughs`,
and the builder page is `/tracker/playthrough/filter`.

| field | reads |
|---|---|
| `game` | `player_game__game__id`, a UUID set |
| `name` | the run's name |
| `started`, `completed` | each endpoint's two bound columns |
| `is_started`, `is_completed` | the two markers |
| `days_to_finish` | both bounds, as date arithmetic |
| `note`, `start_note`, `completion_note` | the same columns |
| `created_at` | `created_at__date` |

`search` reads the game name, the run name and the three notes. `game_filter`
descends to `Game`. `renamed_fields` maps `ended` to `completed`.

## An endpoint is an interval

An endpoint states a day, a month, a year, a decade or a range. Two generated
columns hold the earliest day and the latest day that value can name. Both ends
are inclusive. An absent bound is unbounded. Each comparison first states that
the endpoint holds a value.

| the person asks | the filter reads |
|---|---|
| equals `X` | `lower <= X` and `X <= upper` |
| between `A` and `B` | `lower <= B` and `A <= upper` |
| not equals `X` | `lower > X` or `upper < X` |
| after `X`, before `X` | `lower > X`, `upper < X` |

Equality overlaps. Ordering and negation are certain. An act with no day answers
neither an equality nor its negation. `days_to_finish` counts the days a run
touched, both ends included. A same-day run reads 1.

## Scoping

`Playthrough` declares no manager. Each read states `library`,
`player_game__library`, a null `removed_at` and the ordinary kind.
`playthrough_count` reads `AggregateSpec.base_scope` and counts the runs whose
completion is stated, the number `Played N times` prints.

## The page

The page filters, sorts and paginates live ordinary runs. Its counts read every
live ordinary run of each game it holds, thus a number reads the same as on Game
detail. `playthrough_rows.py` builds the rows for both screens.

| sort key | reads |
|---|---|
| `name` | `player_game__game__sort_name` |
| `started`, `completed` | the lower bound of each |
| `days` | the span, annotated |
| `created` | `created_at` |

The default sort is `-created`. The Playthrough column carries no sort key. The
quick facets are Game, Started, Completed, Days to finish, Note and Created.

## Presets

Migration 0047 rewrites `ended` to `completed`, forward and backward. It walks a
playthroughs-mode criterion blob, the `playthrough_filter` subtree of a
games-mode preset, and the stored sort token. It walks nothing else, because
`ended` is a common word.

## Operands and widgets

The operand walk does not follow a projection's `library` key. It offers the
four bound columns under their own words, such as Started (earliest). A handler
field states its widget's column with `metadata_lookup`. `days_to_finish` names
no column, thus it offers no `is null`. A filter value is a plain ISO day.

## The statistics links

The all-time link reads `is_completed`, the act and not the day. The per-year
link reads `completed` between that year's ends, which overlaps.

## Out of scope

- statistics queries: #1014
- the API bodies and the endpoint screen: #1015
- comparing a run against its game's columns: #765 to #767
- asking about a qualifier: #893, #977
- a bucket a person can filter by: #700, #701
- taking `games_playevent` away: #771
