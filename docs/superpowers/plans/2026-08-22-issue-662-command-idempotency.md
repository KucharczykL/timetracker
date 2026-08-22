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

1. `LibraryIdempotencyRecordQuerySet(LibraryOwnedQuerySet)` with no added
   methods, then `LibraryIdempotencyRecord` using
   `LibraryIdempotencyRecordQuerySet.as_manager()`. The empty per-model queryset
   is the convention — `LibraryEventQuerySet` at `games/models.py:1332` is
   exactly that.
2. Fields and constraints per the design's Schema table. `id` is
   `UUIDv7Field(primary_key=True, editable=False)`; `editable=False` is **not**
   implied by `primary_key=True` (only `serialize=False` is), and omitting it
   produces a migration that does not match `0023`'s tables.
3. `fingerprint_version` is `PositiveSmallIntegerField` with **no default** —
   the writer always states it, so a row can never claim a version it was not
   hashed under.
4. `__str__` returns the key, not the pk.
5. `make makemigrations` (the target passes `--noinput`; running
   `manage.py makemigrations` directly prompts and hangs).
6. **Read the generated migration before committing.** It must depend on
   `("games", "0023_library_event_schema")`, contain no `RunPython` — in
   particular no copy of `0023`'s `refuse_rollback_with_recorded_history` — and
   render `id` as `UUIDv7Field(db_default=PostgreSQLUUIDv7(), default=uuid.uuid7,
   editable=False, primary_key=True, serialize=False)`, matching
   `games/migrations/0023_library_event_schema.py:56-62`.
7. `make migrate`.

Test: `tests/test_event_idempotency.py` (new) — start here with the constraint
tests, which need no application code:

- a duplicate `(library, idempotency_key)` insert raises `IntegrityError`;
- the same key under two libraries inserts fine;
- `first_sequence=0`, `last_sequence < first_sequence`, `idempotency_key=""`,
  `request_fingerprint=""`, and `fingerprint_version=0` each raise
  `IntegrityError`.

Wrap each expected failure in its own `transaction.atomic()` block — a violated
constraint aborts the surrounding transaction, so a second assertion in the same
block fails for the wrong reason.

Also assert reversibility directly, with no migration-rewind harness:

```python
def test_the_migration_is_reversible():
    migration = MigrationLoader(None).disk_migrations[("games", "0024_…")]
    assert not any(
        isinstance(operation, migrations.RunPython)
        for operation in migration.operations
    )
```

`0023` refuses reversal to protect the only copy of the user's history; this
table is operational metadata, so it must stay droppable. A `transaction=True`
rewind test would spend one of the suite's most expensive shapes proving the
absence of an operation.

`make test ARGS="tests/test_event_idempotency.py -x"`.

## Task 2 — `fingerprint_command_input`

File: `games/events/idempotency.py` (new). Test: `tests/test_event_idempotency.py`.

```python
type IdempotencyKey = str  # "session-create-01J8Z3K4M5N6P7Q8R9S0T1U2V3"
type RequestFingerprint = str  # "9f86d081884c7d65…" (sha256 hex)

FINGERPRINT_VERSION = 1
```

Canonical form is `json.dumps(command_input, sort_keys=True,
separators=(",", ":"), default=_encode_command_value)`, then
`hashlib.sha256(canonical.encode("utf-8")).hexdigest()`.

The parameter is `dict[str, Any]`, **not** `Mapping[str, Any]`: `json`'s encoder
dispatches on `isinstance(o, dict)`, so any other `Mapping` falls through to
`default=` and raises, and the wider annotation would promise an input the
implementation rejects.

`_encode_command_value` handles `uuid.UUID` → `str`, `datetime` →
`.isoformat()`, `date` → `.isoformat()`, `Decimal` → `str`, `TemporalValue` →
`.canonical`. **Order the `datetime` branch before the `date` branch**:
`datetime` subclasses `date`, so a `date`-first check swallows datetimes and a
missing `date` branch breaks on `Purchase.date_purchased`
(`games/models.py:707`). Anything else falls through to `json`'s own
`TypeError`; **do not add a `repr()` fallback** — a hash that varies by process
rejects honest retries, which is worse than the error it would hide.

