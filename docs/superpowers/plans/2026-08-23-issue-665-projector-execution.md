# Synchronous projector registration and execution — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold every appended event through an ordered set of projector families,
inside the append's own transaction, under the stream-head lock — with a registry
that does not depend on import order and a payload rule that makes an append-time
event equal to the one a replay reads.

**Architecture:** One new module, `games/events/projection.py`, holding
`ProjectorFamily`, `ProjectorRegistry`, `DEFAULT_REGISTRY`, and `Projector`.
`LockedStream.append` gains a canonical-JSON guard and one call into the
registry; `idempotent_append` and `dispatch` gain a defaulted `registry`
parameter they only pass down. An empty `games/projectors/` package is created
and imported by `GamesConfig.ready()` so #671's families have a working seam. No
migration, no schema change, no data change.

**Spec:** `docs/superpowers/specs/2026-08-23-issue-665-projector-execution-design.md`
— read it before Task 1. It carries the *why* for every decision below; this plan
carries the *what* and the order.

**Tech Stack:** Python 3.14, Django 6, PostgreSQL 18, pytest + pytest-django.

## Global Constraints

- **Python 3.14 only.** Uses PEP 758 bare `except A, B:` and PEP 695 generics
  (`def canonical_json[T]`). A `SyntaxError` in an `except` clause means the wrong
  interpreter, not broken code.
- **Drive everything through `make`.** Never `direnv exec .`, never raw `uv run` /
  `pytest`. Focused runs: `make test ARGS="tests/test_event_projectors.py -k <name> -x"`.
- **`PYTEST_WORKERS=0` when debugging a failure** — parallel output interleaves and
  `-x` stops only the worker that hit it.
- **Iterate on `make check-fast`; gate on the full `make check`** (includes `e2e/`)
  before declaring done.
- **Complete words in identifiers** — `event` not `e`, `handler` not `h`.
- **Comments explain obscure intent only.** No issue or PR references in code
  comments; the spec carries history.
- **Never wrap an exception raised by a projector.** `run_in_transaction`
  classifies by `type(error)` and `error.__cause__.sqlstate`; both must survive.

---

## File structure

**Create `games/events/projection.py`** — the machinery. `EventType`,
`BoundHandler`, `DefinitionSite`, `ProjectorFamily`, `ProjectorRegistry`,
`DEFAULT_REGISTRY`, `Projector`.

Named `projection`, not `projectors`, because `games/projectors/` is the package
of real families. Two importable modules called `projectors` is a standing trap.

**Create `games/projectors/__init__.py`** — empty package with a docstring saying
what belongs in it. #671 adds the first family.

**Modify `games/events/append.py`** — `PayloadNotCanonical`, `canonical_json`, the
`registry` parameter, the guard, and the fold.

**Modify `games/events/idempotency.py` and `games/events/dispatch.py`** — one
defaulted parameter each, passed straight down. Nothing else.

**Modify `games/apps.py`** — `ready()` imports `games.projectors`.

**Create `tests/test_event_projectors.py`** — one test module. Its families are
declared at module level against a module-level `ProjectorRegistry` the module
owns, so they never touch `DEFAULT_REGISTRY` and nothing needs cleaning up.

**Modify `tests/test_event_append.py`** — the canonical-JSON tests belong beside
the other append tests, not in the projector module.

---

## Task 1: The canonical-JSON guard

Independent of everything else; land it first so the projector work builds on an
event whose payload already round-trips.

**Files:**
- Modify: `games/events/append.py`
- Modify: `tests/test_event_append.py`

**Steps:**

- [ ] Add `PayloadNotCanonical(ValueError)` to `append.py`.
- [ ] Add `canonical_json[T](value: T, *, label: str) -> T`: round-trip through
      `json.dumps(..., allow_nan=False)` / `json.loads`, raise
      `PayloadNotCanonical` when `json` raises **or** when the round-trip differs,
      and otherwise **return the round-trip, not the input**.
- [ ] In `LockedStream.append`, run it over `source_metadata or {}` once and over
      every event's `payload` before any row is built, and use the returned values
      when constructing `LibraryEvent` rows.

**Tests (`tests/test_event_append.py`):**

- [ ] a `tuple` in a payload raises `PayloadNotCanonical`
- [ ] an int-keyed dict raises
- [ ] a `Decimal` raises (today this is a bare `TypeError` from `json`)
- [ ] a `set` raises
- [ ] `float("nan")` raises
- [ ] non-canonical `source_metadata` raises on the same terms
- [ ] a rejected append writes nothing — no event row, no head advance
- [ ] the stored `payload` equals the value read back from PostgreSQL
- [ ] the stored `payload` **is not** the caller's dict by identity

