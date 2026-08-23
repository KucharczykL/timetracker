# The authenticated command-dispatch boundary

[#661](https://github.com/KucharczykL/timetracker/issues/661),
[#662](https://github.com/KucharczykL/timetracker/issues/662), and
[#663](https://github.com/KucharczykL/timetracker/issues/663) built the pieces of a
write path with no caller: a stream that locks, a key that deduplicates, a
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
| What a *no-op* command means, and whether one is legal | follow-up, #671-owned |
| Administrator-assisted repair (actor ≠ owner) | follow-up |

This issue owns the command base class, the command-name allowlist, the
authorization check, the canonical-input derivation, the refusal vocabulary, and
the single composition of transaction → idempotency → stream lock → append.

**It ships no domain command.** The first ones are #671's. Everything here is
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
- Every `User` has exactly one `UserLibrary` — but **not** because of the
  `post_save` signal, which returns early on `raw or not created` and so is
  bypassed by `loaddata` and any `bulk_create`. The invariant is enforced by
  `assert_library_structure()` running at WSGI/ASGI import
  (`games/readiness.py`, `timetracker/wsgi.py`, `timetracker/asgi.py`), which
  exists precisely because the signal is not sufficient — and which does not run
  under a plain `manage.py` command. `dispatch` therefore treats a missing
  library as the caller's problem: it takes the library as an argument and never
  reaches for `actor.library`.

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

**What a command may hold is therefore narrow, and narrower than "anything it
wants fingerprinted".** `_encode_command_value` raises `TypeError` on any type
it does not know, so a command **cannot hold a model instance at all**. A
command referencing a `Game` carries the UUID and re-fetches inside `build` —
which is also where the charter's "rejects cross-library references" has to
happen, since only `build` has the context to scope the lookup. No shared helper
for that lookup is delivered here and none is owned elsewhere; it is filed as a
follow-up rather than invented against zero call sites.

`Decimal` is a sharper edge and worth naming before a price command meets it:
`_encode_command_value` canonicalises it as `str(value)`, so `Decimal("1.1")`
and `Decimal("1.10")` compare equal but fingerprint differently, turning an
honest retry into `IdempotencyKeyMismatch`. Normalising it belongs to #662's
canonicalizer and would require a `FINGERPRINT_VERSION` bump, so it is filed,
not fixed here.

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
deliberately built.

The canonical input is **nested, not merged**:

```python
{"command": command.command_name.value, "fields": {…}}
```

A flat merge would let a command field collide with the command's own name key
and silently replace it.

`fields()` is also why the "not a dataclass" check is not merely a nicety.
`Command` is an ABC, and mypy cannot know its subclasses are dataclasses, so
`fields(command)` fails `make check` with an `arg-type` error unless an
`is_dataclass(command)` guard textually precedes it and narrows the type. The
runtime guard and the type check are the same line of code.

### The name is an allowlist member, not a string — and it is not called `name`

`CommandName` is a `StrEnum`, and every command declares
`command_name: ClassVar[CommandName]`. The allowlist is the type: mypy rejects
an unlisted name at check time, and every command the system can run is one grep
in one file.

**The attribute is `command_name`, not `name`.** `name` is the most common field
in this domain — `Game.name`, `Platform.name`, `Device.name` — and a command
carrying one would shadow the `ClassVar` with a dataclass field, so the class
would fail registration with an error about a missing command name rather than
about the collision that caused it.

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

**A concrete command with no name.** `Command.command_name` has no default, so a
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
not that one class owns it. A registry mapping name → definition site catches
this.

That registry has a trap. `@dataclass(slots=True)` cannot add slots to an
existing class, so it **builds a replacement class** — which fires
`__init_subclass__` a second time, for a different class object with the same
qualified name. Verified on 3.14: a slotted command registers twice. A registry
keyed on identity alone would reject every slotted command as a duplicate of
itself, and the natural author reaction — dropping `slots=True` — would make the
check pass by weakening the command.

So the registry stores `name → (module, qualname)`. A second registration
carrying the same pair is the slots rebuild and replaces the entry; a different
pair is the real collision and raises.

Two consequences of that key, stated rather than discovered:

- Two genuinely distinct classes that happen to share `(module, qualname)` —
  defined in two branches of an `if`, or inside a parametrized test — read as
  the slots rebuild and replace each other silently.
- Subclassing a *concrete* command is impossible: the subclass inherits
  `command_name` and registers under it from a different qualname, which is the
  collision case. Commands compose by sharing an abstract base, not by
  inheritance from a concrete one.

### Authorization happens before any database work

`dispatch` checks `actor.is_active` and `library.user_id == actor.pk` before it
touches a connection, raising `CommandNotPermitted`.

The tempting justification for that ordering is wrong and worth recording as
wrong: "authorizing inside the transaction would leave a stream-head row behind,
because `lock_stream` calls `get_or_create`". It would not. `CommandNotPermitted`
is a plain `Exception`, so it escapes `run_in_transaction`'s `atomic` block and
the attempt rolls back, head row included. Verified against a real database.

The ordering earns its place for two other reasons. First, `lock_stream` takes
`SELECT … FOR UPDATE` on the head; authorizing afterwards means a rejected
dispatch briefly **locks another library's stream**, blocking that library's
legitimate writers on a command that can never commit. Second, a command that
cannot succeed should not open a transaction or consume a retry budget.

Both are observable, so the check is pinned by "authorization raises before any
query is issued" rather than by an after-the-fact row count that passes under
either ordering.

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

### A command that refuses has a word for it

The charter says a command "validates current state and emits one or more
immutable events". This boundary therefore owns the vocabulary for the other
outcome, which nothing else does: `CommandRejected`, raised from `build` when
current state does not permit the action ("that session has not started").

It is a plain `Exception`, not a `CommandConflict` — nobody was in the way and
retrying is pointless — and not a `CommandNotPermitted`, which is about who is
asking rather than about what they asked for. Without it, an author's only
options are a bare `ValueError`, which `run_in_transaction` lets through
untranslated, or a conflict subclass that would render as "try again".

**Returning no events is a programming error, not a refusal.**
`LockedStream.append` raises `ValueError` on an empty sequence, and #662 chose
that deliberately to mark it a bug. So a command that finds nothing to do raises
`CommandRejected`; it does not return `[]`. Whether a genuinely idempotent no-op
("set status to `f` when it is already `f`") deserves a *success* outcome
instead is a real question with no real command to answer it — filed for #671.

### The command receives a context, and the context does not contain the stream

`build` takes `CommandContext(library, actor)`.

The library scopes every query a command makes while validating; the actor is
there for a command that records who acted. Passing neither — handing `build`
the `LockedStream` as #662's callback signature does — forces each command to
carry its own copies, and nothing then guarantees the library a command
validates against is the library the dispatcher authorized.

**The stream is deliberately absent.** `LockedStream.append` is public, so a
command holding the stream can append directly and then *also* return events;
`idempotent_append` records only the range it appended itself, leaving the
command's own events committed inside the stream but outside the range the
idempotency key replays. Verified against a real database: a rogue `build`
produced sequences 1–2 with an idempotency record covering only 2, orphaning a
committed event. #662 deleted its `append_events` helper for precisely this
reason — that it "gives a command author in #664 an easy way to write a command
that silently cannot deduplicate" — and putting the stream in the context would
hand the same capability to every command instead of one.

Nothing is lost by withholding it: #901's `expected_sequence` is checked by the
dispatcher against the head, not by `build`, and #665 attaches projectors to the
dispatcher's transaction rather than to the command.

The context is assembled **inside the callback `idempotent_append` invokes**,
per attempt — not once before `run_in_transaction`. A context built outside the
loop would survive a rolled-back attempt and carry stale model instances into
the next one.

### The result collapses the union

`dispatch` returns
`CommandResult(stream_id, first_sequence, last_sequence, replayed, correlation_id)`.

#662 chose `AppendResult | ReplayedAppend` so that running projections against a
replay is a type error rather than a review catch, and said the union should not
propagate past the command boundary. This is that boundary. Projectors (#665)
run *inside* the transaction, so no caller outside needs the event objects, and
letting them escape invites reads taken after the lock is gone.

`replayed: bool` rather than a nullable events tuple: outside callers branch on
"did this actually do something", not on which class they got.

`correlation_id` is on the result because `dispatch` may have generated it. The
charter's compound action — "a compound user action shares a correlation ID.
This lets the Journal render one meaningful entry" — otherwise forces every
caller to generate one defensively just in case a second dispatch follows.

### Correlation ID is a UUIDv7, generated once, outside the retry loop

`LibraryEvent.correlation_id` is a `UUIDv7Field` over a PostgreSQL domain with a
version check, so a `uuid4` reaches the database and dies as SQLSTATE 23514 —
which `is_retryable` correctly classifies as terminal, surfacing a raw
`IntegrityError` rather than any typed conflict. Verified. The annotation
`uuid.UUID` does not catch it, so `dispatch`:

- defaults to `uuid.uuid7()` (stdlib on 3.14, the same callable `UUIDv7Field`
  uses as its default);
- validates a *supplied* one with `validate_uuidv7` from `timetracker.uuidv7`,
  raising rather than letting it become an opaque integrity error four frames
  down. A caller wiring in a request ID from middleware is the obvious way to
  arrive here with a v4.

Generation happens before `run_in_transaction`, so every attempt of a retried
command carries one correlation ID.

The default is safe here in a way the idempotency key's would not be. A
generated correlation ID means "this action is its own action", which is true of
every single-command call. A generated *idempotency key* would mean "this
request has never been seen", which is exactly what a double submission is not —
so the key stays required with no default.

`idempotency_key` is validated for the same reason the correlation ID is: the
column is a `CharField(max_length=255)` under a non-empty check constraint, so
an empty or overlong key would otherwise fail inside `bulk_create` and surface
as a raw `IntegrityError`. `dispatch` rejects both up front.

### System writes are not expressible here

`dispatch` requires a `User`. `actor=None` — which `idempotent_append` accepts, for
migration and import writes — cannot be expressed at this boundary at all.

"Authenticated command dispatch" is then literally true, and a non-human writer
has to be a deliberate decision rather than a default argument. Migrations and
backfills keep calling `idempotent_append` directly; #738's bypass audit decides which of
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
    #: Placeholders exercising dispatch. #671 adds real members and deletes
    #: these.
    TEST_COMMAND_BASIC = "test.command.basic"
    TEST_COMMAND_TWIN = "test.command.twin"
    TEST_COMMAND_TEMPORAL = "test.command.temporal"
    TEST_COMMAND_UNSHAPED = "test.command.unshaped"
    TEST_COMMAND_REJECTING = "test.command.rejecting"
    TEST_COMMAND_FLAKY = "test.command.flaky"


class CommandNotPermitted(Exception): ...


class CommandRejected(Exception): ...


@dataclass(frozen=True, slots=True)
class CommandContext:
    library: UserLibrary
    actor: User


@dataclass(frozen=True, slots=True)
class CommandResult:
    stream_id: uuid.UUID
    first_sequence: int
    last_sequence: int
    replayed: bool
    correlation_id: uuid.UUID


class Command(ABC):
    command_name: ClassVar[CommandName]

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
#663 documented and accepted, and what every test in `tests/test_event_retry.py`
already does.

**Test commands are defined at module level**, one per allowlist member. They
cannot be defined inside test functions: the registry keys on `(module,
qualname)`, so two functions each defining `class Command` produce distinct
qualnames under one member and raise a collision at class-definition time,
inside the test. The one place a class *is* defined in a function body is the
duplicate-name test, which wants exactly that error.

Definition-time guards (no database):

- a concrete command without `command_name` raises at class definition
- an abstract intermediate base without `command_name` is accepted
- a second class claiming a used `CommandName` raises at definition
- a slotted command defines cleanly — the `__init_subclass__` double-fire does
  not read as a duplicate
- **no `TEST_COMMAND_*` member survives alongside a real one.** The placeholders
  are inert only while nothing real shares the allowlist with them, and an
  allowlist that claims to be the readable inventory of everything the system
  can do cannot also hold undeleted scaffolding. The assertion is vacuous until
  the first real member lands and then fails loudly, which makes the cleanup a
  gate rather than a memory.

Dispatch:

- happy path returns `replayed=False` and appends a contiguous range; the events
  carry the library, actor, correlation ID, idempotency key, and source metadata
- the same key with the same command returns `replayed=True`, the original
  range, and appends nothing
- the same key with a changed field value raises `IdempotencyKeyMismatch`
- **the same key and identical field values under a different `CommandName`
  raises `IdempotencyKeyMismatch`** — `TEST_COMMAND_TWIN` exists to be the twin
- a command with a `TemporalValue` field: equal values replay, different values
  mismatch — the shallow read reaches `_encode_command_value`
- a command that is not a dataclass raises `TypeError`
- `build` receives the dispatcher's library and actor, and a context carrying no
  stream — pinned by the dataclass's field set, so adding one is a deliberate act
- a `build` that raises `CommandRejected` appends nothing and the exception
  reaches the caller untranslated

Authorization:

- another user's library raises `CommandNotPermitted` **before any query is
  issued** (`django_assert_num_queries(0)`)
- an inactive user raises `CommandNotPermitted`, likewise with no query
- a staff user against another user's library raises `CommandNotPermitted`

Envelope validation:

- a `uuid4` correlation ID raises before reaching the database
- a supplied `uuid7` is used verbatim and returned on the result
- an empty or 256-character idempotency key raises before reaching the database

Composition:

- the correlation ID is generated **once per dispatch, not once per attempt** —
  pinned by counting calls to the generator across a dispatch that retries, not
  by inspecting the surviving attempt's rows, which look identical either way
- `dispatch` inside an open `atomic()` raises `NestedTransactionNotSupported`
- a command failing retryably on its first attempt produces one result and one
  set of events — the runner is actually wired in, not merely importable

That last test raises an `OperationalError` whose `__cause__` carries SQLSTATE
`40P01`, the shape `tests/test_event_retry.py` already uses. It needs
attempt-counting state that is neither a field nor a database row, which
knowingly violates `run_in_transaction`'s documented "no effects outside the
database" contract. That is the only way to exercise the runner through a
frozen command, and it is a test-only violation worth naming rather than
discovering.

## What this shape forecloses

**Administrator-assisted repair.** `library.user_id == actor.pk` makes
`actor != owner` inexpressible, while the charter explicitly reserves it — "an
explicit administrator-assisted repair may act on behalf of a library while
retaining who performed it" — and `LibraryEvent.actor` is a separate nullable FK
precisely so that case can be recorded. The charter's other sentence ("staff
status is never an *implicit* bypass in normal library *views*") forbids the
implicit form, not the explicit one. Removing the limit costs one predicate plus
a separate, named entry point that cannot be reached by ordinary view code.
Filed as a follow-up; no sibling issue owns it today.

**Dispatching a command by name string.** The registry maps name → definition
site for collision detection, not name → class for lookup. A future HTTP
endpoint accepting `{"command": "session.create", …}` would need the reverse map
and a per-command input deserializer; the map is a few lines, the deserializer
is the real work, and neither is needed by a form-driven UI.

**Two commands in one transaction.** Each `dispatch` opens its own, because
`run_in_transaction` refuses to nest. A compound action shares a correlation ID
but not atomicity. This is the charter's own answer — "compound and bulk
commands therefore never acquire multiple stream-head locks" — a compound action
is *one* command emitting several events. Removing the limit means a
`dispatch_many` running several commands under one runner, and a decision about
what a partial failure means.

**A command holding a model instance.** `_encode_command_value` raises on
unknown types, so commands carry UUIDs and re-fetch. The failure is a runtime
`TypeError` at dispatch, not a mypy error, so it is discovered by the first test
rather than by the type checker.

**A command defined outside this repository.** The allowlist is a closed enum;
a plugin cannot add a member. Deliberate — the audit trail's vocabulary is fixed
and reviewable. The test-only members are the cost of that choice arriving
before any real command; #671 deletes them.

**A non-human writer with a proper envelope.** Imports and migrations bypass the
boundary entirely rather than passing through it with `origin` metadata. #738
decides whether that stays true.

## Verification

Full `make check` — lint, format-check, mypy, ts-check, vitest, and the entire
pytest suite including `e2e/`.

No migration, no schema change, no data change: this issue adds a module and its
tests. Reversibility is `git revert` — nothing has run yet that could leave a
row behind, because no caller exists until #671.

## Follow-up issues

Filed and listed in #601 under "Follow-ups from the dispatch boundary", so they
are tracked by the phase rather than by this document alone.

Needing a real command first, so they follow #671:

- #905 — map `CommandConflict` to an HTTP status, page, or toast at the first
  evented view.
- #906 — decide what a no-op command means: `CommandRejected`, or a success
  result with an empty range.
- #907 — delete the `TEST_COMMAND_*` allowlist members.

Independent of #671:

- #908 — administrator-assisted repair dispatch: an explicit entry point where
  actor and owner differ, recording both.
- #909 — a shared helper resolving a UUID field to a library-scoped object
  inside `build`, so "rejects cross-library references" is one call rather than
  a convention.
- #910 — `Decimal` canonicalisation in `_encode_command_value`: `Decimal("1.1")`
  and `Decimal("1.10")` fingerprint differently, so an honest retry of a price
  command becomes `IdempotencyKeyMismatch`. Needs a `FINGERPRINT_VERSION` bump,
  and is cheaper before the first price-carrying command exists.