Tests: key order does not change the digest · nested dicts are sorted too · list
order *is* significant · a changed value changes the digest · each of `UUID`,
`datetime`, `date`, `Decimal`, `TemporalValue` is accepted, with `datetime` and
`date` producing different digests for the same calendar day · a `set` raises
`TypeError` · the digest is 64 lowercase hex characters.

## Task 3 — `idempotent_append`

File: `games/events/idempotency.py`. Test: `tests/test_event_idempotency.py`.

```python
class IdempotencyKeyMismatch(Exception): ...


@dataclass(frozen=True, slots=True)
class ReplayedAppend:
    stream_id: uuid.UUID
    first_sequence: int
    last_sequence: int


def idempotent_append(
    library: UserLibrary,
    *,
    idempotency_key: IdempotencyKey,
    command_input: dict[str, Any],
    build: Callable[[LockedStream], Sequence[NewEvent]],
    actor: User | None,
    correlation_id: uuid.UUID,
    source_metadata: SourceMetadata | None = None,
    recorded_at: datetime | None = None,
) -> AppendResult | ReplayedAppend: ...
```

`IdempotencyKeyMismatch` derives from `Exception`, not `ValueError`:
`LockedStream.append` already raises `ValueError` for an empty event sequence
(`games/events/append.py:75-76`), and #663 must distinguish a user-visible
conflict from that programming error.

Body order, all inside the caller's transaction:

1. `stream = lock_stream(library)` — inherits `TransactionRequired`; add no
   second guard.
2. `record = LibraryIdempotencyRecord.objects.filter(library=library,
   idempotency_key=idempotency_key).first()`. No `select_for_update`: the head
   lock is the serialization point, and a second lock would be one more thing to
   order.
3. `record` found and `record.fingerprint_version != FINGERPRINT_VERSION` →
   return `ReplayedAppend` **without comparing digests**. The stored hash was
   produced by a canonicalizer this process no longer runs; replaying preserves
   the charter's primary rule and degrades only the mismatch guard.
4. `record` found, same version, digest equal → `ReplayedAppend(stream.stream_id,
   record.first_sequence, record.last_sequence)`. `build` must not have run.
5. `record` found, same version, digest differs → `raise IdempotencyKeyMismatch`.
   The message names the key and the library, never the two digests.
6. Otherwise `events = build(stream)`, then `stream.append(events, …)`, then
   create the record from `result.first_sequence`/`last_sequence`,
   `fingerprint_version=FINGERPRINT_VERSION`.

The fingerprint is computed once, at the top, from `command_input`. Do **not**
add a `request_fingerprint` parameter: it is a transparent `str` alias, so a
caller passing a constant would silently disable mismatch rejection — the same
class of omission the `build` callback exists to make impossible.

`actor` is annotated `User`, not `AbstractBaseUser` — the project defines no
`AUTH_USER_MODEL`, so `auth.User` is the concrete model the foreign key accepts.
#661 hit this in mypy; do not rediscover it.

Tests (plain `django_db`; each write that must commit or roll back gets its own
`transaction.atomic()` block, and `pytest.raises` goes *inside* that block):

- fresh command → `AppendResult`, exactly one record, range equal to the
  result's, `fingerprint_version == FINGERPRINT_VERSION`;
- repeat with the same key and input → `ReplayedAppend` equal to the original
  range, no new events, `current_sequence` unchanged, still one record;
- the repeat does not call `build` — pass a callback appending to a list and
  assert the list is untouched;
- different `command_input`, same key → `IdempotencyKeyMismatch`, nothing
  written, **and the same transaction then completes a different command
  successfully**;
- a record stored with `fingerprint_version=FINGERPRINT_VERSION + 1` and a
  deliberately wrong digest replays instead of raising;
- one key in two libraries → two records, two independent ranges;
- a multi-event `build` → N events, one record whose range spans them;
- `build` returning `[]` → `ValueError` from `append`, no record, key reusable;
- a rolled-back command leaves neither events nor record, and the key works on
  the next attempt.

