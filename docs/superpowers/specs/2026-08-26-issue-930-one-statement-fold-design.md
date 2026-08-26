# A fold of one statement per event

Issue [#930](https://github.com/KucharczykL/timetracker/issues/930). The code is
in `games/events/projection.py`. The numbers are in
[Event benchmarks](../../event-benchmarks.md), which costs a batched replay for
[#932](https://github.com/KucharczykL/timetracker/issues/932).

## The method

`Projector.project()` takes a model, an identity and the columns. It asks its
target for the model, builds the row with the identity on the primary key, and
calls `bulk_create` with `update_conflicts=True`. One statement reaches
PostgreSQL: `INSERT ... ON CONFLICT ("id") DO UPDATE SET ...`.

`unique_fields` holds `pk`, not `id`, so a key with a different name needs no
exception. The identity goes on the instance after construction, because
`Model(pk=...)` is not a valid argument.

`projection.py` holds no runtime ORM reference. `ProjectionModel` is imported
under `TYPE_CHECKING`, because a PEP 695 bound evaluates lazily.

## The whole row

A call passes each column of the row, but not the key or a generated column.

`DO UPDATE` writes only the columns it names. A partial call is correct against
a row that exists. Against an absent row it inserts nulls and defaults, where a
`NOT NULL` column errors and a nullable one loses data quietly. A live fold
finds the row and a rebuild does not, so the rebuild swaps nulls in over the
live values.

`project()` refuses that call. `_required_columns` keeps each column that only a
fold fills; a key, a generated column, a default and an `auto_now` stamp are
filled by something else. A call that omits any other column raises a
`TypeError` naming them. The check is cached per model and costs 0.19 µs.

A second fold writes the same row, by primary key, with no read.

## One statement on both paths

Both paths give the same statement. `ProjectionTarget` supplies the model, so a
rebuild writes `games_playergame__shadow`; `write_targets` reads that name, and
`only_shadow_writes` sees what it guards. `LIKE ... INCLUDING ALL` copies the
primary key index that `ON CONFLICT` infers.

There is no savepoint and no `SELECT`. `bulk_create` opens its transaction with
`savepoint=False`, and a fold always runs inside one: under the stream-head lock
in `LockedStream.append`, and in `transaction.atomic()` in `replay_into_shadow`.

`bulk_create` sends no `post_save`, and no receiver listens to a projection
model. A receiver firing during a shadow replay would write a live table, which
`only_shadow_writes` refuses.

## A second constraint

`PlayerGame` has a second unique constraint, `(library, game)`. A fold with a
new identity for a game the library tracks violates it, and `ON CONFLICT (id)`
does not absorb a violation of a different index: the fold raises
`IntegrityError`.

Do not answer that error with an update by primary key. That key is not in the
table. Zero rows change, no error leaves the handler, and the event folds into
nothing.

`is_retryable` retries a unique violation only for
`LIBRARY_EVENT_SEQUENCE_CONSTRAINT`, so a `(library, game)` collision fails on
the first attempt.

## Out of scope

A handler that deletes a row, or changes a subset of the columns another event
created. The first arrives with the untrack event, and specifies its shape.
