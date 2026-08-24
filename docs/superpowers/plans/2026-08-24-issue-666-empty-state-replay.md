# Deterministic empty-state replay — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold an existing library stream through a projector registry the same
way `append` folds the events it just wrote, so a projection can be rebuilt from
the event store and proven identical to what the write path produced.

**Architecture:** One new module, `games/events/replay.py`, holding
`REPLAY_CHUNK_SIZE`, `StreamNotContiguous`, `ReplayResult`, and `replay()`. It
reads the library's stream head, bounds the read at `current_sequence`, streams
the rows in sequence order with `.iterator()`, converts each with
`RecordedEvent.from_row`, checks contiguity, and calls `registry.apply`. Nothing
existing changes: `replay` imports `envelope`, `projection`, and `models`, and
nothing imports `replay`.

**Spec:** `docs/superpowers/specs/2026-08-24-issue-666-empty-state-replay-design.md`
— read it before Task 1. It carries the *why* for every decision below, including
the four measurements that decided them; this plan carries the *what* and the
order.

**Tech Stack:** Python 3.14, Django 6, PostgreSQL 18, pytest + pytest-django.

## Global Constraints

- **Python 3.14 only.** PEP 758's bare `except A, B:` applies **without** a
  binding; a clause needing the error is `except (A, B) as error:`.
- **Drive everything through `make`.** Focused runs:
  `make test ARGS="tests/test_event_replay.py -k parity -x"`.
- **`PYTEST_WORKERS=0` when debugging a failure**; parallel output interleaves.
- **Iterate on `make check-fast`; gate on the full `make check`.**
- **Complete words in identifiers** — `event`, `sequence`, `previous`, never `e`
  or `seq`.
- **Comments explain obscure intent only.** No issue references in code comments.
- **No migration, no schema change, no data change.** If the work grows one,
  something has gone wrong.

---

## File structure

**Create `games/events/replay.py`** — the whole deliverable. It is the read
counterpart of `append.py` and the only other place the fold loop is written.

**Create `tests/test_event_replay.py`** — families declared at module level
against a registry the module owns, exactly as `tests/test_event_projectors.py`
does. Nothing here may reach `DEFAULT_REGISTRY`.

**Nothing else is touched.** No existing module imports `replay`; `append`,
`dispatch`, `idempotency`, and `projection` are unchanged.

---

## Task 1: The module and its stream contract

**Files:**
- Create: `games/events/replay.py`
- Create: `tests/test_event_replay.py`

**Interfaces produced:**

```python
REPLAY_CHUNK_SIZE = 500


class StreamNotContiguous(Exception): ...


@dataclass(frozen=True, slots=True)
class ReplayResult:
    stream_id: uuid.UUID | None
    folded_through: int
    event_count: int


def replay(
    library: UserLibrary, *, registry: ProjectorRegistry = DEFAULT_REGISTRY
) -> ReplayResult: ...
```

**Steps:**

- [ ] Write the module docstring: what a replay is, and that the bound *is* the
      snapshot because events are immutable and append-only.
- [ ] `replay` reads the head with
      `LibraryEventStreamHead.objects.filter(library=library).first()`. `None`
      returns `ReplayResult(stream_id=None, folded_through=0, event_count=0)`
      **without creating a head row**.
- [ ] Bound the read at the head's `current_sequence`, read
      `LibraryEvent.objects.filter(stream_id=head.id, sequence__lte=bound)
      .order_by("sequence").iterator(chunk_size=REPLAY_CHUNK_SIZE)`.
- [ ] Per row: `RecordedEvent.from_row(row)`, then the contiguity check, then
      `registry.apply(event)` — in that order, so a damaged stream is refused
      before it is projected.
- [ ] Contiguity: track `previous`, starting at 0; `event.sequence` must equal
      `previous + 1`. Raise `StreamNotContiguous` naming the sequence expected
      and the one found.
- [ ] After the loop: `previous` must equal the bound, or raise
      `StreamNotContiguous` naming the sequence the head promised and the one the
      fold reached.
- [ ] Return `ReplayResult(head.id, bound, event_count)`.

**Tests (write each before the code it covers):**

- [ ] a single-append stream folds every event, in sequence order, into the
      module's recorder
- [ ] the result carries the stream id, `folded_through` equal to the head's
      `current_sequence`, and the event count
- [ ] a head at sequence zero folds nothing and returns that stream id with zeros
- [ ] a library with no head returns `(None, 0, 0)` **and**
      `LibraryEventStreamHead.objects.filter(library=library).exists()` is still
      false afterwards
- [ ] deleting a middle event raises `StreamNotContiguous`, the message names the
      missing sequence, and the recorder holds exactly the events before the gap
- [ ] deleting the last event raises, and the message names the sequence the head
      promised
- [ ] an event type no family handles is folded and applied to nothing
- [ ] a handler raising `KeyError` propagates as `KeyError`, with
      `error.__notes__` naming the family, the event type, and the sequence

**Gotchas:**

- **Build streams with `lock_stream(...).append([...])` inside
  `transaction.atomic()`**, not by hand-rolling `LibraryEvent(...)` rows. The
  head must advance or every tail check in this file is testing the fixture.
  `dispatch` works too and is what the parity test in Task 2 uses.
