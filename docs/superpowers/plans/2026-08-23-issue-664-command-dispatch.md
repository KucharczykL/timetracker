# Authenticated command-dispatch boundary — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the #661/#662/#663 event kernel its single authenticated caller — a
`dispatch()` that turns a named, frozen-dataclass command plus an actor and a
library into an appended, idempotent, retried range of events.

**Architecture:** One new module, `games/events/dispatch.py`, composing the three
existing kernel modules in one direction: `dispatch` authorises → derives
canonical input → `run_in_transaction` → `idempotent_append` → `lock_stream` →
`command.build(context)`. Nothing in the kernel changes. No migration, no schema
change, no data change.

**Spec:** `docs/superpowers/specs/2026-08-23-issue-664-command-dispatch-design.md`
— read it before Task 1. It carries the *why* for every decision below; this plan
carries the *what* and the order.

**Tech Stack:** Python 3.14, Django 6, PostgreSQL 18, pytest + pytest-django.

## Global Constraints

- **Python 3.14 only.** Uses PEP 758 bare `except A, B:` and stdlib `uuid.uuid7`.
  A `SyntaxError` in an `except` clause means the wrong interpreter, not broken code.
- **Drive everything through `make`.** Never `direnv exec .`, never raw `uv run` /
  `pytest`. Focused runs: `make test ARGS="tests/test_command_dispatch.py -k <name> -x"`.
- **`PYTEST_WORKERS=0` when debugging a failure** — parallel output interleaves and
  `-x` stops only the worker that hit it.
- **Iterate on `make check-fast`; gate on the full `make check`** (includes `e2e/`)
  before declaring done.
- **Never write to `GeneratedField`s.** Not reachable here, but the rule stands.
- **Complete words in identifiers** — `element` not `el`, `event` not `e`.
- **Comments explain obscure intent only.** No issue or PR references in code
  comments; the spec carries history.

---

## File structure

**Create `games/events/dispatch.py`** — the whole deliverable. Everything public
lives here: `CommandName`, `Command`, `CommandContext`, `CommandResult`,
`CommandNotPermitted`, `CommandRejected`, `dispatch`. It sits beside
`append.py` / `idempotency.py` / `retry.py` / `conflicts.py` as the kernel's front
door and imports from all four.

**Create `tests/test_command_dispatch.py`** — one test module. Its module-level
command classes are shared scaffolding for Tasks 1–4, so they cannot be split
across files: the registry admits one class per `CommandName` member per
interpreter, and a second module defining another command under a used member
would raise at import.

**Nothing else is touched.** No model, no migration, no view, no URL.

---

## Task 1: The allowlist, the base class, and the registry

**Files:**
- Create: `games/events/dispatch.py`
- Create: `tests/test_command_dispatch.py`

**Interfaces:**
- Consumes: `games.events.append.NewEvent` (the return element type of `build`).
- Produces:
  - `class CommandName(StrEnum)` with members `TEST_KERNEL_BASIC`,
    `TEST_KERNEL_TWIN`, `TEST_KERNEL_TEMPORAL`, `TEST_KERNEL_UNSHAPED`,
    `TEST_KERNEL_FLAKY` (values `"test.kernel.basic"` etc.).
  - `class Command(ABC)` with `command_name: ClassVar[CommandName]` and
    `@abstractmethod def build(self, context: CommandContext) -> Sequence[NewEvent]`.
    `CommandContext` arrives in Task 3; until then annotate it as a forward
    reference and add the real class there.

