# Rendering a command conflict

Issue [#905](https://github.com/KucharczykL/timetracker/issues/905). The code is
in `games/writes/conflicts.py`, `games/writes/playergame.py` and `games/api.py`.
#664 gives the dispatch boundary and the typed exceptions. #677 gives the first
evented view, and with it the first translation of those exceptions into words.

A dispatch can be refused in four ways. A person must be told which one, because
two of them ask for a second attempt and two of them do not. #677 wrote that
translation inside the PlayerGame write module, which is the only caller that
exists. This issue moves it to a module that names no domain, and adds the guard
that keeps it complete.

## Where the translation lives

`games/writes/conflicts.py` is a new module. It holds the answer type, the
sentences and the context manager that applies them.

Two other places are refused.

`games/events/conflicts.py` holds `CommandConflict` alone, and imports nothing.
That is what lets `idempotency` and `retry` each raise a subclass without
importing each other. A translation there imports both, thus it makes a cycle.

A module under `games/views/` is refused because the write layer raises the
translated exception. `games/writes/playergame.py` would then import from the
view layer, which inverts the direction every other write takes.

## The names

`PlayerGameWriteFailed` becomes `CommandFailed`. It carries a sentence and a
status code, as before. The name joins `CommandNotPermitted`, `CommandRejected`
and `CommandConflict`, and names no domain.

`CommandRefused` is refused as a name. `CommandRejected` already exists and
means one specific thing, and two near-synonyms at one boundary are read as one.

`_translated` becomes `translated`, and takes the subject noun.

## What the translation answers

| Raised by                | Meaning                                | Answer                                |
| ------------------------ | -------------------------------------- | ------------------------------------- |
| `CommandNotPermitted`    | the actor may not command this library | `Http404`                             |
| `RetryBudgetExhausted`   | writers collided, nothing was recorded | `CommandFailed`, 409, try again       |
| `IdempotencyKeyMismatch` | one key over two different inputs      | `CommandFailed`, 409, never try again |
| `CommandRejected`        | the state does not permit the act      | `CommandFailed`, 409, its own sentence |

The four answers are the ones #677 already gives. No wording changes, and no
status code changes.

`CommandNotPermitted` keeps raising `Http404` from the write layer. An object of
another library is absent, and a 404 is how the charter says so. To answer it as
a `CommandFailed` of 404 instead would read as tidier, and it would replace a
rendered 404 page with a message on the page the view redirects to. That is a
change to what a person sees, thus it is not this issue's to make.

## The subject noun

One sentence names the record. `translated` takes it as an argument.

```python
@contextmanager
def translated(subject: str) -> Iterator[None]:
    """Turn a command failure into an answer."""
```

`games/writes/playergame.py` calls `translated("game")`, and the sentence a
person reads is unchanged. A second domain passes its own noun.

## The sentences are a mapping

The four answers are `except` clauses today. Two of them become entries in a
mapping keyed on the exception type.

```python
class ConflictAnswer(NamedTuple):
    """A sentence for a person, and the status that carries it."""

    sentence: str
    status_code: int
```

`CONFLICT_ANSWERS` maps each `CommandConflict` subclass to one `ConflictAnswer`.
The sentence holds `{subject}` where it names the record.

A mapping is chosen over the clauses for one reason: a test can read it. A chain
of `except` clauses states the same thing and states it only to the interpreter.

Lookup walks the exception's method resolution order, thus a subclass of a
mapped leaf is answered by its parent. An unmapped conflict is re-raised as
itself. It reaches the caller as a 500, which is what an unhandled failure is.
It is not answered with a sentence that was written for another cause.

`CommandNotPermitted` and `CommandRejected` are not in the mapping. Neither is a
`CommandConflict`, by #664's decision, and each has one fixed answer.

## The guard

One test asserts that `CONFLICT_ANSWERS` holds every subclass of
`CommandConflict`, at any depth.

This is the reason to move the code rather than to leave it. Today the mapping
has two entries and the set has two members, thus the test passes and states
nothing. When a later domain raises a third kind of conflict, the test names it
and fails. Without the test that leaf reaches a person as a 500.

`__subclasses__` sees a class only after its module is imported.
`games/writes/conflicts.py` imports `games.events.retry` and
`games.events.idempotency` to build the mapping, thus an import of the module
under test is enough for the two leaves that exist. A later leaf that no module
imports is invisible to the guard and also unreachable at run time.

## What does not move

`new_correlation_id` and the private `_dispatch` stay in
`games/writes/playergame.py`. Both name no domain, and a second evented domain
copies both. Neither is the rendering of a conflict, thus each belongs to the
issue that needs it second.

The three `*_for_request` wrappers in `games/views/playergame_writes.py` stay.
Each takes domain arguments, thus each is domain-shaped. What they share is two
lines: a message and a `False`.

## Dependencies

None outstanding. #664 and #677 are delivered.

## Reversibility

No schema changes. No data changes. No user-visible behavior changes. The commit
is reverted by itself.

## Verification

- Each of the two conflict leaves answers with its sentence and 409, and the
  subject noun is interpolated.
- `CommandNotPermitted` answers `Http404`, and the message names the subject.
- `CommandRejected` answers 409 and carries the sentence its `build` wrote.
- A conflict subclass absent from the mapping is re-raised as itself.
- A subclass of a mapped leaf is answered by its parent's entry.
- `CONFLICT_ANSWERS` holds every subclass of `CommandConflict`.
- Through `record_facts`, an exhausted retry budget still reaches the caller as
  `CommandFailed` with 409, which proves the write path applies the translation.
- Through the API, a refused status change is still answered 409 with a
  `detail` body, which proves the exception handler follows the rename.
- The full `make check` gate passes.

## Out of scope

- A rendered page for a conflict. A view answers a form post with a message on
  the page it redirects to. Whether a conflict deserves a page of its own is a
  question about what a failure looks like, and it governs every evented view.
- Shared library-scoped resolution of the references a command carries, which is
  [#909](https://github.com/KucharczykL/timetracker/issues/909). A game of
  another library is answered 409 by a command's `build`, and the view answers
  404 before the command runs. That pair is #909's to settle.
- A record of a refused command, which is
  [#740](https://github.com/KucharczykL/timetracker/issues/740).
