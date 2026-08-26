# A fold of one statement per event

Issue [#930](https://github.com/KucharczykL/timetracker/issues/930). The code is
in `games/events/projection.py`.

A projector writes one row for one event. `Projector.project()` does that with
one statement.

## The method

`project()` takes a model, an identity and the columns of the row. It asks its
target for the model, builds the row, and puts the identity on the primary key.
It then calls `bulk_create` with `update_conflicts=True`. PostgreSQL receives
one statement:

```sql
INSERT INTO "games_playergame" ("library_id", "id", "game_id", "tracked_at")
VALUES (%s, %s, %s, %s)
ON CONFLICT("id") DO UPDATE SET "library_id" = EXCLUDED."library_id", ...
```

`unique_fields` holds `pk`, not `id`. Thus a projection whose key has a
different name needs no exception. The identity goes on the instance after
construction, because `Model(pk=...)` is not a valid constructor argument.

`projection.py` holds no runtime ORM reference. `ProjectionModel` is imported
under `TYPE_CHECKING`, because a PEP 695 bound is evaluated lazily. The manager
arrives with the model that the family supplies.

## The whole row

A call passes each column of the row. It does not pass the key. It does not pass
a generated column.

`DO UPDATE` writes only the columns that it names. A partial call is correct
against a row that exists. Against a row that is absent, the same call inserts
nulls and defaults: a `NOT NULL` column makes an error, and a nullable column
makes a quiet loss of data. Django refuses an empty set of columns, because
`update_fields` cannot be empty.

## Idempotency

A second fold of one event writes the same row. The primary key enforces this.
There is no read before the write.

## One statement on both paths

The live path and the shadow path give the same statement. `ProjectionTarget`
supplies the model, so a rebuild writes `games_playergame__shadow`.
`write_targets` reads that name, and `only_shadow_writes` sees what it guards.
`LIKE ... INCLUDING ALL` copies the primary key index that `ON CONFLICT` infers.

There is no savepoint and no `SELECT`. `bulk_create` opens its transaction with
`savepoint=False`, and a fold always runs inside one: `LockedStream.append`
folds under the stream-head lock, and `replay_into_shadow` wraps the replay in
`transaction.atomic()`.

## A second constraint

`PlayerGame` has a second unique constraint, `(library, game)`. A fold with a
new identity for a game that the library tracks violates it. `ON CONFLICT (id)`
does not absorb a violation of a different index. The fold raises
`IntegrityError`.

Do not answer that error with an update by primary key. That key is not in the
table. Zero rows change, no error leaves the handler, and the event folds into
nothing.

`is_retryable` retries a unique violation only for
`LIBRARY_EVENT_SEQUENCE_CONSTRAINT`. A `(library, game)` collision fails the
command on the first attempt.

## Signals

`bulk_create` sends no `post_save`. No receiver listens to a projection model. A
receiver that fired during a shadow replay would write a live table, and
`only_shadow_writes` refuses that statement.

## The measured cost

[Event benchmarks](../../event-benchmarks.md) holds the numbers, and costs a
batched replay for
[#932](https://github.com/KucharczykL/timetracker/issues/932).

## Out of scope

A handler that deletes a row, or that changes a subset of the columns of a row
that another event created. The first such handler arrives with the untrack
event, and it specifies its own shape.
