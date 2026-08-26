# Mastered behind commands and events

Issue [#673](https://github.com/KucharczykL/timetracker/issues/673). The code is
in `games/models.py` and the `playergame` modules of `games/events`,
`games/commands` and `games/projectors`.

A library states that it mastered a game it tracks.

## The column

`PlayerGame.mastered` is a `BooleanField` that starts at `False`. No event
states it at creation, so it takes a constant default, as `status` does. `False`
is a literal, thus the `games.checks` rules E004 to E007 permit it, and
`PINNED_DEFAULTS` in `tests/test_projection_model.py` gains the entry that makes
a change to it a reviewed diff.

`project()` names its columns in `update_fields`, and the creation handler does
not name this one. A second run of the creation event thus keeps a value a later
event set.

The migration adds the column with the default. It changes no data: each row is
a projection of events that state nothing about mastery.

## The event

The type is `library.playergame.mastered_changed`, its aggregate id is the
`PlayerGame` identity, and its payload has one key, `mastered`.

One type states both directions. Two types, one to master and one to unmaster,
would put the same information in the type name and need two handlers that write
one column. The payload states the value, thus a replay writes what the event
recorded and not what a toggle computes.

The type of `mastered` is `bool`. `status` needs a `Literal` because strict
validation refuses a plain string for an enum field. A bool is already the type
that a recorded payload reads back as.

## The handler

`_mastered_changed` calls `amend()`: one `UPDATE` on the primary key of a row
that the creation event made. An absent row raises `ProjectionRowMissing`, as it
does for a status.

## The command

`SetPlayerGameMastered` holds a game id and a bool.
`CommandName.PLAYERGAME_SET_MASTERED` is `library.playergame.set_mastered`.
`build()` runs behind the stream-head lock and gives one event.

A game that the library does not track rejects. A value equal to the current one
also rejects, as a repeated `TrackGame` does.
[#906](https://github.com/KucharczykL/timetracker/issues/906) decides whether a
no-op must instead succeed.

`SetPlayerGameStatus._tracked()` becomes `_tracked_game(context, game_id)` at
module level, and the two commands call it. One lookup, and one rejection
message.

## A note for #676

The default covers a row that no event touched. It does not carry the catalog's
`Game.mastered`. The backfill must record a `mastered_changed` event for each
game that a library mastered, or a rebuild loses the flag.

## Out of scope

No view, form or API calls the command. `Game.mastered` stays until #678 moves
the reads. #674 and #675 add the remaining state.
