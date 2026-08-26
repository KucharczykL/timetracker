# A fold of one statement per event

Issue [#930](https://github.com/KucharczykL/timetracker/issues/930). Split out of
[#670](https://github.com/KucharczykL/timetracker/issues/670). Parent phase:
[#601](https://github.com/KucharczykL/timetracker/issues/601).

The current-state family writes its row with `update_or_create`. Django expands
that call into six statements:

```
SAVEPOINT -> SELECT ... FOR UPDATE -> SAVEPOINT -> INSERT -> RELEASE -> RELEASE
```

One statement writes the row. The other five look for a row that neither write
path can hold: a live append mints a new `aggregate_id`, and a replay starts from
an empty shadow table. The recorded benchmark gives 6.00 statements per folded
event, and 59.24 s of replay against a 60 s budget, with one family in existence.

This design replaces the six statements with one. The fold becomes an upsert.

## The change

`Projector` gets one method. It is how a family writes a whole row from one
event. A family that must delete a row, or change a subset of columns on a row
another event created, is not designed here: the first such handler arrives with
the untrack event, and it specifies its own shape.

```python
def project[M: ProjectionModel](
    self, model: type[M], identity: uuid.UUID, **columns: Any
) -> None:
    projected = self.target.model(model)
    row = projected(**columns)
    row.pk = identity
    projected.objects.bulk_create(
        [row],
        update_conflicts=True,
        update_fields=list(columns),
        unique_fields=["pk"],
    )
```

`PlayerGames._created` becomes one call to it. `update_or_create` leaves the
codebase.

The method takes `pk`, not `"id"`. Django permits the primary key in
`unique_fields`, so a projection whose key has another name needs no exception.
The identity goes on the instance after construction, because `Model(pk=...)` is
not a valid constructor argument.

`projection.py` holds no runtime ORM reference, and this method does not add
one. `ProjectionModel` is imported under `TYPE_CHECKING`, as `targets.py` already
imports it: a PEP 695 type parameter bound is evaluated lazily, and the manager
the method calls arrives with the model the family passes. #914 bought that
property; a convenience import would spend it.

**A call passes every column of the row, except the key and any generated
column.** The rule is not decoration. `DO UPDATE` writes only the columns it
names, so a partial call updates an existing row correctly — and then inserts a
row of nulls and defaults on the day the row is absent. A `NOT NULL` column
turns that into an error; a nullable one turns it into silent loss. The helper
therefore has one shape: the whole row, from the event that owns it. Django also
refuses an empty `columns`, because `update_fields` cannot be empty.

## The statement

On the live path and on the shadow path, the call gives one statement:

```sql
INSERT INTO "games_playergame" ("library_id", "id", "game_id", "tracked_at")
VALUES (%s, %s, %s, %s)
ON CONFLICT("id") DO UPDATE SET "library_id" = EXCLUDED."library_id", ...
```

Both paths are measured, not assumed. The shadow path gives the same statement
against `games_playergame__shadow`, and `write_targets` reads that target, so
`only_shadow_writes` still sees what it guards. The temp table is created with
`LIKE ... INCLUDING ALL`, which copies the primary key index that `ON CONFLICT`
infers, and the `(library, game)` index with it.

There is no savepoint, no `SELECT`, and no `RETURNING`. `bulk_create` opens its
transaction with `savepoint=False`, and the fold already runs inside one:
`LockedStream.append` folds under the stream-head lock, and
`replay_into_shadow` wraps the replay in `transaction.atomic()`.

That last fact also rejects the issue's first option. A `create()` in a nested
`atomic()` costs `SAVEPOINT`, `INSERT` and `RELEASE`, because the enclosing
transaction is always open. Three statements, not one.

## Idempotency

A re-fold writes the same row from the same event. The key enforces it, in place
of a read. The property is unchanged; only its mechanism moves into the database.

## The constraint the fallback would have hidden

`PlayerGame` holds a second unique constraint, `(library, game)`. A fold that
carries a new `aggregate_id` for a game the library already tracks violates it.

- Today, `update_or_create` raises `IntegrityError`.
- `ON CONFLICT (id)` does not absorb a violation of another index. It raises the
  same error.
- The issue's option 1 catches `IntegrityError`, then updates by a primary key
  that is not in the table. Zero rows change and no error leaves the handler. The
  event folds into nothing.

This is a second reason to prefer the upsert, independent of the statement count.

## Errors and retries

`ProjectorRegistry.apply` re-raises the error with its note. `is_retryable`
answers a unique violation with the constraint name: only
`LIBRARY_EVENT_SEQUENCE_CONSTRAINT` is retried, so a `(library, game)` collision
fails the command on its first attempt. That is the rule today, and the upsert
raises the same error against the same constraint.

`run_in_transaction` re-runs the whole transaction, so the absent inner savepoint
changes nothing a caller can observe. The one visible difference is inside a
failed transaction: `update_or_create` rolls back to its savepoint and leaves the
transaction usable, and the upsert does not. No caller continues in a transaction
that a fold has failed.

## Signals

`bulk_create` sends no `post_save`. `update_or_create` sends one. No receiver
listens to a projection model, so the change is inert today.

It is also correct. A projection row is derived state. A receiver that fires
during a shadow replay writes a live table, and `only_shadow_writes` refuses that
statement.

## What the tests hold

| Test | Claim |
|---|---|
| `test_folding_one_event_costs_one_statement` | the slope between 10 and 30 events is 1.0 |
| a re-fold test | a second fold of one event gives one row and one statement |
| a collision test | a new identity on a tracked game raises `IntegrityError` |

The first test replaces `test_folding_one_event_costs_six_statements`, whose
docstring names this issue. `test_the_fold_counts_the_shadow_table_as_its_projection`
holds at 10 statements for 10 events and needs no change.

## The recorded numbers

`make bench ARGS="--gate"` and `make bench ARGS="--gate --no-count-fold"` run on
the machine that [Event benchmarks](../../event-benchmarks.md) defines. The
recorded run, the rebuild verdict, and the cost-per-event table are rewritten
from that output.

Three numbers there move, not one. The fold goes from 6.00 statements per event
to 1.00. The command goes from 14 statements to 9, because one dispatch folds one
event. The rebuild verdict section, which names this issue as "the standing lead
on the cheaper fold", is rewritten to say what the lead produced.

The projection row and statement counts per command do not move.
`test_one_dispatch_writes_one_projection_row_through_one_statement` asserts one
row through one statement today: the counter attributes a statement to a table
only when it writes, and the five statements this work removes write nothing.

The 60-second budget itself does not move. The issue excludes it: the charter
permits a revision only with a recorded benchmark and a design review, and this
work is an attempt to make the revision unnecessary.

## The costing of a batched replay

The issue names batching as the largest remaining win. This work does not build
it, and does not guess at it either.

After the fold is one statement, the replay holds per-event Python —
`RecordedEvent.from_row`, the registry dispatch, and one SQL compilation per
`bulk_create` — and one round trip for each event. A throwaway measurement times
a chunked `bulk_create` of the same row count against the same table. That gives
a ceiling for a batched replay.

Both numbers go in the benchmark document. A follow-up issue then opens with a
measured ceiling rather than an estimate.

## What would falsify this

Statements are not the only cost in a replay. If the re-recorded rebuild still
consumes most of the 60 seconds, this work removed five statements an event and
did not buy the headroom the second projector family needs.

That outcome does not invalidate the change, and it is not treated as a failure
to hide. It moves the costing section from a supporting note to the result: the
follow-up issue for a batched replay opens immediately, with the measurement that
argues for it, and the charter's budget conversation happens on evidence.

## Out of scope

- The 60-second rebuild budget.
- The `Projector` contract change that a batched replay needs: handlers would
  return rows instead of writing them.
- `ShadowTarget.starts_empty`, the issue's second option. It puts a performance
  concern in the projector API, and the upsert makes it unnecessary.
