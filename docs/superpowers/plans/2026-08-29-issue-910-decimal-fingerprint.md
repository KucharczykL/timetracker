# Fingerprint canonicalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a command's idempotency fingerprint identify each value's type and meaning rather than the text it was written as.

**Architecture:** All three changes land in one private function,
`_encode_command_value` in `games/events/idempotency.py`, which `json.dumps`
calls for every value json cannot write itself. A `Decimal` gains a canonical
form read from `as_tuple()`; an aware `datetime` is canonicalised to UTC and a
naive one is refused; and every branch returns a `(word, text)` pair instead of
a bare string, so a value and a string holding that same text are no longer one
input. Nothing else in the module changes, and `fingerprint_command_input` is
untouched.

**Tech Stack:** Python 3.14, Django 6, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-29-issue-910-decimal-fingerprint-design.md`

## Global Constraints

- **Run everything through `make`.** Never raw `uv run` / `pytest` / `pnpm`.
  Focused runs: `make test ARGS="tests/test_event_idempotency.py -k decimal -x"`.
- **The gate is the full `make check`** before declaring done. `make check-fast`
  while iterating.
- **Python 3.14.** `python --version` must be 3.14.x; a `SyntaxError` in an
  `except A, B:` means the wrong interpreter, not broken code.
- **`FINGERPRINT_VERSION` stays `1`.** Do not bump it. The reasoning is in the
  spec's "The version is not bumped"; Task 3 rewrites the comment that states
  the condition.
- **Refused words** (`make vale` fails the build on these near an event, a
  projector, or the row it writes): `fold`, `tombstone`, `archive`, `delete`,
  `heal`. A projector *replays*; the row it leaves is a *projection*.
- **Name variables with complete words** — `value` not `v`, `digit` not `d`,
  `exponent` not `exp`.
- **Comment style in this module is `#:`** for inline notes above a statement,
  and a docstring for the function itself. Match the surrounding voice.
- **`DTZ001` is on** — ruff refuses `datetime(...)` with no `tzinfo`. Task 2
  needs one naive value on purpose and carries a line `# noqa: DTZ001` for it.
  Do not widen that into a per-file ignore: the block above the existing ignores
  in `pyproject.toml` says why they are file-specific, and a single line is
  tighter still.
- **Every existing test in `tests/test_event_idempotency.py` is relational**
  (two digests equal, two unequal, a length, a refusal). None should need
  editing. If a step makes an existing test fail, stop — that is a finding, not
  a fixture to update. The single exception is
  `test_a_datetime_and_its_date_differ`, whose docstring Task 2 corrects; its
  assertion stays.

---

### Task 1: The canonical form of a Decimal

**Files:**

- Modify: `games/events/idempotency.py` (add `_canonical_decimal`, call it from
  the `Decimal` branch of `_encode_command_value` at line 80-81)
- Test: `tests/test_event_idempotency.py` (new tests inserted after
  `test_an_unsupported_value_is_refused`, which ends around line 453 —
  `test_the_idempotency_migration_is_reversible` follows at 455, so this is an
  insertion into the canonicalization group, not an append to the file)

**Interfaces:**

- Consumes: nothing from earlier tasks.
- Produces: `_canonical_decimal(value: Decimal) -> str`, used by Task 3's
  `Decimal` branch. Returns a token: coefficient digits, `E`, exponent — e.g.
  `Decimal("1.10")` → `"11E-1"`, `Decimal("100")` → `"1E2"`, any zero → `"0"`.
  Raises `TypeError` for `NaN`, `sNaN`, and `Infinity`.

- [ ] **Step 1: Add the imports the new tests need**

In `tests/test_event_idempotency.py`, change the `decimal` import (line 4):

```python
from decimal import Decimal, localcontext
```

- [ ] **Step 2: Write the failing tests**

Insert into `tests/test_event_idempotency.py`, after
`test_an_unsupported_value_is_refused` and before
`test_the_idempotency_migration_is_reversible`:

```python
@pytest.mark.parametrize(
    ("written", "same_value"),
    [
        pytest.param("1.1", "1.10", id="trailing-zero"),
        pytest.param("100", "1E+2", id="exponent-form"),
        pytest.param("0.00", "-0.00", id="signed-zero"),
    ],
)
def test_a_decimal_is_the_number_not_the_text(written: str, same_value: str):
    """A form renders 12.50, the browser retries with 12.5, and one honest
    retry must not be answered as a conflict."""
    assert fingerprint_command_input(
        {"price": Decimal(written)}
    ) == fingerprint_command_input({"price": Decimal(same_value)})


def test_two_decimals_that_differ_keep_separate_digests():
    assert fingerprint_command_input(
        {"price": Decimal("1.1")}
    ) != fingerprint_command_input({"price": Decimal("1.11")})


def test_a_decimal_differing_past_the_context_precision_is_a_different_input():
    """normalize() rounds to the context's 28 digits, so both of these would
    reach one canonical form and the second command would be answered with the
    first one's range. No shorter pair catches that."""
    assert fingerprint_command_input(
        {"price": Decimal("1.000000000000000000000000000000001")}
    ) != fingerprint_command_input(
        {"price": Decimal("1.000000000000000000000000000000002")}
    )


def test_a_decimal_digest_ignores_the_active_context():
    """The canonical form is read from the value, so no thread-local setting
    in this process can move it."""
    price = Decimal("1.100000001")

    with localcontext() as context:
        context.prec = 5
        narrowed = fingerprint_command_input({"price": price})

    assert narrowed == fingerprint_command_input({"price": price})


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_a_non_finite_decimal_is_refused(value: str):
    """sNaN is here because it signals on comparison: the refusal has to be
    reached before anything compares the value."""
    with pytest.raises(TypeError):
        fingerprint_command_input({"price": Decimal(value)})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_event_idempotency.py -k decimal -x"`

Expected: `test_a_decimal_is_the_number_not_the_text[trailing-zero]` FAILS —
`1.1` and `1.10` produce different digests today. The context, precision, and
refusal tests fail too. `test_two_decimals_that_differ_keep_separate_digests`
passes already; that is fine, it guards the fix rather than driving it.

- [ ] **Step 4: Write the implementation**

In `games/events/idempotency.py`, add above `_encode_command_value`:

```python
def _canonical_decimal(value: Decimal) -> str:
    """The number, not the text it was written as: 1.1 and 1.10 are one value
    and must reach one digest.

    Read from as_tuple() rather than normalize(), which is an arithmetic
    operation: it rounds to the active context's precision, so two values
    differing past the 28th digit would share a canonical form and the second
    command would be answered with the first one's range. The context is also
    thread-local, so the same value would canonicalize two ways in two
    processes.
    """
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        #: The exponent is 'n', 'N' or 'F' for exactly NaN, sNaN and Infinity.
        #: Testing its type refuses them before anything compares the value,
        #: which sNaN signals on, and narrows the exponent for the checker.
        raise TypeError(
            f"{value} has no canonical form for an idempotency fingerprint. "
            "Convert it at the call site: a NaN is not equal to itself, so a "
            "digest that matched would claim an identity the values deny, and "
            "an infinity is no more a price than a NaN is."
        )
    while len(digits) > 1 and digits[-1] == 0:
        digits = digits[:-1]
        exponent += 1
    if digits == (0,):
        #: -0.00 == 0 and the sign survives as_tuple(), so without this the
        #: pair would be -0E0 against 0E0. CPython stores every zero with one
        #: digit, so the loop above never runs for one.
        return "0"
    prefix = "-" if sign else ""
    coefficient = "".join(str(digit) for digit in digits)
    return f"{prefix}{coefficient}E{exponent}"
```

Then change the `Decimal` branch of `_encode_command_value` from
`return str(value)` to:

```python
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_event_idempotency.py -x"`

Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 6: Type-check**

Run: `make typecheck`

Expected: clean. If mypy complains that `exponent` may be a `str`, the
`isinstance(exponent, int)` guard is missing or placed after the loop.

- [ ] **Step 7: Commit**

```bash
git add games/events/idempotency.py tests/test_event_idempotency.py
git commit -m "Read a decimal's canonical form from its digits"
```

---

### Task 2: The canonical form of a datetime

**Files:**

- Modify: `games/events/idempotency.py` (add `_canonical_datetime`, call it from
  the `datetime` branch, correct the branch-order comment at line 72-73)
- Test: `tests/test_event_idempotency.py` (new tests after Task 1's; correct the
  docstring of `test_a_datetime_and_its_date_differ`, around line 441)

**Interfaces:**

- Consumes: nothing from Task 1.
- Produces: `_canonical_datetime(value: datetime) -> str`, used by Task 3's
  `datetime` branch. Returns the ISO text of the instant in UTC. Raises
  `TypeError` for a naive datetime.

