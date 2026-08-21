# EV-06 (#660): library event envelope and stream-head schema

Status: approved 2026-08-21. Slice EV-06 of parent phase #601, governed by the
[overhaul architectural charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md)
(sections *Event envelope* and *Durable references*), whose envelope field list
this record implements and does not re-argue.

## Outcome

Two additive tables — `LibraryEventStreamHead` and `LibraryEvent` — plus their
constraints and a `for_library()` manager. Nothing writes to them yet. The
value delivered is the storage contract every later EV slice builds against,
committed early enough that #661–#668 argue about behaviour rather than columns.

## Boundary

This slice is schema only. Each deferred concern has an owner:

| Deferred | Owner |
| --- | --- |
| Head provisioning, row locking, sequence allocation | #661 |
| `(library, idempotency_key)` command records and replay of a completed command | #662 |
| Serialization-failure / deadlock / collision retries | #663 |
| Dispatch | #664 |
| Projectors | #665 |
| Replay and rebuild | #666, #667 |
| Durable-reference payload and snapshot representation | #668 |
| Relational `PlayerGame → Game` link | #671 |
| Baseline events for existing PlayerGames | #676 |
| Live PlayerGame command/event writes | #677 |

No admin, API, filter, preset, statistics, signal, fixture, or UI registration.
No JSON shape validation, event-name vocabulary, upcasting, or append API. No
data is backfilled: after this migration both tables are empty and stay empty.

## Ownership: why every event has a non-null library

`Game.library = NULL` and `Platform.library = NULL` identify *shared catalog*
rows. That nullability is a catalog concept and must not leak into the stream:

- A `LibraryEvent` always belongs to one concrete `UserLibrary`. There is no
  ownerless event and no shared stream.
- The event's *aggregate* is the private domain object being changed — a future
  `PlayerGame`. `aggregate_id` therefore holds the `PlayerGame` UUID, never the
  shared `Game` UUID.
- A shared catalog UUID appears only *inside* the payload, as a durable
  reference. #668 owns that representation.
- Shared catalog mutations stay conventional relational writes and never enter
  a private stream.

Consequently this slice adds no Game-specific field, payload key, foreign key,
validation, or test. A payload test here asserts only that nested UUID strings
survive a JSON round trip, with no key carrying meaning.

## Decisions

### 1. A separate head table, not a `current_sequence` column on `UserLibrary`

The charter requires commands to lock *one* row before reading projections.
Putting the counter on `UserLibrary` would make every command lock the row that
preferences, ownership checks, and future settings writes also touch, turning
unrelated work into stream contention. A dedicated head row is the lock, and
nothing else has a reason to take it.

The head is also the stream's identity (`id` is the stable stream UUID the
charter calls for), which a column on `UserLibrary` could not express.

### 2. `library` is denormalized onto the event, and that redundancy is enforced

`LibraryEvent.library` is derivable through `stream → library`. It is stored
anyway for two reasons: per-library queries (`for_library()`, and every later
replay/journal read) should not join to the head, and the column is half of the
ownership guard below.

Denormalization without enforcement is a bug generator, so the pair is checked
by the database:

- the head carries a named unique constraint on `(id, library)` — redundant
  against its primary key, and present solely to be a composite FK target;
- the event carries a composite foreign key `(stream_id, library_id) →
  (id, library_id)`.

An event can therefore never name another library's stream. Django has no
composite-FK field, so this is named reversible raw SQL in the migration.

### 3. `stream` is RESTRICT, `library` is CASCADE — verified, not assumed

The combination reads like a contradiction (deleting a library cascades to
events *and* to the head, which events restrict). It works, and the reasons are
mechanical:

- `Collector.collect(..., fail_on_restricted=True)` clears restricted objects
  that are *also* collected for deletion; a library delete collects both the
  head and its events by CASCADE, so the RESTRICT is cleared
  (`django/db/models/deletion.py`, the `fail_on_restricted` block).
- `RESTRICT` calls `collector.add_dependency(head_model, event_model)`, so
  `Collector.sort()` orders events before the head. The raw composite FK is
  plain `NO ACTION` and not deferrable, and this ordering is what keeps it
  satisfied during the cascade.

The net contract: deleting a library removes its events and its head, including
a *populated* head; deleting a populated head directly raises `RestrictedError`.
Both are pinned by tests — the populated-head cascade is the interesting case
and the one the issue text left ambiguous.

### 4. `aggregate_id` and `correlation_id` are explicit-only, spelled `db_default=NOT_PROVIDED`

Both must be supplied by the writer: a generated UUIDv7 default would silently
manufacture a correlation where the caller forgot one, which is exactly the
failure the charter's "compound action shares a correlation ID" rule depends on
not happening. `UUIDv7Field.__init__` `setdefault`s both `default=uuid.uuid7`
and `db_default=PostgreSQLUUIDv7()`, so each must be overridden.

