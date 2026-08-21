# Library event envelope and stream-head schema

`LibraryEventStreamHead` and `LibraryEvent` implement the *Event envelope*
section of the
[overhaul architectural charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md),
whose envelope field list this record does not repeat.

## What the tables are

Storage for a per-library append-only event stream, plus the head row a command
locks to append to it. They are the contract the command, projection, and replay
layers build against.

Nothing writes to them. The schema carries no sequence allocation, head
provisioning, idempotency enforcement, payload validation, event-name
vocabulary, upcasting, or append API, and no admin, API, filter, preset,
statistics, signal, fixture, or UI registration. Both tables are empty on a
freshly migrated database and stay empty until a writer exists.

## Ownership: every event has a non-null library

`Game.library = NULL` and `Platform.library = NULL` identify *shared catalog*
rows. That nullability is a catalog concept and does not reach the stream:

- A `LibraryEvent` always belongs to one concrete `UserLibrary`. There is no
  ownerless event and no shared stream.
- The event's *aggregate* is the private domain object being changed.
  `aggregate_id` holds that object's UUID, never a shared `Game` UUID.
- A shared catalog UUID appears only *inside* the payload, as a durable
  reference.
- Shared catalog mutations are conventional relational writes and never enter a
  private stream.

The schema therefore contains no Game-specific field, payload key, foreign key,
or validation, and its payload tests assert only that nested UUID strings
survive a JSON round trip, with no key carrying meaning.

## Design

### A separate head table, not a `current_sequence` column on `UserLibrary`

A command locks one row before reading projections. On `UserLibrary` that lock
would also block preferences, ownership checks, and settings writes, turning
unrelated work into stream contention. A dedicated head row is the lock, and
nothing else has a reason to take it. The head is also the stream's identity —
its `id` is the stable stream UUID — which a column on `UserLibrary` could not
express.

### `library` is denormalized onto the event, and the redundancy is enforced

`LibraryEvent.library` is derivable through `stream → library`. It is stored
anyway so that per-library reads do not join to the head, and so it can be half
of the ownership guard.

Denormalization without enforcement is a bug generator, so the pair is checked
by the database:

- the head carries a named unique constraint on `(id, library)` — redundant
  against its primary key, and present solely to be a composite FK target;
- the event carries a composite foreign key `(stream_id, library_id) →
  (id, library_id)`.

An event cannot name another library's stream. Django has no composite-FK field,
so this is named reversible raw SQL in migration `0023`.

### `stream` is RESTRICT, `library` is CASCADE

The combination reads like a contradiction — deleting a library cascades to
events *and* to the head, which events restrict — and resolves mechanically:

- `Collector.collect(..., fail_on_restricted=True)` clears restricted objects
  that are *also* collected for deletion; a library delete collects both the
  head and its events by CASCADE, so the RESTRICT is cleared.
- `RESTRICT` calls `collector.add_dependency(head_model, event_model)`, so
  `Collector.sort()` orders events before the head. The raw composite FK is
  plain `NO ACTION` and not deferrable, and this ordering keeps it satisfied
  during the cascade.

So: deleting a library removes its events and its head, including a populated
head; deleting a populated head directly raises `RestrictedError`. Both are
pinned by tests.

The only model change that breaks this is `LibraryEvent.library` ceasing to be
a CASCADE foreign key, which stops events being collected from the same origin.
`related_name="+"` relations are still collected (`include_hidden=True`), and
nullability affects only fast-delete eligibility, which the same guard covers.

### `aggregate_id` and `correlation_id` are explicit-only

Both must be supplied by the writer: a generated UUIDv7 default would silently
manufacture a correlation where the caller forgot one, which is exactly what the
charter's "a compound user action shares a correlation ID" rule depends on not
happening. `UUIDv7Field.__init__` `setdefault`s both `default=uuid.uuid7` and
`db_default=PostgreSQLUUIDv7()`, so each is overridden.

`default=None` makes `has_default()` true and `get_default()` return `None`, so
an unset value hits `NOT NULL`. `db_default` must be `models.NOT_PROVIDED`
rather than `None`: `None` keeps `has_db_default()` true and emits

```
"aggregate_id" uuid_v7 DEFAULT NULL NOT NULL
```

where `NOT_PROVIDED` emits `"aggregate_id" uuid_v7 NOT NULL` and drops
`db_default` from `deconstruct()`. Runtime behaviour is identical either way —
both send an explicit `NULL` — so the difference is only whether the schema
carries a meaningless `DEFAULT NULL`, and no behavioural test separates them.
`has_db_default()` is asserted on the fields directly, and `make
check-migrations` sees the `deconstruct()` kwargs.

