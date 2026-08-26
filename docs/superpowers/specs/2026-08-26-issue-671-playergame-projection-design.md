# The PlayerGame projection

Issue [#671](https://github.com/KucharczykL/timetracker/issues/671). The code is
in `games/models.py`, `games/events/playergame.py`,
`games/commands/playergame.py` and `games/projectors/playergame.py`.

`PlayerGame` records that a library tracks a catalog game: one row for each
tracked game. It is the first projection table of the application.

## The table

`PlayerGame` subclasses `ProjectionModel`. Only a projector writes it.

The primary key is the `aggregate_id` of the creation event. `UUIDv7Field`
supplies a minted default and a database default; this model refuses both.
`games.checks` E004 and E005 refuse a default on a projection, because a default
makes a rebuild write an identity the live table does not have.

`tracked_at` is the `recorded_at` of the creation event. It has no default;
E006 refuses one.

`game` is a foreign key to `Game`, with `RESTRICT` as its delete rule.

A unique constraint over `(library, game)` permits one row for each pair. Two
libraries can track one shared game, each with its own row.

## Retention

A retirement must not delete a projection row. `archive_or_delete()` collects
the rows that cascade from a game with `fail_on_restricted=False`. The cascade
then runs, and the projection rows stay. A replay writes them again; a delete
would make the live table and the rebuilt table disagree.

## The event

The event type is `library.playergame.created`. Its aggregate type is
`playergame`. Its payload has one key, `game`, of type `Reference`.

The payload gives no other fact. The envelope records the library, the identity
and the time.

The `Reference` type connects the event to the reference registry. `append`
writes a `LibraryEventReference` row. The tombstone then refuses a hard delete
of the game. A fold refuses a reference that resolves to nothing.

## The command

`TrackGame` holds a game id, not a `Game`. Dispatch calls `build()` behind the
stream-head lock.

`build()` resolves a game this library can see: a private or shared game that
is not archived. Any other game causes a `CommandRejected`, which tells the
caller nothing about another library.

`build()` refuses a game this library tracks already, and returns one creation
event.

## The projector

`PlayerGames` is in the `CURRENT_STATE` family.

The handler calls `self.project(PlayerGame, ...)`, which asks the target for the
model. A shadow rebuild then sends the write to its temp table.

The handler keys the write on the event's `aggregate_id`, so a second fold
writes no second row.

The handler reads the library from the event, so a replay reproduces the same
ownership.

## Command names

Each command names itself with a member of a `CommandVocabulary`. `CommandName`
is the vocabulary of the application, and it holds real commands only. A test
declares its own. The registry keys on the name, so two vocabularies cannot claim
one. A name is a domain symbol, not a Python path, and the fingerprint reads it,
so a move or a rename keeps an idempotency key valid.

## Out of scope

No view, form or API calls the command. #672–#675 add the state columns and
their events. #676 backfills, #677 switches the writes, #678 switches the reads.
