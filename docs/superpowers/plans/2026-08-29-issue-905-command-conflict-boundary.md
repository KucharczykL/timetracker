# Command conflict boundary implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the translation of a refused command into `games/writes/answers.py`, answer every `CommandConflict` leaf, and guard the mapping against a later leaf that has none.

**Architecture:** A new module holds `CommandFailed`, a `CONFLICT_ANSWERS` mapping from conflict type to sentence and status, and the `answered(subject)` context manager. `games/writes/playergame.py`, `games/views/playergame_writes.py` and `games/api.py` import from it instead of defining or importing the PlayerGame-named exception. Two tests guard completeness: one walks the `games` package and asserts every `CommandConflict` subclass is mapped, the other asserts every exception defined in the five boundary modules is mapped, answered directly, or listed as not answered.

**Tech Stack:** Python 3.14, Django 6, pytest, mypy, ruff, vale.

**Spec:** `docs/superpowers/specs/2026-08-29-issue-905-command-conflict-boundary-design.md`

## Global Constraints

- Drive everything through `make`. Never run raw `uv run`, `pytest` or `pnpm`. Focused runs are `make test ARGS="tests/test_x.py -k name"`.
- Set `PYTEST_WORKERS=0` while debugging one file; parallel output interleaves.
- Python 3.14 is required. A `SyntaxError` in an `except` clause means the wrong interpreter, not broken code.
- Name variables with complete words: `error` not `e`, `answer` not `ans`, `module` not `mod`.
- Name a primitive role with a PEP 695 alias: `type SubjectNoun = str  # e.g. "game"`.
- Name a compound value explicitly: `ConflictAnswer` is a `NamedTuple`, not a bare tuple.
- No behavior changes. Every sentence and every status code a person sees stays exactly as it is today.
- `make vale` refuses `fold`, `tombstone`, `archive` and `delete` in prose and in comments. Say `replay`, `projection`, `remove`, `purge`.
- The verification gate is the full `make check`, including `e2e/`. `make check-fast` is for iterating only.

---

### Task 1: The answers module

**Files:**
- Create: `games/writes/answers.py`
- Test: `tests/test_command_answers.py`

**Interfaces:**
- Consumes: `CommandConflict` from `games/events/conflicts.py`; `CommandNotPermitted` and `CommandRejected` from `games/events/dispatch.py`; `RetryBudgetExhausted` and `NestedTransactionNotSupported` from `games/events/retry.py`; `IdempotencyKeyMismatch` from `games/events/idempotency.py`; `StreamSequenceMismatch`, `TransactionRequired` and `PayloadNotCanonical` from `games/events/append.py`.
- Produces: `CommandFailed(message: str, status_code: int)` with `.message` and `.status_code`; `ConflictAnswer(sentence: str, status_code: int)`; `CONFLICT_ANSWERS: dict[type[CommandConflict], ConflictAnswer]`; `ANSWERED_DIRECTLY: frozenset[type[Exception]]`; `NOT_ANSWERED: frozenset[type[Exception]]`; `answered(subject: SubjectNoun)` as a context manager; `type SubjectNoun = str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_command_answers.py`:

