# The event-type registry and payload validation — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `event_type` a registered value and `payload` a validated shape, so
that when #671 appends the first real event, every event ever recorded was
checked at the only place that writes one.

**Architecture:** A registered event type is a module-level `EventSpec` constant
generic over its payload `TypedDict`, held in an `EventTypeRegistry` that
`append` consults before it writes. One `EventWiring` value replaces the
`registry=`/`policy=` parameters currently threaded through
`dispatch -> idempotent_append -> append`. `aggregate_type` stops being a column;
`payload_schema_version` stops being a caller argument; `RecordedEvent` gains a
key-order normalisation that makes the append and replay values identical.

**Spec:** `docs/superpowers/specs/2026-08-24-issue-900-event-type-registry-design.md`
— read it before Task 1. It carries the *why* for every decision below, including
the seven measurements that decided them, and the four defects an adversarial
review found in the first draft.

**Tech Stack:** Python 3.14, Django 6, PostgreSQL 18, pydantic 2.13.4, pytest +
pytest-django.

## Global Constraints

- **Python 3.14 only.** PEP 758's bare `except A, B:` applies **without** a
  binding; a clause needing the error is `except (A, B) as error:`.
- **Drive everything through `make`.** Focused runs:
  `make test ARGS="tests/test_event_vocabulary.py -k refuses -x"`.
- **`PYTEST_WORKERS=0` when debugging a failure**; parallel output interleaves.
- **Iterate on `make check-fast`; gate on the full `make check`.**
- **Complete words in identifiers** — `event`, `spec`, `registry`, `payload`,
  never `evt`, `sp`, `reg`.
- **Comments explain obscure intent only.** No issue references in code comments.
- **`@with_config(ConfigDict(extra="forbid", strict=True))` is the only schema
  configuration form that works.** `__pydantic_config__` in a `TypedDict` body is
  a mypy error; `TypeAdapter(T, config=...)` is a `PydanticUserError`.
- **One migration, on empty tables.** It drops a column and a constraint and
  nothing else. `make makemigrations` already passes `--noinput`; never run the
  bare management command, which prompts and hangs.

---

## File structure

**Create `games/events/vocabulary.py`** — `EventSpec`, `EventTypeRegistry`,
`DEFAULT_EVENT_TYPES`, the four refusals, and `NewEvent` (moved here from
`append.py`). Named `vocabulary` rather than `schema` because "schema" already
means the database schema in this codebase, and `tests/test_event_schema_migration.py`
already exists.

**Create `games/events/wiring.py`** — `EventWiring` and `DEFAULT_WIRING`. Imports
`projection`, `vocabulary`, and `retry`; nothing imports it back.

**Create `tests/test_event_vocabulary.py`** — every registry refusal, and the
guarantee that a test-owned registry is what `append` actually consults.

**Modify** `games/events/append.py` (validate, stamp, drop two `NewEvent`
fields), `games/events/envelope.py` (drop `aggregate_type`, normalise payload key
order), `games/events/projection.py` (`handles` keys on specs),
`games/events/replay.py` (the read guards), `games/events/dispatch.py` and
`games/events/idempotency.py` (wiring), `games/models.py` (drop the column and
its constraint), `pyproject.toml` (declare pydantic).

**Every test module that appends** gains its own specs and its own registry:
`tests/test_event_append.py`, `test_event_replay.py`, `test_event_projectors.py`,
`test_event_idempotency.py`, `test_event_envelope.py`, `test_event_retry.py`,
`test_command_dispatch.py`, `test_event_models.py`.

---

## Task 1: The vocabulary module

**Files:**
- Create: `games/events/vocabulary.py`, `tests/test_event_vocabulary.py`
- Modify: `games/events/append.py` (remove `NewEvent`, import it),
  `games/events/dispatch.py:34` (import `NewEvent` from its new home)

**Interfaces produced:**

```python
class UnregisteredEventType(ValueError): ...


class PayloadInvalid(ValueError): ...


class SchemaNotConfigured(TypeError): ...


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
    def spec_for(self, event_type: str) -> EventSpec[Any]: ...
    def validate(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def __contains__(self, event_type: str) -> bool: ...


DEFAULT_EVENT_TYPES = EventTypeRegistry()
```