**Gotchas:**

- The guard must run before `bulk_create` *and* before the head advance, or a
  rejected append leaves a moved head inside a transaction that may still commit.
- `label` exists so the message names which of the two values was wrong; a
  message saying only "payload" when `source_metadata` was at fault is worse than
  no message.
- PEP 758's bare `except A, B:` applies only **without** a binding. This clause
  needs the error, so it is `except (TypeError, ValueError) as error:` —
  parenthesized, and a `SyntaxError` here is the code's fault rather than the
  interpreter's.
- `json.dumps(float("nan"))` succeeds by default and yields `NaN`, which
  `json.loads` accepts. `allow_nan=False` is what makes it an error rather than a
  value that compares unequal to itself by accident.

---

## Task 2: The registry and the base class

No database. Everything here is definition-time behaviour.

**Files:**
- Create: `games/events/projection.py`
- Create: `tests/test_event_projectors.py`

**Steps:**

- [ ] Declare the type aliases (`EventType`, `BoundHandler`, `DefinitionSite`)
      with the trailing example-value comments the codebase uses.
- [ ] Declare `ProjectorFamily(StrEnum)` with `CURRENT_STATE`, `JOURNAL`, `STATS`
      in that order, and a docstring saying member order *is* run order.
- [ ] Write `ProjectorRegistry`: holds the family instances, the
      `DefinitionSite` per claimed member for the collision guard, and a
      precomputed `dict[EventType, tuple[BoundHandler, ...]]` rebuilt on every
      `register`. `handlers_for` is a plain `.get(event_type, ())`.
- [ ] `register(projector_class)` validates `family_name` and `handles`,
      rejects a second definition site claiming a member, instantiates the class
      once with no arguments, binds each handler with `__get__`, and rebuilds the
      lookup in `ProjectorFamily` definition order.
- [ ] `DEFAULT_REGISTRY = ProjectorRegistry()` before `Projector`, because
      `__init_subclass__` names it as a default.
- [ ] `Projector(ABC)` with `family_name` / `handles` ClassVars and
      `__init_subclass__(cls, *, abstract=False, registry=DEFAULT_REGISTRY, **kwargs)`.
- [ ] `ProjectorRegistry.apply(event)` iterates `handlers_for(event.event_type)`.
      Its error contract is Task 4; leave it a bare loop for now.

**Tests:**

- [ ] concrete family missing `family_name` raises at class definition
- [ ] concrete family missing `handles` raises at class definition
- [ ] `abstract=True` with neither is accepted
- [ ] two classes claiming one member in one registry raise at definition
- [ ] re-registering the same class is not a collision
- [ ] a non-callable `handles` value raises at definition
- [ ] a family registered into a test registry is absent from `DEFAULT_REGISTRY`
- [ ] families run in `ProjectorFamily` order even when registered backwards
- [ ] several families handling one type all run, in that order
- [ ] an unhandled event type resolves to `()` and runs nothing

**Gotchas:**

- `inspect.isabstract` cannot substitute for `abstract=True`. `Projector` has no
  abstract method — handlers live in a mapping — so every subclass looks
  concrete.
- `handles` values are **plain functions**, read out of the class body before
  descriptor binding. Annotate `Callable[..., None]`; `Callable[[Self, LibraryEvent], None]`
  will not typecheck against an unbound function.
- A family declares `handles: ClassVar[HandlerMap] = {...}`. Without the
  annotation ruff raises RUF012 on the dict literal at **every** family, so the
  alias exists to keep that one line short rather than to be clever.
- Ordering is `ProjectorFamily` **member index**, not `sorted()` on the string
  values — `current_state` < `journal` < `stats` is a coincidence that would
  silently become the real rule.
- The order-independence test must register backwards or it proves nothing.
- Instantiation happens at registration, therefore at import. A family's
  `__init__` must take no arguments and do no work; say so in the base class
  docstring.

---

## Task 3: Wire it into the append path

**Files:**
- Modify: `games/events/append.py`, `games/events/idempotency.py`,
  `games/events/dispatch.py`, `games/apps.py`
- Create: `games/projectors/__init__.py`
- Modify: `tests/test_event_projectors.py`

**Steps:**