`make test ARGS="tests/test_event_idempotency.py -x"`.

## Task 4 — delete `append_events`

Files: `games/events/append.py`, `tests/test_event_append.py`,
`docs/superpowers/specs/2026-08-21-issue-661-stream-sequence-allocation-design.md`.

1. Delete `append_events` and its import in the test module.
2. The test module's local `append(library, events=None, **overrides)` helper
   becomes `lock_stream(library).append(events or [make_new_event()], **fields)`
   — byte-for-byte what `append_events` did (`games/events/append.py:151-158`),
   so every existing test keeps working through it.
3. Delete `test_convenience_function_matches_the_primitive`.
4. **Delete the now-unused `from django.utils import timezone` import at
   `tests/test_event_append.py:9`.** Its only use is `timezone.now()` at line
   221, inside the test being deleted; leaving it fails ruff F401 and therefore
   `make check`.
5. Amend #661's spec at lines 74-76, 276-278, and 315 to record that this issue
   removed the function, and comment the same on issue #661. A shipped spec that
   describes a function the codebase no longer has is how the next reader
   reinvents it.

Confirm with `grep -rn "append_events" --include='*.py' .` before and after.

`make test ARGS="tests/test_event_append.py tests/test_event_idempotency.py -x"`.

## Task 5 — the concurrent-duplicate test, and the harness defect it inherits

Files: `tests/test_event_idempotency.py`, `tests/test_event_append.py`.

**First, fix #661's contention test.**
`tests/test_event_append.py:296`'s
`test_concurrent_appends_serialize_into_one_contiguous_range` starts its threads
with **no committed head**. The holder's head `INSERT` is invisible to the
waiter's snapshot, so the waiter's `SELECT … FOR UPDATE` matches zero rows and
returns immediately — a plain `FOR UPDATE` never waits on an uncommitted insert.
The wrapper fires, the flag is set, and the real serialization happens on the
`OneToOneField` unique index inside `get_or_create`. The test passes without
ever exercising the head lock. Its sibling at `tests/test_event_append.py:272-276`
documents this exact hazard and commits its head first.

Fix: append once in a committed `transaction.atomic()` before starting the
threads, then assert the ranges the seeded append shifts them to.

**Then write the duplicate test**, `@pytest.mark.django_db(transaction=True)`,
with the head likewise committed first. The `execute_wrapper` predicate and the
holder/waiter `threading.Event` pair carry over from
`tests/test_event_append.py:302-345` (itself following the harness at
`tests/test_library_conversion.py:822-830`), but **the holder cannot be a bare
`idempotent_append` call**: #661's holder sets `holder_locked` between
`lock_stream` and `append`, and `idempotent_append` owns both. Have the holder
call `lock_stream(library)` itself, set the flag, then call `idempotent_append`
— the second lock is re-entrant within the same transaction, and the flag then
fires at the same point in the interleaving as #661's.

Keep every `wait()` and `join()` timed out, thread failures collected into an
`errors` list, and `close_old_connections()` in each `finally`: an unbounded
barrier hangs the suite instead of failing it, and a leaked open transaction
blocks `TransactionTestCase` truncation.

Assert: N events, not 2N · exactly one record · both callers received the same
`(first_sequence, last_sequence)` · one returned `AppendResult` and the other
`ReplayedAppend`, without asserting which — thread scheduling decides the
winner, and pinning it would make the test flaky rather than stricter.

`make test ARGS="tests/test_event_idempotency.py tests/test_event_append.py -x" PYTEST_WORKERS=0`
— serially while iterating; parallel output interleaves and `-x` stops only the
worker that hit the failure.

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

`make audit-uuid-identity` separately — it is not part of `make check`. It
should pass with no new entry in `games/identity_audit.py`: the table's order
source is `created_at` (`DEFAULT_ORDER_SOURCE`) and its only relation column is
`library_id`, already a `uuid_v7`. **If it fails, that is a finding, not a
licence to add a registry entry** — check first that the model matches the
design's schema table.

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
#665, #666, #901). The #661 harness defect is corrected here rather than filed,
because this work would otherwise build on it.