- [ ] **Step 1: Add the imports the new tests need**

In `tests/test_event_idempotency.py`, change the `datetime` import (line 3):

```python
from datetime import UTC, date, datetime, timedelta, timezone
```

- [ ] **Step 2: Write the failing tests**

Insert into `tests/test_event_idempotency.py`, after Task 1's tests:

```python
def test_one_instant_in_two_offsets_is_one_input():
    """USE_TZ is on and TIME_ZONE is Europe/Prague, so a local-aware value and
    a UTC one for the same moment are an ordinary pair to hold.

    This also pins the branch order: datetime subclasses date, and a date-first
    branch never applies the UTC canonical form.
    """
    utc_noon = datetime(2026, 8, 22, 12, tzinfo=UTC)
    prague_afternoon = datetime(2026, 8, 22, 14, tzinfo=timezone(timedelta(hours=2)))

    assert utc_noon == prague_afternoon
    assert fingerprint_command_input({"when": utc_noon}) == (
        fingerprint_command_input({"when": prague_afternoon})
    )


def test_a_naive_datetime_is_refused():
    """astimezone() on a naive value reads the machine's timezone, so its
    canonical form would differ between processes."""
    naive = datetime(2026, 8, 22, 12)  # noqa: DTZ001 -- the value under test

    with pytest.raises(TypeError):
        fingerprint_command_input({"when": naive})
```

The `noqa` is required: DTZ001 refuses a `datetime` with no `tzinfo`, and this
test's whole subject is one. Verified — without it, `make lint` fails.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_event_idempotency.py"`

(A `-k` expression with spaces does not survive `ARGS` quoting; run the file.)

Expected: `test_one_instant_in_two_offsets_is_one_input` and
`test_a_naive_datetime_is_refused` FAIL — the first because the two offsets
produce two ISO strings, the second because a naive datetime encodes today
without complaint. Everything else in the file, Task 1's tests included, passes.

- [ ] **Step 4: Write the implementation**

In `games/events/idempotency.py`, add above `_encode_command_value`:

```python
def _canonical_datetime(value: datetime) -> str:
    """One instant, one text: 12:00+00:00 and 13:00+01:00 are the same moment
    and must reach one digest.

    A naive value is refused rather than assumed. astimezone() on one reads the
    machine's timezone, so the same value would canonicalize as +01:00 on a
    Europe/Prague host and +00:00 on a UTC one -- the variance this function
    exists to prevent, arriving as a wrong answer rather than a refusal.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise TypeError(
            "A naive datetime has no canonical form for an idempotency "
            "fingerprint: reading the machine's timezone would vary the digest "
            "between processes. Make it aware at the call site."
        )
    return value.astimezone(UTC).isoformat()
```

Add `UTC` to the module's datetime import (line 15):

```python
from datetime import UTC, date, datetime
```

Change the `datetime` branch of `_encode_command_value` to:

```python
    if isinstance(value, datetime):
        return _canonical_datetime(value)
```

- [ ] **Step 5: Correct the branch-order comment**

The comment above that branch (line 72-73) currently reads:

```python
    #: datetime before date -- datetime subclasses date, so the reverse order
    #: would silently reduce every timestamp to its calendar day.
```

That is false: `value.isoformat()` binds to the instance, so a datetime returns
its full text through either branch. Replace it with what the order actually
protects:

```python
    #: datetime before date -- datetime subclasses date, and the date branch
    #: never applies the UTC canonical form, so the reverse order would give
    #: one instant two digests.
```

- [ ] **Step 6: Correct the docstring that repeats the same false claim**

`test_a_datetime_and_its_date_differ` (around line 441) says "a date-first
branch would collapse them". It would not — the test passes with the branches
reversed. Keep the assertion, replace the docstring:

```python
def test_a_datetime_and_its_date_differ():
    """The same calendar day is not the same input as a moment within it."""
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_event_idempotency.py -x"`

Expected: PASS, including `test_accepted_command_input_values[datetime]`, whose
parameter is already aware.

- [ ] **Step 8: Commit**

```bash
git add games/events/idempotency.py tests/test_event_idempotency.py
git commit -m "Canonicalise an instant to UTC, refuse a naive one"
```

---

### Task 3: The tag

**Files:**

- Modify: `games/events/idempotency.py` (add the `TaggedValue` alias, return a
  pair from all five branches of `_encode_command_value`, rewrite the
  `FINGERPRINT_VERSION` comment at line 36-38)
