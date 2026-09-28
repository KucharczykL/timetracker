# Move back: a broken stream is a defect — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `run_before` and `_put_back_the_run` in `games/bulk_move.py` raise `RowUnreadable` for a broken session stream instead of refusing with `NO_EARLIER_RUN` (#1283).

**Architecture:** `run_before` matches `_earlier` in `games/bulk_session_edit.py`: no run before the batch's `moved` event, or a payload run that is not a key, is `RowUnreadable`. `_put_back_the_run` takes the session key and raises `RowUnreadable` for a run the library does not hold. The forward path's `run_before` call moves inside `answered("session")`, so a broken stream there is `CommandFailed` at `DEFECT_STATUS`.

**Tech Stack:** Django, pytest (`make test`), mypy (`make check`).

**Spec:** `docs/superpowers/specs/2026-09-28-issue-1283-move-back-unreadable-row-design.md`

## Global Constraints

- Run tests through `make`, never raw `pytest`/`uv run`: `make test ARGS="tests/test_bulk_edit_moves.py -x"`.
- Wrap every pytest target in the shared lock: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make …`.
- Gate is full `make check` (includes `e2e/`), never a subset.
- A `RowUnreadable` message names the row and its library; it has no `sentence`.
- `NOT_MOVED_BY_THIS_BATCH` stays a `CommandRejected`.
- Comments ≤7 words; match surrounding `#:` style.

---

### Task 1: `run_before` answers a broken stream as a defect

**Files:**
- Modify: `games/bulk_move.py` (imports; `_remove_the_emptied_bucket` ~l.136-140; `run_before` ~l.193-222)
- Test: `tests/test_bulk_edit_moves.py`

**Interfaces:**
- Produces: `run_before(library, session_id, batch_id) -> uuid.UUID` raises `RowUnreadable` for no earlier run or a bad payload; `CommandRejected(NOT_MOVED_BY_THIS_BATCH)` unchanged. Private `_run_of(event: LibraryEvent) -> uuid.UUID`.

- [ ] **Step 1: Write the failing tests**

Add to imports of `tests/test_bulk_edit_moves.py`:

```python
from games.bulk_session_edit import (
    NOTHING_STATED,
    SEVERAL_GAMES,
    EditStatement,
    edit_back,
    edit_one,
    offer_edit,
    settle_edit,
)
from games.events.dispatch import CommandRejected, RowUnreadable, dispatch
from games.writes.answers import DEFECT_STATUS, CommandFailed
```

Add after `test_a_key_that_is_not_this_batchs_is_refused`:

```python
def _moved_without_a_creation(owned_user, owned_library, game):
    """A hand-written row, then one move."""
    session = a_session(tracked_run(owned_library, game))
    batch = uuid.uuid7()
    move_session(
        owned_user,
        session,
        a_run(owned_library, game, name="Second run").pk,
        correlation_id=batch,
    )
    return session, batch


def test_a_move_with_no_run_before_it_is_a_defect(owned_user, owned_library, game):
    """A stream that states no creation: the row is wrong."""
    session, batch = _moved_without_a_creation(owned_user, owned_library, game)

    with pytest.raises(RowUnreadable):
        run_before(owned_library, session.pk, batch)


def test_the_undo_of_a_move_with_no_run_before_it_is_a_defect(
    owned_user, owned_library, game
):
    session, batch = _moved_without_a_creation(owned_user, owned_library, game)

    with pytest.raises(CommandFailed) as failed:
        edit_back(
            owned_user,
            session.pk,
            undoes=batch,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )

    assert failed.value.status_code == DEFECT_STATUS


def test_a_move_out_of_a_bucket_with_no_creation_is_a_defect(
    owned_user, owned_library, game
):
    """The move is written; the bucket is left."""
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_session(bucket)

    with pytest.raises(CommandFailed) as failed:
        edit_one(
            owned_user,
            session,
            choice=_to(target),
            idempotency_key="one-move",
            correlation_id=uuid.uuid7(),
        )

    assert failed.value.status_code == DEFECT_STATUS
    session.refresh_from_db()
    bucket.refresh_from_db()
    assert session.playthrough_id == target.pk
    assert bucket.removed_at is None
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_bulk_edit_moves.py -k 'no_run_before_it or no_creation' -x"`
Expected: FAIL — `run_before` raises `CommandRejected`, not `RowUnreadable`; the Undo answers 409; `edit_one` returns `moved`.

- [ ] **Step 3: Implement**

In `games/bulk_move.py`, imports:

```python
from games.events.dispatch import CommandRejected, RowUnreadable
from games.models import (
    LibraryEvent,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
    UserLibrary,
)
```

In `_remove_the_emptied_bucket`, replace the `try/except` around `run_before`:

```python
    with answered("session"):
        try:
            emptied = run_before(actor.library, session_id, correlation_id)
        except CommandRejected:
            #: This batch moved no such row.
            return
```

In `run_before`, replace the `if not earlier:` block and the `return`:

```python
    if not earlier:
        raise RowUnreadable(
            f"session {session_id} of library {library.pk} states "
            f"{moved.event_type} at sequence {moved.sequence} and no run "
            "before it"
        )
    return _run_of(earlier[-1])


def _run_of(event: LibraryEvent) -> uuid.UUID:
    """The run a created or moved payload states."""
    run = event.payload.get("playthrough")
    if not isinstance(run, str):
        raise RowUnreadable(f"event {event.pk} states playthrough {run!r}")
    try:
        return uuid.UUID(run)
    except ValueError as error:
        raise RowUnreadable(f"event {event.pk} states playthrough {run!r}") from error
```