`default=None` is right — `has_default()` becomes true, `get_default()` returns
`None`, and an unset value hits `NOT NULL`. `db_default=None` is *not*: measured
against this project's Django 6.0.7 and the `uuid_v7` domain, it keeps
`has_db_default()` true and emits

```
"aggregate_id" uuid_v7 DEFAULT NULL NOT NULL
```

while `db_default=models.NOT_PROVIDED` emits `"aggregate_id" uuid_v7 NOT NULL`
and drops `db_default` from `deconstruct()`, so the migration stays clean. The
two behave identically at runtime — `has_default()` is true either way, so both
send an explicit `NULL` and both hit `NOT NULL`. The difference is whether the
schema carries a meaningless `DEFAULT NULL` forever. Use `NOT_PROVIDED`.

Because runtime behaviour is identical, no behavioural test separates them: the
`db_default` half is pinned by asserting `has_db_default()` is false on the
field, and by `make check-migrations`, which sees the changed `deconstruct()`
kwargs. A test that merely writes an event without `correlation_id` and expects
`IntegrityError` proves only the `default=None` half.

`causation_id` is nullable with `default=None` for the same override reason — a
root event has no cause.

### 5. Sequences are stored and constrained here, never allocated here

`sequence` is a plain `PositiveBigIntegerField` with a `>= 1` check and a unique
`(stream, sequence)` constraint. Tests in this slice assign sequences by hand.
`current_sequence` on the head defaults to `0`, meaning "no event yet", and
nothing in this slice advances it. #661 owns `SELECT … FOR UPDATE` on the head,
the advance, and head creation.

Heads are not provisioned or backfilled, so no `UserLibrary` has one when this
migration finishes. That is deliberate: provisioning is a behaviour with a
transaction contract, and #661 is where it can be tested as one.

### 6. `LibraryEventQuerySet` subclasses the existing `LibraryOwnedQuerySet`

`games/models.py:37` already defines `LibraryOwnedQuerySet.for_library()` with
exactly the required semantics, and `Game`, `Platform`, and `Purchase` use it.
Re-declaring `for_library()` would fork a convention for no gain.

### 7. Rollback is allowed only while the tables are empty

`0023` is reversible so a branch can be abandoned, but reversing it once events
exist destroys the only copy of that history — projections are rebuilt *from*
the stream, so there is nothing to recover from. The migration therefore ends
with a guard operation whose reverse raises when either table has rows, and
whose forward direction is a no-op. Failing visibly beats a silent `DROP TABLE`.

The guard now sits in the unapply path of roughly a dozen existing
migration-rewind fixtures (`tests/test_temporal_domain.py`,
`tests/test_catalog_uuid_primary_key.py`, `tests/test_external_reference_migration.py`
and siblings) which migrate back to an early node during *setup*. They stay
green because nothing has written an event by then — but any future test that
seeds events and then rewinds will hit the guard, and that is the correct
outcome rather than a bug in the test.

### 8. The UUID identity audit must be extended, not worked around

`games/identity_audit.py` pins the schema's relation columns and UUID carriers
by exact set equality in both directions, so *adding* a model fails the audit
until the audit is told about it. Three registrations are required, and each
one is a decision rather than paperwork:

- `EXPECTED_RELATION_COLUMNS` and `EXPECTED_IDENTITY_TABLES`
  (`tests/test_uuid_identity_audit.py:29`, `:203`) gain the four new FK columns
  and the two new tables.
- `RESIDUAL_INTEGER_RELATIONS` (`games/identity_audit.py:41`) gains
  `("games_libraryevent", "actor_id")` labelled *never converts*: it points at
  `auth.User`, whose primary key is integer and is not part of the UUID cutover
  — the same reason `games_userlibrary.user_id` is already listed. Without the
  entry the audit reports it as an unconverted gap.
- `IDENTITY_ORDER_SOURCE` (`games/identity_audit.py:59`) gains
  `"games_libraryevent": "recorded_at"`. The audit's ordering check defaults to
  a `created_at` field; naming `recorded_at` explicitly is what keeps the check
  *running* for the events table instead of silently degrading to a "skipped:
  no creation timestamp" note. Given the charter treats UUIDv7 order as an audit
  tiebreaker, an unaudited ordering here would be a bad place to lose coverage.

`LibraryEventStreamHead` has no timestamp and is therefore skipped by the
ordering check. That is accepted rather than fixed: the issue's field contract
is three columns, one row per library, and cross-library head ordering carries
no meaning.

### 9. No speculative indexes

