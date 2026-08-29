# What a fingerprint identifies

Issue [#910](https://github.com/KucharczykL/timetracker/issues/910). The code is
in `games/events/idempotency.py`, and the tests are in
`tests/test_event_idempotency.py`. #662 gives the idempotency record and the
canonicalizer; #664 gives `canonical_command_input`, which decides what a
command offers it.

A command names itself with an idempotency key. Repeating that key over
different input is refused; repeating it over the same input replays the first
command's result and does not run the second. The digest is how those two cases
are told apart, so a wrong digest fails in one of two directions. Too many
digests refuses an honest retry, loudly. Too few answers a genuinely different
command with another command's result, silently. The second is the worse one.

## The rule

**A digest identifies a value's type and its meaning, never its spelling.**

All three clauses are load-bearing, and the rest of this document is their
consequences.

*Meaning, not spelling*: `Decimal("1.1")` and `Decimal("1.10")` are the same
number, and two datetimes an hour apart in offsets an hour apart are the same
instant. Each pair must reach one digest.

*Type as well as meaning*: `Decimal(1) == 1` and `Decimal("1.5") == 1.5` are
both `True`, and each pair must reach two digests. A command field that holds a
number is not the same input as one that holds a decimal, whatever the two
compare as. Equality alone would say otherwise, which is why the rule is stated
in two parts rather than as "equal values, one digest".

## Where the rule is broken today

`_encode_command_value` turns every value json cannot write into a string.

**Spelling reaches the digest.** `Decimal("1.1")` and `Decimal("1.10")` encode
as `1.1` and `1.10`. A form renders `12.50`, the person retries, the browser
sends `12.5`, and one honest retry is refused as a conflict. The same holds for
an aware `datetime`: `12:00+00:00` and `13:00+01:00` are the same instant and
encode as two strings, and in an app whose `TIME_ZONE` is `Europe/Prague` with
`USE_TZ` on, a local-aware value and a UTC one for one moment are an ordinary
pair to hold.

**Type does not.** The encoder returns a bare string, so nothing records which
branch produced it. A `uuid.UUID` and its own text encode alike, as do a `date`
and its ISO text, a `Decimal` and the text of its canonical form, and — found
while writing this — a `date` and a `TemporalValue` for the same day. A
`TemporalValue` with an unknown time returns `None`, which json writes as the
`null` an unset field also writes. Two fields of different types holding one
value, one key, and a caller that swaps them: the second command is answered
with the first one's range and never runs.

Both are one function's to fix, and the second costs six lines, so this issue
takes both rather than recording one.

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
Testing its type is the refusal *and* the narrowing mypy needs for `exponent +=
1`. The reason to refuse is not that a `NaN` could never match itself; the
fingerprint compares digests, `str(Decimal("NaN"))` is `NaN` on both attempts,
and today such a retry matches perfectly well. That is the defect.
`Decimal("NaN") != Decimal("NaN")`, so a matching digest asserts two commands
carry the same input where the values themselves deny it, and the second command
is answered with the first one's range. It is the rule's dangerous direction,
reached by a value that is no more a price than `Infinity` is.

The refusal is a `TypeError`, joining the one the same function already raises
for an unencodable type, in the same voice: it names the value and says to
convert it at the call site. `ValueError` would read more precisely — the type
is fine and the value is not — but it would give the function a second refusal
channel and every caller a second `except`, to distinguish two cases that are
answered the same way. One channel is the choice made here.

**Zero is written `0`.** `Decimal("-0.00") == Decimal("0")` is `True`, and the
sign survives into `as_tuple()`, so without this the pair would encode as `-0E0`
against `0E0`. Zero is the case an implementation misses —
`BigDecimal.stripTrailingZeros()` left `0.00` unreduced for a decade
([JDK-6480539](https://bugs.openjdk.org/browse/JDK-6480539), fixed in Java 8) —
though not by that route here: CPython stores every zero with a one-digit
coefficient, `Decimal("0.00").as_tuple()` is `digits=(0,), exponent=-2`, and the
loop never runs for one. The reduction is free and the sign is what is left, so
`digits == (0,)` carries the case on its own and its position among the rules is
not load-bearing.

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
obvious implementation. It is wrong, in the rule's dangerous direction.

`normalize()` is an arithmetic operation, so it rounds to the precision of the
active `decimal` context — 28 significant digits by default.
`Decimal("1.000000000000000000000000000000001")` and the same value ending `002`
are unequal, and both normalize to `Decimal("1")`. Two different commands would
share a digest, and the second would be answered with the first one's outcome
without running.

The context is also thread-local and writable by anyone in the process. Under
`localcontext(prec=5)`, `Decimal("1.100000001")` normalizes to `Decimal("1.1")`,
so the same value canonicalizes two ways in two processes — the cross-process
variance `_encode_command_value` refuses a `repr()` fallback to avoid.
`format(..., "f")` compounds it: `Decimal("1E+6000")` renders as 6001
characters, from a field with no length bound.

`as_tuple()` reads data rather than computing, so none of this applies. Its
output is a token rather than a number a person would recognise, which costs
nothing: no one reads the canonical string, and the digest is what is stored.
CPython's `Decimal.__hash__` answers the same requirement from the same data —
the stored digits and exponent, context-free — but not with the same rule: it is
modular arithmetic chosen so that `hash(Decimal(1))` equals `hash(1)` and
`hash(1.0)`, and it refuses signalling `NaN` alone. The agreement is on method,
not on output; this rule keeps types apart where that one deliberately joins
them.

## The canonical form of a datetime

An aware datetime is canonicalised to UTC before its ISO text is taken, so one
instant has one spelling whatever offset it arrived in.

A naive datetime is refused, with the same `TypeError`. `astimezone()` on a
naive value assumes the *system* timezone, so `datetime(2020, 1, 1, 12)`
canonicalizes as `+01:00` on a machine set to `Europe/Prague` and as `+00:00` on
one set to UTC — precisely the cross-process variance this function exists to
prevent, and it would arrive as a silent wrong answer rather than a refusal.
`USE_TZ` is on, so an aware value is what the app has; a naive one reaching a
command is a bug at the call site, which is where the refusal points.

Naive and aware never share a digest by accident: they are unequal in Python,
and the refusal means only one of them has an encoding at all.

**The branch order is load-bearing, and now says so under test.** `datetime`
subclasses `date`, so a `date`-first branch would send every timestamp through
the `date` arm. The comment in the code today claims that would "silently reduce
every timestamp to its calendar day" — it would not, because `value.isoformat()`
binds to the instance and a datetime returns its full text either way, which is
why `test_a_datetime_and_its_date_differ` passes with the branches reversed.
That comment and that docstring are wrong and this issue corrects them. What a
`date`-first branch *does* break is the UTC canonicalization above, which the
wrong arm never applies — so the equal-instants test fails on a reversed order,
and the ordering is pinned by a test rather than by a claim.

## The tag

Every branch returns a pair: the word for what the value is, then its canonical
text.

```python
type TaggedValue = tuple[str, str | None]  # ("decimal", "11E-1")


def _encode_command_value(value: Any) -> TaggedValue:
    if isinstance(value, datetime):
        return ("datetime", _canonical_datetime(value))
    if isinstance(value, date):
        return ("date", value.isoformat())
    if isinstance(value, uuid.UUID):
        return ("uuid", str(value))
    if isinstance(value, Decimal):
        return ("decimal", _canonical_decimal(value))
    if isinstance(value, TemporalValue):
        return ("temporal", value.canonical)
    raise TypeError(...)
```

json writes a tuple as an array, and re-serializes whatever `default` returns —
a non-native return would re-enter `default` — so a pair of strings is the
whole contract. `fingerprint_command_input` does not change. A json string can
never be written the same as a json array, so a tagged value and a plain string
field are now different input.

`tuple` rather than `list`: it states the arity, it cannot be mutated by a
caller, and `list[str | None]` is invariant, so binding the pair to a local
before returning it fails mypy while the literal alone passes — a refactor
away from a confusing error.

**The tag words are the wire form.** Renaming one moves every digest carrying
that type. They are written out rather than taken from `type(value).__name__`,
so a class rename is not a silent canonicalizer change, and a test asserts the
five pairs directly — without one, renaming `"decimal"` to `"dec"`, or giving
`date` and `datetime` one word, passes every other test in the file.

**What the tag does not close.** It reaches the five branches, and json's own
types stay bare:

- A command field holding the sequence `("decimal", "11E-1")` still collides
  with `Decimal("1.10")`. A tuple and a list serialize identically, and a frozen
  dataclass reaches for a tuple, so the claim to check is "no command has a
  sequence field" — none does.
- A `str` subclass never reaches `default`. `PlayerGameStatus` is a
  `TextChoices` member, so it is written as its bare string — harmless, since it
  is equal to that string, but it is untagged.
- `float("nan")` and `float("inf")` are written by json as the bare tokens `NaN`
  and `Infinity` without consulting `default`, so the non-finite refusal above
  does not reach floats.
- `1` and `1.0` are equal and take two digests; `True` and `1` likewise. Under
  the rule's second clause that is correct, not a defect.

Closing the first three means tagging json's natives too — walking the payload
instead of handing json a `default`. That is a different change with a different
blast radius, and it is the boundary this issue stops at.

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

**One writer is not a request.** `0033_playergame_baseline_backfill` runs
`backfill_library`, which appends through `idempotent_append` and records a
fingerprint per baseline fact, and it runs again from `make loadsample`. It is
safe here twice over: it reaches production only in the deployment that also
carries this canonicalizer, and every `command_input` it passes is plain strings
(`str(game.pk)`, `current.value`), so `_encode_command_value` is never called
and none of its digests move. The second reason is what keeps `make loadsample`
working against a dev database seeded by older code, and it is the reason that
would lapse if the boundary above were ever crossed.

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

**Meaning, not spelling.** One digest for:

- `Decimal("1.1")` and `Decimal("1.10")`; `Decimal("100")` and `Decimal("1E+2")`;
- `Decimal("0.00")` and `Decimal("-0.00")` — **load-bearing**: with the rejected
  `normalize()` implementation these encode as `0` and `-0`, so this is one of
  only two listed tests that fail a revert to it;
- `12:00+00:00` and `13:00+01:00` as aware datetimes — which also pins the
  branch order, since a `date`-first arm skips the UTC canonicalization.

**Type as well as meaning.** Separate digests for each value against a plain
string field holding the same text: `Decimal("1.10")` against `"11E-1"`, a
`uuid.UUID` against its own text, a `date` against its ISO text, a `date`
against a `TemporalValue` for that day, and an unknown `TemporalValue` against a
field set to `None`. Also a `Decimal` and an `int` of the same value.

**The tag words.** One test asserts `_encode_command_value`'s return for all
five branches directly. Nothing else in the file would notice a renamed or
misapplied tag word.

**Unequal values stay unequal.**

- `Decimal("1.1")` and `Decimal("1.11")`, so the change cannot pass by making
  every decimal hash alike;
- a pair differing beyond 28 significant digits — **load-bearing**: the other
  test that fails a revert to `normalize()`, and no shorter case catches it.

**Refusals and context.**

- `NaN`, `sNaN`, and `Infinity` raise `TypeError`, `sNaN` among them because it
  raises `InvalidOperation` on comparison and must reach the refusal before
  anything compares it;
- a naive `datetime` raises `TypeError`;
- the digest is unchanged inside `localcontext(prec=5)` — also fails a revert to
  `normalize()`, and the only test that covers the thread-local hazard.

`test_a_record_from_another_fingerprint_version_replays_unchecked` is unchanged
and still covers the version branch. `test_a_datetime_and_its_date_differ` keeps
its assertion and loses its docstring's false claim.

The gate is the full `make check`.
