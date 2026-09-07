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

`_playthroughs_section` in `games/views/game.py` renders one row for each live
ordinary run: the display name, both endpoints, the days to finish, the note,
the creation date and the actions. The note is the run's own. The notes the
two acts carry belong to #1015.

A tracked game holds a run from the moment the library tracks it, so the
section always has one row. The empty branch stays for a section with none.

The remove button renders on every row. `RemovePlaythrough` refuses the last
live ordinary run with its own sentence.

`Playthrough` declares no manager. The section selects on `library` and on
`player_game__library`, because a run can name another library's `PlayerGame`.

## Numbering

`numbered_for(library, player_game_ids)` in
`games/reads/playthrough_numbering.py` selects the live ordinary runs of those
tracked games and numbers each one. `RowNumber` counts across whatever the
caller selected, so the caller states tracked games rather than a queryset and
narrows afterwards. The section orders by `DISPLAY_ORDER`, which is the
window's own order. Another order prints 2 above 1.

## Days to finish

`completed_upper` minus `started_lower`, in days. Equal bounds read 1. An
absent bound reads `-`. A negative span reads `-`, because it is not a length.

## The two counts

The section badge counts every row the section renders. `Played N times`
counts the runs whose completion is stated, the day known or unknown alike. A
run nobody finished is not a time somebody played the game through.

The remove-game confirmation counts by the section's rule. It says what leaves
the screen.

## The routes

`edit_playthrough` and `remove_playthrough` resolve a live `Playthrough` in
the library, on both library columns. A legacy key answers 404. A run
`CreatePlaythrough` states after #687 names no legacy row, so a route on the
legacy key could not reach most runs.

The list page renders legacy rows until #1013. It translates its own action
ids through `runs_for_rows`. A row the map does not reach renders no actions.

## The prefill

`add_playthrough` seeds its start date from the greatest completion the
library's live ordinary runs of that game state. A completion with no day
seeds nothing.

## What stays legacy

The list page until #1013. The API GET bodies until #1015. The statistics
until #1014. The purchase Finished column until #1026. The table until #771.

## Rollback

Reads only. No migration, no event, no column. Reversal is the revert.
