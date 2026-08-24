# The event-type registry and payload validation

[#660](https://github.com/KucharczykL/timetracker/issues/660) gave the library
event stream its columns, and said in as many words what it left open: "`payload`
is unvalidated JSONB. Shape enforcement needs an event vocabulary, which does not
exist." [#661](https://github.com/KucharczykL/timetracker/issues/661) made
`LockedStream.append` the only writer,
[#665](https://github.com/KucharczykL/timetracker/issues/665) folded every
appended event through its projectors, and
[#666](https://github.com/KucharczykL/timetracker/issues/666) folded a recorded
stream back through them. Through all of it, `event_type` has been any non-empty
string and `payload` has been any JSON.

This issue builds the vocabulary. It lands before
[#671](https://github.com/KucharczykL/timetracker/issues/671) appends the first
real event types, so every event ever recorded is validated rather than
retrofitted around.

No production database has been switched to the event stream, and none will be
before this phase completes. There are no historical payloads. The registry is
therefore strict from day one, and payload **upcasting** is a wall this issue
builds rather than machinery it ships -- there is nothing to upcast.

## What it is

A registered event type is a module-level `EventSpec` constant: a name, the
aggregate type it acts on, and a `TypedDict` describing its payload. The spec is
generic over that `TypedDict`, so mypy checks a payload at the call site that
builds it. `append` refuses an event whose spec it does not hold, and refuses a
payload that does not match the spec's schema, before it writes anything.

## Ownership boundary

| Not here | Owner |
| --- | --- |
| The first real event types and their payload schemas | #671 |
| Upcasting a payload from an older schema version | follow-up, filed by this issue |
| Validating `source_metadata` | follow-up, filed by this issue |
| The optional expected-sequence concurrency check | #901 |
| Shadow projection tables, the rebuild, the atomic swap | #667 |
| Durable reference snapshots inside payloads | #668 |
| Blocking direct writes to event-sourced projections | #737 |

This issue owns the spec value, the registry, the write-path refusals, the
read-path version guard, and the plumbing value that carries the registry to
them.

**It registers no real event type.** The vocabulary starts empty and #671 fills
it. Every test brings its own specs and its own registry, so nothing test-shaped
enters the production vocabulary at any point -- see "No placeholders" below.

## Preconditions

- `LockedStream.append` (#661) is the single writer, holds the head lock for the
  caller's transaction, and assigns contiguous sequences.
- `canonical_json` (#665) refuses a payload PostgreSQL would hand back as
  something else, and returns the round trip rather than the caller's object.
- `RecordedEvent.from_row` (#914) copies every concrete field and refuses a
  deferred row. Both the append path and the replay path build their envelope
  through it.
- `ProjectorRegistry.apply` (#665) resolves handlers by event type and runs them
  in `ProjectorFamily` order.
- `run_in_transaction` (#663) retries only `IntegrityError` and
  `OperationalError`, so any other exception already escapes un-retried.
- pydantic 2.13.4 is installed as a transitive dependency of django-ninja. This
  issue promotes it to a declared one.

### Measured, not assumed

Every mechanic below was run against this repo's pinned pydantic 2.13.4, Python
3.14, and PostgreSQL 18.

**The obvious way to configure a schema does not type-check, and the second
obvious way is refused outright.**

| Form | Result |
| --- | --- |
| `__pydantic_config__ = ConfigDict(...)` in the `TypedDict` body | mypy: `Invalid statement in TypedDict definition; expected "field_name: field_type"` |
| `TypeAdapter(SomeTypedDict, config=ConfigDict(...))` | `PydanticUserError: Cannot use config when the type is a BaseModel, dataclass or TypedDict` |
| `@with_config(ConfigDict(...))` on the `TypedDict` | runtime enforcement confirmed; `mypy .` clean over 362 files |

`@with_config` is therefore not a preference. It is the only form that both
enforces and type-checks.

**What strict mode refuses**, with `extra="forbid"`:

| Input against `{game_id: str, count: int}` | Result |
| --- | --- |
| `{"game_id": "x", "count": 1}` | accepted |
| `{"game_id": "x", "count": 1, "zz": 2}` | `extra_forbidden` |
| `{"game_id": "x"}` | `missing` |
| `{"game_id": "x", "count": "1"}` | `int_type` |
| `{"game_id": 5, "count": 1}` | `string_type` |
| `{"game_id": "x", "count": True}` | `int_type` |
| `["nope"]` | `dict_type` |

The `True`-for-`int` refusal is the one that matters most: JSON `true` and JSON
`1` are different values and a lax validator would conflate them.

**What strict mode still converts.** A field typed `float` accepts JSON `1` and
returns `1.0`. Python's own equality hides it -- `{"ratio": 1} == {"ratio": 1.0}`
is `True` -- so no equality check can catch the difference. This decides which
value gets stored; see "The validated value is the stored value".

**A payload integer has no bound.** `10**30` validates against `int` and stores.
Nothing here can know that a projector will write it into an `IntegerField`.

**PostgreSQL does not store the key order you gave it.** `jsonb` sorts keys by
length, then bytewise, recursively:

| | |
| --- | --- |
| written | `bb, a, ccc, ab, b` |
| `jsonb` returns | `a, b, ab, bb, ccc` |
| `sorted()` would give | `a, ab, b, bb, ccc` |

So plain sorting does not reproduce it either. This is a live parity defect in
code that already shipped; see "Key order is part of the value".

**Validation is not a cost.** Ten thousand validations take 5.4 ms; building
forty adapters takes 3.4 ms. Neither import time nor the charter's 100 ms
per-command budget is at risk.

**The generic spec really does check payloads statically.** Against a spec built
from a `{game_id: str, count: int}` schema, mypy reports `Extra key "kount"`,
`Missing key "count"`, and `Incompatible types (expression has type "int",
TypedDict item "game_id" has type "str")`, and accepts the correct call. This is
the whole reason the vocabulary is spec constants rather than an enum.

## Design

### An event type is a value, not an enum member

```python
PLAYTHROUGH_STARTED = EventSpec(
    "library.playthrough.started",
    aggregate_type="playthrough",
    payload=PlaythroughStartedPayload,
)
```

The alternative considered first, and rejected, was a closed `EventType`
`StrEnum` mirroring `CommandName`, with the registry mapping members to schemas.
Four things killed it, and each is permanent rather than transitional:

**A `StrEnum` cannot bind a payload to its type.** `NewEvent.payload` is
`dict[str, Any]`. With an enum, nothing checks that a `PLAYTHROUGH_STARTED` event
carries a playthrough-started payload -- the mistake surfaces at runtime, under
the stream-head lock, inside a command. A spec generic over its schema turns the
same mistake into three mypy errors, measured above. `Projector.handles` already
went to real trouble to make the analogous mistake a `NameError` at class
definition rather than a handler that silently never runs; a payload deserves the
same.

**Test event types would enter the production vocabulary.** The #665 spec named
this outright: "This is the concrete lesson from #907, which exists only because
#664's placeholders had to live in a closed enum shared with production."
`tests/test_command_dispatch.py:502` ships a guard asserting `CommandName` may
never hold placeholder and real members at once. An enum here would be worse than
that precedent, not equal to it: a `CommandName` placeholder is inert because no
command class claims it, while a registered test event type appends perfectly
well -- into an immutable column Audit History reads.

**The placeholders would not be reliably deletable.** A test event type is
removable only while no stream ever recorded one. The moment any environment
appends one, that row is permanent, and the replay guard below refuses an
unregistered type. Deleting the member would make that stream unreplayable.

**Keying `Projector.handles` on an enum cascades through the type layer.**
`RecordedEvent.event_type` is `str`, read off a `CharField`. Enum-keyed handlers
force it to become the enum, which forces a `str -> EventType` conversion inside
`from_row` -- a third refusal point, with different meaning from the registry's,
on the hot path of every replay. `envelope.py` says its field-by-field copy
exists "so mypy checks each field against its declared type", so this is
load-bearing, not incidental.

Spec constants keep the whole vocabulary in one module, as greppable as an enum,
and give up nothing the enum offered.

### `handles` keys on specs

`projection.py` drops `type EventType = str` and keys `Projector.handles` on
`EventSpec` objects. A family cannot claim an event type nobody defined, because
claiming one means naming its spec. The registry continues to resolve handlers by
the event type *string* internally, which is what a `RecordedEvent` carries.

### The registry holds specs, not schemas

```python
DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_STARTED)
```

Registration builds the spec's `TypeAdapter` once, at import, and refuses:

- a second registration of the same event-type string;
- a schema that is not a `TypedDict`;
- a schema whose `@with_config` does not set `extra="forbid"` and `strict=True`
  -- so a schema cannot forget the configuration that makes validation mean
  anything;
- any `version` but 1, naming the upcaster machinery that does not exist.

The registry is an object with a module-level default, exactly as
`ProjectorRegistry` is. A test builds its own and registers into it.

### The version wall is at registration, not at replay

The first draft of this design put the only version check in `replay`: refuse a
row whose stored version is not the registered current one. That is a trap. Since
`append` stamps the current version, a mismatch can arise only from a bump -- and
at that instant every recorded row fails at sequence 1, #667's shadow rebuild
dies for that library, and nobody learns any of it until someone runs a rebuild.
The charter requires the opposite: "Event payloads are upcast when schemas evolve;
historic events are not rewritten for ordinary application changes."

So the wall moves forward. `register()` refuses any version but 1. Bumping a
version without upcasters fails at import, on every test run, at the moment
someone tries it. The replay guard stays as a second line, refusing a mismatch it
can now never see. The follow-up issue that builds upcasting relaxes the
registration check and grows the guard an upcast step.

### The registry stamps what the caller cannot

`NewEvent` loses two fields. `payload_schema_version` becomes the registry's,
because a writer never has a legitimate reason to record an old version -- old
versions are read, not written. `aggregate_type` becomes the registry's because
it is a fact about the event type: `library.playthrough.started` always acts on a
playthrough.

`NewEvent` is left with `spec`, `aggregate_id`, `payload`, `effective_time`, and
`causation_id` -- and is built through `spec.new(...)`, which is what makes the
payload statically checked.

### The `aggregate_type` column goes away

Once the registry stamps it, the column is a pure function of `event_type`,
copied onto every row, where a changed registration would leave old rows carrying
the old string with nothing noticing. The version guard watches versions; nothing
would watch this.

The tables are empty, so dropping the column costs one migration today and would
cost a data migration later. `LibraryEvent` loses the field and the
`library_event_aggregate_type_not_empty` check constraint; `RecordedEvent` loses
the field; the registry derives it.

The cost is that SQL can no longer filter on it directly. "Every playthrough
event" becomes an `IN` list of event-type strings, which the registry generates
and the existing index serves.

### The validated value is the stored value

Order inside `append`, per event, before any row is built and before the head
advances:

1. resolve the spec **in the registry, by event-type string** -- unregistered
   raises `UnregisteredEventType`. The spec the `NewEvent` carries is not trusted
   for this: a caller holding a spec object nobody registered must still be
   refused, which is what makes a test-owned registry mean anything;
2. `canonical_json` the payload -- unchanged from today, and still needed, because
   a field typed `dict[str, Any]` can carry a `Decimal` or a tuple that pydantic
   will pass through untouched;
3. validate the canonical value -- a mismatch raises `PayloadInvalid`;
4. store **pydantic's returned value**, not the canonical input.

Step 4 reverses the first draft. A field typed `float` accepts JSON `1`, and
pydantic returns `1.0` while the canonical input stays `1`; storing the input
would put an `int` on disk under a schema promising a `float`, unnoticed forever,
because Python equality cannot see the difference. Storing the validated value
makes the row match its declared schema by construction. It is safe to store:
every declared field is JSON-native, and anything nested under `Any` already
survived step 2. pydantic returns fresh containers, nested ones included, so the
stored payload aliases nothing the caller holds -- the property `canonical_json`
was written to guarantee.

Both refusals are `ValueError` subclasses, consistent with `PayloadNotCanonical`
and with `pydantic.ValidationError` itself. They are not retried -- though not
for the reason the first draft gave: `run_in_transaction` catches only
`IntegrityError` and `OperationalError`, so *every* other exception is already
un-retried. Both fire before the rows and before the head advance, keeping
`append`'s promise that a refusal leaves a transaction that may still commit
exactly as it found it. `idempotent_append` writes its record only after `append`
returns, so a refused payload leaves no idempotency record behind and cannot
poison an honest retry of the same key.

### Key order is part of the value

`canonical_json` claims to return "`value` as JSONB will return it", and its
check is `round_tripped != value` -- Python dict equality, which ignores key
order. `jsonb` does not: it sorts keys by length then bytes, recursively,
measured above. So a projector reading an appended event sees the caller's key
order and the same projector on replay sees PostgreSQL's. Any family that
iterates the payload, re-dumps it into a column, or hashes it produces different
rows on the two paths -- the exact parity property #666 exists to establish. The
pinned parity test compares `RecordedEvent` dataclasses, whose payload comparison
is also order-insensitive, so it cannot catch this.

`RecordedEvent.from_row` sorts payload keys recursively, by one fixed rule. Both
paths already funnel through it -- `append` builds the envelope from the row it
just created, `replay` from the row it read -- so one change makes both hand a
projector an identical value, and couples us to no PostgreSQL implementation
detail. The row's stored key order no longer matches what projectors see, which
is harmless and stated here so nobody rediscovers it as a bug.

### Replay guards what it reads

`replay` refuses a row whose event type is not registered, and a row whose stored
`payload_schema_version` is not the registered one, raising
`PayloadVersionUnsupported` -- a sibling of `StreamNotContiguous`, and
deliberately neither an `IntegrityError` nor an `OperationalError`, because a
stream carrying a payload nobody can read is not something another attempt fixes.
The lookup is an in-memory dict hit, so the pinned two-query replay floor is
untouched.

### One plumbing value, threaded once

`dispatch` already threads `registry` and `policy` through
`dispatch -> idempotent_append -> append`, each defaulting to a module-level
value; #665 paid "three extra parameters" for it deliberately, so that an
integration test can drive the composed path against its own families. Adding
`event_registry` the same way would make four collaborators threaded
individually, with the upcaster registry arriving as a fifth, and would leave
`dispatch` holding two similarly-named registry parameters.

Instead one frozen value carries the projector registry, the event-type registry,
and the retry policy, threaded once. #667's shadow rebuild constructs one pointed
at shadow tables rather than assembling loose arguments, and the upcaster
registry later arrives as a field rather than as another parameter. This is the
CLAUDE.md rule about naming compound values applied to the seam that keeps
growing.

The cost is real and paid once: 51 call sites across 5 files pass `registry=` or
`policy=` today, nearly all of them tests, and all of them change.

### No placeholders

Because the vocabulary starts empty and every test owns its specs, this issue
adds nothing to production that a later issue must delete. Test modules define
their specs beside the projector families they already define, and register both
into registries they already own. The test suite currently reuses one event-type
string for several incompatible payload shapes -- `test.command.recorded` carries
four, `library.probe.recorded` at least four -- which under `extra="forbid"`
cannot coexist. Test-local specs make that a non-problem: a test declares as many
specs as it has shapes, at no cost to anything shared.

## API contract

`NewEvent` moves out of `append.py` and into `vocabulary.py`, because
`EventSpec.new` returns one and `append` imports the vocabulary -- leaving it
where it is would make the two modules import each other. Nothing else about it
changes except the two removed fields.

```python
# games/events/vocabulary.py

class UnregisteredEventType(ValueError): ...
class PayloadInvalid(ValueError): ...
#: A schema declared without the @with_config the registry requires.
class SchemaNotConfigured(TypeError): ...
#: Registering a version above 1 before upcasting exists.
class VersionNotUpcastable(NotImplementedError): ...

type AggregateType = str  # "playthrough"

@dataclass(frozen=True, slots=True)
class EventSpec[PayloadT]:
    event_type: str
    aggregate_type: AggregateType
    payload: type[PayloadT]
    version: int = 1

    def new(
        self,
        *,
        aggregate_id: uuid.UUID,
        payload: PayloadT,
        effective_time: TemporalValue | None = None,
        causation_id: uuid.UUID | None = None,
    ) -> NewEvent: ...

class EventTypeRegistry:
    def register(self, spec: EventSpec[Any]) -> None: ...
    def spec_for(self, event_type: str) -> EventSpec[Any]: ...   # raises UnregisteredEventType
    def validate(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def __contains__(self, event_type: str) -> bool: ...

DEFAULT_EVENT_TYPES: EventTypeRegistry
```

```python
# games/events/wiring.py

@dataclass(frozen=True, slots=True)
class EventWiring:
    projectors: ProjectorRegistry = DEFAULT_REGISTRY
    event_types: EventTypeRegistry = DEFAULT_EVENT_TYPES
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY

DEFAULT_WIRING: EventWiring
```

```python
# games/events/replay.py

#: A recorded payload no registered schema can read. Sibling of
#: StreamNotContiguous: not something another attempt fixes.
class PayloadVersionUnsupported(Exception): ...
```

`dispatch`, `idempotent_append`, `LockedStream.append`, and `replay` each take
`wiring: EventWiring = DEFAULT_WIRING` in place of their current `registry=` and
`policy=` parameters.

## Where the behaviour is pinned

| Behaviour | Test |
| --- | --- |
| An unregistered event type refuses the append | `tests/test_event_vocabulary.py` |
| A payload with an extra key, a missing key, or a wrong type refuses | `tests/test_event_vocabulary.py` |
| `true` does not satisfy an `int` field | `tests/test_event_vocabulary.py` |
| A refusal leaves the head, the rows, and the idempotency record untouched | `tests/test_event_vocabulary.py` |
| The stored payload is the validated value: `1` into a `float` field stores `1.0` | `tests/test_event_vocabulary.py` |
| Registering a schema without the required config refuses | `tests/test_event_vocabulary.py` |
| Registering a version above 1 refuses, naming upcasting | `tests/test_event_vocabulary.py` |
| Registering the same event type twice refuses | `tests/test_event_vocabulary.py` |
| The registry stamps the aggregate type and the version onto the row | `tests/test_event_append.py` |
| A replayed payload equals the appended one **key order included** | `tests/test_event_replay.py` |
| Replay refuses an unregistered type and a stale version | `tests/test_event_replay.py` |
| The replay query floor is unchanged | `tests/test_event_replay.py` |
| A projector claims types by spec | `tests/test_event_projectors.py` |
| Dispatch drives the whole path against a test-owned `EventWiring` | `tests/test_command_dispatch.py` |
| A payload mismatch is not retried and consumes no attempt | `tests/test_event_retry.py` |

## What this shape forecloses

- **One event type has exactly one aggregate type and one current version.**
  Both become expensive to revisit once rows exist. Checked against the charter's
  spanning operations -- merges, session reassignment, import accept, restore,
  trash and purge -- each names one owning aggregate, so the constraint holds.
- **An event type's string is permanent.** It is the value in an immutable
  column, and replay refuses an unregistered type, so removing or re-valuing a
  spec makes every stream that recorded it unreplayable. Retiring an event type
  needs a "known but retired" tier the registry does not have.
- **A historical payload version cannot be written through `append`.** Backup
  and restore (#796) must upcast on the way in, or reintroduce a caller override.
  The version wall makes this moot until upcasting exists, and #796 owns the
  decision.
- **The guard is writer-side only.** Nothing at the database level enforces
  registration; a direct insert bypasses all of it, and several tests already
  write rows that way.
- **`extra="forbid"` guards the top level only.** A field typed `dict[str, Any]`
  accepts arbitrary nested content. #668's durable-reference snapshots are
  exactly the feature that will nest, and will need nested `TypedDict`s to stay
  inside the guarantee.
- **A payload integer is unbounded.** `10**30` validates. A projector writing one
  into an `IntegerField` fails at projection time, inside the command's
  transaction.
- **`source_metadata` stays unvalidated**, as does `idempotency_key` beyond its
  non-empty constraint.

## Verification

- `make check` in full, including `e2e/`.
- The migration dropping `aggregate_type` applies and reverses on an empty
  database.
- Issue #900's acceptance text names `games.events.append_events()`, which does
  not exist; the writer is `LockedStream.append`. The criterion is read against
  the real writer.

## Follow-up issues

1. **Payload upcasting and the read-side leg.** Register an upcaster per
   `(event_type, from_version)`, relax the registration version wall, and upcast
   in `RecordedEvent`/`replay` before a projector sees a payload. Hard
   prerequisite for the first schema change.
2. **A retired-event-type tier.** So an event type can stop being appendable
   without making historic streams unreplayable.
3. **`source_metadata` validation.** The last unvalidated JSONB column on the
   event row.
4. **Nested payload schemas.** Decide, with #668, whether nested objects must be
   `TypedDict`s to stay inside `extra="forbid"`.