- Test: `tests/test_event_idempotency.py` (new tests after Task 2's; add
  `_encode_command_value` to the import block at line 21-28)

**Interfaces:**

- Consumes: `_canonical_decimal` (Task 1) and `_canonical_datetime` (Task 2).
- Produces: `_encode_command_value(value: Any) -> TaggedValue` where
  `type TaggedValue = tuple[str, str | None]`. The five words are `"datetime"`,
  `"date"`, `"uuid"`, `"decimal"`, `"temporal"`. This is the module's final
  shape; no later task changes it.

- [ ] **Step 1: Import the encoder into the tests**

In `tests/test_event_idempotency.py`, add `_encode_command_value` to the
`games.events.idempotency` import block (line 21-28), keeping the names sorted:

```python
from games.events.idempotency import (
    FINGERPRINT_VERSION,
    IdempotencyKeyMismatch,
    ReplayedAppend,
    UnchangedAppend,
    _encode_command_value,
    fingerprint_command_input,
    idempotent_append,
)
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_event_idempotency.py`, after Task 2's tests:

```python
def test_the_tag_words_are_the_wire_form():
    """Renaming one moves every digest that carries that type, which is a
    FINGERPRINT_VERSION bump. Nothing else in this file would notice."""
    identifier = uuid.uuid7()

    assert _encode_command_value(datetime(2026, 8, 22, 12, tzinfo=UTC)) == (
        "datetime",
        "2026-08-22T12:00:00+00:00",
    )
    assert _encode_command_value(date(2026, 8, 22)) == ("date", "2026-08-22")
    assert _encode_command_value(identifier) == ("uuid", str(identifier))
    assert _encode_command_value(Decimal("1.10")) == ("decimal", "11E-1")
    assert _encode_command_value(TemporalValue.from_year(2026)) == (
        "temporal",
        "2026",
    )
    assert _encode_command_value(TemporalValue.unknown()) == ("temporal", None)


def test_a_value_and_its_own_text_are_not_the_same_input():
    """Without the word, a key issued for one replays the other."""
    identifier = uuid.uuid7()
    day = date(2026, 8, 22)
    pairs = [
        (Decimal("1.10"), "11E-1"),
        (identifier, str(identifier)),
        (day, day.isoformat()),
    ]

    for value, text in pairs:
        assert fingerprint_command_input({"field": value}) != (
            fingerprint_command_input({"field": text})
        )


def test_a_date_and_a_temporal_value_for_that_day_differ():
    """Both canonicalize to 2026-08-22, so only the word keeps them apart."""
    day = date(2026, 8, 22)

    assert fingerprint_command_input({"when": day}) != fingerprint_command_input(
        {"when": TemporalValue.from_day(day)}
    )


def test_an_unknown_temporal_value_and_an_unset_field_differ():
    """An unknown time encodes as None, which json writes as the null an unset
    field also writes."""
    assert fingerprint_command_input(
        {"when": TemporalValue.unknown()}
    ) != fingerprint_command_input({"when": None})


def test_a_decimal_and_an_int_of_the_same_value_differ():
    """Decimal(1) == 1, and they are still two different inputs: the digest
    identifies a value's type as well as its meaning."""
    assert fingerprint_command_input(
        {"count": Decimal(1)}
    ) != fingerprint_command_input({"count": 1})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_event_idempotency.py"`

Expected: `test_the_tag_words_are_the_wire_form` FAILS (the encoder returns a
bare string), as do the value-versus-text, date-versus-temporal, and
unknown-versus-unset tests. `test_a_decimal_and_an_int_of_the_same_value_differ`
already passes — json writes a bare `int` as a number and the encoder's return
as a string — and stays as a guard.

- [ ] **Step 4: Write the implementation**

In `games/events/idempotency.py`, add the alias beside the two at line 33-34:

```python
type TaggedValue = tuple[str, str | None]  # ("decimal", "11E-1")
```

Replace `_encode_command_value` entirely:

```python
def _encode_command_value(value: Any) -> TaggedValue:
    """What the value is, then what it means.

    The word is what keeps a value and its own text apart: without it a uuid
    and the string of that uuid are one input, and a key issued for either
    replays the other. json writes the pair as an array, which a string can
    never be written as.

    The words are the wire form. Renaming one moves every digest that carries
    that type, so they are written out rather than read from the class -- a
    rename is then a visible canonicalizer change rather than a silent one.
    """
    #: datetime before date -- datetime subclasses date, and the date branch
    #: never applies the UTC canonical form, so the reverse order would give
    #: one instant two digests.
    if isinstance(value, datetime):
        return ("datetime", _canonical_datetime(value))
    if isinstance(value, date):
        return ("date", value.isoformat())
    if isinstance(value, uuid.UUID):
        return ("uuid", str(value))
    if isinstance(value, Decimal):
        return ("decimal", _canonical_decimal(value))
    if isinstance(value, TemporalValue):
        #: None for an unknown time, which json renders as null inside the pair.
        return ("temporal", value.canonical)
    raise TypeError(
        f"{type(value).__name__} has no canonical form for an idempotency "
        "fingerprint. Convert it at the call site: a repr() fallback would "
        "vary between processes and turn honest retries into mismatches."
    )
```

- [ ] **Step 5: Rewrite the FINGERPRINT_VERSION comment**

Lines 36-38 currently read "Bump it when `_encode_command_value` or the
canonical form changes", which this very change contradicts. Replace with the
condition that actually forces a bump, and the fact it turns on:

```python
#: Stamped on every record. Bump it when a change could give a different digest
#: for input a deployed record already holds: those records are no longer
#: comparable and replay unchecked, rather than rejecting every retry that
#: predates the change. No deployment has run 0024, so no record holds anything
#: and every canonicalizer change until the first one that does is free.
FINGERPRINT_VERSION = 1
```

- [ ] **Step 6: Run the whole module's tests**

Run: `make test ARGS="tests/test_event_idempotency.py tests/test_command_dispatch.py -x"`

Expected: PASS. Every digest in the suite has changed, and nothing should
notice: all assertions are relational. A failure here means a test asserts a
digest literal, which the spec claims none does — investigate rather than edit.

- [ ] **Step 7: Type-check**

Run: `make typecheck`

Expected: clean. If mypy reports `list[str]` against `tuple[str, str | None]`,
a branch is returning a list; if it reports an incompatible return, a branch is
returning a bare string.

- [ ] **Step 8: Commit**

```bash
git add games/events/idempotency.py tests/test_event_idempotency.py
git commit -m "Say what a value is, not only what it reads as"
```

---

### Task 4: The gate

**Files:** none — this task only runs checks and reports.

**Interfaces:**

- Consumes: Tasks 1-3 complete and committed.
- Produces: a green `make check`, or a list of what is not green.

- [ ] **Step 1: Run the backfill's own path**

The baseline backfill writes idempotency records through `idempotent_append`,
and `0033_playergame_baseline_backfill` runs it twice to prove it is idempotent.
Its `command_input` is all plain strings, so the encoder is never reached and
its digests should not move — confirm that rather than assume it:

Run: `make test ARGS="tests/test_playergame_backfill.py -x"`

Expected: PASS. A mismatch here means something in that path reaches
`_encode_command_value` after all, which the spec's version argument depends on
being false. Report it instead of working around it.

- [ ] **Step 2: Run the full gate**

Run: `make check`

Expected: green — lint, format check, mypy, vale, ts-check, vitest, and the
entire pytest suite including `e2e/`.

- [ ] **Step 3: Report**

State plainly whether `make check` is green. If any step is red, quote the
output rather than summarising it.

---

## Notes for the implementer

**Do not bump `FINGERPRINT_VERSION`.** It is the first thing this change looks
like it needs and the spec spends a section on why it is wrong. Task 3 rewrites
the comment so the code stops appearing to break its own rule.

**Do not "simplify" `_canonical_decimal` to `str(value.normalize())`.** It is
one line, it looks equivalent, and it is the defect this issue exists to avoid:
`normalize()` rounds to the active context, so two values differing past the
28th digit reach one canonical form and the second command is answered with the
first one's result. Three tests fail if you try it —
`test_a_decimal_differing_past_the_context_precision_is_a_different_input`,
`test_a_decimal_digest_ignores_the_active_context`, and the `signed-zero` case
of `test_a_decimal_is_the_number_not_the_text`.

**The known boundary, in case it looks like an omission:** json's own types stay
untagged, so a command field holding the sequence `("decimal", "11E-1")` still
collides with `Decimal("1.10")`, a `TextChoices` member is written as its bare
string, and `float("nan")` never reaches the encoder at all. No command has a
sequence field. Closing this means walking the payload instead of handing json a
`default`, which is a different change; the spec records it as the boundary.
