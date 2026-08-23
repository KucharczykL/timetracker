# Synchronous projector registration and execution

[#664](https://github.com/KucharczykL/timetracker/issues/664) closed the write
path's first half: a named command, an authorized actor, and a library produce a
committed range of events. Nothing reads them. This issue closes the other half —
the step that turns an appended event into the projection rows every page
actually queries, in the same transaction, before the command returns.

The
[overhaul architectural charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md)
fixes the contract: "Events and their synchronous projection updates commit in
the same PostgreSQL transaction. The design does not introduce eventual
consistency." And, for the read side: "Normal pages and APIs query ordinary
Django projection models. They do not replay events during requests."

## What it is

A registry of ordered projector families, and one call inside the append path
that folds every appended event through them — under the stream-head lock, in the
command's transaction, in an order that does not depend on import order.

## Ownership boundary

| Not here | Owner |
| --- | --- |
| Deterministic empty-state replay | #666 |
| Shadow rebuild, atomic swap, and the `select_related` a replay read needs | #667 |
| Event-type registry and payload *schema* validation | #900 |
| Optional `expected_sequence` concurrency check | #901 |
| Durable reference snapshots in payloads | #668 |
| Real projector families and the projection tables they write | #671 |
| Blocking direct writes to event-sourced projections | #737 |
| Benchmarking the write amplification this makes possible | #670 |
| A per-append aggregate phase (`ProjectorPhase`) | follow-up |

This issue owns the `Projector` base class, the `ProjectorFamily` order, the
registry, the invocation point, the projector error contract, and the
JSON-canonical payload rule that makes append-time and replay-time events the
same value.

**It ships no projector and no projection table.** The first ones are #671's.
Everything here is proven against families defined in the test module and
registered into a registry of the test module's own.

## Preconditions

Nothing already established is restated. What is load-bearing:

- `LockedStream.append` (#661) is reached only through `lock_stream`, holds the
  head lock for the rest of the caller's transaction, and is the single writer of
  `LibraryEvent`.
- `idempotent_append` (#662) calls `build` and `stream.append` only when the key
  is new; a replay returns `ReplayedAppend`, which carries no events.
- `run_in_transaction` (#663) classifies a failure by `type(error)`
  (`IntegrityError` / `OperationalError`) and by `error.__cause__.sqlstate`.
  **Both must survive anything a projector raises**, or the bounded retry stops
  working for every projected command.
- `dispatch` (#664) composes the three and already carries one
  injected-for-tests parameter (`policy`), so a second one is not a new idea.

### Measured, not assumed

A probe appended one event and compared the in-memory `LibraryEvent` that
`bulk_create` produced against the same row read back from PostgreSQL:

| Fact | Result |
| --- | --- |
| `bulk_create` assigns the pk | yes — `UUIDv7Field` has a Python-side default |
| `effective_time`, `recorded_at`, `sequence` round-trip | identical |
| `payload` round-trips | **no** — `("a","b")` → `["a","b"]`, `{1:"a"}` → `{"1":"a"}` |
| `Decimal` / `date` inside a payload | `TypeError` at insert; cannot reach the database |
| `event.payload` is the caller's dict | **yes**, by identity |
| relation caches | append-time instance has `actor` and `stream` cached; the row read back has neither |

The payload result is the one that matters. A family reading
`event.payload["tags"]` would get a `tuple` during dispatch and a `list` during
replay — silently, and exactly where #666 is supposed to prove parity. The
identity result is its twin: a family mutating `event.payload` would mutate the
`NewEvent` the command built.

## Design

### Projectors run inside `LockedStream.append`

`append` writes the rows, advances the head, and then folds those rows through
the registry — all before returning, all under the lock it was already holding,
all in the caller's transaction.

The alternative placements each open a hole. At `idempotent_append`, the public
`LockedStream.append` still commits unprojected events. At `dispatch`, so does
everything that reaches `idempotent_append` or `lock_stream` directly. Putting it
in `append` makes "no event commits unprojected" a property of the only supported
writer rather than a rule people have to remember.

Signals were never available: events are written with `bulk_create`, which emits
no `pre_save` or `post_save`. That constraint pointed at the better design
anyway, since projectors must run in a defined order inside the append's
transaction rather than in whatever order receivers happen to connect.

### The registered unit is a family, not a function

The charter counts in families — "every phase that attaches another synchronous
projector **family** re-measures ordinary and representative bulk commands". A
family is one class, owning one projection concern, declaring which event types
it handles:

```python
class CurrentStateProjector(Projector):
    family_name = ProjectorFamily.CURRENT_STATE

    def _session_created(self, event: LibraryEvent) -> None: ...
    def _session_deleted(self, event: LibraryEvent) -> None: ...

    handles = {
        "session.created": _session_created,
        "session.deleted": _session_deleted,
    }
```

`handles` maps to the **function objects** defined above it in the class body,
never to method-name strings. Renaming `_session_created` without updating the
map is a `NameError` at class definition; with strings it would be a handler that
silently never runs. The registry binds each function to the family instance with
`__get__`.

A class is the unit rather than a free function because #667 must eventually
point a whole family at shadow tables. That is a constructor argument on a class.
For a module-level function it would be a parameter threaded through every
projector ever written, or a thread-local — which is worse.

### Order is the `ProjectorFamily` enum's definition order

```python
class ProjectorFamily(StrEnum):
    CURRENT_STATE = "current_state"
    JOURNAL = "journal"
    STATS = "stats"
```

The order members are written *is* the order they run. Journal and statistics
families will read current-state rows that the current-state family must already
have written in this same transaction, so the order is load-bearing and must not
depend on which module Python imported first.

The three members are the charter's own pipeline (`Projectors → Current-state
projections / Journal / Stats`), declared now with nothing implementing them.
Nothing persists a family name — it is an ordering key, not an audit vocabulary —
so #671 may add, rename, or reorder members freely. That is the difference from
`CommandName`, whose members are hashed into idempotency fingerprints and stored.

A family claiming a member another class already claimed raises at class
definition, guarded on `(module, qualname)` the way `_COMMAND_REGISTRY` is.

### The fold is event-major

```
for event in appended order:
    for family in ProjectorFamily order:
        handler(event)
```

Appending N events and replaying those same N events therefore run the identical
sequence of applications. Parity is structural rather than tested-and-hoped, and
it is the only shape that streams — #666 folding a hundred thousand events cannot
buffer them to hand a family a whole batch.

Family-major would coalesce writes: one Journal row per action instead of one per
event. The charter already supplies that without a batch, because "a compound
user action shares a correlation ID… this lets the Journal render one meaningful
entry", and `correlation_id` is a column on every event row. One row per action is
an upsert keyed on it — expressible event-major, and replay-safe, since re-folding
upserts the same row. This is what Marten calls slicing: a grouping key, not a
transaction boundary. Marten's own async daemon re-batches events into arbitrary
pages precisely so no projection can depend on the original grouping.

The cost of the alternative is not the loop. It is that #666 and #667 would have
to reconstruct the original append batches from contiguous runs of one
`idempotency_key`, which makes *how events were grouped into appends* permanently
part of the domain's meaning — an append could never afterwards be split or
merged without changing projection results.

### An event no family handles is a no-op

Zero handlers is a legitimate state, not an error. Audit History reads
`LibraryEvent` rows directly, so an event whose only consumer is the audit trail
has no projector by design; refusing it would make that inexpressible, and the
first such event would force either a null projector registered to satisfy the
check or the rule being dropped under pressure.

The cost is that a misspelled `event_type` projects nothing and says nothing.
That hole is #900's to close, and it closes it better: an unregistered event type
is rejected at append, which catches the typo whether or not anything was ever
meant to handle it.

### A projector's exception is annotated, never wrapped

```python
try:
    handler(event)
except Exception as error:
    error.add_note(
        f"raised by {family_name} applying {event.event_type} #{event.sequence}"
    )
    raise
```

`run_in_transaction` decides retryability from `type(error)` and
`error.__cause__.sqlstate`. Wrapping a projector failure in a `ProjectionFailed`
would satisfy neither test, so a serialization failure raised inside a projector
would stop being retried — silently, and only for projected commands, which is to
say for every real command after #671. Teaching the retry module to unwrap would
couple it to the projector module and create a second place where "is this
retryable" can be wrong.

`add_note` (3.11+, and the project pins 3.14) leaves the type, the cause and the
SQLSTATE untouched while putting the missing fact — which family, which event —
into the traceback. Its limit is real: nothing can branch on which family failed,
only a human reading the traceback. No caller needs to.

### Payloads must be JSON-canonical, and the row gets the round-trip

`append` refuses a `payload` or `source_metadata` that is not already the value
PostgreSQL will hand back, and stores the round-tripped copy rather than the
caller's object:

```python
def canonical_json[T](value: T, *, label: str) -> T:
    try:
        round_tripped = json.loads(json.dumps(value, allow_nan=False))
    except TypeError, ValueError as error:
        raise PayloadNotCanonical(...) from error
    if round_tripped != value:
        raise PayloadNotCanonical(...)
    return round_tripped
```

`Decimal`, a `set`, and `NaN` all fail as one kind of thing, and a `tuple` or an
int-keyed dict fails on the comparison.

This is what makes handing a projector the in-memory `LibraryEvent` safe: a
payload that survives the check is byte-for-byte what a replay will read, so
append-time and replay-time families see the same value. It rejects rather than
coerces because a command that put a tuple in a payload asked for something the
event store cannot record, and quietly recording a list instead means the event
is not what the command described.

Returning the round-trip rather than the original closes the second half of the
probe's finding, which validation alone does not: `event.payload` is otherwise
the command's own dict *by identity*, so a family mutating it would reach back
into the `NewEvent` that built it — at append, and not on replay, where the dict
is freshly decoded. The round-trip is already computed, so the fresh object is
free.

It is deliberately not schema validation. The rule is "this JSON is already
JSON", knows nothing about which event type it belongs to, and leaves #900's
registry untouched. Every payload literal in the current suite already satisfies
it.

The relation-cache asymmetry is *not* closed here. A family touching
`event.actor` costs no query during dispatch and one query per event during a
rebuild. That is a rebuild-read concern — #667 fixes it with `select_related` on
the replay query, where the knowledge of what to prefetch lives.

### The registry is an object, and tests bring their own

```python
class Widget(Projector, registry=test_registry):
    family_name = ProjectorFamily.CURRENT_STATE
    ...
```

`__init_subclass__` registers into `DEFAULT_REGISTRY` unless handed another. A
test module declares its families at module level against a registry it owns, so
it can claim real family names, mutates nothing global, needs no snapshot/restore
fixture, and leaves nothing to delete when #671 lands. This is the concrete
lesson from #907, which exists only because #664's placeholders had to live in a
closed enum shared with production.

`registry` is threaded through `dispatch` → `idempotent_append` → `append`, each
defaulting to `DEFAULT_REGISTRY`, so an integration test can drive the whole
composed path against its own families. Three extra parameters is the price;
`policy` already set the precedent.

A registry instantiates a family once at registration, with no arguments, and
precomputes `event_type → ordered tuple of bound handlers` so a no-op event is
one dictionary miss. A family's `__init__` therefore runs at import and must do
no work.

`GamesConfig.ready()` imports `games.projectors`, a package created empty by this
issue. Real families live there from #671 onward; importing it now means the
discovery seam is wired and exercised rather than invented later.

The machinery is `games/events/projection.py`, one word apart from the
`games/projectors/` package that holds families. Two modules both called
`projectors` would be unambiguous to the interpreter and a standing trap for
everyone else.

## API contract

```python
# games/events/projection.py

type EventType = str  # "session.created"
type BoundHandler = Callable[[LibraryEvent], None]
type DefinitionSite = tuple[str, str]  # ("games.projectors.current_state", "CurrentStateProjector")


class ProjectorFamily(StrEnum):
    """Every projection family, in the order they run within one event."""
    CURRENT_STATE = "current_state"
    JOURNAL = "journal"
    STATS = "stats"


class ProjectorRegistry:
    def register(self, projector_class: type[Projector]) -> None: ...
    def handlers_for(self, event_type: EventType) -> tuple[BoundHandler, ...]: ...
    def apply(self, event: LibraryEvent) -> None: ...


DEFAULT_REGISTRY = ProjectorRegistry()


class Projector(ABC):
    family_name: ClassVar[ProjectorFamily]
    #: Callable[..., None] rather than Callable[[Self, LibraryEvent], None]:
    #: the values are plain functions read out of the class body, before any
    #: descriptor binding, and mypy will not reconcile the implicit `self`.
    handles: ClassVar[Mapping[EventType, Callable[..., None]]]

    def __init_subclass__(
        cls,
        *,
        abstract: bool = False,
        registry: ProjectorRegistry = DEFAULT_REGISTRY,
        **kwargs: object,
    ) -> None: ...
```

```python
# games/events/append.py — new guard and changed signature

class PayloadNotCanonical(ValueError):
    """A payload or source metadata that is not already what JSONB returns."""


def canonical_json[T](value: T, *, label: str) -> T:
    """Return `value` as JSONB will return it, or raise if it differs."""


class LockedStream:
    def append(
        self,
        events: Sequence[NewEvent],
        *,
        actor: User | None,
        correlation_id: uuid.UUID,
        idempotency_key: str,
        source_metadata: SourceMetadata | None = None,
        recorded_at: datetime | None = None,
        registry: ProjectorRegistry = DEFAULT_REGISTRY,
    ) -> AppendResult: ...
```

`idempotent_append` and `dispatch` each gain the same defaulted `registry`
parameter and pass it down.

`abstract=True` marks an intermediate base. #664's `inspect.isabstract` check
cannot be reused: a family declares handlers in a mapping rather than overriding
an abstract method, so nothing makes an intermediate base detectable.

`DefinitionSite` is redeclared here rather than imported from `dispatch`, because
`append` imports `projection` and `dispatch` imports `append`; importing the
alias back would close the cycle.

## Where the behaviour is pinned

`tests/test_event_projectors.py`. Families are declared at module level against a
module-level test registry.

Definition time, no database:

- a concrete family without `family_name` raises at class definition
- a concrete family without `handles` raises at class definition
- `Projector` subclassed with `abstract=True` and no `family_name` is accepted
- two classes claiming one `ProjectorFamily` in one registry raise at definition
- re-registering the *same* class is not a collision — the `(module, qualname)`
  guard. Unlike `_COMMAND_REGISTRY` no double-fire forces this (a family is not a
  slotted dataclass), so the guard is symmetry and headroom rather than a fix for
  something already happening
- a `handles` entry that is not callable raises at definition
- a family registered into a test registry is absent from `DEFAULT_REGISTRY`

Registry:

- families run in `ProjectorFamily` definition order **regardless of registration
  order** — pinned by registering them backwards
- several families handling one event type all run, in that order
- an event type no family handles resolves to an empty tuple and runs nothing

Append integration (`django_db(transaction=True)`, as every test reaching
`run_in_transaction` must be):

- the recorded call sequence for two events and two families is event-major:
  `(e1, first), (e1, second), (e2, first), (e2, second)`
- a handler receives the persisted row: `pk`, `sequence`, `library_id`,
  `correlation_id` all set
- the head has already advanced when the handler runs
- a handler's write is in the command's transaction: it is gone after a later
  failure rolls the attempt back
- a replayed dispatch — same idempotency key — runs no handler at all
- a handler raising leaves no event, no head advance, and no projection row —
  the whole attempt is gone

The error contract:

- a handler raising `KeyError` propagates as `KeyError`, and its notes name the
  family, the event type, and the sequence
- **a handler raising an `OperationalError` whose `__cause__` carries SQLSTATE
  `40P01` is still retried, and the retry succeeds.** This is the test that
  matters: it is the one that fails if anyone later wraps a projector's exception.
  It uses the `wrapped` helper `tests/test_event_retry.py` already provides.

Payload canonicality:

- a `tuple`, an int-keyed dict, a `Decimal`, a `set`, and `NaN` are each rejected
  with `PayloadNotCanonical`, and nothing is written
- the stored `payload` is **not** the caller's dict by identity, so a handler
  mutating it cannot reach the `NewEvent` the command built
- `source_metadata` is checked on the same terms
- a canonical payload is accepted and equals the value read back — the probe's
  finding, turned into a standing assertion

## What this shape forecloses

**A per-append aggregate phase.** A family folds one event at a time and has no
hook that sees a whole action. The escape hatch is your ordered enum:
`ProjectorPhase` with members in run order, each handler declaring its phase, the
loop becoming phase-major over event-major. It is purely additive — every existing
family reads as `PER_EVENT` — which is exactly why it is not built now. What it
does not do is answer the hard part: what "a batch" means when #666 folds an
existing stream. Filed as a follow-up.

**Pointing a family at a different write target.** A family is instantiated with
no arguments at registration. #667 needs a constructor parameter and a registry
that supplies it; the registry being an object rather than a module dict is what
makes that a change to one class instead of to every projector.

**A projector observing another projector.** Families see events, never each
other's output events, because a projector cannot append. Deliberate: a projector
that emitted events would need its own place in the sequence, its own idempotency
story, and would make replay a fixpoint rather than a fold.

The refusal is enforced, but obliquely: a projector calling `dispatch` is already
inside `run_in_transaction`'s transaction, so it raises
`NestedTransactionNotSupported` — a true message about the wrong subject. Nothing
in this issue improves that, because the first person to hit it will be writing
#671 and will be told to stop, which is the point.

**Asynchronous or deferred projection.** Everything commits together. The charter
forbids the alternative outright, and the 100 ms command budget is what pays for
it. Removing the limit is not a code change but a consistency decision.

**Branching on which family failed.** `add_note` annotates; it does not
discriminate. A caller that needed to recover from "the stats family is broken but
the command should still commit" cannot express it — and should not, since the
charter's guarantee is that projections commit with their events or not at all.

**Per-event queries during rebuild.** Nothing stops a family calling
`event.actor`, which is free at append and one query per event on replay. #667
owns the fix, and until it exists a family doing this passes every test in this
issue while being unusable at rebuild scale.

## Verification

Full `make check` — lint, format-check, mypy, ts-check, vitest, and the entire
pytest suite including `e2e/`.

No migration, no schema change, no data change. The one behavioural change to
existing code is the canonical-payload rule in `append`, which every payload in
the current suite already satisfies. Reversibility is `git revert`: no projector
exists to have written a projection row.

## Follow-up issues

To be filed against #601 and listed there, so the phase tracks them rather than
this document alone:

- `ProjectorPhase`: an ordered phase enum giving families a per-append aggregate
  hook, with a decision about what a batch means during replay.
- Relation prefetching on the replay read, so a family touching `event.actor` is
  not an N+1 across a rebuild — assigned to #667 if it is not already inside it.