```python
"""A refused command becomes an answer."""

import pytest
from django.http import Http404

from games.events.append import StreamSequenceMismatch
from games.events.conflicts import CommandConflict
from games.events.dispatch import CommandNotPermitted, CommandRejected
from games.events.idempotency import IdempotencyKeyMismatch
from games.events.retry import RetryBudgetExhausted
from games.writes.answers import CONFLICT_ANSWERS, CommandFailed, answered


def test_an_exhausted_budget_asks_for_another_attempt():
    with pytest.raises(CommandFailed) as failure:
        with answered("game"):
            raise RetryBudgetExhausted(3)

    assert failure.value.status_code == 409
    assert "try again" in failure.value.message


def test_a_moved_stream_asks_for_another_attempt():
    with pytest.raises(CommandFailed) as failure:
        with answered("game"):
            raise StreamSequenceMismatch(expected=1, actual=2)

    assert failure.value.status_code == 409
    assert "try again" in failure.value.message


def test_a_reused_key_says_a_second_attempt_will_not_help():
    with pytest.raises(CommandFailed) as failure:
        with answered("game"):
            raise IdempotencyKeyMismatch("that key belongs to another request")

    assert failure.value.status_code == 409
    assert "cannot be retried" in failure.value.message


def test_the_subject_noun_reaches_the_sentence():
    with pytest.raises(CommandFailed) as failure:
        with answered("playthrough"):
            raise RetryBudgetExhausted(3)

    assert "this playthrough" in failure.value.message


def test_every_sentence_interpolates_and_leaves_no_brace():
    #: A mistyped placeholder fails here, not in a request.
    for answer in CONFLICT_ANSWERS.values():
        rendered = answer.sentence.format(subject="probe")
        assert "{" not in rendered and "}" not in rendered


def test_an_actor_who_may_not_command_is_not_found():
    #: Another library's object is absent, not forbidden.
    with pytest.raises(Http404) as refusal:
        with answered("game"):
            raise CommandNotPermitted("That library belongs to another account.")

    assert "No such game." in str(refusal.value)


def test_a_rejected_command_carries_its_own_sentence():
    with pytest.raises(CommandFailed) as failure:
        with answered("game"):
            raise CommandRejected("The library tracks no such game.")

    assert failure.value.status_code == 409
    assert failure.value.message == "The library tracks no such game."


def test_a_subclass_of_a_mapped_leaf_takes_its_parents_answer():
    class NarrowerExhaustion(RetryBudgetExhausted):
        pass

    with pytest.raises(CommandFailed) as failure:
        with answered("game"):
            raise NarrowerExhaustion(3)

    assert "try again" in failure.value.message


def test_an_unmapped_conflict_leaves_unchanged():
    #: A wrong sentence is worse than a reported failure.
    class UnmappedConflict(CommandConflict):
        pass

    with pytest.raises(UnmappedConflict):
        with answered("game"):
            raise UnmappedConflict("nobody answers this")


def test_nothing_raised_is_nothing_answered():
    with answered("game"):
        pass
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_command_answers.py -x"`

Expected: collection error, `ModuleNotFoundError: No module named 'games.writes.answers'`.

- [ ] **Step 3: Write the module**

Create `games/writes/answers.py`:

```python
"""Turn a refused command into an answer a person reads.

One module for every evented domain, so the sentences and the
status codes cannot drift apart between them.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import NamedTuple

from django.http import Http404

from games.events.append import (
    PayloadNotCanonical,
    StreamSequenceMismatch,
    TransactionRequired,
)
from games.events.conflicts import CommandConflict
from games.events.dispatch import CommandNotPermitted, CommandRejected
from games.events.idempotency import IdempotencyKeyMismatch
from games.events.retry import NestedTransactionNotSupported, RetryBudgetExhausted

#: The record a sentence names.
type SubjectNoun = str  # e.g. "game"

CONFLICT_STATUS = 409


class CommandFailed(Exception):
    """A stated fact could not be recorded.

    It carries a status code as well as a sentence, because the
    conflict leaves disagree about what to do next.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ConflictAnswer(NamedTuple):
    """A sentence for a person, and the status that carries it."""

    sentence: str
    status_code: int


_COLLIDED = (
    "Another change reached this {subject} first. Nothing was recorded; try again."
)

#: A mapping rather than clauses, so a test can read it.
CONFLICT_ANSWERS: dict[type[CommandConflict], ConflictAnswer] = {
    RetryBudgetExhausted: ConflictAnswer(_COLLIDED, CONFLICT_STATUS),
    StreamSequenceMismatch: ConflictAnswer(_COLLIDED, CONFLICT_STATUS),
    IdempotencyKeyMismatch: ConflictAnswer(
        "This request cannot be retried, because its key already belongs "
        "to a different one.",
        CONFLICT_STATUS,
    ),
}

#: Answered by a clause of their own. Neither is a CommandConflict.
ANSWERED_DIRECTLY: frozenset[type[Exception]] = frozenset(
    {CommandNotPermitted, CommandRejected}
)

#: A defect in the program, not a conflict a person can act on.
NOT_ANSWERED: frozenset[type[Exception]] = frozenset(
    {NestedTransactionNotSupported, TransactionRequired, PayloadNotCanonical}
)


def answer_for(error: CommandConflict) -> ConflictAnswer | None:
    """The nearest mapped ancestor's answer, or none."""
    for ancestor in type(error).__mro__:
        answer = CONFLICT_ANSWERS.get(ancestor)
        if answer is not None:
            return answer
    return None


@contextmanager
def answered(subject: SubjectNoun) -> Iterator[None]:
    """Turn a refused command into an answer."""
    try:
        yield
    except CommandNotPermitted as error:
        #: Absent, not forbidden: a refusal discloses nothing.
        #: Http404 from the write layer is the cost #905 accepted;
        #: the alternative replaces a 404 page with a toast.
        raise Http404(f"No such {subject}.") from error
    except CommandConflict as error:
        answer = answer_for(error)
        if answer is None:
            #: A wrong sentence is worse than a failure.
            raise
        raise CommandFailed(
            answer.sentence.format(subject=subject), answer.status_code
        ) from error
    except CommandRejected as error:
        raise CommandFailed(str(error), CONFLICT_STATUS) from error
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_command_answers.py -v"`

