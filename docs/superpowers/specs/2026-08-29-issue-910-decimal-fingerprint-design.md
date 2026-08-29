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

Three rules, in the order the branch applies them.

```python
def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise TypeError(...)
    if value == 0:
        return "0"
    return format(value.normalize(), "f")
```

**`normalize()` removes the exponent difference**, which is the whole defect:
`Decimal("1.10").normalize()` is `Decimal("1.1")`.

**`"f"` keeps the result positional.** `normalize()` also rewrites a trailing
zero as an exponent, so `Decimal("100")` becomes `Decimal("1E+2")` while
`Decimal("100.0")` becomes the same thing — equal values agreeing on a form no
reader recognises as a price. `format(..., "f")` returns `100` for both.

**Zero is written `0`.** This is the rule an implementation reaches for last and
needs most. `Decimal("-0.00") == Decimal("0")` is `True`, and `normalize()`
keeps the sign, so the pair would encode as `-0` against `0` and hash
differently — the original defect surviving its own fix, for the one value most
likely to be typed two ways.

**A non-finite value is refused.** `Decimal("NaN") != Decimal("NaN")`, so a key
carrying one could never match itself and every retry would be a mismatch. There
is no canonical form for a value that is not equal to itself, and `Infinity` is
no more a price than `NaN` is. The raise joins the `TypeError` the same function
already raises for an unencodable type, in the same voice: it names the value
and says to convert it at the call site.

| Value               | Today   | Canonical |
| ------------------- | ------- | --------- |
| `Decimal("1.1")`    | `1.1`   | `1.1`     |
| `Decimal("1.10")`   | `1.10`  | `1.1`     |
| `Decimal("100")`    | `100`   | `100`     |
| `Decimal("1E+2")`   | `1E+2`  | `100`     |
| `Decimal("-1.50")`  | `-1.50` | `-1.5`    |
| `Decimal("0.00")`   | `0.00`  | `0`       |
| `Decimal("-0.00")`  | `-0.00` | `0`       |
| `Decimal("NaN")`    | `NaN`   | refused   |
| `Decimal("-Infinity")` | `-Infinity` | refused |

## The version is not bumped

`FINGERPRINT_VERSION` stays `1`. The constant exists so that a canonicalizer
change cannot turn every record written before it into a mismatch: a record
stamped with another version replays unchecked rather than being compared. This
change needs none of that, for two independent reasons.

**No digest that exists changes.** Only the `Decimal` branch is edited, so a
recorded fingerprint moves only if the command behind it carried a `Decimal`.
None can have. `canonical_command_input` fingerprints a command's dataclass
fields, the seven commands in `games/commands/playergame.py` declare UUIDs, a
status and a bool, and `games/backfill/playergame.py` passes dicts of strings.
The old canonicalizer and the new one agree on every input any record holds.

**No record exists outside a development database.** The deployed database is at
`main-e45911c`, whose tree ends at `games/migrations/0022_external_references` —
`0024_libraryidempotencyrecord` is not in it, so the table itself is not there.

A bump would therefore claim that records are incomparable when they are
identical, and would suspend the mismatch guard for every key predating it to
buy nothing.

The window in which this is true closes at #725/#726, the first commands to
carry a price. That is the timing this issue records: not that the bump is cheap
now, but that the canonicalizer must be right before a digest is ever taken over
a `Decimal`.

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

`Decimal("1.1")` and the string `"1.1"` still fingerprint identically, because
both reach `json.dumps` as the same text. The same is true of a `uuid.UUID` and
its string, and of a `date` and its ISO text: the canonicalizer has never tagged
a type. Reaching it requires a command with two fields of different types
holding the same text, one key, and a caller that swaps them — and the fix is a
different one, over every branch rather than this one. Recorded here so it is a
known hole rather than an unnoticed one; #910's boundary leaves it.

## Verification

New tests in `tests/test_event_idempotency.py`, beside the existing
canonicalization group:

- equal values share a digest, over `1.1`/`1.10`, `100`/`1E+2`, and
  `0.00`/`-0.00`;
- unequal values still differ, over `1.1` and `1.11`, so the change cannot pass
  by making every decimal hash alike;
- `NaN` and `Infinity` are refused with `TypeError`;
- a `Decimal` and an `int` of the same value keep separate digests, because json
  writes the encoder's return as a string and a bare `int` as a number.

`test_a_record_from_another_fingerprint_version_replays_unchecked` is unchanged
and still covers the version branch.

The gate is the full `make check`.