**Steps:**

- [ ] Write the module docstring: an event type is a value, the registry is the
      gate, and the vocabulary is deliberately empty until #671.
- [ ] Move `NewEvent` verbatim from `append.py:63-71`, then replace its
      `event_type`/`aggregate_type`/`payload_schema_version` fields with a single
      `spec: EventSpec[Any]`. `append.py` and `dispatch.py` import it from here.
- [ ] `EventSpec.new` returns `NewEvent(spec=self, ...)`. The generic parameter
      is what types `payload`; do not annotate it `dict[str, Any]` "for
      convenience", which throws away the whole point of the shape.
- [ ] `register()` refuses, each with its own exception and a message naming the
      spec: a duplicate `event_type` string, a `payload` that is not a
      `TypedDict` (`typing.is_typeddict`), a schema whose
      `__pydantic_config__` does not set both `extra="forbid"` and
      `strict=True` (`SchemaNotConfigured`), and any `version` but 1
      (`VersionNotUpcastable`, naming upcasting as the missing machinery).
- [ ] `register()` builds the `TypeAdapter` once and keeps it beside the spec.
      Building one per validation is the obvious slow mistake.
- [ ] `validate()` returns pydantic's value and raises `PayloadInvalid` from the
      `ValidationError`, with the event type and the pydantic error list in the
      message.

**Tests:**

- [ ] a registered spec round-trips: `spec_for` returns it, `in` is true
- [ ] `spec_for` on an unknown string raises `UnregisteredEventType` naming it
- [ ] registering two specs sharing an `event_type` string refuses
- [ ] a schema that is not a `TypedDict` refuses
- [ ] a `TypedDict` with no `@with_config` refuses with `SchemaNotConfigured`
- [ ] a `TypedDict` configured `extra="allow"` refuses; so does one without
      `strict=True`
- [ ] `version=2` refuses with `VersionNotUpcastable`, and the message says
      upcasting
- [ ] `validate` accepts a correct payload and returns a dict that is **not** the
      argument object
- [ ] `validate` refuses an extra key, a missing key, a `str` for an `int`, an
      `int` for a `str`, and `True` for an `int` — one parametrized test
- [ ] `validate` on a `float` field given `1` returns `1.0`
- [ ] two registries are independent: registering in one leaves the other empty

**Gotchas:**

- **`EventSpec` must be hashable** — Task 6 uses specs as dict keys. A frozen
  dataclass is, as long as nobody adds an unhashable field.
- **Read the config off the class, not off the adapter.** `with_config` sets
  `__pydantic_config__`; assert on that mapping so the refusal message can say
  which key is wrong.
- **This task registers nothing into `DEFAULT_EVENT_TYPES`** and adds no test
  event type to it. Every spec in the test module is local to the test module.
- Do not give `EventTypeRegistry` a `clear()` or a module-level reset fixture.
  Tests construct their own; a shared mutable default that tests reset is how the
  suite becomes order-dependent.

---

## Task 2: One wiring value instead of three parameters

**Files:**
- Create: `games/events/wiring.py`
- Modify: `games/events/append.py:107`, `games/events/idempotency.py:107`,
  `games/events/dispatch.py:243`, `games/events/replay.py:57`
- Modify: `tests/test_event_replay.py`, `tests/test_event_projectors.py`,
  `tests/test_event_retry.py` (the ~51 `registry=`/`policy=` call sites)

**Interfaces produced:**

```python
@dataclass(frozen=True, slots=True)
class EventWiring:
    projectors: ProjectorRegistry = DEFAULT_REGISTRY
    event_types: EventTypeRegistry = DEFAULT_EVENT_TYPES
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY


DEFAULT_WIRING = EventWiring()
```

**Steps:**

- [ ] Write `wiring.py` with a docstring saying what it is: the collaborators a
      dispatch composes, named once so the seam stops growing a parameter each
      time one is added.
- [ ] Replace `registry: ProjectorRegistry = DEFAULT_REGISTRY` and
      `policy: RetryPolicy = DEFAULT_RETRY_POLICY` with
      `wiring: EventWiring = DEFAULT_WIRING` on `LockedStream.append`,
      `idempotent_append`, `dispatch`, and `replay`. Bodies read
      `wiring.projectors` / `wiring.retry_policy`.