Expected: 10 passed.

- [ ] **Step 5: Type check and lint**

Run: `make typecheck && make lint && make format`

Expected: no errors. If mypy complains that `CONFLICT_ANSWERS.get(ancestor)` takes the wrong key type, the fix is a `cast` on the lookup, not a widening of the dict's declared key type — the declared type is what the guard in Task 2 reads.

- [ ] **Step 6: Commit**

```bash
git add games/writes/answers.py tests/test_command_answers.py
git commit -m "Answer a refused command in one place"
```

---

### Task 2: The two guards

**Files:**
- Modify: `tests/test_command_answers.py` (append)

**Interfaces:**
- Consumes: `CONFLICT_ANSWERS`, `ANSWERED_DIRECTLY`, `NOT_ANSWERED` from Task 1.
- Produces: nothing importable. Two tests.

- [ ] **Step 1: Write the failing guards**

Append to `tests/test_command_answers.py`, and add `import importlib` and `import pkgutil` to its imports:

```python
def _import_every_games_module() -> None:
    """__subclasses__ sees a class only once imported."""
    import games

    for module in pkgutil.walk_packages(games.__path__, prefix="games."):
        if ".migrations" in module.name:
            continue
        importlib.import_module(module.name)


def _descendants(root: type) -> set[type]:
    """Every subclass, at any depth."""
    found: set[type] = set()
    for child in root.__subclasses__():
        found.add(child)
        found |= _descendants(child)
    return found


def test_every_conflict_leaf_of_the_application_has_an_answer():
    """The walk is the test.

    Without it this reads only the import graph of the module under
    test, which holds exactly the leaves that module maps, so the
    assertion compares a set with itself and passes whatever the
    code does.
    """
    _import_every_games_module()
    #: A subclass a test declares is not the application's.
    leaves = {
        leaf
        for leaf in _descendants(CommandConflict)
        if leaf.__module__.startswith("games.")
    }

    unanswered = leaves - set(CONFLICT_ANSWERS)
    assert not unanswered, (
        f"{sorted(leaf.__name__ for leaf in unanswered)} reach a person as a "
        "500. Add each to CONFLICT_ANSWERS in games/writes/answers.py."
    )


def test_every_boundary_exception_is_classified():
    """A sibling outside the hierarchy is the other way to be missed.

    CommandNotPermitted and CommandRejected are that shape already.
    """
    from games.events import append, conflicts, dispatch, idempotency, retry

    boundary = (conflicts, dispatch, retry, idempotency, append)
    #: The base is answered through its leaves.
    classified = set(CONFLICT_ANSWERS) | ANSWERED_DIRECTLY | NOT_ANSWERED
    classified.add(CommandConflict)

    declared = {
        value
        for module in boundary
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, Exception)
        and value.__module__ == module.__name__
    }

    unclassified = declared - classified
    assert not unclassified, (
        f"{sorted(item.__name__ for item in unclassified)} are raised by the "
        "dispatch boundary and named nowhere in games/writes/answers.py. Put "
        "each in CONFLICT_ANSWERS, ANSWERED_DIRECTLY, or NOT_ANSWERED."
    )
```

Update the import block at the top of the file to add:

```python
import importlib
import pkgutil
```

and add `ANSWERED_DIRECTLY` and `NOT_ANSWERED` to the existing
`from games.writes.answers import ...` line.

- [ ] **Step 2: Run the guards**

Run: `make test ARGS="tests/test_command_answers.py -v"`

Expected: 12 passed. The two guards pass because Task 1 answered
`StreamSequenceMismatch` and listed the three defect exceptions. If either
fails, its message names what is missing — add that to the right set in
`games/writes/answers.py`, never to the test.

