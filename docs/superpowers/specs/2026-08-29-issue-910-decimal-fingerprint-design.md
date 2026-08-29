# Canonicalising a Decimal in the fingerprint

Issue [#910](https://github.com/KucharczykL/timetracker/issues/910). The code is
in `games/events/idempotency.py`, and the tests are in
`tests/test_event_idempotency.py`. #662 gives the idempotency record and the
canonicalizer; #664 gives `canonical_command_input`, which decides what a
command offers it.

A command names itself with an idempotency key. Repeating that key over
different input is refused, and the fingerprint is how the two cases are told
apart. `_encode_command_value` encodes a `Decimal` as `str(value)`, which is the
text the caller wrote rather than the number it means.

## The defect

`Decimal("1.1") == Decimal("1.10")` is `True`. The two encode as `1.1` and
`1.10`, so they hash differently, and the second one raises
`IdempotencyKeyMismatch` — "this key already recorded a different command" — for
a difference that does not exist.

A price is the value that meets it first. A form renders `12.50`, the person
retries, the browser sends `12.5`, and one honest retry is answered as a
conflict. The exponent is a property of how a decimal was written; equality
ignores it, and so must the digest.

## The canonical form

The encoder reads the number's stored parts and writes them back as a token.

```python
def _canonical_decimal(value: Decimal) -> str:
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        raise TypeError(...)
    while len(digits) > 1 and digits[-1] == 0:
        digits = digits[:-1]
        exponent += 1
    if digits == (0,):
        return "0"
    prefix = "-" if sign else ""
    coefficient = "".join(str(digit) for digit in digits)
    return f"{prefix}{coefficient}E{exponent}"
```

**`as_tuple()` computes nothing.** It returns the three fields the object holds:
a sign, a tuple of digits, and an exponent. Removing a trailing zero from the
digits and adding one to the exponent leaves the value unchanged, so equal
values arrive at one pair of digits and exponent, and unequal values cannot.

**A non-finite value is refused.** The exponent is a string — `n`, `N`, `F` —
for exactly the three that are not a number: `NaN`, `sNaN`, and `Infinity`.
Testing its type is therefore the refusal *and* the narrowing mypy needs to add
to it. `Decimal("NaN") != Decimal("NaN")`, so a key carrying one could never
match itself and every retry would be a mismatch; there is no canonical form for
a value that is not equal to itself, and `Infinity` is no more a price than
`NaN` is. The refusal is a `TypeError`, joining the one the same function
already raises for an unencodable type, in the same voice: it names the value
and says to convert it at the call site. `ValueError` would read more precisely
— the type is fine and the value is not — but it would give the function a
second refusal channel and every caller a second `except`, to distinguish two
cases that are answered the same way. One channel is the choice made here.

**Zero is written `0`.** `Decimal("-0.00") == Decimal("0")` is `True`, and the
sign survives into `as_tuple()`, so without this the pair would encode as `-0E0`
against `0E0` and hash differently — the original defect surviving its own fix,
for the one value most likely to be typed two ways. Reducing the digits first is
what makes one test cover `0`, `0.00`, and `0E+100` alike.

| Value                  | Today       | Canonical |
| ---------------------- | ----------- | --------- |
| `Decimal("1.1")`       | `1.1`       | `11E-1`   |
| `Decimal("1.10")`      | `1.10`      | `11E-1`   |
| `Decimal("100")`       | `100`       | `1E2`     |
| `Decimal("1E+2")`      | `1E+2`      | `1E2`     |
| `Decimal("-1.50")`     | `-1.50`     | `-15E-1`  |
| `Decimal("1.11")`      | `1.11`      | `111E-2`  |
| `Decimal("0.00")`      | `0.00`      | `0`       |
| `Decimal("-0.00")`     | `-0.00`     | `0`       |
| `Decimal("NaN")`       | `NaN`       | refused   |
| `Decimal("-Infinity")` | `-Infinity` | refused   |

### Why not normalize()

`format(value.normalize(), "f")` states the same intent in one line and is the
obvious implementation. It is wrong, and wrong in the direction that does not
announce itself.

`normalize()` is an arithmetic operation, so it rounds to the precision of the
active `decimal` context — 28 significant digits by default.
`Decimal("1.000000000000000000000000000000001")` and the same value ending `002`
are unequal, and both normalize to `Decimal("1")`. Two different commands would
share a digest, and the second would be answered with the first one's recorded
outcome without running. Today's defect refuses a retry loudly; that one accepts
a different command silently.

The context is also thread-local and writable by anyone in the process. Under
`localcontext(prec=5)`, `Decimal("1.100000001")` normalizes to `Decimal("1.1")`,
so the same value canonicalizes two ways in two processes — the cross-process
variance `_encode_command_value` refuses a `repr()` fallback to avoid.
`format(..., "f")` compounds it: `Decimal("1E+6000")` renders as 6001
characters, from a field with no length bound.

`as_tuple()` reads data rather than computing, so none of this applies. Its
output is a token rather than a number a person would recognise, which costs
nothing: no one reads the canonical string, and the digest is what is stored.

## The version is not bumped

`FINGERPRINT_VERSION` stays `1`. The constant exists so that a canonicalizer
change cannot turn every record written before it into a mismatch: a record
stamped with another version replays unchecked rather than being compared.

**No digest that exists changes.** Only the `Decimal` branch is edited, so a
recorded fingerprint moves only if the command behind it carried a `Decimal`.
None can have. `canonical_command_input` fingerprints a command's dataclass
fields, the seven commands in `games/commands/playergame.py` declare UUIDs, a
status and a bool, and `games/backfill/playergame.py` passes dicts of strings.
The old canonicalizer and the new one agree on every input any record holds.

A bump would therefore claim that records are incomparable when they are
identical, and would suspend the mismatch guard for every key predating it to
buy nothing.

Corroborating, with a shorter shelf life: the deployed database is at
`main-e45911c`, whose tree ends at `games/migrations/0022_external_references`,
so `0024_libraryidempotencyrecord` is not there and the table holds nothing at
all. That is true until the next deployment. The argument above is the one that
holds afterwards.

The window closes at #725/#726, the first commands to carry a price. That is the
timing this issue records: not that the bump is cheap now, but that the
canonicalizer must be right before a digest is ever taken over a `Decimal`.

### The comment the constant carries

Today it reads "Bump it when `_encode_command_value` or the canonical form
changes". Read literally, this change is exactly that, so leaving the words
alone means the code broke its own stated rule and the next reader either bumps
for nothing or stops believing the comment.

The rewritten comment states the condition that actually forces a bump: a change
that could give a *different digest for input some record already holds*. An
edit to a branch no recorded command ever reached does not qualify, and this
issue is the worked example.

## What this does not change

The canonicalizer has never tagged a type, so a value and a string that encode
alike still fingerprint alike: a `uuid.UUID` and its own text, a `date` and its
ISO text, and now a `Decimal` and the literal string `"11E-1"`. Reaching it
requires a command with two fields of different types holding the same text, one
key, and a caller that swaps them — and the fix is a different one, over every
branch rather than this one. Recorded here so it is a known hole rather than an
unnoticed one; #910's boundary leaves it.

## Verification

New tests in `tests/test_event_idempotency.py`, beside the existing
canonicalization group:

- equal values share a digest, over `1.1`/`1.10`, `100`/`1E+2`, and
  `0.00`/`-0.00`;
- unequal values still differ, over `1.1` and `1.11`, so the change cannot pass
  by making every decimal hash alike;
- a pair differing beyond 28 significant digits keeps separate digests — the
  regression that `normalize()` would introduce and no shorter case catches;
- the digest is unchanged inside `localcontext(prec=5)`, so the canonical form
  cannot be moved by unrelated code in the same thread;
- `NaN`, `sNaN`, and `Infinity` are refused with `TypeError`, `sNaN` among them
  because it raises `InvalidOperation` on comparison and must reach the refusal
  before anything compares it;
- a `Decimal` and an `int` of the same value keep separate digests, because json
  writes the encoder's return as a string and a bare `int` as a number.

`test_a_record_from_another_fingerprint_version_replays_unchecked` is unchanged
and still covers the version branch.

The gate is the full `make check`.
