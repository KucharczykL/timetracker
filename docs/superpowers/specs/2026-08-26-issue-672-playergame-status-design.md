# Played status behind commands and events

Issue [#672](https://github.com/KucharczykL/timetracker/issues/672). The code is
in `games/models.py`, `games/checks.py`, `games/events/projection.py`,
`games/events/playergame.py`, `games/events/dispatch.py`,
`games/commands/playergame.py` and `games/projectors/playergame.py`.

A library sets the status of a game it tracks. A command records the change and
a projector folds it onto the `PlayerGame` row. No view, form or API calls the
command yet.

## The status vocabulary

`PlayerGameStatus` is a `TextChoices` in `games/models.py`. It holds the six
values the charter names: `unplayed`, `played`, `completed`, `retired`,
`shelved` and `abandoned`.

The values are the charter's, not the five single letters of `Game.status`. A
recorded payload cannot be upcast, because the event registry refuses a version
above 1. A payload that recorded `f` would therefore mean `completed` forever,
and `shelved` would have no code at all.

`Game.status` keeps its own five values. [#677](https://github.com/KucharczykL/timetracker/issues/677)
switches the writes and [#678](https://github.com/KucharczykL/timetracker/issues/678)
switches the reads. Until then the two are independent.

## How a projection row gets its columns

This rule holds for every projection of the phase, not only for this one.

A column that an event states carries no default. The fold that creates the row
names it. `_required_columns` requires it, and a fold that omits it raises.

A column that no event states carries a constant model default. `PlayerGame.status`
defaults to `unplayed`. Tracking a game asserts nothing more than that the
library tracks it.

The default also makes the creation fold safe to repeat. `project()` passes the
columns it names as `update_fields`, so `ON CONFLICT DO UPDATE` writes only
those. A defaulted column is absent from that list. A second fold of the
creation event therefore keeps a status that a later event set.

A creation payload never grows a column later. [#675](https://github.com/KucharczykL/timetracker/issues/675)
adds `archived_at` to this row, [#694](https://github.com/KucharczykL/timetracker/issues/694)
adds `deleted_at` to `Session` and [#727](https://github.com/KucharczykL/timetracker/issues/727)
adds a refund to `Purchase`. Each one is a default and a new event, not an edit
to a payload that has recorded events.

### The default is code

A rebuild reproduces a constant default. It does not reproduce a change to that
constant: an edit would rewrite the status of every game no event has touched.

Two guards answer this. `games.checks` E007 refuses a callable default on a
projection field, so only a constant qualifies. E007 tests `has_default()`
first, because `models.NOT_PROVIDED` is a class and therefore callable. It makes
E005 and E006 special cases of one rule and closes the wrapper hole E006's hint
admits.

A test pins the defaults. It reads every `ProjectionModel` subclass and compares
each defaulted column to a literal in the test. An edit to a default is then a
reviewed diff.

## Amending a row another event created

`Projector.amend()` writes a subset of a row that exists. It asks its target for
the model, issues one `UPDATE` keyed on the primary key, and raises
`ProjectionRowMissing` when no row matches.

[#930](https://github.com/KucharczykL/timetracker/issues/930) deferred this
shape to the first handler that needed it. `project()` cannot serve it: the
status event states the identity and the status, and no later event can know
the `tracked_at` of the creation event.

The absent row is loud. A replay folds a stream in sequence order, so the
creation event has already inserted the row. Zero rows matched means a broken
stream. `ProjectorRegistry.apply` annotates the failure with the family and the
sequence.

`amend()` costs one statement and takes no read.

## The event

The event type is `library.playergame.status_changed`. Its aggregate type is
`playergame`. Its aggregate id is the `PlayerGame` identity, which is the
aggregate id of the creation event.

The payload has one key, `status`. Its type is a `Literal` over the six values.
A `Literal` rather than the enum, because it accepts both forms the value
takes: a `TextChoices` member at the call site, and the plain string a recorded
payload is read back as. A test asserts the `Literal` arguments equal
`PlayerGameStatus.values`.

The payload carries no reference. A reference stops a hard delete of a
referenced row, and the creation event already holds the one reference this
aggregate has.

## The command

`SetPlayerGameStatus` holds a game id and a status. It is `CommandName.PLAYERGAME_SET_STATUS`,
`library.playergame.set_status`.

The command takes the game id, not the `PlayerGame` identity. `TrackGame` takes
the same handle. The resolution then runs inside `build()`, under the
stream-head lock. #677 switches the writes before #678 switches the reads, so
the caller holds a `Game` when it first issues this command.

`build()` finds the `PlayerGame` of this library for that game. It reads the
projection only. It does not read the catalog: a library that tracks a game may
set its status, and an archived catalog row is a catalog concern. A game of
another library resolves to no row of this library, so the rejection tells the
caller nothing.

A game the library does not track is a `CommandRejected`.
[#676](https://github.com/KucharczykL/timetracker/issues/676) backfills a row
for every game of every library before #677 wires a caller, so the case is a
defect.

The status is a `PlayerGameStatus` field. The fingerprint needs no new
canonical form: a `TextChoices` member is a `str`, so `json.dumps` writes its
value.

A status equal to the current status is a `CommandRejected`. The message points
at [#906](https://github.com/KucharczykL/timetracker/issues/906), as
`TrackGame`'s duplicate check does. #906 decides whether a no-op rejects or
succeeds with an empty range; one convention gives it one place to change.

`build()` returns one event.

## The fold

`PlayerGames` handles the new type. The handler calls `self.amend(PlayerGame,
event.aggregate_id, status=event.payload["status"])`.

The handler reads the payload, never a command. Thus a replay writes the status
the event recorded.

## Dependencies

#601 sequences #906 before #677. The rejection of a redundant set is otherwise
visible to a user who picks the status a game already has.

Nothing else blocks this issue. #671 delivered the row, the command and the
projector this issue extends.

## Reversibility

The migration adds one column with a default. Django backfills the existing
rows and leaves no database default. The reverse migration drops the column.

No caller writes the event, so a revert loses no user action. A recorded event
of the new type outlives a revert of the code, and a replay would then raise
`UnregisteredEventType`. This is theoretical while the command has no caller.

## Verification

- The command sets the status, and rejects an untracked game, a game of another
  library and a redundant set.
- A repeated dispatch with one idempotency key appends one event.
- `amend()` writes one column, and raises `ProjectionRowMissing` for an absent
  row.
- A second fold of the creation event keeps a status a later event set.
- A replay into an empty projection, of a stream that holds a creation and a
  status change, reproduces the status.
- A shadow rebuild swaps in a table that carries the status.
- E007 refuses a callable default on a projection field, and accepts a constant.
- The pinned defaults match the models.
- The `Literal` arguments equal `PlayerGameStatus.values`.
- `make check` passes. `make bench` still runs: the benchmark seeds creation
  events, and the default fills the new column.

## Out of scope

No view, form or API. #673 adds mastered, #674 the unfinished-list exclusion and
#675 archive and restore, each as a default and an event under the rule above.
#676 backfills, #677 switches the writes and #678 switches the reads. Filters,
saved presets, statistics and the API read `Game.status` until #678.

The benchmark gains no scenario. A fold that accumulates a sum, which
[#697](https://github.com/KucharczykL/timetracker/issues/697) needs, is a third
shape and is specified there.
