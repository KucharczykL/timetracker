# The authenticated command-dispatch boundary

[#661](https://github.com/KucharczykL/timetracker/issues/661),
[#662](https://github.com/KucharczykL/timetracker/issues/662), and
[#663](https://github.com/KucharczykL/timetracker/issues/663) built an event
kernel with no caller: a stream that locks, a key that deduplicates, a
transaction that retries. Each one deferred the same questions to this issue —
what a command *is*, who is allowed to issue one, and which library it acts on.

The
[overhaul architectural charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md)
states the contract this issue implements: "All player-history writes go through
named commands. A command validates current state and emits one or more
immutable events." And, for the boundary's other half: "Every command accepts a
PlayerLibrary context and rejects cross-library references… Staff status is never
an implicit bypass in normal library views."

## What it is

One function that turns an authenticated actor plus a named command into an
appended, idempotent, retried, library-scoped range of events — and one base
class that makes a command's input and its idempotency fingerprint the same
thing.

## Ownership boundary

| Not here | Owner |
| --- | --- |
| Synchronous projector registration and execution inside the transaction | #665 |
| Deterministic empty-state replay | #666 |
| Optional `expected_sequence` optimistic-concurrency check | #901 |
| Event-type registry and payload validation | #900 |
| Durable reference snapshots in payloads | #668 |
| Concrete domain commands, their forms, views, and URLs | #671 |
| Blocking direct writes to event-sourced projections | #737 |
| Auditing forms, APIs, admin, imports, tasks, scripts for bypasses | #738 |
| Mapping a conflict to an HTTP status, a page, or a toast | follow-up, #671-owned |

This issue owns the command base class, the command-name allowlist, the
authorization check, the canonical-input derivation, and the single composition
of transaction → idempotency → stream lock → append.

**It ships no domain command.** The first one is #671's. Everything here is
proven against commands defined for the purpose, whose names are allowlist
members marked as such.

## Preconditions

Nothing already established is restated. What is load-bearing:

- `lock_stream` (#661) refuses to run outside an open transaction and holds the
  head lock until the caller commits.
- `idempotent_append` (#662) checks the key *under* that lock, hashes canonical
  input through the single canonicalizer `_encode_command_value`, and returns
  `AppendResult | ReplayedAppend`.
- `run_in_transaction` (#663) opens the transaction, refuses to nest, retries a
  closed set of PostgreSQL failures, and raises `RetryBudgetExhausted`.
- `ATOMIC_REQUESTS` is unset, so a request does not arrive inside a transaction.
- `UserLibrary` is one-to-one with `User` and created by signal, so an
  authenticated actor always has exactly one library.

## Design

### A command is a frozen dataclass whose fields are its input

`Command` is an ABC with one abstract method, `build(context) -> Sequence[NewEvent]`.
Concrete commands are frozen dataclasses, and **their fields are the canonical
input** — the dispatcher derives the idempotency fingerprint from them rather
than accepting an input dict alongside.

This closes the hazard #662 named explicitly and could not fix from where it
sat: a `command_input` parameter and the values a command actually uses are two
things kept in sync by hand, so a field added to a command but forgotten in its
input dict produces a fingerprint that cannot distinguish the new field's values.
Two genuinely different commands then share a fingerprint, and a reused key
replays one as the other. Deriving from `fields()` makes adding a field change
the fingerprint by construction.

The cost is that a command cannot hold anything it does not want fingerprinted —
no request objects, no caches, no lazily-derived conveniences. That is the
intended shape: a command is a value describing an intent, not a service.

### The fingerprint reads fields shallowly, never `dataclasses.asdict`

`asdict()` is the obvious way to turn a dataclass into `fingerprint_command_input`'s
`dict` and it is wrong here. It recurses: any field that is *itself* a dataclass
is destructured into a plain dict before the encoder ever sees it.

`TemporalValue` is a frozen dataclass. So a command carrying one would be
fingerprinted over `TemporalValue`'s internal layout — `canonical`, bounds,
kind, precision, nested `TemporalEndpoint`s — instead of over the canonical
string that #662's `_encode_command_value` exists to produce. The failure is
silent in the direction that matters: equal values still hash equally today, so
tests pass, while the fingerprint's stability now depends on a private field
layout rather than on a documented canonical form. A later refactor of
`TemporalValue` would invalidate every in-flight idempotency key without
touching anything named "idempotency".

Shallow extraction — `{f.name: getattr(command, f.name) for f in fields(command)}` —
keeps `_encode_command_value` as the single canonicalizer, which is what #662
deliberately built. A field type it does not know still raises the `TypeError`
that spec designed, pointing the author at the call site.

### The name is an allowlist member, not a string

`CommandName` is a `StrEnum`, and `Command.name` is a `ClassVar[CommandName]`.
The allowlist is the type: mypy rejects an unlisted name at check time, and
every command the system can run is one grep in one file.

A plain `str` alias would carry no enforcement at all, and a `NewType` would
force wrapping every literal while still validating nothing. A format regex
(`^[a-z]+(\.[a-z_]+)+$`) was considered and rejected as the weaker guard: it
constrains shape without constraining membership, so a typo that happens to be
well-formed still defines a command.

The name is in the fingerprint alongside the fields. Without it, one key reused
across two command types whose fields coincide replays one as the other — the
exact failure idempotency exists to prevent, arriving silently as someone else's
sequence range.

Members are stable domain symbols (`session.create`), not Python paths. Renaming
or moving a command class must not invalidate keys already issued under it, and
an audit row should read as a domain term.

### `__init_subclass__` enforces the two things the type cannot

The enum makes an *unlisted* name impossible. Two remaining errors are runtime:

**A concrete command with no name.** `Command.name` has no default, so a
subclass that omits it fails at first dispatch with `AttributeError` — far from
the definition that caused it. `__init_subclass__` raises at class definition,
which is import time, which is startup.

Distinguishing "concrete command that forgot its name" from "abstract
intermediate base that legitimately has none" uses `inspect.isabstract(cls)`.
This looks unsafe — `ABCMeta.__new__` computes `__abstractmethods__` *after*
`type.__new__` calls `__init_subclass__`, so the flag is not set yet. It works
anyway, and deliberately: `__abstractmethods__` is a getset on `type`, not an
ordinary inherited attribute, so `hasattr` is `False` during subclass creation
and CPython's `inspect.isabstract` falls through to a manual scan for
still-abstract members. Verified on 3.14: an intermediate base that does not
implement `build` reports `True`, a concrete command reports `False`.

**Two classes claiming one member.** The enum guarantees the *member* is unique,
not that one class owns it. A registry mapping name → class catches this.

That registry has a trap. `@dataclass(slots=True)` cannot add slots to an
existing class, so it **builds a replacement class** — which fires
`__init_subclass__` a second time, for a different class object with the same
name. Verified on 3.14: a slotted command registers twice. A registry keyed on
identity alone would reject every slotted command as a duplicate of itself, and
the natural author reaction — dropping `slots=True` — would make the check pass
by weakening the command.

So the registry stores `name → (module, qualname)`. A second registration
carrying the same pair is the slots rebuild and replaces the entry; a different
pair is the real collision and raises.

### Authorization happens before the database

`dispatch` checks `actor.is_active` and `library.user_id == actor.pk` before it
touches a connection, raising `CommandNotPermitted`.

Order matters: `lock_stream` calls `get_or_create` on the stream head, so
authorizing after opening the transaction would let a rejected dispatch leave a
stream-head row behind for a library it was never allowed to write. Checking
first means a refused command is inert.

Staff status appears nowhere in the check, per the charter. There is no
`is_superuser` branch to remove later because there is none to add.

`CommandNotPermitted` is **not** a `CommandConflict`. #663's base means "another
command was in the way; retrying may work". A cross-library dispatch will never
work, and inheriting the conflict base would put it inside whatever retry-prompt
handling #671 builds.

The charter's "an object belonging to another library is returned as not found,
not disclosed through a permission error" governs the *view* layer, where a
lookup happens. By the time `dispatch` is called the caller already holds both
objects; a typed exception is the honest signal, and the view (#671) decides
whether that becomes a 404.

### The command receives a context, not a stream

`build` takes `CommandContext(library, actor, stream)`, not `LockedStream`.

A command validating against current state needs the library to scope its
queries; a command recording who acted may need the actor. Passing only the
stream forces each command to carry its own copy of both — and nothing then
guarantees the library a command validates against is the library the dispatcher
authorized. One object, assembled by the dispatcher after the check, removes
that gap.

It is also the extension point the next two issues want: #665 attaches projector
execution and #901 an expected-sequence check, both by adding to the context
rather than by changing every command's signature.

### The result collapses the union

`dispatch` returns `CommandResult(stream_id, first_sequence, last_sequence, replayed)`.

#662 chose `AppendResult | ReplayedAppend` so that running projections against a
replay is a type error rather than a review catch, and said the union should not
propagate past the command boundary. This is that boundary. Projectors (#665)
run *inside* the transaction, so no caller outside needs the event objects, and
letting them escape invites reads taken after the lock is gone.

`replayed: bool` rather than a nullable events tuple: outside callers branch on
"did this actually do something", not on which class they got.

### Correlation ID is generated once, outside the retry loop

Optional parameter, defaulting to a fresh UUID — generated before
`run_in_transaction`, so every attempt of a retried command carries one
correlation ID.

The default is safe here in a way the idempotency key's would not be. A
generated correlation ID means "this action is its own action", which is true of
every single-command call. A generated *idempotency key* would mean "this
request has never been seen", which is exactly what a double submission is not —
so the key stays required with no default, and a caller omitting it gets a type
error rather than silently unprotected dedupe.

Compound actions spanning two dispatches pass one correlation ID deliberately.
They do **not** get one transaction: each dispatch owns its own (see
foreclosures).

### System writes are not expressible here

`dispatch` requires a `User`. `actor=None` — which the kernel accepts, for
migration and import writes — cannot be expressed at this boundary at all.

"Authenticated command dispatch" is then literally true, and a non-human writer
has to be a deliberate decision rather than a default argument. Migrations and
backfills keep calling the kernel directly; #738's bypass audit decides which of
them deserve a door.

### It stops at the exception

#663 parked conflict-to-response mapping here. It is deferred again, for the
same reason #663 deferred it: there is still no evented view. A handler written
now is shaped against an imaginary request and would be rewritten by the first
real one.

A follow-up issue is filed and owned by #671, which is where a conflict has a
request, a page, and a user to be shown to.

## API contract

```python
# games/events/dispatch.py

class CommandName(StrEnum):
    #: Placeholders exercising the kernel until #671 lands real commands.
    TEST_KERNEL_ONE = "test.kernel.one"
    TEST_KERNEL_TWO = "test.kernel.two"


class CommandNotPermitted(Exception): ...


@dataclass(frozen=True, slots=True)
class CommandContext:
    library: UserLibrary
    actor: User
    stream: LockedStream


@dataclass(frozen=True, slots=True)
class CommandResult:
    stream_id: uuid.UUID
    first_sequence: int
    last_sequence: int
    replayed: bool


class Command(ABC):
    name: ClassVar[CommandName]

    @abstractmethod
    def build(self, context: CommandContext) -> Sequence[NewEvent]: ...


def dispatch(
    command: Command,
    *,
    actor: User,
    library: UserLibrary,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID | None = None,
    source_metadata: SourceMetadata | None = None,
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
) -> CommandResult: ...
```

## Where the behaviour is pinned

`tests/test_command_dispatch.py`. Every test that reaches `dispatch` needs
`django_db(transaction=True)`, because `run_in_transaction` refuses to nest and
pytest-django's ordinary `django_db` wraps each test in a transaction — the tax
#663 documented and accepted.

Definition-time guards (no database):

- a concrete command without `name` raises at class definition
- an abstract intermediate base without `name` is accepted
- two classes claiming one `CommandName` raise at definition
- a slotted command defines cleanly — the `__init_subclass__` double-fire does
  not read as a duplicate

Dispatch:

- happy path returns `replayed=False` and appends a contiguous range; the events
  carry the library, actor, correlation ID, idempotency key, and source metadata
- the same key with the same command returns `replayed=True`, the original
  range, and appends nothing
- the same key with a changed field value raises `IdempotencyKeyMismatch`
- **the same key and identical field values under a different `CommandName`
  raises `IdempotencyKeyMismatch`** — the name is in the fingerprint
- a command with a `TemporalValue` field: equal values replay, different values
  mismatch — the shallow read reaches `_encode_command_value`
- a command that is not a dataclass raises `TypeError`
- `build` receives the dispatcher's library and actor

Authorization:

- another user's library raises `CommandNotPermitted`, appends nothing, and
  leaves **no stream-head row** for that library
- an inactive user raises `CommandNotPermitted`
- a staff user against another user's library raises `CommandNotPermitted`

Composition:

- correlation ID is generated when absent and shared by every event of the
  dispatch; a supplied one is used verbatim across two dispatches
- `dispatch` inside an open `atomic()` raises `NestedTransactionNotSupported`
- a command failing retryably on its first attempt produces one result and one
  set of events — the runner is actually wired in, not merely importable

## What this shape forecloses

**Dispatching a command by name string.** The registry maps name → definition
site for collision detection, not name → class for lookup. A future HTTP
endpoint accepting `{"command": "session.create", …}` would need the reverse
map and a per-command input deserializer; the map is a few lines, the
deserializer is the real work, and neither is needed by a form-driven UI.

**Two commands in one transaction.** Each `dispatch` opens its own, because
`run_in_transaction` refuses to nest. A compound action shares a correlation ID
but not atomicity. This is the charter's own answer — "compound and bulk
commands therefore never acquire multiple stream-head locks" — a compound action
is *one* command emitting several events. Removing the limit means a
`dispatch_many` that runs several commands under one runner with one key each,
and a decision about what a partial failure means.

**A command defined outside this repository.** The allowlist is a closed enum;
a plugin cannot add a member. Deliberate — the audit trail's vocabulary is
fixed and reviewable.

**A non-human writer with a proper envelope.** Imports and migrations bypass the
boundary entirely rather than passing through it with `origin` metadata. #738
decides whether that stays true.

## Verification

Full `make check` — lint, format-check, mypy, ts-check, vitest, and the entire
pytest suite including `e2e/`.

No migration, no schema change, no data change: this issue adds a module and its
tests. Reversibility is `git revert` — nothing has run yet that could leave a
row behind, because no caller exists until #671.

## Follow-up issues to file

- Map `CommandConflict` to an HTTP status, page, or toast at the first evented
  view — owned by #671.
