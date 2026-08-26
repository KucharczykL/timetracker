# Played status behind commands and events

Issue [#672](https://github.com/KucharczykL/timetracker/issues/672). The code is
in `games/models.py`, `games/checks.py`, `games/events/projection.py` and the
`playergame` modules of `games/events`, `commands` and `projectors`.

A library gives a status to a game it tracks.

## The vocabulary

`PlayerGameStatus` holds six values: `unplayed`, `played`, `completed`,
`retired`, `shelved` and `abandoned`. They are full words, not the letters of
`Game.Status`: a recorded payload cannot be upcast, so an event recording `f`
would mean Completed forever.

## How a projection row gets its columns

This rule applies to each projection of the phase. A column an event states has
no default, and the creating handler must name it. A column no event states has a
constant default: `PlayerGame.status` starts at `unplayed`. The default also
makes the creation handler safe to repeat, because `project()` names its columns in
`update_fields`.

A creation payload does not grow a column later. #675, #694 and #727 each add
one to a row with recorded events: a default and a new event.

A default is code: a rebuild reproduces a constant, but not a change to one,
which rewrites each row no event touched. `games.checks` E007 therefore refuses
a callable default, with E005 and E006 as special cases and the one-value
builtins permitted. A test pins each projection default to a literal, so an edit
is a reviewed diff.

## Amendment

`Projector.amend()` writes part of a row that exists: one `UPDATE` on the
primary key, through the target's model, with no read. `project()`
cannot serve this, because an event that changes one column knows nothing of
the others.

A missing row raises `ProjectionRowMissing`. A replay runs in sequence order,
so the row exists already; an insert here would write a part-row a rebuild
cannot reproduce.

The handler amends from the payload, not from a command, so a replay writes the
recorded status.

## The event

The type is `library.playergame.status_changed`, and its aggregate id is the
`PlayerGame` identity. The payload has one key, `status`, and no reference: the
creation event holds this aggregate's one reference.

The type of `status` is a `Literal`, not the enum: strict validation refuses a
plain string for an enum field, and a recorded payload reads back as one. A
test pins the `Literal` to `PlayerGameStatus.values`.

## The command

`SetPlayerGameStatus` holds a game id and a status. `build()` runs behind the
stream-head lock and returns one event.

`build()` finds the `PlayerGame` row of this library, reading the projection
only: an archived catalog row is a catalog concern. A game of another library
resolves to no row, so the rejection says nothing about it.

A game the library does not track rejects. #676 backfills a row for each before
#677 wires a caller.

A status equal to the current one also rejects, as a repeated `TrackGame` does.
[#906](https://github.com/KucharczykL/timetracker/issues/906) decides whether a
no-op should.

## Out of scope

No view, form or API calls the command. #673–#675 add the other state columns.
#676 backfills, #677 switches the writes and #678 the reads.
