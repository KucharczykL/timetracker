# Read Playthroughs on Game detail

The Game detail Playthrough section reads the `Playthrough` projection. The
two counts beside it read the same rows. No screen this issue delivers reads
`games_playevent`.

## What a run states

A run separates an act from its day. Three states reach a person:

| the run states | the section renders |
|---|---|
| no marker | `-` |
| a marker and a day | the day, at its own precision |
| a marker and no day | `Unknown` |

`games/reads/playthrough_endpoints.py` answers the marker. `TemporalText`
answers the words.

## The section

`_playthroughs_section` in `games/views/game.py` renders the section.
`games/views/playthrough_rows.py` builds one row for each live ordinary run:
the display name, both endpoints, the days to finish, the note, the creation
date and the actions. The note is the run's own. The notes the two acts carry
belong to #1015.

`TrackGame` states a run, so a game tracked after #679 holds one. The empty
branch stays: #684 gave no run to a tracked game whose catalog row the library
marks removed, and a person can remove every run but one.

The remove button renders on every row. `RemovePlaythrough` refuses the last
live ordinary run with its own sentence.

`Playthrough` declares no manager. The section selects on `library` and on
`player_game__library`, because a run can name another library's `PlayerGame`.

## Numbering

`numbered_for(library, player_game_ids)` in
`games/reads/playthrough_numbering.py` selects the live ordinary runs of those
tracked games and numbers each one. `RowNumber` counts across whatever the
queryset holds, so the caller states the tracked games it wants and narrows
nothing after. A later `filter()` takes rows away and leaves gaps in the
numbers. The section orders by `DISPLAY_ORDER`, which is the window's own
order. Another order prints 2 above 1.

## Days to finish

`completed_upper` minus `started_lower`, in days. Equal bounds read 1. An
absent bound reads `-`. A negative span reads `-`, because it is not a length.

## The counts

Three counts read the same rows. The section badge counts every row the
section renders. `Played N times` counts the runs whose completion is stated,
the day known or unknown alike, because a run nobody finished is not a time
somebody played the game through. The remove-game confirmation counts by the
section's rule, because it says what leaves the screen.

## The routes

`edit_playthrough` and `remove_playthrough` resolve a live ordinary
`Playthrough` in the library, on both library columns. A legacy key answers 404. A run
`CreatePlaythrough` states after #687 names no legacy row, so a route on the
legacy key could not reach most runs.

The list page renders legacy rows until #1013. It translates its own action
ids through `runs_for_rows`. A row the map does not reach renders no actions.

## The prefill

`add_playthrough` seeds nothing for a game with no live session. For a game
with one, it seeds the start date with the day after the greatest completion
the library's live ordinary runs of that game state. A completion with no day
counts as none, and the earliest session's day seeds the start instead.

## What stays legacy

The list page until #1013. The API GET bodies until #1015. The statistics
until #1014. The purchase Finished column until #1026. The table until #771.

## Rollback

Reads only. No migration, no event, no column. Reversal is the revert.
