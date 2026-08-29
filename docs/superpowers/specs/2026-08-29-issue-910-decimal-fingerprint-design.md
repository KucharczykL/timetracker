# What a fingerprint identifies

The code is in `games/events/idempotency.py`. The tests are in
`tests/test_event_idempotency.py`.

A command names itself with an idempotency key. The same key over the same
input replays the first result. The same key over different input is refused. A
digest tells the two apart.

A wrong digest fails in one of two directions. Too many digests refuse an
honest retry. Too few answer one command with another command's result. The
second direction is the worse one.

## The rule

A digest identifies the type of a value and its meaning. It does not identify
its spelling.

`Decimal("1.1")` and `Decimal("1.10")` are one number. They get one digest. Two
datetimes for one instant get one digest.

`Decimal(1)` and `1` are equal. They get two digests. A field that holds a
decimal is not a field that holds a number.

## Decimal

`_canonical_decimal` reads `as_tuple()`. It removes the trailing zeros from the
digits and adds to the exponent. It writes the sign, the digits, `E`, and the
exponent. `Decimal("1.10")` becomes `11E-1`.

Every zero becomes `0`. `Decimal("-0.00")` equals `Decimal("0")`, and the sign
stays in `as_tuple()`.

`NaN`, `sNaN`, and `Infinity` are refused with a `TypeError`. Their exponent is
a string. A test of the type of the exponent refuses them before a comparison.
`sNaN` signals on a comparison.

Do not use `normalize()`. It is an arithmetic operation. It rounds to the
precision of the active context. Two values that differ after 28 digits then
get one digest. The context is also thread-local. The same value then gets two
digests in two processes.

## Datetime

`_canonical_datetime` converts an aware value to UTC. It then takes the ISO
text.

A naive value is refused. `astimezone()` reads the timezone of the machine. The
digest then changes between hosts.

The `datetime` branch is before the `date` branch. `datetime` is a subclass of
`date`, and the `date` branch does not convert to UTC.

## The tag

Each branch returns a pair. The first item is a word for the type. The second
item is the canonical text. The words are `datetime`, `date`, `uuid`,
`decimal`, and `temporal`.

json writes the pair as an array. A string is never written as an array. A
value and its own text are therefore different input.

The words are the wire form. A new word changes every digest of that type.

json writes its own types without a tag. A `str` subclass stays bare.
`float("nan")` does not reach the encoder. No command has a sequence field, so
no field collides with a pair.

## The version

`FINGERPRINT_VERSION` is stamped on each record. Bump it when a change can give
a different digest for input that a deployed record holds. A record with
another version replays without a comparison.

No deployment has run `0024_libraryidempotencyrecord`. No record holds a
fingerprint. Each change to the canonical form is free until a deployment runs
that migration.
