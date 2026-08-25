# The optional expected-sequence concurrency check

## Purpose

A caller reads the library stream. The caller then does work. The caller then
writes. The stream can move in that time. This check lets the caller give the
sequence that it read. The check refuses the write if the stream moved.

## The interface

```python
class StreamSequenceMismatch(CommandConflict):
    def __init__(self, *, expected: int, actual: int) -> None: ...


class LockedStream:
    def require_sequence(self, expected: int) -> None: ...

    def append(self, events, *, ..., expected_sequence: int | None = None): ...
```

`append` calls `require_sequence` if you give the parameter. It does this after
the empty-events guard, and before it validates the payloads. A refusal thus
writes no row and moves no head.

The method is public because the first caller writes no events. A shadow rebuild
(#667) must only make sure that the stream did not move.

## The four results

| `expected` | Result |
| --- | --- |
| less than 0 | `ValueError`, before the query |
| more than the head | `ValueError` |
| less than the head | `StreamSequenceMismatch` |
| equal to the head | none; the caller continues |

The head only goes up. A number above the head is thus not a race. It is an
error in the caller, and no new attempt can correct it. An expectation of 0
means that the library is still empty.

## The check reads the database

`require_sequence` does a `SELECT`. It does not use the value in the
`LibraryEventStreamHead` object.

That object can be too old. `lock_stream` makes a new object at each call, and
`append` changes only its own object. Two locked streams in one transaction thus
disagree after one of them writes. A rollback to a savepoint has the same
result.

An object that is too low is dangerous. The check then agrees with an
expectation that is also too low. The check passes, but it must refuse.

The lock holds the row still. The lock makes the check sensible. The query makes
the value correct.

## The caller does the work again

`StreamSequenceMismatch` is not an `IntegrityError` or an `OperationalError`.
`run_in_transaction` thus does not try the command again. This is correct. The
caller must read the stream again before it can make a new expectation.

## The token applies to the full library

Any event in the library makes the token wrong. This is correct for an operation
on the full library, such as a rebuild (#667) or a restore (#796).

It is not correct for an edit form for one entity, where a write to a different
record would refuse the form. `idempotent_append` and `dispatch` thus do not
have this parameter. #671 owns the conflict for one entity.

## Limit

`LockedStream` does not show which library it belongs to. The check thus cannot
find a caller that compares the number of one library with the stream of a
different library. The check passes if the two numbers agree. The message for a
mismatch must not tell the user about an error of one.
