# EV-07: atomic library-stream sequence allocation — implementation plan

Design: [Atomic library-stream sequence allocation](../specs/2026-08-21-issue-661-stream-sequence-allocation-design.md).
Schema it writes to: [#660's event schema](../specs/2026-08-21-issue-660-library-event-schema-design.md).

**Goal:** make `games/events/` the only writer of `LibraryEvent`, allocating
contiguous per-library sequences under the stream-head lock, inside the caller's
transaction.

**Constraints:** no schema change, no migration. READ COMMITTED is a
precondition, not an assertion. The only exception this module raises is
`TransactionRequired`; every database error propagates untranslated.

## Task 1 — package and value types

Files: `games/events/__init__.py` (new, empty — `games/views/__init__.py` is the
precedent), `games/events/append.py` (new).

1. `type SourceMetadata = dict[str, Any]` with an example value in a trailing
   comment, per CLAUDE.md's primitive-role rule.
2. `NewEvent`: frozen slotted dataclass, per-event fields only — `event_type`,
   `aggregate_type`, `aggregate_id`, `payload`, `payload_schema_version=1`,
   `effective_time=None`, `causation_id=None`.
3. `AppendResult`: frozen slotted dataclass — `stream_id`, `first_sequence`,
   `last_sequence`, `events: tuple[LibraryEvent, ...]`.
4. `TransactionRequired(RuntimeError)`.

No test of its own; Task 3's tests are the first consumer.

## Task 2 — `lock_stream`

File: `games/events/append.py`.

1. Guard: `transaction.get_connection(router.db_for_write(LibraryEvent))` —
   not the `default` singleton — and raise `TransactionRequired` when
   `in_atomic_block` is false. This must run **before** any query: the hazard it
   prevents is `get_or_create` autocommitting a head row, not the
   `select_for_update`, which raises on its own.
2. Lock-then-provision, in this order (one round trip in the common case, and no
   window where a concurrent library delete turns a follow-up lookup into an
   unhandled `DoesNotExist`):
   - `select_for_update().get(library=library)`;
   - on `DoesNotExist`, `get_or_create(library=library)` — Django wraps its
     `create()` in `atomic()` and falls back to `get()` on `IntegrityError`, so
     no hand-rolled savepoint — then re-select `FOR UPDATE` unconditionally, so
     the row is locked whichever branch produced it.
3. Define `LockedStream` in the same module — it holds the locked head row and
   exposes `stream_id` plus a mutable `current_sequence`. It is not a dataclass:
   `current_sequence` changes as appends land, and nothing constructs one except
   `lock_stream`.

Plain `FOR UPDATE`, not `no_key=True`: it also blocks out-of-band event inserts,
which nothing should be doing.

## Task 3 — `LockedStream.append` and `append_events`

File: `games/events/append.py`. Test: `tests/test_event_append.py` (new).

1. `append(events, *, actor, correlation_id, idempotency_key,
   source_metadata=None, recorded_at=None) -> AppendResult`:
   - empty `events` → `ValueError`, before anything else;
   - one `recorded_at` for the whole call (`timezone.now()` when not given);
   - `source_metadata or {}` — the column is NOT NULL with `default=dict`;
   - sequences `current_sequence + 1 …`, one `bulk_create`, then
     `head.save(update_fields=["current_sequence"])`, then update the instance's
     `current_sequence` so a second `append` on the same `LockedStream`
     continues the range.
2. `append_events(library, events, **kwargs)` = `lock_stream(library).append(...)`.
   One implementation, no duplicated logic.
3. Tests under plain `django_db`: first append provisions a head and starts at
   1 · second append continues without a gap · multi-event append is contiguous
   and shares one `correlation_id` and one `recorded_at` · two appends on one
   `LockedStream` continue the range · rollback leaves the table and
   `current_sequence` untouched · empty sequence rejected · two libraries
   independent · `AppendResult` matches the persisted rows · `actor=None`
   accepted · `source_metadata=None` stored as `{}` · `append_events` and the
   primitive produce identical rows.

Reuse the `owned_library` fixture; a second library comes from
`django_user_model.objects.create_user(...).library`, as in
`tests/test_event_models.py`.

`make test ARGS="tests/test_event_append.py -x"`.

## Task 4 — the three `transaction=True` tests

File: `tests/test_event_append.py`.

Plain `django_db` builds a `TestCase` subclass that wraps every test in an
atomic block, so `in_atomic_block` is always true and the first test below is
unwritable without `transaction=True`.

1. **Outside a transaction:** `lock_stream` raises `TransactionRequired` and no
   head row exists afterwards.
2. **Lock probe:** open an append transaction, then from a raw
   `psycopg.connect(**connection.get_connection_params())` assert `SELECT … FOR
   UPDATE NOWAIT` against that head fails. Follow
   `tests/test_purchase_uuid_primary_key.py:315-345` — it uses `SET LOCAL
   lock_timeout` and catches `psycopg.errors.LockNotAvailable`; `NOWAIT` raises
   the same class. No thread needed.
3. **Contention:** two threads, two events each, forced to overlap rather than
   left to chance — a `connection.execute_wrapper` in thread A signals once it
   holds the lock, and only then does B start. Follow
   `tests/test_library_conversion.py:815-850` exactly for the harness shape:
   every `Event.wait()` and `join()` carries a timeout, thread bodies append
   exceptions to an `errors` list, and every thread calls
   `close_old_connections()` in a `finally`. Assert the union of assigned
   sequences is exactly 1…4, no duplicates, one shared `stream_id`.

Without the forced overlap the union assertion passes under fully serial
execution and proves nothing. Without the timeouts and the `finally`, a failure
hangs the suite: an unbounded barrier blocks forever, and a thread leaking an
open transaction blocks `TransactionTestCase`'s truncation teardown.

`make test ARGS="tests/test_event_append.py -x" PYTEST_WORKERS=0` — run these
serially while iterating; parallel output interleaves and `-x` stops only the
worker that hit the failure.

## Task 5 — migration-rewind interaction

These are the first tests to commit rows into `games_libraryevent`, and #660's
migration `0023` refuses reversal while either table has rows.

Run the rewind harnesses together with the new file and confirm no
ordering-dependent failure:

```
make test ARGS="tests/test_event_append.py tests/test_event_schema_migration.py tests/test_catalog_hierarchy_migration.py tests/test_shared_catalog_migration.py tests/test_external_reference_migration.py tests/test_purchase_uuid_primary_key.py"
```

`TransactionTestCase` truncation should clear the rows before any rewind runs.
If it does not, the fix belongs here — not in `0023`'s guard, which is behaving
as designed.

## Task 6 — gate

`make check` in full, including `e2e/`. Never a subset.

`make audit-uuid-identity` should be unaffected: no new tables, no new relation
columns.

## Notes for whoever implements this

- Do not add an `expected_sequence` parameter (#901) or any idempotency
  behaviour — repeating a key appends again, by design, until #662.
- Do not translate `IntegrityError`/`OperationalError`/`DataError`/
  `ValidationError` into module exceptions; #663 classifies them.
- Do not add a savepoint around `bulk_create`. A failed insert aborts the
  transaction, and retry belongs at the boundary above.
- Do not register signals on `LibraryEvent`; `bulk_create` emits none, and #665
  is already told so.