Beyond the constraint-backed indexes, nothing. Query shapes come from #664–#667;
indexes added now would be guesses, and an unused index on the hottest insert
path in the system is a real cost.

## Schema contract

### `LibraryEventStreamHead`

| Field | Type | Notes |
| --- | --- | --- |
| `id` | `UUIDv7Field(primary_key=True, editable=False)` | stable stream UUID |
| `library` | `OneToOneField(UserLibrary, CASCADE)` | required; `related_name="event_stream_head"` |
| `current_sequence` | `PositiveBigIntegerField(default=0)` | `0` = no events yet |

### `LibraryEvent`

| Field | Type | Notes |
| --- | --- | --- |
| `id` | `UUIDv7Field(primary_key=True, editable=False)` | |
| `library` | `ForeignKey(UserLibrary, CASCADE)` | required; `related_name="events"` |
| `stream` | `ForeignKey(LibraryEventStreamHead, RESTRICT)` | required; `related_name="events"` |
| `sequence` | `PositiveBigIntegerField()` | starts at 1 |
| `event_type` | `CharField(max_length=255)` | non-empty |
| `aggregate_type` | `CharField(max_length=100)` | non-empty |
| `aggregate_id` | `UUIDv7Field(default=None, db_default=NOT_PROVIDED)` | explicit only |
| `payload_schema_version` | `PositiveIntegerField(default=1)` | `>= 1` |
| `recorded_at` | `DateTimeField(default=timezone.now, editable=False)` | UTC |
| `effective_time` | `TemporalValueField()` | real-world time, when known; the field forces `null=True` itself |
| `actor` | `ForeignKey(AUTH_USER_MODEL, SET_NULL, null=True, related_name="+")` | survives user deletion |
| `correlation_id` | `UUIDv7Field(default=None, db_default=NOT_PROVIDED)` | explicit only |
| `causation_id` | `UUIDv7Field(null=True, default=None, db_default=NOT_PROVIDED)` | root events have none |
| `source_metadata` | `JSONField(default=dict, blank=True)` | manual / migration / import provenance |
| `idempotency_key` | `CharField(max_length=255)` | non-empty; uniqueness is #662's |
| `payload` | `JSONField()` | required, domain-neutral |

### Named constraints

| Name | Kind |
| --- | --- |
| `unique_library_event_stream_head_library_identity` | unique `(id, library)` on the head |
| `unique_library_event_stream_sequence` | unique `(stream, sequence)` |
| `library_event_sequence_positive` | check `sequence >= 1` |
| `library_event_payload_schema_version_positive` | check `payload_schema_version >= 1` |
| `library_event_type_not_empty` | check |
| `library_event_aggregate_type_not_empty` | check |
| `library_event_idempotency_key_not_empty` | check |
| `library_event_stream_matches_library` | raw-SQL composite FK `(stream_id, library_id) → (id, library_id)` |

## Verification

`tests/test_event_models.py` — identities, nullability, JSON round trips,
independent `dict` defaults, `for_library()`, actor nulling, and every
constraint above including the cross-library rejection and both delete
behaviours. The eight constraint *names* are read back from `pg_constraint` in
one test: the composite FK is raw SQL that Django's migration state cannot see,
so nothing else would notice a typo in it until someone attempted a rollback.

`tests/test_uuid_identity_audit.py` — the three audit registrations of decision
8, which are assertions about the whole schema and belong with the audit rather
than with the new models.

`tests/test_event_schema_migration.py` — migration-executor test on the harness
pattern of `tests/test_external_reference_migration.py`: seed users, libraries,
private Games and a shared `Game.library = NULL`; migrate `0022 → 0023`;
assert existing rows unchanged and both new tables empty; reverse cleanly;
reverse *fails* once a head or event exists; restore the leaf afterwards.

Gate: `make check` with the default `PYTEST_WORKERS`, plus
`make check-migrations` (already inside `check`) and `git diff --check`.

## What this shape forecloses

- **One stream per library, forever.** A per-aggregate or per-year stream would
  need a new head table and a rewrite of every `(stream, sequence)` reader.
  Deliberate: the charter buys contiguous per-action appends and a single lock
  order with it.
- **No `(library, idempotency_key)` uniqueness yet.** #662 must both add the
  constraint and decide what to do about any rows written before it lands. Cheap
  now (tables are empty), expensive later.
- **`aggregate_id` has no foreign key** and cannot have one — aggregates span
  models. Dangling aggregate IDs are possible by construction; validation, if
  wanted, belongs to the dispatcher.
- **`payload` is unvalidated JSONB.** Shape enforcement arrives with the event
  vocabulary, not before it.
- **No archival or partitioning.** The events table grows without bound; the
  charter's 100,000-event rebuild budget is the first place that bites.
