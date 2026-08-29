# Canonicalising a Decimal, and saying what a value is

Issue [#910](https://github.com/KucharczykL/timetracker/issues/910). The code is
in `games/events/idempotency.py`, and the tests are in
`tests/test_event_idempotency.py`. #662 gives the idempotency record and the
canonicalizer; #664 gives `canonical_command_input`, which decides what a
command offers it.

A command names itself with an idempotency key. Repeating that key over
different input is refused, and the fingerprint is how the two cases are told
apart. `_encode_command_value` turns every value json cannot write into a
string. Two defects follow from that, and both are one function's to fix.

## Two values that mean the same thing

`Decimal("1.1") == Decimal("1.10")` is `True`. The two encode as `1.1` and
`1.10`, so they hash differently, and the second one raises
`IdempotencyKeyMismatch` — "this key already recorded a different command" — for
a difference that does not exist.

A price is the value that meets it first. A form renders `12.50`, the person
retries, the browser sends `12.5`, and one honest retry is answered as a
conflict. The exponent is a property of how a decimal was written; equality
ignores it, and so must the digest.

## Two values that do not

The encoder returns a bare string, so nothing in the digest records which branch
produced it. A `uuid.UUID` and its own text encode alike. So do a `date` and its
ISO text, and a `Decimal` and the text of its canonical form. A `TemporalValue`
with an unknown time returns `None`, which json writes as `null` — the same
`null` an unset field writes.

Two fields of different types holding one value, one key, and a caller that
swaps them: the second command is answered with the first one's sequence range
and never runs. It is the quieter defect of the two, and it costs six lines to
close, so this issue closes it rather than recording it.

## The canonical form of a Decimal

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
against `0E0` and hash differently — the first defect surviving its own fix, for
the one value most likely to be typed two ways. Reducing the digits first is
what makes one rule cover `0`, `0.00`, and `0E+100` alike. The JDK shipped
`BigDecimal.stripTrailingZeros()` for a decade with this case missing
([JDK-6480539](https://bugs.openjdk.org/browse/JDK-6480539), fixed in Java 8),
so the paragraph is not hypothetical.

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
outcome without running. The first defect refuses a retry loudly; that one
accepts a different command silently.

The context is also thread-local and writable by anyone in the process. Under
`localcontext(prec=5)`, `Decimal("1.100000001")` normalizes to `Decimal("1.1")`,
so the same value canonicalizes two ways in two processes — the cross-process
variance `_encode_command_value` refuses a `repr()` fallback to avoid.
`format(..., "f")` compounds it: `Decimal("1E+6000")` renders as 6001
characters, from a field with no length bound.

`as_tuple()` reads data rather than computing, so none of this applies. Its
output is a token rather than a number a person would recognise, which costs
nothing: no one reads the canonical string, and the digest is what is stored.
CPython's own `Decimal.__hash__` is built the same way — digits and exponent,
context-free arithmetic, specials refused before anything compares the value —
which is the same requirement answered by the same means.

## The tag

Every branch returns a two-element list: the word for what the value is, then
its canonical text.

```python
type TaggedValue = list[str | None]  # ["decimal", "11E-1"]


def _encode_command_value(value: Any) -> TaggedValue:
    if isinstance(value, datetime):
        return ["datetime", value.isoformat()]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, uuid.UUID):
        return ["uuid", str(value)]
    if isinstance(value, Decimal):
        return ["decimal", _canonical_decimal(value)]
    if isinstance(value, TemporalValue):
        return ["temporal", value.canonical]
    raise TypeError(...)
```

`json.dumps` writes whatever `default` returns, so `fingerprint_command_input`
does not change. A json string can never be written the same as a json list, so
a tagged value and a plain string field are now different input.

**The tag words are the wire form.** Renaming one moves every digest that
carries that type, which is the bump condition below. They are written out
rather than taken from `type(value).__name__`, so a class rename is not a silent
canonicalizer change.

**The datetime-before-date order still matters.** A date-first branch would send
every timestamp through `["date", ...]`, which is a wrong tag and a reduced
value; the tag makes the mistake visible in a failing test rather than
inevitable.

**What the tag does not close.** A command field holding the literal list
`["decimal", "11E-1"]` still collides with `Decimal("1.10")`. Closing that means
tagging json's own types too — walking the payload instead of handing json a
`default` — for a case that needs a list-valued command field, a caller filling
it with the tag's exact shape, and one key across both. No command has a list
field. Recorded as the boundary, not as an oversight.

## The version is not bumped

`FINGERPRINT_VERSION` stays `1`. The constant exists so that a canonicalizer
change cannot turn every record written before it into a mismatch: a record
stamped with another version replays unchecked rather than being compared.

Every digest changes here — the tag reaches all five branches. The bump is still
wrong, because the condition it protects against needs a *record*, and no
deployment holds one. `0024_libraryidempotencyrecord` is on `main` and has not
run: the deployed database is at `main-e45911c`, whose tree ends at
`0022_external_references`. The table does not exist there, so it holds no rows,
so there is no fingerprint for the new canonicalizer to disagree with.
Development databases hold rows and do not count — they are rebuilt, and a
mismatch in one is a message on a screen rather than a refused write.

**The condition is the deployment, and it is met with room to spare.** The next
one is planned for after #599 completes, so `0024` reaches production alongside
every command the overhaul writes, this canonicalizer among them. No production
record can predate it.

That deployment is also what freezes the canonical form. Until it runs, any
change to the canonicalizer is free; after it, every change needs a bump.
#725/#726 does not enter into it — this issue still belongs before the first
price-carrying command, so that no command is designed against a canonicalizer
known to be wrong, but that is a reason of order rather than of cost.

The fact the rule turns on — whether a deployment has run `0024` — cannot be
read from the code, so the constant's comment is where it has to live.

### The comment the constant carries

Today it reads "Bump it when `_encode_command_value` or the canonical form
changes". Read literally, this change is exactly that, so leaving the words
alone means the code broke its own stated rule and the next reader either bumps
for nothing or stops believing the comment.

The rewritten comment states the condition that actually forces a bump: a change
that could give a *different digest for input a deployed record already holds*.
It also states the fact that condition turns on, because nothing in the code
does — no deployment has run `0024`, so no record exists to hold anything, and
every canonicalizer change until the first one that does is free. This issue is
the worked example.

## Verification

New tests in `tests/test_event_idempotency.py`, beside the existing
canonicalization group. Every test already there is relational — two digests
equal, two unequal, a length, a refusal — so none of them changes.

Equal values, one digest:

- `1.1`/`1.10`, `100`/`1E+2`, and `0.00`/`-0.00`.

Unequal values, separate digests:

- `1.1` and `1.11`, so the change cannot pass by making every decimal hash
  alike;
- a pair differing beyond 28 significant digits — the regression `normalize()`
  would introduce, and no shorter case catches it;
- a `Decimal` and an `int` of the same value, because json writes the encoder's
  return as a list and a bare `int` as a number.

The tag, each against a plain string field of the same text:

- `Decimal("1.10")` against `"11E-1"`;
- a `uuid.UUID` against its own text;
- a `date` against its ISO text;
- a `TemporalValue` with an unknown time against a field set to `None`.

Refusals and context:

- `NaN`, `sNaN`, and `Infinity` raise `TypeError`, `sNaN` among them because it
  raises `InvalidOperation` on comparison and must reach the refusal before
  anything compares it;
- the digest is unchanged inside `localcontext(prec=5)`, so the canonical form
  cannot be moved by unrelated code in the same thread.

`test_a_record_from_another_fingerprint_version_replays_unchecked` is unchanged
and still covers the version branch.

The gate is the full `make check`.