`UUIDv7Field.deconstruct()` records that absence explicitly. Django's
`Field.deconstruct()` emits `db_default` only when one exists, so without this
`clone()` — which the migration autodetector uses — rebuilds the field through
`__init__` and re-applies the generated default, leaving migration state
permanently disagreeing with the model.

`causation_id` is nullable with the same overrides: a root event has no cause.

### Sequences are stored and constrained, never allocated

`sequence` is a `PositiveBigIntegerField` with a `>= 1` check and a unique
`(stream, sequence)` constraint; writers assign it. `current_sequence` on the
head defaults to `0`, meaning no event yet, and nothing advances it. Heads are
not provisioned, so no `UserLibrary` has one.

### `LibraryEventQuerySet` subclasses `LibraryOwnedQuerySet`

`LibraryOwnedQuerySet.for_library()` already has the required semantics and is
used by `Game`, `Platform`, and `Purchase`. Re-declaring it would fork a
convention for no gain.

### Rollback is allowed only while the tables are empty

Migration `0023` is reversible so a branch can be abandoned, but reversing it
once events exist destroys the only copy of that history — projections are
rebuilt *from* the stream. Its last operation is a guard whose forward direction
is a no-op and whose reverse raises when either table has rows; being last, a
reversal hits it before anything is dropped. The migration is atomic on
PostgreSQL, so a refused reversal leaves the database at `0023`.

That guard sits in the unapply path of every migration-rewind test fixture that
migrates back past `0023`. Those pass because nothing has written an event; a
fixture that seeds events and then rewinds will hit the guard, which is the
intended outcome.

### No speculative indexes

Only the constraint-backed indexes and the ones Django creates for its own
foreign keys. Query shapes belong to the readers, and an unused index on the
hottest insert path in the system is a real cost.

### The UUID identity audit records both tables

`games/identity_audit.py` pins relation columns and UUID carriers by exact set
equality in both directions, so a model it does not know about fails the audit.
Three registrations carry the new tables:

- `EXPECTED_RELATION_COLUMNS` and `EXPECTED_IDENTITY_TABLES` list the four
  foreign-key columns and both tables.
- `RESIDUAL_INTEGER_RELATIONS` marks `("games_libraryevent", "actor_id")` as
  never converting: it points at `auth.User`, whose primary key is integer and
  outside the UUID cutover, like `games_userlibrary.user_id`.
- `IDENTITY_ORDER_SOURCE` maps `games_libraryevent` to `recorded_at`. The
  ordering check looks for a `created_at` field by default; naming `recorded_at`
  keeps the check running rather than degrading to a "no creation timestamp"
  note.

`LibraryEventStreamHead` has no timestamp and is skipped by the ordering check.
Its field contract is three columns, one row per library, and cross-library head
ordering carries no meaning.

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
| `idempotency_key` | `CharField(max_length=255)` | non-empty, not unique |
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

## Where the behaviour is pinned

`tests/test_event_models.py` covers identities, nullability, JSON round trips,
independent `dict` defaults, `for_library()`, actor nulling, and every
constraint including the cross-library rejection and both delete behaviours. It
reads the eight constraint *names* back from `pg_constraint`, because the
composite FK is raw SQL that Django's migration state cannot see and nothing
else would notice a misspelling in it before a rollback attempt.

`tests/test_event_schema_migration.py` drives the migration executor across
`0022 → 0023`: catalog data unchanged, both tables empty, clean reversal while
empty, refused reversal once a head or event exists.

`make sqlmigrate ARGS="games 0023_library_event_schema"` reads back the emitted
DDL, which is the only place the composite FK and the identity columns' absent
defaults are visible together.

## What this shape forecloses

- **One stream per library.** A per-aggregate or per-year stream would need a
  new head table and a rewrite of every `(stream, sequence)` reader. The trade
  buys contiguous per-action appends and a single lock order.
- **No `(library, idempotency_key)` uniqueness.** Adding it is cheap while the
  tables are empty and expensive afterwards.
- **`aggregate_id` has no foreign key** and cannot have one — aggregates span
  models. Dangling aggregate IDs are possible by construction; validation
  belongs to the writer.
- **`payload` is unvalidated JSONB.** Shape enforcement needs an event
  vocabulary, which does not exist.
- **No archival or partitioning.** The events table grows without bound.