- [ ] `LockedStream.append` gains `registry: ProjectorRegistry = DEFAULT_REGISTRY`
      and, after `head.save(...)`, folds the rows: `for event in rows:
      registry.apply(event)` — event-major, in the order the rows were built.
- [ ] `idempotent_append` and `dispatch` gain the same defaulted parameter and
      pass it down. They do nothing else with it.
- [ ] Create `games/projectors/__init__.py` and import it from
      `GamesConfig.ready()` beside the existing `import games.signals`.

**Tests:**

- [ ] two events × two families produce the event-major call sequence
      `(e1, first), (e1, second), (e2, first), (e2, second)`
- [ ] a handler receives the persisted row with `pk`, `sequence`, `library_id`
      and `correlation_id` set
- [ ] the head has already advanced when the handler runs
- [ ] a handler's own write is rolled back when a later failure kills the attempt
- [ ] a replayed dispatch (same idempotency key) runs no handler
- [ ] a `dispatch(..., registry=test_registry)` drives the whole composed path

**Gotchas:**

- Every test reaching `dispatch` or `run_in_transaction` needs
  `django_db(transaction=True)`; the ordinary `django_db` fixture wraps the test
  in a transaction and `run_in_transaction` refuses to nest. `tests/test_event_retry.py`
  already does this throughout.
- Fold **after** the head advance, so a handler reading the head sees the
  post-append value. The test above pins this.
- The fold happens before `AppendResult` is constructed but operates on the same
  row objects the result will carry.
- `import games.projectors` in `ready()` is a no-op today. It is there so the
  seam is exercised, not because it does anything yet.

---

## Task 4: The error contract

**Files:**
- Modify: `games/events/projection.py`
- Modify: `tests/test_event_projectors.py`

**Steps:**

- [ ] Wrap each handler call in `ProjectorRegistry.apply` with
      `except Exception as error: error.add_note(...); raise` — the note naming
      the family, the event type, and the sequence.
- [ ] Nothing is caught, converted, logged, or suppressed.

**Tests:**

- [ ] a handler raising `KeyError` propagates as `KeyError`, and
      `error.__notes__` names the family, the event type, and the sequence
- [ ] **a handler raising `OperationalError` chained from SQLSTATE `40P01` is
      still retried by `run_in_transaction`, and the retry succeeds.** Build the
      exception with the `wrapped` helper from `tests/test_event_retry.py`; make
      the handler fail only on its first attempt.
- [ ] a handler raising leaves no event, no head advance, and no projection row

**Gotchas:**

- The retry test is the load-bearing one: it is what fails if anyone later
  "improves" this into a `ProjectionFailed` wrapper. Give it a docstring saying
  so.
- Attempt-counting state for the flaky handler lives outside the database, which
  knowingly violates `run_in_transaction`'s documented "no effects outside the
  database" contract. `tests/test_command_dispatch.py` already accepts this
  trade for `FlakyCommand`; follow it rather than inventing a second approach.
- `add_note` mutates the exception in place. Do not rebuild it.

---

## Task 5: Close the loop

**Files:** none beyond docs and the issue tracker.

**Steps:**

- [ ] Run the full `make check` and confirm green — lint, format-check, mypy,
      ts-check, vitest, and the whole pytest suite including `e2e/`.
- [ ] File the two follow-up issues named in the spec and add them to #601 under
      the dispatch/projector follow-ups list:
      - `ProjectorPhase` — an ordered phase enum giving families a per-append
        aggregate hook, plus a decision about what a batch means during replay.
      - Relation prefetching on the replay read, so a family touching
        `event.actor` is not an N+1 across a rebuild. Fold into #667 if #667's
        own planning already owns it.
- [ ] Comment on #665 linking the spec and this plan.

---

## Self-review notes

- **The spec's own probe is a standing test.** The `payload_is_callers_dict` and
  `payload_equal` findings became Task 1 assertions on purpose; without them the
  reason for `canonical_json` is invisible and someone deletes it as ceremony.
- **`ProjectorFamily` members are cheap to change.** Nothing persists a family
  name — it is an ordering key, not an audit vocabulary — so #671 may rename or
  reorder freely. This is the opposite of `CommandName`, whose members are hashed
  into stored idempotency fingerprints.
- **No placeholder members.** Test families claim real member names inside a
  registry the test module owns. There is deliberately no `TEST_FAMILY_*` and
  therefore no cleanup issue of the #907 kind.
- **The three defaulted `registry` parameters are the price of that.** They exist
  so an integration test can drive `dispatch` against its own families without
  touching global state; `policy` set the precedent in #664.