- [ ] Update every call site. This is mechanical: `registry=some_registry`
      becomes `wiring=EventWiring(projectors=some_registry)`.
- [ ] `make check-fast` is green before committing. **No behaviour changes in
      this task** — if a test needs new assertions, it belongs in a later task.

**Gotchas:**

- **`EventWiring` defaults must be the module-level singletons**, not fresh
  instances. A default-constructed `ProjectorRegistry()` would silently detach
  production from every registered family.
- Test modules that build a registry at import time (`test_event_projectors.py:91`,
  `test_event_replay.py:35`) should build one module-level `EventWiring` beside
  it rather than constructing one per call.
- Keep the parameter name `wiring` everywhere. Two names for one thing across
  four modules is exactly the drift the value exists to prevent.

---

## Task 3: `append` validates, and stamps the version

**Files:**
- Modify: `games/events/append.py`, `games/events/vocabulary.py`
- Modify: `tests/test_event_append.py`, and every test module that appends

**Steps:**

- [ ] In `LockedStream.append`, before any row is built and before the head
      advances, per event: resolve the spec **from `wiring.event_types` by
      `event.spec.event_type`** — never from the carried spec object — then
      `canonical_json` the payload, then `wiring.event_types.validate(...)`.
- [ ] Build the row from the **registry's** spec: `event_type` from it,
      `payload_schema_version` from its `version`, `payload` from the validated
      value.
- [ ] Delete `payload_schema_version` from `NewEvent`.
- [ ] Every test module that appends declares its own specs and registers them
      into its own `EventTypeRegistry`, wired in via Task 2's `EventWiring`.
      `tests/test_event_append.py:35` and its siblings stop passing raw strings.
- [ ] Replace `tests/test_event_append.py:172-195` — it currently asserts a
      caller-supplied `aggregate_type` and `payload_schema_version` reach the
      row, a premise this task and Task 4 remove.

**Tests:**

- [ ] appending an event whose type is not in the wired registry raises
      `UnregisteredEventType`, and afterwards: no `LibraryEvent` rows exist, the
      head's `current_sequence` is unchanged, and the transaction can still commit
- [ ] the same three assertions for a payload that fails validation
- [ ] a spec object the test built but never registered is still refused
- [ ] the row's `payload_schema_version` is the spec's, not anything a caller
      passed
- [ ] a `float` field given `1` is stored as `1.0` — read it back from the
      database, not from the returned row
- [ ] a payload that is fine by shape but not JSON-carryable (a `Decimal` under a
      `dict[str, Any]` field) still raises `PayloadNotCanonical`
- [ ] the stored payload is not the caller's object: mutating the dict passed to
      `spec.new` after the append does not change the row

**Gotchas:**

- **Order matters and is testable.** `canonical_json` before `validate`, because
  a field typed `dict[str, Any]` carries content pydantic will not inspect.
- **The refusals must precede `bulk_create` and the head advance.** The existing
  comment at `append.py:110-112` states this contract; the new checks join the
  same block rather than moving into the row loop.
- Do not catch `PayloadInvalid` anywhere in `append` or `dispatch`.
  `run_in_transaction` catches only `IntegrityError` and `OperationalError`, so
  it already escapes un-retried — and a `try` around `registry.apply`-style code
  is what breaks that classifier.
- `tests/test_event_retry.py:288` and `tests/test_event_models.py:49` write
  `LibraryEvent` rows directly, on purpose. They bypass validation and should
  keep doing so; do not "fix" them into `append` calls.

---

## Task 4: `aggregate_type` stops being a column

**Files:**
- Modify: `games/models.py:1391-1392` (constraint), `:1413` (field),
  `games/events/append.py:127`, `games/events/envelope.py:42,78`,
  `games/events/vocabulary.py` (`NewEvent` loses the field)
- Create: `games/migrations/00XX_drop_library_event_aggregate_type.py` (generated)
- Modify: `tests/test_event_models.py:19,49,166`, and every test passing
  `aggregate_type=`