- Any test touching `lock_stream` needs `@pytest.mark.django_db(transaction=True)`
  — `select_for_update` requires a real transaction, as every existing event test
  already does.
- `ReplayResult.stream_id` is `uuid.UUID | None`. Do not "simplify" it by raising
  for a library that never appended: an empty stream is a legitimate replay, and
  raising would make every caller special-case the case that needs no special
  casing.
- Contiguity starts at 1, not at the first row's sequence. A stream whose first
  event is #2 is exactly as damaged as one with a hole in the middle, and reading
  the start from the data would make it undetectable.
- `StreamNotContiguous` inherits `Exception`. Deriving it from `IntegrityError`
  or `OperationalError` would make `run_in_transaction` retry a damaged stream.
- Do not wrap `registry.apply` in a `try`. It already annotates and re-raises;
  a second note or a wrapper breaks the retry classifier the same way.
- No `.only()`, `.defer()`, `.values()`, or `select_related` on the read. The
  first two are refused by `from_row`, the third bypasses it, and the fourth
  joins for relations the value does not carry.

---

## Task 2: Parity, determinism, and the query floor

**Files:**
- Modify: `tests/test_event_replay.py`

**Interfaces consumed:** `replay`, `ReplayResult` from Task 1;
`dispatch`/`BasicCommand` from `tests/test_command_dispatch.py`;
`Projector`/`ProjectorFamily`/`HandlerMap`/`ProjectorRegistry` from
`games.events.projection`.

**Steps:**

- [ ] Add a module-level recorder family that appends the whole `RecordedEvent`
      to a list sink (the `SEEN` pattern from `tests/test_event_projectors.py`),
      with an autouse fixture clearing every sink before and after each test.
- [ ] Add a second family on another `ProjectorFamily` member handling the same
      event type, so ordering is observable.

**Tests:**

- [ ] **fold parity**: append several events (one `append` call with three
      `NewEvent`s, plus a second append, so the stream spans two actions), keep
      the list the append fold recorded, clear the sink, `replay(library)`, and
      assert the replayed list **equals** the appended list — full
      `RecordedEvent` values, in order. This is the issue's acceptance criterion.
- [ ] **determinism**: clear the sink, replay again, assert the second recording
      equals the first
- [ ] **event-major across families**: with both families registered, the
      recorded `(family, sequence)` pairs are
      `(first, 1), (second, 1), (first, 2), (second, 2)`
- [ ] **the query floor**: `django_assert_num_queries(2)` around a replay of a
      10-event stream, and again around a 60-event stream — the head read and the
      cursor, whatever N is
- [ ] **the bound**: replay, then append two more events, and assert the first
      result's `folded_through` is the old head; a second replay covers the new
      events and reports the new head
- [ ] **isolation**: two libraries with streams of different lengths; replaying
      one folds only its own events (assert on the `library_id` of everything the
      recorder saw)

**Gotchas:**

- The parity comparison must be on `RecordedEvent` values, not on
  `(event_type, sequence)` tuples. `RecordedEvent` is a frozen dataclass, so `==`
  compares all sixteen fields — which is the whole assertion. A tuple projection
  would pass while `payload` or `recorded_at` differed.
- Clear the sink between the append and the replay, or the "equal" assertion
  compares a list to itself doubled.
- Two libraries need two users: `owned_library` plus a second created with
  `django_user_model.objects.create_user(...).library`, the way
  `tests/test_event_projectors.py`'s `second_library` fixture does.
- `django_assert_num_queries` counts the `.iterator()` read as one query — the
  probe measured this. If it comes out higher, something added a per-event query
  and the test is doing its job.
- Do not assert wall-clock time anywhere. The measurements belong in the spec;
  a timing assertion in the suite is a flake generator.

---

## Task 3: Close the loop

**Files:** none beyond the tracker.

**Steps:**

- [ ] Run the full `make check` and confirm green — lint, format-check, mypy,
      ts-check, vitest, and the entire pytest suite including `e2e/`.
- [ ] Comment on #666 linking the spec and this plan, and stating what replay
      deliberately does not do: it empties nothing, locks nothing, and promises
      no quiescence — #667 owns the shadow tables and the swap, #901 owns the
      concurrency check.

---

## Self-review notes

- **The fold loop is the deliverable, not the read.** Everything else in the
  module exists to make `registry.apply(RecordedEvent.from_row(row))` happen once
  per event in sequence order. A reviewer should be able to see that the loop is
  the append's loop with a different source of rows.
- **The bound is doing more work than it looks like.** It is what lets replay run
  without a lock, without a transaction, and without blocking writers — and what
  gives #667 and #901 something to compare against later. Removing it "because
  the head already limits the stream" quietly removes all three.
- **The contiguity check guards the one failure with no other symptom.** Every
  other way a rebuild can go wrong announces itself. A stream with a hole
  produces projections that look ordinary and are wrong.
- **Nothing here is reversible-by-halves**, but nothing here needs to be: no
  existing behaviour changes, so the revert is deleting a module and its tests.
