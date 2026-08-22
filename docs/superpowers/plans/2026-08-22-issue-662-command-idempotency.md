# EV-08: command idempotency records — implementation plan

Design: [Command idempotency records](../specs/2026-08-22-issue-662-command-idempotency-design.md).
Builds on: [#661's append module](../specs/2026-08-21-issue-661-stream-sequence-allocation-design.md),
[#660's event schema](../specs/2026-08-21-issue-660-library-event-schema-design.md).

**Goal:** a repeated `(library, idempotency_key)` returns the original sequence
range instead of appending again, and the same key with different command input
is rejected.

**Constraints:** one new table and migration `0024`. The check runs under the
head lock `lock_stream` already takes. `IdempotencyKeyMismatch` is the only new
exception; every database error still propagates untranslated to #663.

## Task 1 — the record model and migration `0024`

Files: `games/models.py` (after `LibraryEvent`), `games/migrations/0024_*.py` (generated).

1. `LibraryIdempotencyRecord` with the fields and constraints in the design's
   Schema table. Manager is `LibraryOwnedQuerySet.as_manager()`, matching
   `LibraryEvent`; declare it as `LibraryIdempotencyRecordQuerySet(LibraryOwnedQuerySet)`
   only if a method is needed — it is not, so use `LibraryOwnedQuerySet` directly.
2. `__str__` returns the key, not the pk.
3. `make makemigrations` (the target passes `--noinput`; running
   `manage.py makemigrations` directly will prompt and hang).
4. **Read the generated migration before committing.** It must:
   - depend on `("games", "0023_library_event_schema")`;
   - contain no `RunPython` — in particular no copy of `0023`'s
     `refuse_rollback_with_recorded_history`. This table is reconstructible from
     the events; the design says so, and adding the guard is the expected wrong
     move;
   - render `id` as `UUIDv7Field(db_default=PostgreSQLUUIDv7(), default=uuid.uuid7, …)`,
     matching `0023`'s two tables.
5. `make migrate` and confirm it applies.

Reversibility is pinned as a test, not checked by hand — `make migrate` takes no
arguments and CLAUDE.md forbids reaching around the Makefile with a raw
`uv run manage.py migrate games 0023`. Add a `django_db(transaction=True)` test
following the `MigrationExecutor` harness in
`tests/test_event_schema_migration.py:27-44`: seed one record, reverse to
`("games", "0023_library_event_schema")`, assert it succeeds **with records
present** — that is the behavioural difference from `0023`, which refuses — then
migrate forward to the leaf nodes in the fixture teardown exactly as that file
does.

Test: `tests/test_event_idempotency.py` (new) — start it here with the
constraint tests, which need no application code:

- a duplicate `(library, idempotency_key)` insert raises `IntegrityError`;
- the same key under two libraries inserts fine;
- `first_sequence=0`, `last_sequence < first_sequence`, `idempotency_key=""`,
  and `request_fingerprint=""` each raise `IntegrityError`.

Wrap each expected failure in its own `transaction.atomic()` block — a violated
constraint aborts the surrounding transaction, so a second assertion in the same
block fails for the wrong reason.

`make test ARGS="tests/test_event_idempotency.py -x"`.

## Task 2 — `fingerprint_command_input`

File: `games/events/idempotency.py` (new). Test: `tests/test_event_idempotency.py`.

```python
type IdempotencyKey = str  # "session-create-01J8Z3K4M5N6P7Q8R9S0T1U2V3"
type RequestFingerprint = str  # "9f86d081884c7d65…" (sha256 hex)
```

Canonical form is `json.dumps(command_input, sort_keys=True,
separators=(",", ":"), default=_encode_command_value)`, then
`hashlib.sha256(canonical.encode("utf-8")).hexdigest()`.

`_encode_command_value` handles exactly `uuid.UUID` → `str`, `datetime` →
`.isoformat()`, `Decimal` → `str`. Anything else falls through to `json`'s own
`TypeError`; **do not add a `repr()` fallback** — a hash that varies by process
rejects honest retries, which is worse than the error it would hide.

Tests: key order does not change the digest · a changed value does · nested
dicts are sorted too · list order *is* significant · `UUID`/`datetime`/`Decimal`
accepted · a `set` raises `TypeError` · the digest is 64 lowercase hex
characters.

## Task 3 — `idempotent_append`

File: `games/events/idempotency.py`. Test: `tests/test_event_idempotency.py`.

```python
class IdempotencyKeyMismatch(ValueError): ...


@dataclass(frozen=True, slots=True)
class ReplayedAppend:
    stream_id: uuid.UUID
    first_sequence: int
    last_sequence: int


def idempotent_append(
    library: UserLibrary,
    *,
    idempotency_key: IdempotencyKey,
    request_fingerprint: RequestFingerprint,
    build: Callable[[LockedStream], Sequence[NewEvent]],
    actor: User | None,
    correlation_id: uuid.UUID,
    source_metadata: SourceMetadata | None = None,
    recorded_at: datetime | None = None,
) -> AppendResult | ReplayedAppend: ...
```

Body order, all inside the caller's transaction:

1. `stream = lock_stream(library)` — inherits `TransactionRequired`; add no
   second guard.
2. `record = LibraryIdempotencyRecord.objects.filter(library=library,
   idempotency_key=idempotency_key).first()`. No `select_for_update`: the head
   lock is the serialization point, and a second lock would be one more thing to
   order.
3. `record` found, fingerprint equal → `ReplayedAppend(stream.stream_id,
   record.first_sequence, record.last_sequence)`. `build` must not have been
   called by this point.
4. `record` found, fingerprint differs → `raise IdempotencyKeyMismatch(...)`.
   Message names the key and the library, never the two digests.
5. Otherwise `events = build(stream)`, then `stream.append(events, …)`, then
   create the record from `result.first_sequence`/`last_sequence`.

`actor` is annotated `User`, not `AbstractBaseUser` — the project defines no
`AUTH_USER_MODEL`, so `auth.User` is the concrete model the foreign key accepts.
#661 hit this in mypy; do not rediscover it.

Tests (plain `django_db`, each in its own `transaction.atomic()` where a write
must commit or roll back):

- fresh command → `AppendResult`, exactly one record, its range equal to the
  result's;
- repeat with the same key and fingerprint → `ReplayedAppend` equal to the
  original range, no new events, `current_sequence` unchanged, still one record;
- the repeat does not call `build` — pass a callback that appends to a list and
  assert the list is untouched;
- different fingerprint, same key → `IdempotencyKeyMismatch`, nothing written,
  **and the same transaction then completes a different command successfully**
  (this is the point of raising before any write);
- one key in two libraries → two records, two independent ranges;
- a multi-event `build` → N events, one record whose range spans them;
- `build` returning `[]` → `ValueError` from `append`, no record, and the key is
  reusable afterwards;
- a rolled-back command leaves neither events nor record, and the key works on
  the next attempt.

`make test ARGS="tests/test_event_idempotency.py -x"`.

## Task 4 — delete `append_events`

Files: `games/events/append.py`, `tests/test_event_append.py`.

1. Delete `append_events` and its import in the test module.
2. The test module's local `append(library, events=None, **overrides)` helper
   becomes `lock_stream(library).append(events or [make_new_event()], **fields)`.
   Every existing test keeps working through it, including the two
   `transaction=True` ones.
3. Delete `test_convenience_function_matches_the_primitive` — it tested that the
   convenience and the primitive agree, and there is no longer a convenience.

Nothing outside `tests/test_event_append.py` imports it; confirm with
`grep -rn "append_events" --include='*.py' .` before and after.

`make test ARGS="tests/test_event_append.py tests/test_event_idempotency.py -x"`.

## Task 5 — the concurrent-duplicate test

File: `tests/test_event_idempotency.py`, `@pytest.mark.django_db(transaction=True)`.

Two threads issue **the same key** against one library. Copy the harness shape
from `tests/test_event_append.py`'s contention test verbatim — the
`connection.execute_wrapper` that fires on
`"games_libraryeventstreamhead" in sql and "FOR UPDATE" in sql`, the holder/waiter
`threading.Event` pair, timeouts on every `wait()` and `join()`, thread failures
collected into an `errors` list, `close_old_connections()` in each `finally`.

Assert: the library holds N events, not 2N · exactly one record · both callers
received the same `(first_sequence, last_sequence)` · one of the two returns
`AppendResult` and the other `ReplayedAppend`, without asserting which — thread
scheduling decides the winner, and pinning it would make the test flaky rather
than stricter.

Without the forced overlap the test passes under serial execution and proves
nothing. Without the timeouts and the `finally`, a failure hangs the suite: an
unbounded barrier blocks forever and a thread leaking an open transaction blocks
`TransactionTestCase` truncation.

`make test ARGS="tests/test_event_idempotency.py -x" PYTEST_WORKERS=0` — run
these serially while iterating.

## Task 6 — migration-rewind interaction

`0024`'s table joins the set of tables the rewind harnesses in `tests/` pass
through. Run them together with the new file:

```
make test ARGS="tests/test_event_idempotency.py tests/test_event_append.py tests/test_event_schema_migration.py tests/test_catalog_hierarchy_migration.py tests/test_shared_catalog_migration.py tests/test_external_reference_migration.py tests/test_purchase_uuid_primary_key.py"
```

`0024` has no rollback guard, so it should rewind silently. A failure here means
`TransactionTestCase` truncation is leaving records behind — fix it in the test,
not by adding a guard to the migration.

## Task 7 — gate

`make check` in full, including `e2e/`. Never a subset.

`make audit-uuid-identity` separately. It should pass with no new entry in
`games/identity_audit.py`: the table's order source is `created_at`
(`DEFAULT_ORDER_SOURCE`) and its only relation column is `library_id`, already a
`uuid_v7`. **If it fails, that is a finding, not a licence to add a registry
entry** — check first that the model matches the design's schema table.

## Notes for whoever implements this

- Do not add `expected_sequence` (#901), retry or backoff (#663), projector
  dispatch (#665), or a command object (#664).
- Do not translate `IntegrityError` from the record insert. It means the head
  lock failed to serialize two commands with one key, and the constraint name
  says that better than a wrapper would.
- Do not add a pruning command or a TTL. A pruned key becomes executable a
  second time; the design records this as deliberate.
- Do not store the canonical input alongside the hash "for debugging". The
  design weighed it and rejected it on retention grounds.
- Follow CLAUDE.md's naming rules: PEP 695 `type` aliases for the two string
  roles with an example value in a trailing comment, complete words in every
  identifier (`command_input`, not `payload` or `data`).

## Follow-up issues to file

None. Every deferral in the design already has a numbered owner (#663, #664,
#665, #666, #901).
