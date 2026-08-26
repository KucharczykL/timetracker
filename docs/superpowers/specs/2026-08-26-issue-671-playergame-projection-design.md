# The PlayerGame projection

Issue [#671](https://github.com/KucharczykL/timetracker/issues/671). The code is
in `games/models.py`, `games/events/playergame.py`,
`games/commands/playergame.py` and `games/projectors/playergame.py`.

`PlayerGame` records that a library tracks a catalog game. There is one row for
each tracked game. It is the first projection table of the application.

## The table

`PlayerGame` is a subclass of `ProjectionModel`. Only a projector writes it.

The primary key is the `aggregate_id` of the creation event. `UUIDv7Field`
supplies a minted default and a database default. This model refuses both.
`games.checks` E004 and E005 refuse a default on a projection. A default makes a
rebuild write an identity that the live table does not have.

`tracked_at` is the `recorded_at` of the creation event. It has no default. E006
refuses one.

`game` is a foreign key to `Game`. Its delete rule is `RESTRICT`.

A unique constraint over `(library, game)` permits one row for each pair. Two
libraries can track one shared game. Each library gets its own row.

## Retention

A retirement must not delete a projection row. `archive_or_delete()` collects
the rows that cascade from a game. It collects with `fail_on_restricted=False`.
The cascade then runs, and the projection rows stay. A replay writes those rows
again. A delete would make the live table and the rebuilt table disagree.

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

`build()` resolves a game that this library can see. A visible game is private
to the library or shared. An archived game is not visible. Any other game causes
a `CommandRejected`, which tells the caller nothing about another library.

`build()` refuses a game that this library tracks already.

`build()` returns one creation event.

## The projector

`PlayerGames` is in the `CURRENT_STATE` family.

The handler writes `self.target.model(PlayerGame)`, not the imported model. A
shadow rebuild then sends the write to its temp table.

The handler keys the write on the `aggregate_id` of the event. A second fold of
one event writes no second row.

The handler reads the library from the event. Thus a replay reproduces the same
ownership.

## Command names

Each command names itself with a member of a `CommandVocabulary`. `CommandName`
is the vocabulary of the application, and it holds real commands only. A test
declares its own vocabulary. The registry keys on the name, so two vocabularies
cannot claim one name. A name is a domain symbol, not a Python path, and the
fingerprint reads it. Thus a move or a rename keeps an idempotency key valid.

## Out of scope

No view, form or API calls the command. #672–#675 add the state columns and
their events. #676 backfills, #677 switches the writes, #678 switches the reads.
