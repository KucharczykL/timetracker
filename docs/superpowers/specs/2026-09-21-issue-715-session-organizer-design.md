# The desktop Session organizer

The session list groups its rows by the playthrough each session sits on. This
is the view for [#713](https://github.com/KucharczykL/timetracker/issues/713)'s
Move act. A person sees the grouping, moves a session, and sees where it landed.

## A sort key names an ordering

`SortSpec` in `games/sorting.py` holds one `expression` and a tuple `then`.
`apply_sort` writes the expression and each entry of `then` as one `ORDER BY`
term. Each term takes the direction of the sort term and `NULLS LAST`. `F("pk")`
closes the order.

A run's place on a screen is a four-field order. One field cannot hold it.
Before `then`, the Playthrough list's own first column had no sort key.

## What orders a run

`games/reads/playthrough_numbering.py` owns that order.

| Name | Content |
|---|---|
| `DISPLAY_ORDER_FIELDS` | The four field names, in order |
| `DISPLAY_ORDER` | The same fields for the window that counts `Playthrough N` |
| `display_order_through(path)` | The same fields through a relation |
| `numbered_sort_key(path)` | Null where no number is counted across the run |

`numbered_sort_key` is the ORM twin of `is_numbered`. It answers a value for a
live ordinary run and null for a bucket or a removed run. Only null against
not-null has meaning.

## The two keys

`SESSION_SORTS["playthrough"]` and `PLAYTHROUGH_SORTS["playthrough"]` lead with
the game's `sort_name`, then `numbered_sort_key`, then the display order. The
session key ends with `sort_instant`.

The game leads because a run's number has no meaning outside its game. On a
list of many games, the runs of unrelated games would interleave by start day.

`apply_sort` writes `NULLS LAST` on both branches. Because of this, the bucket
sorts last under its own game in both directions, and so does a run that states
no start. Descending is not a mirror of ascending.

## The column

`sole_game` in `games/reads/player_sessions.py` answers the one game that the
filtered rows name, or null. It clears the ordering first. Django adds each
ordering expression to the `SELECT DISTINCT` list. An ordered queryset distincts
over the instant and the key beside the game, and one game with two sessions
answers two rows.

While `sole_game` answers a game:

- a `Playthrough` column comes after Name, at priority 3;
- each cell names the run, through `every_run_label`. A sole run is named. The
  bucket reads `Imported history`;
- the name cell drops its own run label. The run is named in one place.

A library that holds one game always sees the column. The same rows get the
same table, whatever narrowed them.

## The stacked cell

Each row states a summary, the second line that
[#711](https://github.com/KucharczykL/timetracker/issues/711) built. It joins the
run label, the time range, the duration and the device with commas. The run label
is there only while the column is declared. Below `md` the column drops with the
others, and nothing else names the run.

Commas, not a middle dot. A screen reader speaks a comma as a pause and a middle
dot as a word.

## Game detail

The Sessions section shows Organize beside View all while the section has rows.
Organize is the filtered list under `sort=playthrough`. The button carries the
`list-tree` glyph. The section header wraps.
