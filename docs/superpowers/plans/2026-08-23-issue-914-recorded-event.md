# The value a projector reads — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `LibraryEvent` a projector is handed with a frozen
`RecordedEvent` carrying the envelope by value, so relation traversal, mutation,
and re-saving an immutable event become impossible rather than discouraged.

**Architecture:** One new module, `games/events/envelope.py`, holding
`RecordedEvent` and its `from_row`. `games/events/projection.py` swaps its
`LibraryEvent` references for it and stops importing the ORM entirely.
`games/events/append.py` converts each row before running the handlers. No migration, no
schema change, no data change.

**Spec:** `docs/superpowers/specs/2026-08-23-issue-914-recorded-event-design.md`
— read it before Task 1. It carries the *why* for every decision below; this plan
carries the *what* and the order.

**Tech Stack:** Python 3.14, Django 6, PostgreSQL 18, pytest + pytest-django.

## Global Constraints

- **Python 3.14 only.** PEP 758's bare `except A, B:` applies **without** a
  binding; a clause needing the error is `except (A, B) as error:`.
- **Drive everything through `make`.** Focused runs:
  `make test ARGS="tests/test_event_envelope.py -k contract -x"`.
- **`PYTEST_WORKERS=0` when debugging a failure.**
- **Iterate on `make check-fast`; gate on the full `make check`.**
- **Complete words in identifiers.**
- **Comments explain obscure intent only.** No issue references in code comments.
- **This must land before #671.** The projector input has zero consumers today.

---

## File structure

**Create `games/events/envelope.py`** — `RecordedEvent` and `from_row`. Named for
the charter's "Event envelope" section. Its own module because `append`
constructs it, `projection` consumes it, and #666's replay will construct it from
a read; it cannot live in `append.py`, which already imports `projection`.

**Modify `games/events/projection.py`** — three references to `LibraryEvent`
(the import, the `BoundHandler` alias, `apply`'s parameter). After this the
module has no ORM import at all.

**Modify `games/events/append.py`** — convert each row before running the handlers.

**Create `tests/test_event_envelope.py`** — the value and the contract test.

**Modify `tests/test_event_projectors.py`** — handlers take `RecordedEvent`.

**Nothing else is touched.** `AppendResult.events` keeps carrying ORM rows.

---

## Task 1: `RecordedEvent` and its contract

**Files:**
- Create: `games/events/envelope.py`
- Create: `tests/test_event_envelope.py`

**Steps:**

- [ ] Write the frozen, slotted dataclass with all sixteen fields, in
      `LibraryEvent._meta.concrete_fields` order, using `attname` names so the
      three foreign keys are `library_id`, `stream_id`, `actor_id`.
- [ ] Write `from_row` as sixteen explicit assignments, so mypy checks each one.
- [ ] `from_row` raises when `row.get_deferred_fields()` is non-empty, naming the
      deferred fields.

**Tests:**

- [ ] **the contract test**: for every field in `_meta.concrete_fields`, a
      converted row's attribute equals the row's. Build the row with distinct
      values per field so a miswiring cannot pass by coincidence
- [ ] assignment to a converted value raises `FrozenInstanceError`
- [ ] the value exposes no `actor`, `library`, `stream`, `objects`, `save`, or
      `_meta`
- [ ] converting a row **read back from the database** issues zero queries
- [ ] converting a `.only("id", "sequence")` row raises, and the message names
      the deferred fields
- [ ] a value built from an appended row equals one built from the same row
      re-read from PostgreSQL — the parity property as one assertion

**Gotchas:**

- The contract test must assert **values**, not field names. A name-only test
  passes `actor_id=row.library_id`.
- Distinct per-field values matter: two UUID fields both set to the same UUID
  would let a swap pass. Use a different UUID per field.
- `actor_id` is `int | None`; `effective_time` and `causation_id` are the other
  nullable fields. Everything else is non-null at the database.
- The zero-query test needs a row fetched fresh (`LibraryEvent.objects.get(...)`),
  not the one `append` returned — the appended instance has its relations cached
  and would pass for the wrong reason.
- Do not give the dataclass field defaults. A partially-populated envelope is
  never wanted, and defaults would let the contract test pass with a field the
  `from_row` forgot.

---

## Task 2: Swap the projector contract

**Files:**
- Modify: `games/events/projection.py`, `games/events/append.py`
- Modify: `tests/test_event_projectors.py`

**Steps:**

- [ ] `BoundHandler` becomes `Callable[[RecordedEvent], None]`; `apply` takes a
      `RecordedEvent`; delete the `games.models` import.
- [ ] `append` runs `registry.apply(RecordedEvent.from_row(row))` per row, in
      the same place and order as before.
- [ ] Update the test module's handlers to take `RecordedEvent`, and add a
      `make_recorded_event(**overrides)` helper with sensible defaults so a test
      does not spell sixteen fields. The helper belongs in the test module; the
      production dataclass keeps no defaults.
- [ ] The no-database tests construct the helper's value directly instead of an
      unsaved `LibraryEvent`, so they stop importing `games.models`.
- [ ] Rename "a handler receives the persisted row" to "a handler receives the
      recorded event", asserting the same envelope fields.

**Tests:** the existing nineteen keep passing, with two additions:

- [ ] a handler cannot reach `event.actor` — `AttributeError`, not a query
- [ ] the whole append path still issues no extra query per projected event

**Gotchas:**

- `projection.py` losing its ORM import is the point, not a side effect. If
  anything still needs `LibraryEvent` there, the conversion is in the wrong place.
- The handlers' position is unchanged: after the head advance, event-major. Only
  what is passed changes.
- `AppendResult.events` still carries rows. Tests asserting on `result.events`
  keep working and should not be converted.

---

## Task 3: Close the loop

**Files:** none beyond docs and the issue tracker.

**Steps:**

- [ ] Run the full `make check` and confirm green.
- [ ] Correct #914's body: it claims the replay read "can use `.only()` and
      `.iterator()`". `.only()` is now refused — `from_row` needs every field, so
      selecting fewer columns makes conversion cost a query per deferred field.
      `.iterator()` is unaffected.
- [ ] Comment on #914 linking the spec and plan, and restate the ordering
      constraint against #671.

---

## Self-review notes

- **The measurements are the argument.** The relation asymmetry, the deferred-row
  cost, and the four-way payload comparison are all in the spec because each one
  overturned a plausible design. Without them `from_row`'s deferred check and the
  plain-dict payload both read as arbitrary.
- **`payload` staying a plain dict is the one guarantee resting on discipline.**
  Every mechanism that would freeze it breaks either `== {...}` or
  `json.dumps`, and a projection writing a JSONField needs the latter.
- **Nothing here is reversible-by-halves.** Either handlers take the value or
  they take the row; a period where both work would be worse than either.
