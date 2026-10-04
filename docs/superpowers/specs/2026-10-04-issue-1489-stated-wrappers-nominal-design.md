# A command's value objects compare and fingerprint by type

Issues #1489 and #1491.

## Problem

A command carries value objects in its fields: `ActStatement`,
`WayActStatement`, `StatedPrice`, `EntryStatement`,
`HistoricalPlaytimeStatement`, `TimedTiming`, `DurationOnlyTiming`,
`CorrectedTiming`, `StatedDevice` and `StatedRelease`. Each is a
`NamedTuple`. A `NamedTuple` is a tuple, so two of them with equal fields
compare equal, and each equals a bare tuple. `UNKNOWN_PRICE ==
UNDATED_PURCHASE` is true.

The fingerprint has the same fault. `json.dumps` writes a tuple as an
array and never calls the encoder for it. The array carries no type, so
the three timing statements are told apart by their length alone.

## Decision

1. Every value object a command field holds is a
   `@dataclass(frozen=True, slots=True)` subclass of `FingerprintedValue`
   (`games/events/idempotency.py`). Equality is nominal.
2. Each subclass states its wire word as a `ClassVar`, written out:
   `fingerprint_word = "stated_device"`. A rename of the class moves no
   digest.
3. `FingerprintedValue.__init_subclass__` refuses a subclass that states no
   word, and a word another class holds. It keys the holder by module and
   `__name__`, as the command registry does: `slots=True` rebuilds the
   class and fires the hook a second time.
4. The encoder writes a fingerprinted value as
   `{"value": <word>, "fields": {<name>: <value>}}`, the shape
   `canonical_command_input` gives a command. `json` encodes each field
   again. A tagged scalar is a two-item array, so no word collides with a
   tag word. A field order change moves no digest.
5. The encoder refuses every other dataclass, as it refuses every other
   unknown type.
6. `FINGERPRINT_VERSION` is 5.

## Why the bump is free

A record stored under another version replays its key unchecked
(`idempotent_append`). The mismatch check lapses for every key stored
before the deploy, on every command. A key belongs to one request, and a
client repeats it within seconds. `tests/test_endpoint_fingerprints.py`
records the new digests.

## Guard

`json` writes a tuple itself, so the encoder cannot refuse a `NamedTuple`.
A test walks the type of every `Command` field, through aliases, unions
and nested value objects, and refuses a `NamedTuple` it reaches.

## Callers

- Each `_replace` call on a value object becomes `dataclasses.replace`, in
  code and in tests. `_replace` on a form group or a result tuple stays.
- `purchase.py` unpacks a `StatedPrice`; it reads the fields by name.
- `case` patterns name keyword attributes or a bare class. A dataclass
  matches both.
- mypy refuses unpacking, indexing, `len` and ordering on a dataclass, so
  any other such caller fails the type check.

## Out of scope

`NamedTuple`s that no command field holds (`HeldTarget`, `NewlyTracked`,
`Rejection` and the like) are not fingerprinted. They stay as they are.