The walk imports every module of the package, which nothing else in the suite
does. If one module cannot be imported on its own, the fix is a named skip in
`_import_every_games_module` carrying the reason, not a `try`/`except` that
swallows every import error and quietly shrinks what the guard reads.

- [ ] **Step 3: Prove the hierarchy guard can fail**

Temporarily comment out the `StreamSequenceMismatch` entry in `CONFLICT_ANSWERS`, then run:

Run: `make test ARGS="tests/test_command_answers.py::test_every_conflict_leaf_of_the_application_has_an_answer"`

Expected: FAIL, naming `StreamSequenceMismatch`. A guard that has never been seen to fail is not a guard. Restore the entry and re-run to green.

- [ ] **Step 4: Prove the boundary guard can fail**

Temporarily remove `TransactionRequired` from `NOT_ANSWERED`, then run:

Run: `make test ARGS="tests/test_command_answers.py::test_every_boundary_exception_is_classified"`

Expected: FAIL, naming `TransactionRequired`. Restore it and re-run to green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_command_answers.py
git commit -m "Refuse a conflict leaf that answers nobody"
```

---

### Task 3: Switch the PlayerGame write path onto it

**Files:**
- Modify: `games/writes/playergame.py:1-71` (imports, the removed class, the removed `_translated`) and its three `with _translated():` call sites
- Modify: `games/views/playergame_writes.py:15-21,30,53,70`
- Modify: `games/api.py:62-66,94-95`
- Modify: `tests/test_playergame_write_path.py:6-14,112,128,157,176` and remove one test
- Modify: `tests/test_playergame_view_cutover.py:131,136,339,352,370,373,390,393,413,434`

**Interfaces:**
- Consumes: `CommandFailed` and `answered` from Task 1.
- Produces: nothing new. `games.writes.playergame` no longer exports `PlayerGameWriteFailed`.

- [ ] **Step 1: Run the affected tests to record the green baseline**

Run: `make test ARGS="tests/test_playergame_write_path.py tests/test_playergame_view_cutover.py"`

Expected: all pass. Note the count; Step 7 expects it minus one.

- [ ] **Step 2: Rewrite the head of `games/writes/playergame.py`**

Replace lines 1 through 71 — the docstring, the imports, the `PlayerGameWriteFailed` class and the `_translated` context manager — with:

```python
"""State a fact; answer a refused one.

Takes an actor, not a request.
The view half makes it a toast.
"""

import uuid

from django.contrib.auth.models import User

from games.commands.playergame import (
    PlayerGameNotTracked,
    RecordPlayerGameFacts,
    RemovePlayerGame,
    TrackGame,
)
from games.events.dispatch import Command, dispatch
from games.models import Game, PlayerGameStatus, UserLibrary
from games.writes.answers import answered
```

The removed names are `Iterator`, `contextmanager`, `Http404`, `CommandNotPermitted`, `CommandRejected`, `IdempotencyKeyMismatch`, `RetryBudgetExhausted`, `PlayerGameWriteFailed` and `_translated`. `Command` and `dispatch` stay: `_dispatch` still takes and calls them.

- [ ] **Step 3: Point the three call sites at `answered`**

In the same file, replace each `with _translated():` with `with answered("game"):`. There are three, in `track_game`, `untrack_game` and `record_facts`.

- [ ] **Step 4: Follow the rename in the two importers**

In `games/views/playergame_writes.py`, change the import block to:

```python
from games.writes.answers import CommandFailed
from games.writes.playergame import (
    new_correlation_id,
    record_facts,
    track_game,
    untrack_game,
)
```

and change the three `except PlayerGameWriteFailed as failure:` clauses to
`except CommandFailed as failure:`.

In `games/api.py`, drop `PlayerGameWriteFailed` from the
`from games.writes.playergame import (...)` block, add
`from games.writes.answers import CommandFailed` beside it, and rewrite the
handler as:

```python
@api.exception_handler(CommandFailed)
def _command_failed(request, failure: CommandFailed):
    #: The message rides the middleware's header.
    #: The status code reverts the optimistic label.
    messages.error(request, failure.message)
    return api.create_response(
        request, {"detail": failure.message}, status=failure.status_code
    )
