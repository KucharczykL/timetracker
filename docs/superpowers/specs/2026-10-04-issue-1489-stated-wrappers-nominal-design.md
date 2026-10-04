# A stated device and a stated release compare by type

Issue #1489.

## Problem

`StatedDevice` and `StatedRelease` in `games/commands/playersession.py` are
`NamedTuple`s. A `NamedTuple` is a tuple. So `StatedDevice(x) ==
StatedRelease(x) == (x,)` is true at runtime, and both unpack and index.
mypy keeps one type out of the other's field. Runtime equality cannot tell
them apart.

## Decision

1. Both types are `@dataclass(frozen=True, slots=True)`. Equality is then
   nominal: a dataclass `__eq__` returns `NotImplemented` for another class.
   Each keeps its one field (`device_id`, `release_id`).
2. The idempotency encoder (`_encode_command_value`,
   `games/events/idempotency.py`) accepts a dataclass instance. It writes
   the instance as the list of its field values, in field order. The
   encoder's return type and docstring widen to say so.
3. `FINGERPRINT_VERSION` stays at 4.

## Why the version stays

`json.dumps` writes a tuple as a JSON array and never calls `default` for
it. So a `NamedTuple` field fingerprints as the array of its values. The
new branch writes the same array for the dataclass. The digest of every
deployed `DescribeSession` record is therefore unchanged.
`tests/test_endpoint_fingerprints.py` pins `DescribeSession` digests
recorded on the code before the change.

## Why any dataclass instance

The encoder refuses a value with no canonical form, because a `repr()`
would vary between processes. A dataclass instance has a canonical form:
every entry `dataclasses.fields()` gives, `compare=False` ones included,
each encoded by the same rules. A class is refused (`is_dataclass` is true
for one). The branch does not ask whether the dataclass is frozen: that
check would read `__dataclass_params__`, which is not public API. Every
command is frozen, and every value object on one is now frozen too.

The branch sits after the `TemporalValue` branch. `TemporalValue` is a
dataclass itself, so the order keeps its tagged canonical text. The
existing tag-words test pins that.

The branch writes no type word. Two dataclasses with equal fields give one
array, and so does a one-element list. That is the behaviour a `NamedTuple`
has today, and the field name in the command's `fields` mapping already
tells the two facts apart. The encoder's docstring states this, so a later
reader does not add a type word and move every digest.

## Callers

Every caller constructs the types by position or reads the field by name:
`DescribeSession`, `games/writes/playersession.py`, `EditStatement` and the
bulk Edit's settle and Undo halves in `games/bulk_session_edit.py`, and the
two session `PATCH` routes in `games/api.py`. No caller unpacks, indexes or calls `_replace` on them. They
need no change.

## Statements the change makes false

The #689 spec and the `TimedTiming` docstring say a dataclass reaches the
encoder's fallback and raises. Both are amended.

## Out of scope

The other `NamedTuple` value objects that ride on commands (`ActStatement`,
`WayActStatement`, `StatedPrice`, `EntryStatement`, the timing statements,
`HistoricalPlaytimeStatement`) have the same runtime equality. The new
encoder branch lets each become a dataclass with no digest change. Several
call `_replace`, which becomes `dataclasses.replace`.

## Follow-up issues to file

- Make the remaining command value objects frozen dataclasses, moving
  each `_replace` call to `dataclasses.replace`.
