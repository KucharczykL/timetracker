# The stream key is checked at commit (#1450)

## Defect

`make purge-library` failed for a library that holds an add-on. PostgreSQL
refused the delete of the stream head:

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
`library_event_stream_matches_library` is a raw-SQL composite key. It was
created without `DEFERRABLE`, so PostgreSQL checks it at each statement.
It is the only key in the schema with this property.

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

- `anonymize_sample` keeps the stream head id. An immediate key was the
  reason; that reason is gone. #1454 re-mints it.
- The Collector's self-dependency stays a Django property. Any later
  raw-SQL foreign key must be `DEFERRABLE INITIALLY DEFERRED` too.
- `make verify-baseline` against a dump from before that migration reports this
  constraint's definition as drift. Run it with `--migrate`.
- The fix is the last member of the purchase stack (#723 and after). Its
  migration takes the number after the stack's last. The stack's numbers
  stay fixed, because its specs and its deploy rehearsal name them.

## Tests

- `tests/test_retention.py`: a purge of a library with a parented add-on
  and a tracked game removes every event and every game. The module's
  `untracked_games` mark is necessary. Without it, `TrackGame` writes no
  event and the test passes with no events.
- `tests/test_event_models.py`: `pg_constraint` holds no immediate foreign
  key; a cross-library event fails at `check_constraints()`.

## Follow-up issues

- #1454: `anonymize_sample` re-mints the stream head id.