Update the `_remove_the_emptied_bucket` docstring's last paragraph so it no longer says every answer is swallowed:

```
    A batch that moved no such row removes nothing. A
    broken stream is a defect and ends the batch.
```

- [ ] **Step 4: Fix the test that moved a hand-written row**

`test_a_row_moves` (~l.328) builds its row with `a_session(bucket)`, which has no stream. Replace:

```python
    session = a_session(bucket)
```

with:

```python
    session = a_bucket_session(owned_user, target, bucket)
```

`owned_user` is already a parameter; keep the existing assertions.

- [ ] **Step 5: Run the file**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_bulk_edit_moves.py tests/test_bulk_session_edit.py"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add games/bulk_move.py tests/test_bulk_edit_moves.py
git commit -m "fix: a move with no run before it is a defect (#1283)"
```

### Task 2: `_put_back_the_run` answers a run the library does not hold as a defect

**Files:**
- Modify: `games/bulk_move.py` (`NO_EARLIER_RUN` ~l.52-55; `_put_back_the_run` ~l.225-265; `move_back_row` ~l.282-283)
- Test: `tests/test_bulk_edit_moves.py`

**Interfaces:**
- Consumes: `run_before` from Task 1.
- Produces: `_put_back_the_run(actor, act, batch_id, session_id, run_id, idempotency_key, correlation_id) -> None`.

- [ ] **Step 1: Write the failing test**

Add after the Task 1 tests:

```python
def test_a_move_back_to_a_run_another_library_holds_is_a_defect(
    owned_user, owned_library, game, django_user_model
):
    """No command moves a run; the row drifted."""
    target = tracked_run(owned_library, game)
    earlier = a_run(owned_library, game, name="Second run")
    session = a_recorded_session(owned_user, earlier)
    batch = uuid.uuid7()
    edit_one(
        owned_user,
        session,
        choice=_to(target),
        idempotency_key="one-move",
        correlation_id=batch,
    )
    stranger = django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library
    Playthrough.objects.filter(pk=earlier.pk).update(library=stranger)

    with pytest.raises(CommandFailed) as failed:
        edit_back(
            owned_user,
            session.pk,
            undoes=batch,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )

    assert failed.value.status_code == DEFECT_STATUS
```

- [ ] **Step 2: Run it to verify it fails**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_bulk_edit_moves.py -k another_library_holds -x"`
Expected: FAIL — status code is 409 (`NO_EARLIER_RUN`).

- [ ] **Step 3: Implement**

Delete the `NO_EARLIER_RUN = (...)` constant.

Add `session_id` to `_put_back_the_run`, after `batch_id`:

```python
def _put_back_the_run(
    actor: User,
    act: ActName,
    batch_id: uuid.UUID,
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> None:
```

Replace its `if run is None:` block:

```python
        if run is None:
            raise RowUnreadable(
                f"session {session_id} of library {actor.library.pk} sat on "
                f"playthrough {run_id} before batch {batch_id}, which this "
                "library does not hold"
            )
```

In `move_back_row`:

```python
    _put_back_the_run(
        actor, act, undoes, session_id, earlier, idempotency_key, correlation_id
    )
```

- [ ] **Step 4: Run the file and confirm no stale reference**

Run: `git grep -n NO_EARLIER_RUN` — expected: no output.
Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_bulk_edit_moves.py tests/test_bulk_session_edit.py"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/bulk_move.py tests/test_bulk_edit_moves.py
git commit -m "fix: a move back to a run the library lacks is a defect (#1283)"
```

### Task 3: Docs sweep and the gate

**Files:**
- Modify: `docs/superpowers/specs/2026-09-19-selectable-tables-wave-design.md:376-377`
- Modify: `docs/superpowers/specs/2026-09-27-issue-1310-bulk-edit-moves-design.md:50-55`

- [ ] **Step 1: Wave spec** — replace

```
person cannot act on (`games/bulk_session_edit.py` does; move's `run_before`
still refuses, #1283); and a second press of Undo runs under a fresh
```

with

```
person cannot act on (`games/bulk_session_edit.py` and `run_before` in
`games/bulk_move.py`); and a second press of Undo runs under a fresh
```

- [ ] **Step 2: #1310 spec** — replace the paragraph under `## The inverse` with:

```
`edit_back` reads the facts that the batch changed: the move from
`moved_by`, the others from `values_before`. When it finds neither, it
refuses with `NOT_EDITED_BY_THIS_BATCH`. It restates the described facts
first. Then it restores the bucket that the batch removed and moves the row
back. A bucket removed after the batch refuses the row with
`SOURCE_TAKEN_AWAY`; a stream that cannot tell the earlier run is a defect
([#1283](2026-09-28-issue-1283-move-back-unreadable-row-design.md)).
```

- [ ] **Step 3: Gate**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`
Expected: lint, format, mypy, ts-check, vitest, pytest including `e2e/` all green.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs
git commit -m "docs: #1283 in the wave and #1310 specs"
```