**Why these guards exist** (spec: "`__init_subclass__` enforces the two things
the type cannot"): the enum makes an *unlisted* name impossible, so only two
errors remain runtime — a concrete command that declares no name, and two classes
claiming one member.

**Two traps, both already verified on 3.14 — do not re-litigate them:**

1. `inspect.isabstract(cls)` **works** inside `__init_subclass__`, even though
   `ABCMeta` sets `__abstractmethods__` after `type.__new__`. `__abstractmethods__`
   is a getset on `type`, not an inherited attribute, so `hasattr` is `False`
   during subclass creation and CPython falls through to a manual scan.
2. `@dataclass(slots=True)` **rebuilds the class**, firing `__init_subclass__` a
   second time for a different class object with the same qualname. A registry
   keyed on class identity would reject every slotted command as a duplicate of
   itself.

- [ ] **Step 1: Write the failing tests**

`tests/test_command_dispatch.py`. No database — none of these touch one.

Module-level scaffolding first (every later task reuses it):

```python
@dataclass(frozen=True, slots=True)
class BasicCommand(Command):
    command_name: ClassVar[CommandName] = CommandName.TEST_KERNEL_BASIC
    label: str
    count: int

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        return [
            NewEvent(
                event_type="test.kernel.recorded",
                aggregate_type="test",
                aggregate_id=uuid.uuid7(),
                payload={"label": self.label, "count": self.count},
            )
        ]
```

`TwinCommand` is `BasicCommand`'s fields exactly, under `TEST_KERNEL_TWIN`.

Tests:

- `test_a_concrete_command_must_name_itself` — define a `Command` subclass that
  implements `build` and declares no `command_name`, inside
  `pytest.raises(TypeError)`. Assert the message names `command_name`.
- `test_an_abstract_base_need_not_name_itself` — a subclass that does *not*
  implement `build` defines cleanly. This is the `inspect.isabstract` branch.
- `test_two_classes_cannot_claim_one_name` — inside `pytest.raises(TypeError)`,
  define a second command under `CommandName.TEST_KERNEL_BASIC`. It must be
  defined in the function body: that is what makes its `(module, qualname)`
  differ from `BasicCommand`'s and read as a real collision.
- `test_a_slotted_command_is_not_a_duplicate_of_itself` — assert
  `BasicCommand(label="x", count=1).label == "x"`. The class defining at module
  import *is* the assertion; the double-fire would have raised at collection.

- [ ] **Step 2: Run to verify they fail**

```bash
make test ARGS="tests/test_command_dispatch.py -x"
```

Expected: collection error, `ImportError: cannot import name 'Command' from 'games.events.dispatch'`.

- [ ] **Step 3: Implement**

`CommandName` as a `StrEnum`. Its members carry a comment marking them as kernel-test
placeholders that #671 deletes.

`Command(ABC)` with the `ClassVar` and the abstract `build`. The registry is a
module-level `dict[CommandName, tuple[str, str]]` mapping name → `(module, qualname)`.

```python
def __init_subclass__(cls, **kwargs: object) -> None:
    super().__init_subclass__(**kwargs)
    if inspect.isabstract(cls):
        return
    name = getattr(cls, "command_name", None)
    if not isinstance(name, CommandName):
        raise TypeError(
            f"{cls.__qualname__} declares no command_name. Every concrete "
            "command names itself with a CommandName member."
        )
    definition_site = (cls.__module__, cls.__qualname__)
    registered = _COMMAND_REGISTRY.get(name)
    #: dataclass(slots=True) rebuilds the class, so the same definition site
    #: registering twice is that rebuild rather than a second command.
    if registered is not None and registered != definition_site:
        raise TypeError(
            f"{cls.__qualname__} claims {name.value!r}, already owned by "
            f"{registered[0]}.{registered[1]}."
        )
    _COMMAND_REGISTRY[name] = definition_site
```

Two consequences to record in the module docstring, not discover later: two
distinct classes sharing a `(module, qualname)` replace each other silently, and
subclassing a *concrete* command is impossible (the subclass inherits
`command_name` from a different qualname, which is the collision case).

- [ ] **Step 4: Run to verify they pass**

```bash
make test ARGS="tests/test_command_dispatch.py -x"
```

- [ ] **Step 5: Commit**

```bash
git add games/events/dispatch.py tests/test_command_dispatch.py
git commit -m "feat: name commands from a closed allowlist"
```

---

## Task 2: Canonical input derivation

**Files:**
- Modify: `games/events/dispatch.py`
- Modify: `tests/test_command_dispatch.py`

**Interfaces:**
- Consumes: `Command` (Task 1); `games.events.idempotency.fingerprint_command_input`.
- Produces: `def canonical_command_input(command: Command) -> dict[str, Any]`,
  returning `{"command": <name value>, "fields": {<field name>: <value>}}`.

**The two rules this task exists to enforce** (spec: "The fingerprint reads fields
shallowly, never `dataclasses.asdict`"):

1. **Shallow, never `asdict`.** `TemporalValue` is itself a frozen dataclass, so
   `asdict` would destructure it and never reach `_encode_command_value`'s
   canonical-string branch. Equal values would still hash equally *today*, so the
   bug is invisible until a `TemporalValue` refactor invalidates every in-flight
   idempotency key.
2. **Nested, never merged.** A flat `{**fields, "command": name}` lets a command
   field named `command` silently replace the command's own identity.

`is_dataclass(command)` must textually precede `fields(command)`. It is not only
a runtime guard: `Command` is an ABC, mypy cannot know subclasses are dataclasses,
and `fields()` fails `make check` with an `arg-type` error without the narrowing.

- [ ] **Step 1: Write the failing tests**

- `test_canonical_input_nests_name_and_fields` — assert the exact dict for
  `BasicCommand(label="x", count=1)`.
- `test_canonical_input_reads_temporal_values_shallowly` — a command with a
  `TemporalValue` field; assert `canonical_command_input(...)["fields"]["when"]`
  **is the `TemporalValue` instance**, not a dict. Then assert
  `fingerprint_command_input` of it succeeds and differs from the same command
  with a different temporal value. Use `TEST_KERNEL_TEMPORAL`.
- `test_a_command_that_is_not_a_dataclass_is_rejected` — a plain-class command
  under `TEST_KERNEL_UNSHAPED` implementing `build`; `pytest.raises(TypeError)`.
- `test_the_command_name_enters_the_fingerprint` — `fingerprint_command_input` of
  `BasicCommand(label="x", count=1)` differs from that of
  `TwinCommand(label="x", count=1)`, whose fields are identical.

- [ ] **Step 2: Run to verify they fail**

```bash
make test ARGS="tests/test_command_dispatch.py -k canonical -x"
```

- [ ] **Step 3: Implement**

```python
def canonical_command_input(command: Command) -> dict[str, Any]:
    if not is_dataclass(command):
        raise TypeError(
            f"{type(command).__qualname__} is not a dataclass. A command's "
            "fields are its canonical input, so it has none to fingerprint."
        )
    #: Shallow: asdict() would destructure a TemporalValue field before
    #: idempotency's canonicalizer could reduce it to its canonical string.
    return {
        "command": command.command_name.value,
        "fields": {
            field.name: getattr(command, field.name) for field in fields(command)
        },
    }
```

- [ ] **Step 4: Run to verify they pass, and that mypy is clean**

```bash
make test ARGS="tests/test_command_dispatch.py -x"
make typecheck
```

- [ ] **Step 5: Commit**

```bash
git add games/events/dispatch.py tests/test_command_dispatch.py
git commit -m "feat: derive a command's canonical input from its fields"
```

---

## Task 3: Context, result, refusals, and envelope validation

**Files:**
- Modify: `games/events/dispatch.py`
- Modify: `tests/test_command_dispatch.py`

**Interfaces:**
- Consumes: `games.models.UserLibrary`; `django.contrib.auth.models.User`;
  `timetracker.uuidv7.validate_uuidv7`; `games.events.append.LockedStream` (for
  the docstring's contrast only — it is deliberately *not* a field).
- Produces:
  - `CommandContext(library: UserLibrary, actor: User)` — frozen, slots.
  - `CommandResult(stream_id, first_sequence, last_sequence, replayed: bool,
    correlation_id: uuid.UUID)` — frozen, slots.
  - `class CommandNotPermitted(Exception)`, `class CommandRejected(Exception)`.
  - `def authorize(actor: User, library: UserLibrary) -> None`
  - `def resolve_correlation_id(correlation_id: uuid.UUID | None) -> uuid.UUID`
  - `def validate_idempotency_key(key: IdempotencyKey) -> None`

**`CommandContext` must not carry the stream.** `LockedStream.append` is public;
a command holding it can append directly *and* return events, and
`idempotent_append` records only the range it appended itself — leaving committed
events inside the stream but outside the range the key replays. #662 deleted its
`append_events` helper for exactly this. Nothing is lost: #901 checks
`expected_sequence` at the dispatcher, #665 attaches projectors to the transaction.

**Neither refusal is a `CommandConflict`.** `CommandNotPermitted` is about who is
asking, `CommandRejected` about what they asked for; #663's conflict base means
"someone was in the way, retrying may work", which is false for both.

**`correlation_id` must be a UUIDv7.** `LibraryEvent.correlation_id` is a
`UUIDv7Field` over a PostgreSQL domain with a version check, so a `uuid4` dies
as SQLSTATE 23514 — which `is_retryable` correctly calls terminal, surfacing a
raw `IntegrityError` four frames from the caller. The `uuid.UUID` annotation
catches nothing.

**`idempotency_key` is validated for the same reason**: the column is
`CharField(max_length=255)` under a non-empty check constraint.

- [ ] **Step 1: Write the failing tests**

Needs `owned_user` / `owned_library` from `tests/conftest.py`, plus local fixtures
for a second user (`other_library`) and a staff user. These tests read model
attributes only, so plain `django_db` is fine here — `transaction=True` becomes
necessary in Task 4, where `run_in_transaction` enters.

- `test_the_owner_is_permitted` — `authorize(owned_user, owned_library)` returns
  `None`.
- `test_another_users_library_is_refused` — `pytest.raises(CommandNotPermitted)`.
- `test_an_inactive_user_is_refused` — set `is_active = False`; raises.
- `test_staff_is_not_a_bypass` — a staff+superuser actor against
  `other_library`; raises. Pins the charter's rule.
- `test_a_uuid4_correlation_id_is_refused` — `resolve_correlation_id(uuid.uuid4())`
  raises `ValueError`.
- `test_a_supplied_uuid7_is_used_verbatim`, `test_an_absent_correlation_id_is_generated`
  (assert `.version == 7`).
- `test_an_empty_idempotency_key_is_refused`,
  `test_an_overlong_idempotency_key_is_refused` (256 characters).
- `test_the_context_carries_no_stream` — assert
  `{f.name for f in fields(CommandContext)} == {"library", "actor"}`. Adding the
  stream back must be a deliberate act that breaks a test naming the reason.

- [ ] **Step 2: Run to verify they fail**

```bash
make test ARGS="tests/test_command_dispatch.py -k 'permitted or refused or correlation or idempotency or context' -x"
```

- [ ] **Step 3: Implement**

`authorize` checks `actor.is_active` then `library.user_id == actor.pk`, raising
`CommandNotPermitted` with a message that names neither the other user nor their
library. `resolve_correlation_id` returns `uuid.uuid7()` when given `None`,
otherwise calls `validate_uuidv7` and re-raises as `ValueError`.
`validate_idempotency_key` rejects `""` and anything over 255 characters.

`CommandContext`'s docstring states why the stream is absent.

- [ ] **Step 4: Run to verify they pass**

```bash
make test ARGS="tests/test_command_dispatch.py -x"
```

- [ ] **Step 5: Commit**

```bash
git add games/events/dispatch.py tests/test_command_dispatch.py
git commit -m "feat: add the command boundary's context, result, and refusals"
```

---

## Task 4: `dispatch()`

**Files:**
- Modify: `games/events/dispatch.py`
- Modify: `tests/test_command_dispatch.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3; `run_in_transaction`, `RetryPolicy`,
  `DEFAULT_RETRY_POLICY` (`games.events.retry`); `idempotent_append`,
  `IdempotencyKey`, `ReplayedAppend` (`games.events.idempotency`);
  `SourceMetadata` (`games.events.append`).
- Produces:

```python
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

**Ordering inside the function is load-bearing:**

1. `authorize`, `validate_idempotency_key`, `resolve_correlation_id`,
   `canonical_command_input` — **all before any database work**. A rejected
   dispatch must not take `SELECT … FOR UPDATE` on another library's stream head,
   which would block that library's legitimate writers on a command that can
   never commit, and must not open a transaction or spend a retry budget.
   (The tempting justification — "it would leave a stream-head row behind" — is
   *false*: `CommandNotPermitted` escapes `atomic` and the attempt rolls back.
   Do not write that reason into a comment.)
2. The correlation ID is generated **once, outside** `run_in_transaction`, so
   every attempt of a retried command shares one.
3. `CommandContext` is built **inside** the `build` callback that
   `idempotent_append` invokes — per attempt, not once. A context built outside
   the loop would carry model instances from a rolled-back attempt into the next.

- [ ] **Step 1: Write the failing tests**

**Every test in this task needs `@pytest.mark.django_db(transaction=True)`**, because
`run_in_transaction` refuses to nest and pytest-django's ordinary `django_db`
wraps each test in a transaction. `tests/test_event_retry.py` does the same
throughout; combining it with the `db`-based `owned_library` fixture works.

- `test_a_dispatched_command_appends_its_events` — `replayed is False`, sequence
  range contiguous from 1, and the persisted `LibraryEvent` rows carry the
  library, actor, correlation ID, idempotency key, and source metadata.
- `test_repeating_a_key_replays_the_original_range` — second dispatch returns
  `replayed is True` with the same range; `LibraryEvent.objects.count()` unchanged.
- `test_repeating_a_key_over_changed_fields_is_refused` —
  `pytest.raises(IdempotencyKeyMismatch)`.
- `test_repeating_a_key_under_another_command_name_is_refused` — `BasicCommand`
  then `TwinCommand` with identical field values and the same key;
  `pytest.raises(IdempotencyKeyMismatch)`. This is why `TEST_KERNEL_TWIN` exists.
- `test_build_receives_the_dispatchers_library_and_actor` — a command that records
  `context.library.pk` / `context.actor.pk` into its event payload; assert both.
- `test_a_rejected_command_appends_nothing` — a `build` raising `CommandRejected`;
  the exception reaches the caller untranslated and no events exist.
- `test_authorization_precedes_any_query` — wrap a foreign-library dispatch in
  `django_assert_num_queries(0)` inside `pytest.raises(CommandNotPermitted)`.
  **This is the test that actually pins the ordering** — a row-count assertion
  afterwards passes under either ordering and proves nothing.
- `test_dispatch_refuses_to_nest` — inside `transaction.atomic()`,
  `pytest.raises(NestedTransactionNotSupported)`.
- `test_a_retryable_failure_is_retried_once` — `FlakyCommand`
  (`TEST_KERNEL_FLAKY`) whose `build` raises `wrapped(OperationalError, "40P01")`
  on its first call and succeeds on the second. Reuse `wrapped` from
  `tests/test_event_retry.py` — import it or copy the three-class helper.
  Assert one `CommandResult` and exactly one set of events.
  The attempt counter must be a class attribute or module-level counter, since
  the command is frozen — which knowingly violates `run_in_transaction`'s
  "no effects outside the database" contract. Say so in a comment on the counter:
  it is the only way to exercise the runner through a frozen command.
- `test_the_correlation_id_is_generated_once_per_dispatch` — `monkeypatch` the
  `uuid7` reference *in the dispatch module* with a counting wrapper, dispatch
  `FlakyCommand` so the runner retries, and assert the counter is `1`. Inspecting
  the surviving attempt's rows cannot distinguish once-per-dispatch from
  once-per-attempt, because rolled-back rows are gone.
- `test_a_supplied_correlation_id_is_shared_across_dispatches` — two dispatches,
  distinct keys, one supplied `uuid7`; both results and all events carry it.

- [ ] **Step 2: Run to verify they fail**

```bash
PYTEST_WORKERS=0 make test ARGS="tests/test_command_dispatch.py -x"
```

- [ ] **Step 3: Implement**

```python
def dispatch(command, *, actor, library, idempotency_key, correlation_id=None,
             source_metadata=None, policy=DEFAULT_RETRY_POLICY) -> CommandResult:
    authorize(actor, library)
    validate_idempotency_key(idempotency_key)
    #: Once per dispatch, so every attempt of a retried command shares it.
    resolved_correlation_id = resolve_correlation_id(correlation_id)
    command_input = canonical_command_input(command)

    def build(stream: LockedStream) -> Sequence[NewEvent]:
        #: Per attempt: a context built outside the retry loop would carry
        #: model instances from a rolled-back attempt into the next one.
        return command.build(CommandContext(library=library, actor=actor))

    def run() -> AppendResult | ReplayedAppend:
        return idempotent_append(
            library,
            idempotency_key=idempotency_key,
            command_input=command_input,
            build=build,
            actor=actor,
            correlation_id=resolved_correlation_id,
            source_metadata=source_metadata,
        )

    outcome = run_in_transaction(run, policy=policy)
    return CommandResult(
        stream_id=outcome.stream_id,
        first_sequence=outcome.first_sequence,
        last_sequence=outcome.last_sequence,
        replayed=isinstance(outcome, ReplayedAppend),
        correlation_id=resolved_correlation_id,
    )
```

The `build` closure takes `stream` and ignores it — that is the signature
`idempotent_append` requires, and dropping the parameter on the floor here is
precisely how the stream is kept out of commands' hands.

- [ ] **Step 4: Run to verify they pass**

```bash
PYTEST_WORKERS=0 make test ARGS="tests/test_command_dispatch.py -x"
```

- [ ] **Step 5: Run the full gate**

```bash
make check
```

Expected: green. Not `check-fast` — this is the gate.

- [ ] **Step 6: Commit**

```bash
git add games/events/dispatch.py tests/test_command_dispatch.py
git commit -m "feat: dispatch an authenticated command to the event stream"
```

---

## Task 5: Close the loop on the issue

**Files:**
- Modify: none (repository metadata only)

- [ ] **Step 1: Open the pull request**

Branch is `claude/issue-664-command-dispatch`. The PR body states what the module
delivers, links the spec, and lists the six follow-ups (#905–#910) as filed
rather than forgotten. Per project convention the PR merges with `--merge`, never
squash or rebase.

- [ ] **Step 2: Comment on #664**

Link the spec path and the follow-up issues, so the issue records where its
deferred work went.

---

## Self-review notes

**Spec coverage.** Every design section maps to a task: command shape and
allowlist → 1; fingerprint derivation → 2; context, result, refusals, envelope
validation → 3; ordering, composition, retry and correlation semantics → 4.
Sections with no task are deliberate: "It stops at the exception" and "System
writes are not expressible here" are both *absences*, and the absence of a
system path is enforced by `dispatch`'s `actor: User` signature written in Task 4.

**Deliberately not tested.** That `dispatch` cannot accept `actor=None` is a type
signature, not a runtime check — mypy is the test, and `make check` runs it.

**Known ordering hazard for the implementer.** Task 1 annotates `build`'s
parameter as `CommandContext` before Task 3 defines it. Use
`from __future__ import annotations` or a string annotation, and remove the
workaround in Task 3 — do not create a placeholder class in Task 1 and forget it.
