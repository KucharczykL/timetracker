# Played status behind commands and events

Issue [#672](https://github.com/KucharczykL/timetracker/issues/672). The code is
in `games/models.py`, `games/checks.py`, `games/events/projection.py`,
`games/events/playergame.py`, `games/commands/playergame.py` and
`games/projectors/playergame.py`.

A library gives a status to a game it tracks. A command records the change, and
a projector writes it to the `PlayerGame` row.

## The vocabulary

`PlayerGameStatus` holds six values: `unplayed`, `played`, `completed`,
`retired`, `shelved` and `abandoned`. The values are full words, where
`Game.Status` keeps five single letters. A recorded payload cannot be upcast, so
an event that records `f` would mean Completed for as long as the stream
exists.

## How a projection row gets its columns

This rule applies to each projection of the phase.

A column that an event states has no default. The fold that creates the row
names it, and a fold that omits it raises.

A column that no event states has a constant default. `PlayerGame.status` starts
at `unplayed`.

The default also makes the creation fold safe to repeat. `project()` names its
columns in `update_fields`, so a second fold of the creation event keeps a
status that a later event set.

A creation payload does not grow a column later. #675, #694 and #727 each add a
column to a row that has recorded events. Each one is a default and a new event.

### A default is code

A rebuild reproduces a constant, but not a change to one: such an edit rewrites
each row that no event touched.

`games.checks` E007 therefore refuses a callable default on a projection field,
and E005 and E006 become special cases of it. E007 permits the container and
scalar builtins, which return one value. A test pins each projection default to
a literal, so an edit is a reviewed diff.

## Amendment

`Projector.amend()` writes part of a row that exists. It asks the target for the
model, runs one `UPDATE` on the primary key, and takes no read. `project()`
cannot serve this, because an event that changes one column knows nothing of the
columns that the creation event wrote.

A missing row raises `ProjectionRowMissing`. A replay folds a stream in sequence
order, so the creation event wrote the row already, and an insert here would
write a part-row that a rebuild cannot reproduce.

## The event

The event type is `library.playergame.status_changed`. The aggregate id is the
identity of the `PlayerGame` row. The payload has one key, `status`, and no
reference: the creation event holds the one reference of this aggregate.

The type of `status` is a `Literal`, not the enum. Strict validation refuses a
plain string for an enum field, and a recorded payload is read back as one. A
test pins the `Literal` to `PlayerGameStatus.values`.

## The command

`SetPlayerGameStatus` holds a game id and a status. `build()` runs behind the
stream-head lock and returns one event.

`build()` finds the `PlayerGame` row of this library. It reads the projection
only, because an archived catalog row is a catalog concern. A game of another
library resolves to no row, so the rejection tells the caller nothing.

A game that the library does not track causes a `CommandRejected`. #676
backfills a row for each game before #677 wires a caller.

A status equal to the current status also causes a `CommandRejected`, as a
repeated `TrackGame` does.
[#906](https://github.com/KucharczykL/timetracker/issues/906) decides whether a
no-op rejects.

## The fold

The handler calls `self.amend(PlayerGame, event.aggregate_id, ...)` with the
status. It reads the payload, not a command, so a replay writes the recorded
status.

## Out of scope

No view, form or API calls the command. #673, #674 and #675 add the other state
columns. #676 backfills, #677 switches the writes and #678 switches the reads.
