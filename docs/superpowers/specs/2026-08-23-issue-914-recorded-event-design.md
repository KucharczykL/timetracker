# The value a projector reads

[#665](https://github.com/KucharczykL/timetracker/issues/665) shipped the projector
registry and handed each family the persisted `LibraryEvent`. That was the wrong
input, and this issue replaces it with a frozen value carrying the envelope and
nothing else.

The
[overhaul architectural charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md)
names the field set exactly, in its "Event envelope" section, and states the
property this issue protects: "Projections are rebuildable and tested against a
replay from an empty state." A projector that behaves differently depending on
whether it was reached from an append or from a replay makes that untestable.

## What it is

One frozen dataclass, `RecordedEvent`, built from a `LibraryEvent` row, carrying
all sixteen concrete fields with the three relations as ids — and no relation
descriptor, no manager, and no `save()`.

## Ownership boundary

| Not here | Owner |
| --- | --- |
| Deterministic empty-state replay, which will construct this value from its read | #666 |
| Shadow rebuild and atomic swap | #667 |
| Event-type registry and payload schema validation | #900 |
| Real projector families | #671 |
| A per-append aggregate phase | #913 |
| `AppendResult.events`, which keeps carrying ORM rows | unchanged, see below |

This issue owns the value type, its derivation from the row, the contract test
that keeps the two in step, and the signature changes in
`games/events/projection.py` and `games/events/append.py` that pass it.

## Why the ORM row was the wrong input

A probe measured the append-time row against the same row read back from
PostgreSQL:

| | append-time row | row read back |
| --- | --- | --- |
| `event.actor` | **0 queries** — cached by `bulk_create` | **1 query**, per event |
| `event.stream` | 0 queries | 1 query, per event |
| `event.library` | 1 query | 1 query |

`library` is symmetric only by accident: `append` builds rows with `library_id=`
while using `stream=` and `actor=` for the other two. So a family reading
`event.actor` costs nothing under test and issues 100,000 extra queries across a
100,000-event rebuild, against the charter's 60-second budget.

The fix this issue originally proposed — `select_related("actor", "stream")` on
the replay read — covers the two relations known today. A family traversing a
third one later silently regresses, and every future read has to remember the
right prefetch. It patches instances of the hazard.

Building rows with `actor_id`/`stream_id` so nothing is ever cached would make
the two paths symmetric and cannot drift, but only prices the hazard honestly: a
family can still traverse and be an N+1 on both paths.

Removing the relations from what a family is handed removes the hazard. It also
removes three others the ORM row carried for free — a projector could `save()` an
immutable event, reach `LibraryEvent.objects` through the instance, or hold a row
whose deferred state differs between the two paths.

**This is the moment to do it.** #665 deliberately shipped no family, so the
projector input has zero consumers. After #671 it has one per family.

## Design

### Sixteen fields, relations as ids

Read off `LibraryEvent._meta.concrete_fields`, using `attname` so the three
foreign keys arrive as ids:

`id`, `library_id`, `stream_id`, `sequence`, `event_type`, `aggregate_type`,
`aggregate_id`, `payload_schema_version`, `recorded_at`, `effective_time`,
`actor_id`, `correlation_id`, `causation_id`, `source_metadata`,
`idempotency_key`, `payload`.

Everything, rather than a curated subset. A subset needs a deny-list, which is a
place for judgement to rot, and the first family wanting an excluded field
changes a type every other family shares. Completeness also makes the contract
test trivially strong: it asserts *every* concrete field, with no allow-list to
argue about, so a new column on `LibraryEvent` fails until somebody decides what
it means.

`idempotency_key` is command bookkeeping rather than domain fact and is carried
anyway, because "the envelope, entire" is a rule a reader can check and "the
envelope minus the parts we thought you would not want" is not.

### The derivation is written out, and a test proves it

`from_row` assigns all sixteen fields explicitly, so mypy checks every one. The
guard is a test that walks `LibraryEvent._meta.concrete_fields`, builds a row,
converts it, and asserts each field's **value** survives.

Asserting values rather than field names is deliberate: a name-only test catches
a field the value never grew, but not `actor_id=row.library_id`. Both are drift;
only one of them is visible by reading.

The alternative — `cls(**{field.attname: getattr(row, field.attname) for field in
...})` — makes both failures impossible by construction, and was rejected because
mypy sees `**dict` and checks nothing. That forfeits the static verification that
is most of the reason to introduce a value type at all, and turns a model change
into a cryptic `TypeError` inside an append rather than a named test failure.

### A deferred row is refused

`from_row` reads all sixteen fields, so a row loaded with `.only(...)` or
`.defer(...)` costs **one query per deferred field, per event** — measured: a
deferred attribute access is a real round trip. This is a trap laid directly in
the path of the issue's own purpose, because the obvious way to make a
hundred-thousand-event rebuild read cheaper is to select fewer columns, and here
that makes it fourteen times more expensive.

`from_row` therefore raises when `row.get_deferred_fields()` is non-empty, naming
the deferred fields. The check is sixteen dict lookups per event, which is
nothing beside the round trip it prevents, and it turns a silent performance
collapse into an error at the first event.

### `payload` and `source_metadata` stay plain dicts

The frozen dataclass fixes which objects the fields name; it does not freeze
those objects. Four candidates were measured against what a projector actually
does:

| | deep | `== plain dict`/`list` | `json.dumps` | `isinstance(_, dict)` | new dependency |
| --- | --- | --- | --- | --- | --- |
| plain dict | no | **yes** | **yes** | yes | — |
| `MappingProxyType` | no | yes | **no** | no | — |
| `frozendict` (stdlib, 3.15) | no | yes | **no** | no | — |
| `pyrsistent.freeze` | **yes** | yes | **no** | no | yes |
| `frozendict.deepfreeze` | **yes** | **no** | yes | yes | yes |

Two results decide it.

**Every immutability mechanism breaks either equality or JSON serialization.**
`json.dumps(MappingProxyType({...}))` raises, and so will PEP 814's `frozendict`,
which inherits from `object` rather than subclassing `dict`. A projector writing
`ProjectionRow.objects.create(data=event.payload)` — an ordinary thing for a
projection to do — would break. That is a far more common operation than the
nested mutation being defended against.

**Nothing available is deep and cheap.** Python's immutable containers are all
shallow: `t = (1, [2]); t[1].append(3)` succeeds, and `frozendict` behaves the
same way. `frozenset` is the exception only because it refuses unhashable
elements outright, which a payload type cannot do. Going deep means a
third-party dependency in a twelve-dependency project, and either losing
`json.dumps` (pyrsistent) or losing `payload["tags"] == ["a", "b"]` because lists
become tuples (`frozendict.deepfreeze`).

What remains is narrow and was already narrowed by #665: the payload is a fresh
round-tripped dict, and the row is already inserted, so a mutation cannot reach
the command or the database. The whole exposure is one family mutating what a
later family in the same fold reads — reviewable, and symmetric between append
and replay because both decode a fresh dict.

The docstring says the dicts are read-only. That is discipline, and it is the one
guarantee in this type that rests on it.

### `RecordedEvent`, in `games/events/envelope.py`

The name states what is true of the value — the event exists in the stream —
without presupposing a reader. #666's replay reads the same type and is not
projecting, so `AppliedEvent` or `ProjectedEvent` would claim a lifecycle
position the value does not have.

The module is named for the charter's own section heading, so a reader who greps
the design document for "envelope" finds the code. It is its own module rather
than part of `projection.py` because the value is shared vocabulary: `append`
constructs it, `projection` consumes it, and #666's replay will construct it from
a read without caring whether anything projects. Putting it in `append.py` is not
possible — `append` already imports `projection`, so the type would close an
import cycle.

### The registry stops knowing about the ORM

`projection.py` currently imports `LibraryEvent` for its type aliases. After this
change it imports `RecordedEvent` instead and has no ORM import at all: a
registry of families, keyed by event type, over a value. That is worth naming
because it is the shape the eventual shadow-rebuild registry (#667) needs — a
family set that can be pointed at different tables without the machinery holding
a model reference.

### `AppendResult.events` is unchanged

It keeps carrying `tuple[LibraryEvent, ...]`. Its consumers are `append`'s own
tests and anything wanting the rows it just wrote; none of them is a projector,
and none of them is subject to the replay-parity property this issue protects.
Converting it would widen the change for no guarantee.

## API contract

```python
# games/events/envelope.py

@dataclass(frozen=True, slots=True)
class RecordedEvent:
    """One event as a projector reads it: the envelope, by value.

    Carries no relation, no manager, and no save(), so a family cannot traverse
    to the actor (free at append, one query per event on replay), cannot mutate
    an immutable event, and reads the same value whichever path reached it.

    `payload` and `source_metadata` are plain dicts and are read-only by
    convention; see the design document for why nothing available freezes them
    without breaking either equality or json.dumps.
    """

    id: uuid.UUID
    library_id: uuid.UUID
    stream_id: uuid.UUID
    sequence: int
    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    payload_schema_version: int
    recorded_at: datetime
    effective_time: TemporalValue | None
    actor_id: int | None
    correlation_id: uuid.UUID
    causation_id: uuid.UUID | None
    source_metadata: dict[str, Any]
    idempotency_key: str
    payload: dict[str, Any]

    @classmethod
    def from_row(cls, row: LibraryEvent) -> RecordedEvent: ...
```

```python
# games/events/projection.py — changed

type BoundHandler = Callable[[RecordedEvent], None]
type HandlerMap = Mapping[EventType, Callable[..., None]]


class ProjectorRegistry:
    def apply(self, event: RecordedEvent) -> None: ...
```

```python
# games/events/append.py — changed

for row in rows:
    registry.apply(RecordedEvent.from_row(row))
```

`actor_id` is `int | None` because `LibraryEvent.actor` points at
`settings.AUTH_USER_MODEL`, whose primary key is still an integer — measured, not
assumed. `effective_time` and `causation_id` are the other two nullable fields;
every remaining field is non-null at the database.

## Where the behaviour is pinned

`tests/test_event_envelope.py`, new:

- **the contract test**: for every field in `LibraryEvent._meta.concrete_fields`,
  a converted row's attribute equals the row's — catching a field the value never
  grew *and* a field wired to the wrong source, with a failure naming the field
- the value is frozen: assignment raises `FrozenInstanceError`
- it exposes no `actor`, `library`, `stream`, `objects`, `save`, or `_meta`
- converting a row issues **zero queries** (`django_assert_num_queries(0)`) even
  for a row read back from the database with no relation cached — the measurement
  this whole issue exists for, turned into an assertion
- converting a row loaded with `.only("id", "sequence")` raises, and the message
  names the deferred fields
- a `RecordedEvent` built from an appended row equals one built from the same row
  re-read from PostgreSQL, which is the append/replay parity property stated as a
  single assertion

`tests/test_event_projectors.py`, updated:

- handlers take `RecordedEvent`; the no-database tests construct one directly
  instead of an unsaved model instance, so they stop touching `games.models` at
  all
- the existing "a handler receives the persisted row" test becomes "a handler
  receives the recorded event", asserting the same envelope fields

## What this shape forecloses

**Reading anything not in the envelope.** A family needing the actor's username
must query for it, scoped by `actor_id`, and pay that query visibly on both
paths. That is the point, but it means a Journal family rendering "Lukáš started
X" does a lookup per event unless it batches — a real cost that #671 will meet
and should solve with a per-rebuild cache rather than by restoring the relation.

**Mutating an event.** Deliberate, and the reason the row does not travel.

**Nested payload mutation.** Not closed, and cannot be closed cheaply; see the
measurement above. `event.payload["nested"]["x"] = 1` still succeeds and the next
family in the fold sees it.

**A projector holding a queryset from the event.** Also deliberate: a family that
wants the event's siblings should be given a reason to ask for them explicitly,
because a query per event is the rebuild cost this issue is about.

**Cheap access to the row in a projector's own tests.** A test that wants to
assert against `LibraryEvent` still can; it just cannot get there from what the
handler was given.

## Verification

Full `make check` — lint, format-check, mypy, ts-check, vitest, and the entire
pytest suite including `e2e/`.

No migration, no schema change, no data change. Reversibility is `git revert`: no
projection row exists, because no family does.

**Ordering: this must land before #671.** The projector input is the widest
interface in the event system and it has no consumers today. After #671 the same
change is a migration across every family.

## Follow-up issues

None. #913 remains the only open projector follow-up, and this issue removes the
prefetch work that #666 would otherwise have inherited rather than deferring it.
