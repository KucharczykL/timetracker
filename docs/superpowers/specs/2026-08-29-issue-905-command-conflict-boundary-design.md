# Rendering a command conflict

Issue [#905](https://github.com/KucharczykL/timetracker/issues/905). The code is
in `games/writes/answers.py`, `games/writes/playergame.py` and `games/api.py`.
#664 gives the dispatch boundary and the typed exceptions. #677 gives the first
evented view, and with it the first translation of those exceptions into words.

A dispatch can be refused in several ways. A person must be told which one,
because some of them ask for a second attempt and some do not. #677 wrote that
translation inside the PlayerGame write module, which was the only caller.
`games/writes/answers.py` holds it now, names no domain, answers every leaf, and
carries the guards that keep it complete.

## Every leaf is answered

`CommandConflict` has three subclasses.

| Subclass                 | Module                        |
| ------------------------ | ----------------------------- |
| `RetryBudgetExhausted`   | `games/events/retry.py`       |
| `IdempotencyKeyMismatch` | `games/events/idempotency.py` |
| `StreamSequenceMismatch` | `games/events/append.py`      |

The translation in #677 answered the first two. The third reached a person as a
500.

`StreamSequenceMismatch` is unreachable through `dispatch`. `LockedStream.append`
raises it only for a caller that passes `expected_sequence`, `idempotent_append`
passes none, and the one caller that does — `games/events/rebuild.py` — catches
its own. Its answer is therefore written against a later command rather than
against a current defect. It is written because the guard below refuses an
unanswered leaf, and because a leaf that is answered when it appears needs no
second memory.

## Where the translation lives

`games/writes/answers.py` holds the answer type, the sentences and the context
manager that applies them. The name states what the module makes:
`games/writes/playergame.py` opens with "State a fact; answer a refused one".

Three other places are refused.

`games/events/conflicts.py` holds `CommandConflict` alone, and imports nothing.
That is what lets `idempotency`, `retry` and `append` each raise a subclass
without importing each other. A translation there imports all three, thus it
makes a cycle.

`games/writes/conflicts.py` is refused for its name. Two modules called
`conflicts.py` in one application make every import of either ambiguous to a
reader, which is the opposite of what this issue delivers.

A module under `games/views/` is refused because the write layer raises the
translated exception. `games/writes/playergame.py` would then import from the
view layer, which inverts the direction every other write takes.

## The names

`CommandFailed` carries a sentence and a status code. The name joins
`CommandNotPermitted`, `CommandRejected` and `CommandConflict`, and names no
domain. It replaces `PlayerGameWriteFailed`, which named one.

`CommandRefused` is refused as a name. `CommandRejected` already exists and means
one specific thing, and two near-synonyms at one boundary are read as one.

`answered` takes the subject noun. A call site reads `with answered("game"):`.

## What the translation answers

| Raised by                | Meaning                                | Answer                                 |
| ------------------------ | -------------------------------------- | -------------------------------------- |
| `CommandNotPermitted`    | the actor may not command this library | `Http404`                              |
| `RetryBudgetExhausted`   | writers collided, nothing was recorded | `CommandFailed`, 409, try again        |
| `IdempotencyKeyMismatch` | one key over two different inputs      | `CommandFailed`, 409, never try again  |
| `StreamSequenceMismatch` | the stream moved under the command     | `CommandFailed`, 409, try again        |
| `CommandRejected`        | the state does not permit the act      | `CommandFailed`, 409, its own sentence |

The first, second, third and fifth answers are the ones #677 gives. No wording
changed, and no status code changed.

`CommandNotPermitted` raises `Http404` from the write layer. An object of another
library is absent, and a 404 is how the charter says so. To answer it as a
`CommandFailed` of 404 instead reads as tidier, and it replaces a rendered 404
page with a message on the page the view redirects to. That is a change to what a
person sees, thus it is not this issue's to make. The layering cost is recorded
below.

## The subject noun

One sentence names the record. `answered` takes it as an argument.

```python
type SubjectNoun = str  # e.g. "game"
```

`games/writes/playergame.py` calls `answered("game")`, and the sentence a person
reads is unchanged. A second domain passes its own noun.

## The sentences are a mapping

The three conflict leaves are entries in a mapping keyed on the exception type.

```python
class ConflictAnswer(NamedTuple):
    """A sentence for a person, and the status that carries it."""

    sentence: str
    status_code: int
```

`CONFLICT_ANSWERS` maps each `CommandConflict` subclass to one `ConflictAnswer`.
The sentence holds `{subject}` where it names the record, and `answered`
interpolates it.

A mapping is chosen over `except` clauses for one reason: a test can read it. A
chain of clauses states the same thing and states it only to the interpreter.

Lookup walks the exception's method resolution order, thus a subclass of a mapped
leaf is answered by its parent.

`CommandNotPermitted` and `CommandRejected` are fixed clauses. Neither is a
`CommandConflict`, by #664's decision, and each has one answer that no table
makes clearer. The module names them in `ANSWERED_DIRECTLY`, which the second
guard reads.

## An unanswered conflict is re-raised

A `CommandConflict` absent from the mapping leaves `answered` as itself. It
reaches a person as a 500.

This branch is reachable. The first guard below closes the ordinary path to it,
and no guard closes every path: a leaf that no import reaches is invisible to a
test and still raised by the module that defines it.

A 500 is chosen over a generic sentence. The leaves disagree about what to do
next, thus an answer written for an unknown cause either tells a person to retry
something that can never work, or tells them to give up on something a second
attempt would complete. Neither is better than a failure that is reported as one.

## The guards

Two tests in `tests/test_command_answers.py`, because two things can go wrong.

**Every leaf of the hierarchy is answered.** The test imports every module of the
`games` package with `pkgutil.walk_packages`, collects the subclasses of
`CommandConflict` at any depth, and asserts each is in `CONFLICT_ANSWERS`.

The walk is what makes the test worth writing. `__subclasses__` sees a class only
after its module is imported, and `games/writes/answers.py` imports exactly the
modules whose leaves it maps. A guard that reads only its own import graph
therefore compares a set with itself and passes whatever the code does. The walk
makes the test read the repository instead.

**Every exception of the boundary is classified.** The second test collects every
`Exception` subclass defined in `games/events/conflicts.py`, `dispatch.py`,
`retry.py`, `idempotency.py` and `append.py`, and asserts each is in
`CONFLICT_ANSWERS`, in `ANSWERED_DIRECTLY`, or in `NOT_ANSWERED`.

`NOT_ANSWERED` holds the exceptions that state a defect in the program rather
than a conflict a person can act on: `NestedTransactionNotSupported`,
`TransactionRequired` and `PayloadNotCanonical`.

The first guard catches a new leaf of the hierarchy, wherever it is defined. The
second catches a sibling outside the hierarchy, which is what
`CommandNotPermitted` and `CommandRejected` are. Neither guard subsumes the
other. Each was seen to fail on the thing it guards before it was committed.

## The status code has one reader

`CommandFailed` carries a status code, and one caller reads it: the Ninja
exception handler in `games/api.py`.

No HTML view can. The three `*_for_request` wrappers in
`games/views/playergame_writes.py` catch the exception, raise a message, and
answer `bool`. `games/views/purchase.py` needs a status anyway, so it restates
the value as the literal `409`.

That literal is correct while every leaf answers 409, and it is a copy of a
number rather than a reading of one.
[#958](https://github.com/KucharczykL/timetracker/issues/958) owns the repair,
because the fix is the return type of the three wrappers, which this issue does
not move. This issue keeps the field and the literal as they are.

## The layering cost

`answered` raises `Http404` from the write layer. That was one module's shortcut
and becomes the rule of a shared boundary, which makes it harder to reverse.

The alternative changes what a person sees, thus it is refused above. The cost is
recorded here and in a comment on the clause, so a later reader finds a decision
rather than an oversight.

## What did not move

`new_correlation_id` and the private `_dispatch` stay in
`games/writes/playergame.py`. Both name no domain, and a second evented domain
copies both. Neither is the rendering of a conflict, thus each belongs to the
issue that needs it second.

The three `*_for_request` wrappers stay, for the reason #958 records.

## Reversibility

No schema changes. No data changes. No user-visible behavior changes, because the
one answer this issue adds is for a leaf that `dispatch` cannot raise.

## Out of scope

- A rendered page for a conflict. A view answers a form post with a message on
  the page it redirects to, a re-rendered form, or an empty 409 for a cell that
  htmx must not swap. Whether a conflict deserves a page of its own is a question
  about what a failure looks like, and it governs every evented view.
- The status code a view cannot read, which is #958.
- Shared library-scoped resolution of the references a command carries, which is
  [#909](https://github.com/KucharczykL/timetracker/issues/909). A game of
  another library is answered 409 by a command's `build`, and the view answers
  404 before the command runs. That pair is #909's to settle.
- A record of a refused command, which is
  [#740](https://github.com/KucharczykL/timetracker/issues/740).