```

- [ ] **Step 5: Follow the rename in the tests**

In `tests/test_playergame_write_path.py`, drop `PlayerGameWriteFailed` from the
`from games.writes.playergame import (...)` block, add
`from games.writes.answers import CommandFailed`, and change the four
`pytest.raises(PlayerGameWriteFailed)` calls to `pytest.raises(CommandFailed)`.

In `tests/test_playergame_view_cutover.py`, change the five function-local
`from games.writes.playergame import PlayerGameWriteFailed` lines to
`from games.writes.answers import CommandFailed`, and the six
`raise PlayerGameWriteFailed("Nothing was recorded; try again.", 409)` lines to
`raise CommandFailed("Nothing was recorded; try again.", 409)`.

- [ ] **Step 6: Remove the one test the boundary now covers**

Delete `test_a_reused_key_over_different_input_says_it_will_never_work`
(the last test in the file, at lines 168-183) from
`tests/test_playergame_write_path.py`. It monkeypatches `dispatch` to raise
`IdempotencyKeyMismatch` and asserts the sentence, which
`test_a_reused_key_says_a_second_attempt_will_not_help` now asserts directly.

It was the file's only user of `IdempotencyKeyMismatch`, so drop
`from games.events.idempotency import IdempotencyKeyMismatch` from the imports
as well, or `make lint` reports it. `RetryBudgetExhausted` and `Http404` both
stay: the two tests that use them stay.

Keep `test_an_exhausted_retry_budget_asks_the_player_to_try_again`. It is the
one proof that the write path applies the translation at all, and removing both
would leave the wiring untested.

Keep `test_a_failed_status_write_answers_409_with_a_toast` in
`tests/test_playergame_view_cutover.py` for the same reason on the other side.
It monkeypatches `games.api.record_facts`, PATCHes `/api/games/{id}/status`, and
asserts 409 with a `detail` body, which is the spec's evidence that the Ninja
handler follows the rename. Step 5 renames what it raises; nothing else about it
changes.

- [ ] **Step 7: Run the affected tests**

Run: `make test ARGS="tests/test_playergame_write_path.py tests/test_playergame_view_cutover.py tests/test_command_answers.py"`

Expected: Step 1's count, minus the one removed test, plus Task 1 and Task 2's twelve.

- [ ] **Step 8: Confirm nothing still names the old exception**

Run: `grep -rn "PlayerGameWriteFailed\|_translated" --include=*.py . | grep -v __pycache__`

Expected: no output.

- [ ] **Step 9: Commit**

```bash
git add games/writes/playergame.py games/views/playergame_writes.py games/api.py tests/test_playergame_write_path.py tests/test_playergame_view_cutover.py
git commit -m "Answer the PlayerGame write path from the boundary"
```

---

### Task 4: Record the rule and run the gate

**Files:**
- Modify: `CLAUDE.md` (the "Conventions for AI assistants" list)

**Interfaces:**
- Consumes: everything above. Produces nothing importable.

- [ ] **Step 1: Add the convention**

In `CLAUDE.md`, immediately after the bullet beginning **A PlayerGame fact is
stated as a command**, add:

```markdown
- **A refused command becomes an answer** — `answered(subject)` in
  `games/writes/answers.py` turns every `CommandConflict`, `CommandNotPermitted`
  and `CommandRejected` into a sentence and a status. A new conflict type goes
  in `CONFLICT_ANSWERS`, `ANSWERED_DIRECTLY` or `NOT_ANSWERED`, or
  `tests/test_command_answers.py` fails. Never translate one at a call site.
```

- [ ] **Step 2: Lint the prose**

Run: `make vale`

Expected: no errors. Three pre-existing `archive` warnings in
`scripts/db_dump.py`, `scripts/ensure_postgres.py` and
`tests/test_ensure_postgres.py` are not yours.

- [ ] **Step 3: Run the full gate**

Run: `make check`

Expected: green. This is the verification gate and it includes `e2e/`. A
hand-picked subset does not substitute.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "Say where a refused command becomes an answer"
```

- [ ] **Step 5: Report the verification evidence**

State the `make check` result and the test counts. Do not open a pull request
unless asked.

---

## What this plan does not do

- It does not change `new_correlation_id` or `_dispatch` in
  `games/writes/playergame.py`. Both are generic and both stay, per the spec's
  "What does not move".
- It does not change what `*_for_request` returns.
  [#958](https://github.com/KucharczykL/timetracker/issues/958) owns that, and
  with it the literal `409` in `games/views/purchase.py:579`.
- It does not add a rendered page for a conflict.
