# The stream key is checked at commit (#1450)

## Defect

Without this change, `make purge-library` fails for a library that holds an
add-on. PostgreSQL refuses the delete of the stream head:

```text
IntegrityError: update or delete on table "games_libraryeventstreamhead"
violates foreign key constraint "library_event_stream_matches_library"
```

## Cause

`Game.parent` is a self key with `RESTRICT`. Django's `RESTRICT` handler
calls `Collector.add_dependency(Game, Game)` and ignores nullability.
`Collector.sort()` cannot satisfy a dependency of a model on itself. It
then stops and keeps the collection order for every model, not only for
`Game`. In that order, the stream head can come before its events.

Django accepts this on PostgreSQL. Every foreign key Django creates is
`DEFERRABLE INITIALLY DEFERRED`, so the delete order does not matter.
`library_event_stream_matches_library` is a raw-SQL composite key. Created
without `DEFERRABLE`, PostgreSQL checks it at each statement; it is the only
such key in the schema.

## Decision

Migration `defer_library_event_stream_matches_library` makes the constraint `DEFERRABLE INITIALLY DEFERRED`.
The reverse makes it `NOT DEFERRABLE`.

The fix is on the constraint, not on the purge. The purge is the one
production caller today. But every other foreign key in the schema is
deferred, and the `Collector` depends on that property. A purge-only change,
such as a delete of events first, keeps one key outside that property. A
test now refuses any immediate foreign key.

The constraint keeps its refusal. A cross-library event still fails, at
commit or at `connection.check_constraints()`. No command can write such an
event: `append` copies `library_id` from the head to each event.

## Consequences

- `anonymize_sample` keeps the stream head id, a leftover it lists. The
  key no longer stops a re-mint; #1454 does it.
- `anonymize_sample` and `load_sample_data` call
  `connection.check_constraints()`, so a deferred key is checked before the
  dump is written and before the replay.
- The Collector's self-dependency stays a Django property. Any later
  raw-SQL foreign key must be `DEFERRABLE INITIALLY DEFERRED` too.
- `make verify-baseline` against a dump from before that migration reports
  this constraint's definition as drift. Run
  `make verify-baseline ARGS="--migrate"`.

## Tests

- `tests/test_retention.py`: a purge of a library with a parented add-on
  and a tracked game removes every event, the stream head and every game,
  directly and through `purge_user_library`. Each test first asserts the
  events exist.
- `tests/test_event_models.py`: `pg_constraint` holds no immediate foreign
  key; a cross-library event fails at `check_constraints()`.

## Follow-up issues

- #1454: `anonymize_sample` re-mints the stream head id.