**Steps:**

- [ ] Remove the field and the `library_event_aggregate_type_not_empty`
      constraint from `LibraryEvent`.
- [ ] `make makemigrations` (it passes `--noinput`), then read the generated
      migration: it must contain exactly one `RemoveConstraint` and one
      `RemoveField`.
- [ ] `make migrate`.
- [ ] Drop `aggregate_type` from `NewEvent`, from the row construction in
      `append`, and from `RecordedEvent` including its `from_row` copy.
- [ ] `tests/test_event_models.py:19` lists the constraint names and `:166`
      parametrizes over the non-empty-string columns — both lose the
      `aggregate_type` entry.

**Tests:**

- [ ] the spec answers for the aggregate type: `spec_for(event_type).aggregate_type`
      returns it, and `RecordedEvent` has no such attribute
- [ ] `RecordedEvent.from_row` still refuses a deferred row and still copies every
      remaining concrete field with a distinct value (the existing envelope
      contract test, one field shorter)

**Gotchas:**

- **`tests/test_event_envelope.py:34` sets `payload_schema_version=3` on purpose**
  — the module's stated rule is that every field holds a distinct value, so a
  `from_row` that read the wrong field cannot pass. After Task 3 the version is
  stamped, and a stamped `1` collides with `sequence == 1`. Registering the spec
  at version 3 is not available: Task 1 refuses any version above 1. **Append two
  events and assert on the second**, so `sequence` is 2 against a version of 1.
  Keep the module's comment explaining why the values must differ, and update it
  to say where the distinctness now comes from.
- `tests/test_event_schema_migration.py` walks the historical migration graph
  around `0023_library_event_schema`. It constructs a row with
  `aggregate_type="probe"` at `:124` against the **old** model state, which is
  correct and must stay. Only the current-state usages change.
- Re-run `make check-migrations` — the drift guard is part of `make check` and
  will fail if the migration was not generated.

---

## Task 5: A payload is the same value on both paths

**Files:**
- Modify: `games/events/envelope.py`
- Modify: `tests/test_event_envelope.py`, `tests/test_event_replay.py`

**Steps:**

- [ ] In `RecordedEvent.from_row`, rebuild the payload with its keys sorted
      recursively, by one fixed rule, before storing it on the value. Sort nested
      dicts inside lists too.
- [ ] Extend the docstring: the payload is a canonical value, so the append path
      and the replay path hand a projector the identical object, and the row's
      stored key order is deliberately not what a projector sees.

**Tests:**

- [ ] appending a payload whose keys are in a deliberately awkward order, then
      replaying it, produces payloads equal **key order included** — compare
      `list(payload)`, not the dicts, since dict equality ignores order and is
      exactly why this defect survived
- [ ] the same for a nested dict, and for a dict inside a list
- [ ] the existing replay parity test still passes unchanged

**Gotchas:**

- **`{"ratio": 1} == {"ratio": 1.0}` is `True` and dict comparison ignores key
  order.** Any assertion written with `==` will pass whether or not this task
  works. Compare key sequences explicitly.
- Sort keys, do not sort values. Lists are ordered data.
- This is the one part of the plan that fixes a defect in already-shipped code.
  If it grows beyond a helper and a docstring, stop and re-read the spec section
  "Key order is part of the value".

---

## Task 6: A projector claims specs, not strings

**Files:**
- Modify: `games/events/projection.py:25,80-90,110-125`
- Modify: `tests/test_event_projectors.py`, and every module declaring a family

**Steps:**

- [ ] Delete `type EventType = str`. `HandlerMap` becomes
      `Mapping[EventSpec[Any], Callable[..., None]]`.
- [ ] `_rebuild_handlers` keys `self._handlers` on `spec.event_type`, so
      `handlers_for` and `apply` keep taking the string a `RecordedEvent`
      carries. Only the *declaration* changes type.
- [ ] `register()`'s existing check that every `handles` value is callable stays;
      add one that every key is an `EventSpec`.

**Tests:**

- [ ] a family declaring `handles` keyed on a spec is dispatched for that spec's
      event type
