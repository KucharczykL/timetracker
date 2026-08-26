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

`Projector` gets one method. It is the only sanctioned way a family writes a row.

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

## The statement

On the live path and on the shadow path, the call gives one statement:

```sql
INSERT INTO "games_playergame" ("library_id", "id", "game_id", "tracked_at")
VALUES (%s, %s, %s, %s)
ON CONFLICT("id") DO UPDATE SET "library_id" = EXCLUDED."library_id", ...
```

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

`ProjectorRegistry.apply` re-raises the error with its note. `run_in_transaction`
reads the SQLSTATE and re-runs the whole transaction from the start. The absent
inner savepoint changes nothing that a caller can observe.

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

## Out of scope

- The 60-second rebuild budget.
- The `Projector` contract change that a batched replay needs: handlers would
  return rows instead of writing them.
- `ShadowTarget.starts_empty`, the issue's second option. It puts a performance
  concern in the projector API, and the upsert makes it unnecessary.
