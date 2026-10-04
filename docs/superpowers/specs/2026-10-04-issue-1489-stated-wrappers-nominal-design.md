# A command's value objects compare and fingerprint by type

Issues #1489 and #1491.

## Rule

A command field holds a scalar or a value object. A value object is a
`@dataclass(frozen=True, slots=True)` subclass of `FingerprintedValue`
(`games/events/idempotency.py`). The ten value objects are `ActStatement`,
`WayActStatement`, `StatedPrice`, `EntryStatement`,
`HistoricalPlaytimeStatement`, `TimedTiming`, `DurationOnlyTiming`,
`CorrectedTiming`, `StatedDevice` and `StatedRelease`.

Equality is nominal. Two value objects of different classes are not equal,
and no value object equals a tuple. `UNKNOWN_PRICE != UNDATED_PURCHASE`.

A value object is never a `NamedTuple`. `json.dumps` writes a tuple as an
array and does not call the encoder, so the array carries no type.

## Word

Each subclass states its wire word as a `ClassVar`, written out:
`fingerprint_word: ClassVar[FingerprintWord] = "stated_device"`. A class
rename moves no digest.

`FingerprintedValue.__init_subclass__` refuses:

- a subclass that states no word of its own. A subclass does not inherit
  a word.
- a word that another class holds.

The registry keys a holder by module and `__name__`, as the command
registry does. `slots=True` rebuilds the class, the hook runs a second
time, and the rebuilt class has no `<locals>` in its `__qualname__`.

## Encoding

The encoder writes a value object as
`{"value": <word>, "fields": {<name>: <value>}}`. A command's input has
the same shape under the key `command`. `json` encodes each field again,
so a nested value object keeps its word. A tagged scalar is a two-item
array, so a word does not collide with a tag word.

The encoder reads the word off the class. It refuses:

- a `FingerprintedValue` that is not a dataclass.
- a value object that declares `fingerprint_word` as a field. A caller
  could restate that word. mypy refuses it too.
- every other dataclass, and every other unknown type.

## Version

Field order does not move a digest. These changes move every digest that
holds the value object, and need a `FINGERPRINT_VERSION` bump:

- a field rename,
- a new field,
- a new word.

A record stored under another version replays its key unchecked
(`idempotent_append`). A repeated key still answers with what it did. Only
the mismatch check lapses, for the keys stored before the deploy.
`tests/test_endpoint_fingerprints.py` records one digest for each value
object.

## Guard

`tests/test_command_value_objects.py` walks the type of every `Command`
field, through aliases, unions and nested value objects. It refuses:

- a `NamedTuple`,
- a dataclass with no word,
- a `FingerprintedValue` that is not a dataclass.

It asserts that it reaches known nested value objects, so an empty walk
fails.

## Not value objects

A `NamedTuple` that no command field holds is not fingerprinted.
`HeldTarget`, `NewlyTracked` and `Rejection` are examples. Such a tuple
can stay a `NamedTuple`.