- [ ] a family whose `handles` key is a bare string refuses at registration
- [ ] the existing family-ordering and unhandled-type tests pass unchanged

**Gotchas:**

- `RecordedEvent.event_type` stays `str`. Do not "finish the job" by converting it
  to a richer type — the spec's rejected-alternative section explains why that
  cascade is the reason specs won over an enum.
- A family may claim a spec that no registry registered. That is fine and out of
  scope; the append path refuses the event, which is the gate that matters.

---

## Task 7: Replay refuses what it cannot read

**Files:**
- Modify: `games/events/replay.py`
- Modify: `tests/test_event_replay.py`

**Interfaces produced:**

```python
class PayloadVersionUnsupported(Exception): ...
```

**Steps:**

- [ ] Per row, after `RecordedEvent.from_row` and the contiguity check, before
      `apply`: the event type must be in `wiring.event_types`, and its
      `payload_schema_version` must equal the registered spec's `version`.
- [ ] An unregistered type raises `UnregisteredEventType`; a version mismatch
      raises `PayloadVersionUnsupported`, naming the stored version, the
      registered one, and the sequence.

**Tests:**

- [ ] a stream containing a row whose type the wired registry does not hold
      raises, and the projector saw only the events before it
- [ ] a row written directly with `payload_schema_version=2` raises
      `PayloadVersionUnsupported`, and the message names both versions
- [ ] the pinned query floor is unchanged — the registry lookup is a dict hit and
      must add no query

**Gotchas:**

- **This guard can only be reached by a row written outside `append`**, since
  `append` stamps the registered version and Task 1 refuses to register anything
  but version 1. Build those rows directly, the way `tests/test_event_models.py:49`
  already does.
- `PayloadVersionUnsupported` inherits `Exception`, matching `StreamNotContiguous`
  and for the same reason: a stream nobody can read is not a database conflict and
  must not look like one to the retry classifier.
- Check before `apply`, not after. A projector must never see a payload the
  registry cannot vouch for.

---

## Task 8: Close the loop

**Files:**
- Modify: `pyproject.toml`, `uv.lock`
- Modify: `docs/superpowers/specs/2026-08-24-issue-900-event-type-registry-design.md`

**Steps:**

- [ ] Add `pydantic>=2.13.4,<3` to `[project].dependencies` — it is currently
      installed only as a transitive dependency of django-ninja, and this code
      imports it directly. Run `uv sync`; the lock is expected to change little
      or not at all.
- [ ] File the four follow-up issues from the spec's final section, and replace
      the "follow-up, filed by this issue" cells in the ownership table with
      their numbers.
- [ ] Comment on #671 (its event types must be registered specs, its payloads
      `TypedDict`s configured with `@with_config`) and on #796 (restore cannot
      write a historical payload version through `append`; it upcasts on the way
      in or reopens the question).
- [ ] Run the **full** `make check`, including `e2e/`. Not `check-fast`.
- [ ] Verify the migration reverses: `make migrate ARGS="games 00XX"` back and
      forward on an empty database.

**Gotchas:**

- The repo's `uv` config pins an `exclude-newer` window on purpose. If `uv sync`
  wants to move unrelated packages, stop — that is a machine configuration
  problem, not a dependency decision this task gets to make.
- `make check` runs `mypy .` over `tests/` too. Every test-local spec and schema
  is type-checked, which is the point.

---

## Self-review notes

- **Spec coverage.** Every spec section maps to a task: vocabulary and refusals →
  1; plumbing → 2; validation, stamping, stored-value → 3; the dropped column →
  4; key order → 5; `handles` → 6; replay guards → 7; dependency and follow-ups →
  8. The two foreclosures with no task (unbounded payload integers, writer-side-only
  enforcement) are stated limits, not work.
- **`aggregate_type` is declared but never stored.** Task 4 removes the column;
  no task restamps it. That contradiction existed in the spec's first draft and
  is fixed there too.
- **`wiring` is the parameter name in all four signatures**, `event_types` and
  `projectors` the field names. No other spelling appears in this plan.
- **Tasks 3 and 4 both touch every appending test module.** They are separate
  because a reviewer can reject the validation semantics while accepting the
  column removal, and because Task 4 carries a migration.
