# Temporal qualifiers implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a temporal value carry `?` (uncertain), `~` (approximate), or `%` (both) after its atom, in Python and in PostgreSQL, without moving the bounds the atom already states.

**Architecture:** The qualifier is one trailing symbol on an atom. The parser splits it off before every family check and every regex match, so a qualified token refuses exactly the way its unqualified twin does. The parsed value carries a `TemporalQualifier | None` beside `precision`. PostgreSQL gains two private helpers that split the symbol and five public projections built on them; one migration replaces four function bodies and adds three persisted generated columns to each of the two models that already carry temporal projections.

**Tech Stack:** Python 3.14, Django 6, PostgreSQL 18, plpgsql, pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-issue-656-temporal-qualifiers-design.md`

## Global Constraints

- **Drive everything through `make`.** No raw `uv run`, `pytest`, or `pnpm`. Focused runs use `make test ARGS="…"`.
- **`make check-fast` while iterating; the full `make check` is the gate** before declaring done.
- **Never write to a `GeneratedField`.** The new qualifier columns are database-computed.
- **Every new SQL function carries `SET search_path = pg_catalog, public`.** Migration 0034 added it because `pg_dump` opens a dump with an empty search path; a function that omits it makes the schema unrestorable.
- **Every regex in `timetracker/temporal.py` carries `re.ASCII`.** Without it the parser accepts Arabic-Indic and full-width digits, which `tests/test_temporal_domain.py` feeds it.
- **Name variables with complete words** — `qualifier` not `qual`, `element` not `el`.
- **`make vale` grades prose in docs and code comments.** Do not write "fold", "tombstone", "archive", "delete", or "heal" in a comment or docstring.
- **Migration reversibility is mandatory** even though no deployment reverses. Six test modules drive `MigrationExecutor.migrate()` down past this node; an irreversible operation turns a green run into 37 failures.
- **The qualifier never widens bounds.** `1984~` has the same `lower_bound`, `upper_bound`, and `precision` as `1984`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `timetracker/temporal.py` | The `TemporalQualifier` enum, the symbol split, the refusal rules, the parsed field, the part accessors, three `Func` wrappers, two `Q` helpers | 1, 2, 4, 5 |
| `games/migrations/0038_temporal_qualifiers.py` | Two new private plpgsql helpers, three new public projections, four replaced bodies, six `AddField` operations | 3, 4 |
| `games/models.py` | Three generated columns on `Game.original_release_date`, three on `Release.release_date` | 4 |
| `common/criteria.py` | The new wrappers join `_TEMPORAL_PROJECTION_EXPRESSIONS` so the filter picker keeps ignoring them | 4 |
| `tests/test_temporal.py` | Grammar: accepted values, the refusal table, the part accessors | 1, 2 |
| `tests/test_temporal_domain.py` | SQL↔Python parity, the `search_path` guard, the domain's refusals | 3 |
| `tests/test_temporal_field.py` | Field round-trip through real generated columns, the `Q` helpers | 1, 5 |
| `tests/test_catalog_hierarchy.py` | The new columns stay out of fixtures and out of the filter picker | 4 |

---

### Task 1: The grammar accepts one trailing symbol

Every family check in `_reject_unsupported_family()` reads the token **without** its
symbol. Five of the six checks are written against the whole token today, and a
trailing symbol defeats three of them — most importantly the decade check, which
would refuse `198X~`, the accept case this issue exists to add.

**Files:**
- Modify: `timetracker/temporal.py:213-217` (regex constants), `:239-276` (`_reject_unsupported_family`), `:279-342` (`_parse_atom`, `_atomic_parts`), `:39-48` (`_TemporalParts`), `:50-107` (`TemporalEndpoint`), `:109-210` (`TemporalValue`)
- Test: `tests/test_temporal.py`, `tests/test_temporal_field.py:62-64`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `class TemporalQualifier(StrEnum)` with members `UNCERTAIN = "uncertain"`, `APPROXIMATE = "approximate"`, `BOTH = "both"`.
  - `TemporalValue.qualifier: TemporalQualifier | None` — a dataclass field, positioned after `precision`.
  - `TemporalValue.is_uncertain: bool`, `TemporalValue.is_approximate: bool` — properties.
  - `TemporalValue.from_day(value: date, *, qualifier: TemporalQualifier | None = None)`, and the same keyword on `from_month(year, month, *, qualifier=…)`, `from_year(year, *, qualifier=…)`, `from_decade(start_year, *, qualifier=…)`.
  - `TemporalEndpoint.qualifier: TemporalQualifier | None` — a property reading `self.value`.
  - `_split_qualifier(token: str) -> tuple[str, TemporalQualifier | None]` — module-private.
  - New parse error codes: `invalid_qualifier`, `unsupported_component_qualifier`, `unsupported_endpoint_qualifier`. The code `unsupported_qualifier` no longer exists.

- [ ] **Step 1: Write the failing acceptance test**

Append to `tests/test_temporal.py`, and add `TemporalQualifier` to the import block
at the top of the file:

```python
@pytest.mark.parametrize(
    ("canonical", "qualifier", "precision", "lower", "upper"),
    [
        (
            "1984-06-11~",
            TemporalQualifier.APPROXIMATE,
            TemporalPrecision.DAY,
            date(1984, 6, 11),
            date(1984, 6, 11),
        ),
        (
            "1984-06?",
            TemporalQualifier.UNCERTAIN,
            TemporalPrecision.MONTH,
            date(1984, 6, 1),
            date(1984, 6, 30),
        ),
        (
            "1984%",
            TemporalQualifier.BOTH,
            TemporalPrecision.YEAR,
            date(1984, 1, 1),
            date(1984, 12, 31),
        ),
        (
            "198X~",
            TemporalQualifier.APPROXIMATE,
            TemporalPrecision.DECADE,
            date(1980, 1, 1),
            date(1989, 12, 31),
        ),
        ("1984", None, TemporalPrecision.YEAR, date(1984, 1, 1), date(1984, 12, 31)),
    ],
)
def test_a_qualifier_says_how_sure_and_never_moves_the_bounds(
    canonical, qualifier, precision, lower, upper
):
    value = TemporalValue.parse(canonical)

    assert value.canonical == canonical
    assert value.qualifier is qualifier
    assert value.precision is precision
    assert value.lower_bound == lower
    assert value.upper_bound == upper
    assert value.kind is TemporalValueKind.ATOMIC
    assert value.is_uncertain is (
        qualifier in (TemporalQualifier.UNCERTAIN, TemporalQualifier.BOTH)
    )
    assert value.is_approximate is (
        qualifier in (TemporalQualifier.APPROXIMATE, TemporalQualifier.BOTH)
    )
    assert TemporalValue.parse(value.serialize()) == value


def test_a_range_qualifies_each_endpoint_on_its_own():
    value = TemporalValue.parse("1984/1986~")

    assert value.kind is TemporalValueKind.RANGE
    assert value.qualifier is None
    assert value.start is not None
    assert value.end is not None
    assert value.start.qualifier is None
    assert value.end.qualifier is TemporalQualifier.APPROXIMATE
    assert value.lower_bound == date(1984, 1, 1)
    assert value.upper_bound == date(1986, 12, 31)


def test_an_endpoint_without_a_value_answers_no_qualifier():
    assert TemporalEndpoint.unknown().qualifier is None
    assert TemporalEndpoint.open().qualifier is None
    assert TemporalValue.unknown().qualifier is None
    assert TemporalValue.unknown().is_approximate is False


def test_named_constructors_write_the_symbol_they_are_given():
    approximate = TemporalQualifier.APPROXIMATE
    uncertain = TemporalQualifier.UNCERTAIN
    both = TemporalQualifier.BOTH

    assert (
        TemporalValue.from_day(date(2024, 2, 29), qualifier=both).canonical
        == "2024-02-29%"
    )
    assert (
        TemporalValue.from_month(2024, 2, qualifier=uncertain).canonical == "2024-02?"
    )
    assert TemporalValue.from_year(2024, qualifier=approximate).canonical == "2024~"
    assert TemporalValue.from_decade(1990, qualifier=approximate).canonical == "199X~"
    assert TemporalValue.from_year(2024).canonical == "2024"

    start = TemporalEndpoint.known(TemporalValue.from_year(1984, qualifier=approximate))
    end = TemporalEndpoint.known(TemporalValue.from_year(1986, qualifier=approximate))
    assert TemporalValue.range(start=start, end=end).canonical == "1984~/1986~"

    with pytest.raises(TypeError):
        TemporalValue.from_year(2024, qualifier="approximate")
```

- [ ] **Step 2: Rewrite the refusal table in the same file**

In `tests/test_temporal.py`, find these three rows in the
`test_temporal_validation_fails_closed_with_precise_code` parametrize
(around `:270-272`):

```text
("2024?", "unsupported_qualifier"),
("2024-02~", "unsupported_qualifier"),
("2024-02-29%", "unsupported_qualifier"),
```

Replace them with:

```text
("?2024", "unsupported_component_qualifier"),
("2024-?02", "unsupported_component_qualifier"),
("~2024-02-29", "unsupported_component_qualifier"),
("2024?~", "invalid_qualifier"),
("2024~?", "invalid_qualifier"),
("2024??", "invalid_qualifier"),
("2024-02-29~~", "invalid_qualifier"),
("~/2025", "unsupported_endpoint_qualifier"),
("..?/2025", "unsupported_endpoint_qualifier"),
("2024/%", "unsupported_endpoint_qualifier"),
("?", "invalid_syntax"),
("~", "invalid_syntax"),
("%", "invalid_syntax"),
("2001-21~", "unsupported_season"),
("[2020~]", "unsupported_set"),
("2024-01-01T12:00~", "unsupported_timestamp"),
("19X4~", "unsupported_unspecified_component"),
("0000~", "unsupported_year"),
("10000~", "unsupported_year"),
("Y170000002~", "unsupported_year"),
("-1985~", "unsupported_year"),
```

The last eight rows are the point of the task: each is a qualified twin of a case
already in the table, and each must keep the code its twin gets.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_temporal.py -x -q"`
Expected: FAIL — `ImportError: cannot import name 'TemporalQualifier'`.

- [ ] **Step 4: Add the enum and the symbol split**

In `timetracker/temporal.py`, add the enum below `TemporalEndpointKind` (after
line 30):

```python
class TemporalQualifier(StrEnum):
    UNCERTAIN = "uncertain"
    APPROXIMATE = "approximate"
    BOTH = "both"
```

Below the regex constants at line 217, add the symbol table and the split:

```python
_QUALIFIER_BY_SYMBOL: dict[str, TemporalQualifier] = {
    "?": TemporalQualifier.UNCERTAIN,
    "~": TemporalQualifier.APPROXIMATE,
    "%": TemporalQualifier.BOTH,
}
_SYMBOL_BY_QUALIFIER: dict[TemporalQualifier, str] = {
    qualifier: symbol for symbol, qualifier in _QUALIFIER_BY_SYMBOL.items()
}


def _split_qualifier(token: str) -> tuple[str, TemporalQualifier | None]:
    """The token without its trailing symbol, and that symbol's meaning."""
    if not token:
        return token, None
    qualifier = _QUALIFIER_BY_SYMBOL.get(token[-1])
    if qualifier is None:
        return token, None
    return token[:-1], qualifier


def _qualifier_symbol(qualifier: TemporalQualifier | None) -> str:
    if qualifier is None:
        return ""
    if not isinstance(qualifier, TemporalQualifier):
        raise TypeError("qualifier must be a TemporalQualifier or None.")
    return _SYMBOL_BY_QUALIFIER[qualifier]
```

- [ ] **Step 5: Rewrite `_reject_unsupported_family()`**

Replace the whole function (`timetracker/temporal.py:239-276`) with:

```python
def _reject_unsupported_family(canonical: str) -> None:
    if canonical.startswith(("[", "{")) or canonical.endswith(("]", "}")):
        raise TemporalValueParseError(
            f"Temporal sets are not supported: {canonical!r}.",
            code="unsupported_set",
        )
    if "T" in canonical:
        raise TemporalValueParseError(
            f"Temporal timestamps are not supported: {canonical!r}.",
            code="unsupported_timestamp",
        )
    tokens = canonical.split("/")
    split_tokens = tuple(_split_qualifier(token) for token in tokens)
    unqualified = tuple(atom for atom, _ in split_tokens)
    for atom in unqualified:
        if atom and atom[-1] in _QUALIFIER_BY_SYMBOL:
            raise TemporalValueParseError(
                "A temporal position takes one qualifier symbol, and '%' is the "
                f"symbol for both: {canonical!r}.",
                code="invalid_qualifier",
            )
        if any(symbol in atom for symbol in _QUALIFIER_BY_SYMBOL):
            raise TemporalValueParseError(
                f"Component temporal qualifiers are not supported: {canonical!r}.",
                code="unsupported_component_qualifier",
            )
    if len(tokens) > 1 and any(
        qualifier is not None and atom in ("", "..") for atom, qualifier in split_tokens
    ):
        raise TemporalValueParseError(
            "An open or unknown temporal endpoint holds no date to qualify: "
            f"{canonical!r}.",
            code="unsupported_endpoint_qualifier",
        )
    bare = "/".join(unqualified)
    if re.fullmatch(r"[0-9]{4}-(?:2[1-4])", bare, re.ASCII):
        raise TemporalValueParseError(
            f"Temporal seasons are not supported: {canonical!r}.",
            code="unsupported_season",
        )
    if "X" in bare and any(
        "X" in atom and not _DECADE_RE.fullmatch(atom) for atom in unqualified
    ):
        raise TemporalValueParseError(
            f"Unspecified temporal components are not supported: {canonical!r}.",
            code="unsupported_unspecified_component",
        )
    if any(
        atom.startswith(("-", "Y"))
        or re.match(r"(?:0000|[0-9]{5,})(?:$|-)", atom, re.ASCII)
        for atom in unqualified
    ):
        raise TemporalValueParseError(
            f"Unsupported, extended, or negative temporal year: {canonical!r}.",
            code="unsupported_year",
        )
```

Order matters and is not arbitrary. The set and timestamp checks read the raw
string, so `[2020~]` is a set rather than a component qualifier. The
double-symbol check runs before the component check, so `2024?~` is
`invalid_qualifier` rather than `unsupported_component_qualifier`. The remaining
three read `bare`/`unqualified`, which is the whole point of the task.

- [ ] **Step 6: Carry the qualifier through the parse**

Add the field to `_TemporalParts` (`timetracker/temporal.py:39-48`), after
`precision`. It needs a default because `start` and `end` already have one:

```python
@dataclass(frozen=True, slots=True)
class _TemporalParts:
    canonical: str | None
    lower_bound: date | None
    upper_bound: date | None
    kind: TemporalValueKind
    precision: TemporalPrecision | None
    qualifier: TemporalQualifier | None = None
    start: TemporalEndpoint | None = None
    end: TemporalEndpoint | None = None
```

Replace `_parse_atom()` and `_atomic_parts()` with versions that split first and
match on the atom, while every message keeps naming the value the caller passed:

```python
def _parse_atom(canonical: str) -> _TemporalParts:
    atom, qualifier = _split_qualifier(canonical)

    if match := _DAY_RE.fullmatch(atom):
        year, month, day = (int(part) for part in match.groups())
        try:
            value = date(year, month, day)
        except ValueError as exc:
            raise TemporalValueParseError(
                f"Invalid calendar day: {canonical}.", code="invalid_date"
            ) from exc
        return _atomic_parts(canonical, value, value, TemporalPrecision.DAY, qualifier)

    if match := _MONTH_RE.fullmatch(atom):
        year, month = (int(part) for part in match.groups())
        try:
            last_day = monthrange(year, month)[1]
            lower = date(year, month, 1)
            upper = date(year, month, last_day)
        except (ValueError, OverflowError) as exc:
            raise TemporalValueParseError(
                f"Invalid calendar month: {canonical}.", code="invalid_date"
            ) from exc
        return _atomic_parts(
            canonical, lower, upper, TemporalPrecision.MONTH, qualifier
        )

    if match := _YEAR_RE.fullmatch(atom):
        year = int(match.group(1))
        try:
            lower = date(year, 1, 1)
            upper = date(year, 12, 31)
        except ValueError as exc:
            raise TemporalValueParseError(
                f"Invalid calendar year: {canonical}.", code="unsupported_year"
            ) from exc
        return _atomic_parts(canonical, lower, upper, TemporalPrecision.YEAR, qualifier)

    if match := _DECADE_RE.fullmatch(atom):
        first_year = int(match.group(1)) * 10
        try:
            lower = date(first_year, 1, 1)
            upper = date(first_year + 9, 12, 31)
        except ValueError as exc:
            raise TemporalValueParseError(
                f"Unsupported calendar decade: {canonical}.",
                code="unsupported_year",
            ) from exc
        return _atomic_parts(
            canonical, lower, upper, TemporalPrecision.DECADE, qualifier
        )

    raise TemporalValueParseError(
        f"Invalid temporal value syntax: {canonical!r}.", code="invalid_syntax"
    )


def _atomic_parts(
    canonical: str,
    lower: date,
    upper: date,
    precision: TemporalPrecision,
    qualifier: TemporalQualifier | None,
) -> _TemporalParts:
    return _TemporalParts(
        canonical=canonical,
        lower_bound=lower,
        upper_bound=upper,
        kind=TemporalValueKind.ATOMIC,
        precision=precision,
        qualifier=qualifier,
    )
```

- [ ] **Step 7: Add the field, the properties, and the constructor keywords**

In `TemporalValue`, declare the field after `precision` and set it in `__init__`:

```text
    kind: TemporalValueKind
    precision: TemporalPrecision | None
    qualifier: TemporalQualifier | None
    start: TemporalEndpoint | None
    end: TemporalEndpoint | None
```

```text
        object.__setattr__(self, "precision", parsed.precision)
        object.__setattr__(self, "qualifier", parsed.qualifier)
        object.__setattr__(self, "start", parsed.start)
```

Replace the four named constructors:

```text
    @classmethod
    def from_day(
        cls, value: date, *, qualifier: TemporalQualifier | None = None
    ) -> TemporalValue:
        if type(value) is not date:
            raise TypeError("A day temporal value requires a date.")
        return cls(f"{value.isoformat()}{_qualifier_symbol(qualifier)}")

    @classmethod
    def from_month(
        cls, year: int, month: int, *, qualifier: TemporalQualifier | None = None
    ) -> TemporalValue:
        _reject_boolean_integer(year, "year")
        _reject_boolean_integer(month, "month")
        return cls(f"{year:04d}-{month:02d}{_qualifier_symbol(qualifier)}")

    @classmethod
    def from_year(
        cls, year: int, *, qualifier: TemporalQualifier | None = None
    ) -> TemporalValue:
        _reject_boolean_integer(year, "year")
        return cls(f"{year:04d}{_qualifier_symbol(qualifier)}")

    @classmethod
    def from_decade(
        cls, start_year: int, *, qualifier: TemporalQualifier | None = None
    ) -> TemporalValue:
        _reject_boolean_integer(start_year, "start_year")
        if start_year % 10 or not 10 <= start_year <= 9990:
            raise ValueError(
                "A decade must start on a ten-year boundary from 0010 through 9990."
            )
        return cls(f"{start_year // 10:03d}X{_qualifier_symbol(qualifier)}")
```

Add the two properties beside `is_range`/`is_unknown`:

```text
    @property
    def is_uncertain(self) -> bool:
        return self.qualifier in (
            TemporalQualifier.UNCERTAIN,
            TemporalQualifier.BOTH,
        )

    @property
    def is_approximate(self) -> bool:
        return self.qualifier in (
            TemporalQualifier.APPROXIMATE,
            TemporalQualifier.BOTH,
        )
```

Add the delegating property to `TemporalEndpoint`, beside its `precision`
property:

```text
    @property
    def qualifier(self) -> TemporalQualifier | None:
        return None if self.value is None else self.value.qualifier
```

- [ ] **Step 8: Retarget the one Python-only assertion in the field tests**

`tests/test_temporal_field.py:62-64` asserts that `2024?` is refused. It is now
accepted. Change it to a value that is still refused, and to the code that
refusal now carries:

```text
    with pytest.raises(ValidationError) as caught:
        field.to_python("2024??")
    assert caught.value.code == "invalid_qualifier"
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_temporal.py tests/test_temporal_field.py -q"`
Expected: PASS, except `test_temporal_field_round_trips_generated_projections_and_query_helpers`, which inserts `"2024?"` into a probe table and expects the database to refuse it. The database has not been taught the grammar yet, so it still refuses and that test still passes. If it fails, stop — something else changed.

- [ ] **Step 10: Verify the parser is the only thing that moved**

Run: `make test ARGS="tests/test_temporal_domain.py -q"`
Expected: PASS. `test_temporal_domain_rejects_invalid_or_unsupported_raw_values` parametrizes `"2024?"` and asserts both halves refuse it; Python now accepts it, so this run FAILS on that one case. That failure is expected and Task 3 fixes it. Record it and continue — do not weaken the test here.

- [ ] **Step 11: Lint, format, and commit**

```bash
make format
make lint
make typecheck
git add timetracker/temporal.py tests/test_temporal.py tests/test_temporal_field.py
git commit -m "Read every family check against the token without its symbol"
```

---

### Task 2: A value can be read apart without inventing a part

`TemporalValue("1984-06").lower_bound` is 1984-06-01, so a caller that reads
`.day` off the bound gets 1 from a value that never knew a day. These accessors
answer `None` there instead.

**Files:**
- Modify: `timetracker/temporal.py` — `TemporalValue` (properties beside `has_known_day`), `TemporalEndpoint` (delegates)
- Test: `tests/test_temporal.py`

**Interfaces:**
- Consumes: `TemporalQualifier`, `TemporalValue.qualifier` from Task 1.
- Produces: `TemporalValue.year`, `.month`, `.day`, `.decade_start_year`, each `int | None`; the same four names on `TemporalEndpoint`, delegating.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_temporal.py`:

```python
@pytest.mark.parametrize(
    ("canonical", "year", "month", "day", "decade_start_year"),
    [
        ("1984-06-11", 1984, 6, 11, None),
        ("1984-06-11~", 1984, 6, 11, None),
        ("1984-06", 1984, 6, None, None),
        ("1984", 1984, None, None, None),
        ("198X", None, None, None, 1980),
        ("198X~", None, None, None, 1980),
        ("1984/1986", None, None, None, None),
        (None, None, None, None, None),
    ],
)
def test_a_value_reads_apart_into_the_parts_its_precision_knows(
    canonical, year, month, day, decade_start_year
):
    value = TemporalValue.parse(canonical)

    assert value.year == year
    assert value.month == month
    assert value.day == day
    assert value.decade_start_year == decade_start_year


def test_an_endpoint_delegates_the_parts_of_the_value_it_holds():
    value = TemporalValue.parse("1984-06?")
    known = TemporalEndpoint.known(value)

    assert (known.year, known.month, known.day) == (1984, 6, None)
    assert known.decade_start_year is None
    assert known.qualifier is TemporalQualifier.UNCERTAIN

    for endpoint in (TemporalEndpoint.unknown(), TemporalEndpoint.open()):
        assert endpoint.year is None
        assert endpoint.month is None
        assert endpoint.day is None
        assert endpoint.decade_start_year is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_temporal.py -k reads_apart -q"`
Expected: FAIL with `AttributeError: 'TemporalValue' object has no attribute 'year'`.

- [ ] **Step 3: Add the accessors**

In `TemporalValue`, after `has_known_day`:

```text
    @property
    def year(self) -> int | None:
        if self.lower_bound is None or not self.has_known_year:
            return None
        return self.lower_bound.year

    @property
    def month(self) -> int | None:
        if self.lower_bound is None or not self.has_known_month:
            return None
        return self.lower_bound.month

    @property
    def day(self) -> int | None:
        if self.lower_bound is None or not self.has_known_day:
            return None
        return self.lower_bound.day

    @property
    def decade_start_year(self) -> int | None:
        if self.kind is not TemporalValueKind.ATOMIC:
            return None
        if self.precision is not TemporalPrecision.DECADE:
            return None
        return None if self.lower_bound is None else self.lower_bound.year
```

`has_known_*` already tests `kind is ATOMIC`, so a range answers `None` to all
four. The `lower_bound is None` arm is what mypy needs, not a live branch.

In `TemporalEndpoint`, after its `qualifier` property:

```text
    @property
    def year(self) -> int | None:
        return None if self.value is None else self.value.year

    @property
    def month(self) -> int | None:
        return None if self.value is None else self.value.month

    @property
    def day(self) -> int | None:
        return None if self.value is None else self.value.day

    @property
    def decade_start_year(self) -> int | None:
        return None if self.value is None else self.value.decade_start_year
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_temporal.py -q"`
Expected: PASS.

- [ ] **Step 5: Lint, format, type-check, and commit**

```bash
make format
make lint
make typecheck
git add timetracker/temporal.py tests/test_temporal.py
git commit -m "Answer none where the precision knows no part"
```

---

### Task 3: PostgreSQL reads the same grammar

The database is the second half of the parser, and
`tests/test_temporal_domain.py` runs both halves over one table of values so
neither drifts. This task widens the SQL and grows that parity table.

**Files:**
- Create: `games/migrations/0038_temporal_qualifiers.py`
- Test: `tests/test_temporal_domain.py`

**Interfaces:**
- Consumes: the Python grammar from Task 1, which the parity test compares against.
- Produces, in the `public` schema:
  - `_timetracker_temporal_atom_unqualified(text) RETURNS text`
  - `_timetracker_temporal_atom_qualifier(text) RETURNS text` — `uncertain` / `approximate` / `both` / `NULL`, raising on a second symbol
  - `timetracker_temporal_qualifier(text) RETURNS text`
  - `timetracker_temporal_start_qualifier(text) RETURNS text`
  - `timetracker_temporal_end_qualifier(text) RETURNS text`
  - Replaced bodies for `_timetracker_temporal_atom_precision`, `_timetracker_temporal_atom_lower`, `_timetracker_temporal_atom_upper`, `timetracker_temporal_is_valid`
  - The migration node `("games", "0038_temporal_qualifiers")`, with a working `reverse_sql`.

- [ ] **Step 1: Write the failing tests**

Edit `tests/test_temporal_domain.py`.

First, split the function constants (replacing lines 14-31) so the reversal test
can still name what exists at node 0017:

```python
PUBLIC_FUNCTIONS_AT_0017 = {
    "timetracker_temporal_is_valid": ("boolean", "i"),
    "timetracker_temporal_lower": ("date", "i"),
    "timetracker_temporal_upper": ("date", "i"),
    "timetracker_temporal_kind": ("text", "i"),
    "timetracker_temporal_precision": ("text", "i"),
    "timetracker_temporal_start_kind": ("text", "i"),
    "timetracker_temporal_end_kind": ("text", "i"),
    "timetracker_temporal_start_precision": ("text", "i"),
    "timetracker_temporal_end_precision": ("text", "i"),
}
PRIVATE_FUNCTIONS_AT_0017 = {
    "_timetracker_temporal_atom_lower": ("date", "i"),
    "_timetracker_temporal_atom_upper": ("date", "i"),
    "_timetracker_temporal_atom_precision": ("text", "i"),
}
FUNCTIONS_AT_0017 = PUBLIC_FUNCTIONS_AT_0017 | PRIVATE_FUNCTIONS_AT_0017
PUBLIC_QUALIFIER_FUNCTIONS = {
    "timetracker_temporal_qualifier": ("text", "i"),
    "timetracker_temporal_start_qualifier": ("text", "i"),
    "timetracker_temporal_end_qualifier": ("text", "i"),
}
PRIVATE_QUALIFIER_FUNCTIONS = {
    "_timetracker_temporal_atom_qualifier": ("text", "i"),
    "_timetracker_temporal_atom_unqualified": ("text", "i"),
}
PUBLIC_FUNCTIONS = PUBLIC_FUNCTIONS_AT_0017 | PUBLIC_QUALIFIER_FUNCTIONS
ALL_FUNCTIONS = (
    FUNCTIONS_AT_0017 | PUBLIC_QUALIFIER_FUNCTIONS | PRIVATE_QUALIFIER_FUNCTIONS
)
SEARCH_PATH = "pg_catalog, public"
```

Second, add a reader for the three new projections beside `temporal_projection`
(after line 64):

```python
def temporal_qualifier_projection(value):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                timetracker_temporal_qualifier(%s),
                timetracker_temporal_start_qualifier(%s),
                timetracker_temporal_end_qualifier(%s)
            """,
            [value] * 3,
        )
        return cursor.fetchone()
```

Third, grow `python_projection` (lines 98-111) to the matching eleven values:

```python
def python_projection(canonical):
    value = TemporalValue.parse(canonical)
    start = value.start
    end = value.end
    return (
        value.lower_bound,
        value.upper_bound,
        value.kind.value,
        None if value.precision is None else value.precision.value,
        None if start is None else start.kind.value,
        None if end is None else end.kind.value,
        None if start is None or start.precision is None else start.precision.value,
        None if end is None or end.precision is None else end.precision.value,
        None if value.qualifier is None else value.qualifier.value,
        None if start is None or start.qualifier is None else start.qualifier.value,
        None if end is None or end.qualifier is None else end.qualifier.value,
    )
```

Fourth, replace the parity test (lines 263-285) so it compares all eleven and
carries qualified values:

```python
@pytest.mark.parametrize(
    "canonical",
    [
        None,
        "0001-01-01",
        "9999-12-31",
        "1900-02",
        "2000-02",
        "0010",
        "9999",
        "001X",
        "999X",
        "2020/2020-01",
        "2020-02/2020-02-01",
        "199X/2001-03-04",
        "../2001-03",
        "/2001-03",
        "1999/..",
        "1999/",
        "1984~",
        "1984-06?",
        "1984-06-11%",
        "198X~",
        "1984~/1986~",
        "1984/1986~",
        "1984?/..",
        "../1986%",
        "1984%/",
    ],
)
def test_temporal_sql_projection_matches_python_contract(canonical):
    assert temporal_projection(canonical) + temporal_qualifier_projection(
        canonical
    ) == python_projection(canonical)
```

Fifth, replace the `search_path` guard (lines 84-95 and 132-136) so a new
function cannot be forgotten. Delete `temporal_function_settings` and write:

```python
def temporal_function_settings():
    """Every temporal function the schema holds, found by name rather than list."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.proname, p.proconfig
            FROM pg_proc AS p
            WHERE p.pronamespace = current_schema()::regnamespace
              AND p.proname ~ '^_?timetracker_temporal_'
            """
        )
        return dict(cursor)


def test_temporal_functions_carry_the_search_path_their_bodies_need():
    """Every body calls its helpers by bare name, and a restore supplies none."""
    settings = temporal_function_settings()

    assert set(settings) == set(ALL_FUNCTIONS)
    assert settings == {name: [f"search_path={SEARCH_PATH}"] for name in ALL_FUNCTIONS}
```

Sixth, update the refusal list (lines 288-324): replace `"2024?"` with the
qualified refusals the database must also reject:

```text
        "2024??",
        "2024?~",
        "?2024",
        "2024-?02",
        "~/2025",
        "..?/2025",
        "2001-21~",
        "0000~",
        "10000~",
        "2004-XX~",
```

Seventh, point the reversal test (lines 359-371) at the 0017 constant:

```python
@pytest.mark.django_db(transaction=True)
def test_temporal_domain_migration_reverses_and_reapplies():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        MigrationExecutor(connection).migrate([BEFORE_TEMPORAL])
        assert temporal_domain_base_type() is None
        assert temporal_function_metadata(ALL_FUNCTIONS) == {}

        MigrationExecutor(connection).migrate([WITH_TEMPORAL])
        assert temporal_domain_base_type() == "varchar"
        assert temporal_function_metadata(FUNCTIONS_AT_0017) == FUNCTIONS_AT_0017
        assert temporal_function_metadata(PUBLIC_QUALIFIER_FUNCTIONS) == {}
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
```

The added `== {}` line is what proves the reverse actually drops the new
functions rather than leaving them behind.

Eighth, add a test that the new columns read the symbol of each position:

```python
@pytest.mark.parametrize(
    ("canonical", "expected"),
    [
        (None, (None, None, None)),
        ("1984", (None, None, None)),
        ("1984~", ("approximate", None, None)),
        ("1984-06?", ("uncertain", None, None)),
        ("1984-06-11%", ("both", None, None)),
        ("198X~", ("approximate", None, None)),
        ("1984/1986", (None, None, None)),
        ("1984~/1986~", (None, "approximate", "approximate")),
        ("1984/1986~", (None, None, "approximate")),
        ("1984?/..", (None, "uncertain", None)),
        ("../1986%", (None, None, "both")),
    ],
)
def test_temporal_sql_reads_the_qualifier_of_each_position(canonical, expected):
    assert temporal_qualifier_projection(canonical) == expected


@pytest.mark.parametrize("canonical", ["1984", "1984-06", "198X", "1984/1986"])
def test_a_qualifier_does_not_move_the_bounds_it_is_written_beside(canonical):
    for symbol in ("?", "~", "%"):
        qualified = canonical.replace("/", f"{symbol}/") + symbol
        assert temporal_projection(qualified)[:2] == temporal_projection(canonical)[:2]
        assert temporal_projection(qualified)[3] == temporal_projection(canonical)[3]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_temporal_domain.py -q"`
Expected: FAIL — `psycopg.errors.UndefinedFunction: function timetracker_temporal_qualifier(unknown) does not exist`.

- [ ] **Step 3: Write the migration**

Create `games/migrations/0038_temporal_qualifiers.py` with exactly this content:

```python
from django.db import migrations

# A qualifier says how sure the writer is of a date. It does not say which days
# the value covers, so `1984~` projects the bounds and the precision of `1984`.
#
# This widens the grammar. No stored string can carry a symbol -- the domain
# refused one until now -- so every value the schema holds still parses to the
# verdict it parsed to before. The domain constraint therefore stays and the
# persisted generated columns are not rebuilt, on the same reasoning 0034
# recorded for the same shape of change.
#
# The reverse below exists for the test suite, which drives the executor down
# past this node in six modules. No deployment reverses it.

ADD_QUALIFIER_SUPPORT = r"""
CREATE FUNCTION _timetracker_temporal_atom_unqualified(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF value IS NOT NULL AND right(value, 1) IN ('?', '~', '%') THEN
        RETURN left(value, -1);
    END IF;
    RETURN value;
END
$$;

CREATE FUNCTION _timetracker_temporal_atom_qualifier(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    symbol text;
    atom text;
BEGIN
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    symbol := right(value, 1);
    IF symbol IN ('?', '~', '%') THEN
        atom := left(value, -1);
    ELSE
        symbol := NULL;
        atom := value;
    END IF;
    IF atom ~ '[?~%]' THEN
        RAISE EXCEPTION 'invalid temporal qualifier: %', value;
    END IF;
    IF symbol IS NULL THEN
        RETURN NULL;
    ELSIF symbol = '?' THEN
        RETURN 'uncertain';
    ELSIF symbol = '~' THEN
        RETURN 'approximate';
    END IF;
    RETURN 'both';
END
$$;

CREATE OR REPLACE FUNCTION _timetracker_temporal_atom_precision(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    atom text;
    year_number integer;
    month_number integer;
    day_number integer;
BEGIN
    PERFORM _timetracker_temporal_atom_qualifier(value);
    atom := _timetracker_temporal_atom_unqualified(value);
    IF atom ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
        year_number := substring(atom FROM 1 FOR 4)::integer;
        month_number := substring(atom FROM 6 FOR 2)::integer;
        day_number := substring(atom FROM 9 FOR 2)::integer;
        PERFORM make_date(year_number, month_number, day_number);
        RETURN 'day';
    ELSIF atom ~ '^[0-9]{4}-[0-9]{2}$' THEN
        year_number := substring(atom FROM 1 FOR 4)::integer;
        month_number := substring(atom FROM 6 FOR 2)::integer;
        PERFORM make_date(year_number, month_number, 1);
        RETURN 'month';
    ELSIF atom ~ '^[0-9]{4}$' THEN
        year_number := atom::integer;
        PERFORM make_date(year_number, 1, 1);
        RETURN 'year';
    ELSIF atom ~ '^[0-9]{3}X$' THEN
        year_number := substring(atom FROM 1 FOR 3)::integer * 10;
        PERFORM make_date(year_number, 1, 1);
        PERFORM make_date(year_number + 9, 12, 31);
        RETURN 'decade';
    END IF;

    RAISE EXCEPTION 'invalid temporal atom: %', value;
END
$$;

CREATE OR REPLACE FUNCTION _timetracker_temporal_atom_lower(value text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    precision_name text;
    atom text;
    year_number integer;
    month_number integer;
BEGIN
    precision_name := _timetracker_temporal_atom_precision(value);
    atom := _timetracker_temporal_atom_unqualified(value);
    IF precision_name = 'day' THEN
        RETURN make_date(
            substring(atom FROM 1 FOR 4)::integer,
            substring(atom FROM 6 FOR 2)::integer,
            substring(atom FROM 9 FOR 2)::integer
        );
    ELSIF precision_name = 'month' THEN
        year_number := substring(atom FROM 1 FOR 4)::integer;
        month_number := substring(atom FROM 6 FOR 2)::integer;
        RETURN make_date(year_number, month_number, 1);
    ELSIF precision_name = 'year' THEN
        RETURN make_date(atom::integer, 1, 1);
    END IF;

    year_number := substring(atom FROM 1 FOR 3)::integer * 10;
    RETURN make_date(year_number, 1, 1);
END
$$;

CREATE OR REPLACE FUNCTION _timetracker_temporal_atom_upper(value text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    precision_name text;
    atom text;
    year_number integer;
    month_number integer;
BEGIN
    precision_name := _timetracker_temporal_atom_precision(value);
    atom := _timetracker_temporal_atom_unqualified(value);
    IF precision_name = 'day' THEN
        RETURN make_date(
            substring(atom FROM 1 FOR 4)::integer,
            substring(atom FROM 6 FOR 2)::integer,
            substring(atom FROM 9 FOR 2)::integer
        );
    ELSIF precision_name = 'month' THEN
        year_number := substring(atom FROM 1 FOR 4)::integer;
        month_number := substring(atom FROM 6 FOR 2)::integer;
        IF month_number = 12 THEN
            RETURN make_date(year_number, 12, 31);
        END IF;
        RETURN make_date(year_number, month_number + 1, 1) - 1;
    ELSIF precision_name = 'year' THEN
        RETURN make_date(atom::integer, 12, 31);
    END IF;

    year_number := substring(atom FROM 1 FOR 3)::integer * 10;
    RETURN make_date(year_number + 9, 12, 31);
END
$$;

CREATE FUNCTION timetracker_temporal_qualifier(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL OR strpos(value, '/') > 0 THEN
        RETURN NULL;
    END IF;
    RETURN _timetracker_temporal_atom_qualifier(value);
END
$$;

CREATE FUNCTION timetracker_temporal_start_qualifier(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    slash_position integer;
    endpoint_value text;
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    slash_position := strpos(value, '/');
    IF slash_position = 0 THEN
        RETURN NULL;
    END IF;
    endpoint_value := substring(value FROM 1 FOR slash_position - 1);
    IF endpoint_value IN ('', '..') THEN
        RETURN NULL;
    END IF;
    RETURN _timetracker_temporal_atom_qualifier(endpoint_value);
END
$$;

CREATE FUNCTION timetracker_temporal_end_qualifier(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    slash_position integer;
    endpoint_value text;
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    slash_position := strpos(value, '/');
    IF slash_position = 0 THEN
        RETURN NULL;
    END IF;
    endpoint_value := substring(value FROM slash_position + 1);
    IF endpoint_value IN ('', '..') THEN
        RETURN NULL;
    END IF;
    RETURN _timetracker_temporal_atom_qualifier(endpoint_value);
END
$$;

CREATE OR REPLACE FUNCTION timetracker_temporal_is_valid(value text)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
BEGIN
    PERFORM timetracker_temporal_lower(value);
    PERFORM timetracker_temporal_upper(value);
    PERFORM timetracker_temporal_kind(value);
    PERFORM timetracker_temporal_precision(value);
    PERFORM timetracker_temporal_start_kind(value);
    PERFORM timetracker_temporal_end_kind(value);
    PERFORM timetracker_temporal_start_precision(value);
    PERFORM timetracker_temporal_end_precision(value);
    PERFORM timetracker_temporal_qualifier(value);
    PERFORM timetracker_temporal_start_qualifier(value);
    PERFORM timetracker_temporal_end_qualifier(value);
    RETURN true;
EXCEPTION WHEN raise_exception OR data_exception THEN
    RETURN false;
END
$$;
""".strip()


# The four bodies below are the 0017 forms carrying the 0034 search_path and the
# 0034 exception handler. Restore them before dropping what they would call.
REMOVE_QUALIFIER_SUPPORT = r"""
CREATE OR REPLACE FUNCTION _timetracker_temporal_atom_precision(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    year_number integer;
    month_number integer;
    day_number integer;
BEGIN
    IF value ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
        year_number := substring(value FROM 1 FOR 4)::integer;
        month_number := substring(value FROM 6 FOR 2)::integer;
        day_number := substring(value FROM 9 FOR 2)::integer;
        PERFORM make_date(year_number, month_number, day_number);
        RETURN 'day';
    ELSIF value ~ '^[0-9]{4}-[0-9]{2}$' THEN
        year_number := substring(value FROM 1 FOR 4)::integer;
        month_number := substring(value FROM 6 FOR 2)::integer;
        PERFORM make_date(year_number, month_number, 1);
        RETURN 'month';
    ELSIF value ~ '^[0-9]{4}$' THEN
        year_number := value::integer;
        PERFORM make_date(year_number, 1, 1);
        RETURN 'year';
    ELSIF value ~ '^[0-9]{3}X$' THEN
        year_number := substring(value FROM 1 FOR 3)::integer * 10;
        PERFORM make_date(year_number, 1, 1);
        PERFORM make_date(year_number + 9, 12, 31);
        RETURN 'decade';
    END IF;

    RAISE EXCEPTION 'invalid temporal atom: %', value;
END
$$;

CREATE OR REPLACE FUNCTION _timetracker_temporal_atom_lower(value text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    precision_name text;
    year_number integer;
    month_number integer;
BEGIN
    precision_name := _timetracker_temporal_atom_precision(value);
    IF precision_name = 'day' THEN
        RETURN make_date(
            substring(value FROM 1 FOR 4)::integer,
            substring(value FROM 6 FOR 2)::integer,
            substring(value FROM 9 FOR 2)::integer
        );
    ELSIF precision_name = 'month' THEN
        year_number := substring(value FROM 1 FOR 4)::integer;
        month_number := substring(value FROM 6 FOR 2)::integer;
        RETURN make_date(year_number, month_number, 1);
    ELSIF precision_name = 'year' THEN
        RETURN make_date(value::integer, 1, 1);
    END IF;

    year_number := substring(value FROM 1 FOR 3)::integer * 10;
    RETURN make_date(year_number, 1, 1);
END
$$;

CREATE OR REPLACE FUNCTION _timetracker_temporal_atom_upper(value text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    precision_name text;
    year_number integer;
    month_number integer;
BEGIN
    precision_name := _timetracker_temporal_atom_precision(value);
    IF precision_name = 'day' THEN
        RETURN make_date(
            substring(value FROM 1 FOR 4)::integer,
            substring(value FROM 6 FOR 2)::integer,
            substring(value FROM 9 FOR 2)::integer
        );
    ELSIF precision_name = 'month' THEN
        year_number := substring(value FROM 1 FOR 4)::integer;
        month_number := substring(value FROM 6 FOR 2)::integer;
        IF month_number = 12 THEN
            RETURN make_date(year_number, 12, 31);
        END IF;
        RETURN make_date(year_number, month_number + 1, 1) - 1;
    ELSIF precision_name = 'year' THEN
        RETURN make_date(value::integer, 12, 31);
    END IF;

    year_number := substring(value FROM 1 FOR 3)::integer * 10;
    RETURN make_date(year_number + 9, 12, 31);
END
$$;

CREATE OR REPLACE FUNCTION timetracker_temporal_is_valid(value text)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
BEGIN
    PERFORM timetracker_temporal_lower(value);
    PERFORM timetracker_temporal_upper(value);
    PERFORM timetracker_temporal_kind(value);
    PERFORM timetracker_temporal_precision(value);
    PERFORM timetracker_temporal_start_kind(value);
    PERFORM timetracker_temporal_end_kind(value);
    PERFORM timetracker_temporal_start_precision(value);
    PERFORM timetracker_temporal_end_precision(value);
    RETURN true;
EXCEPTION WHEN raise_exception OR data_exception THEN
    RETURN false;
END
$$;

DROP FUNCTION timetracker_temporal_end_qualifier(text);
DROP FUNCTION timetracker_temporal_start_qualifier(text);
DROP FUNCTION timetracker_temporal_qualifier(text);
DROP FUNCTION _timetracker_temporal_atom_qualifier(text);
DROP FUNCTION _timetracker_temporal_atom_unqualified(text);
""".strip()


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0037_session_start_id_index"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ADD_QUALIFIER_SUPPORT,
            reverse_sql=REMOVE_QUALIFIER_SUPPORT,
        ),
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_temporal_domain.py -q"`
Expected: PASS, all cases, including `test_temporal_domain_migration_reverses_and_reapplies`.

- [ ] **Step 5: Verify the two halves agree and nothing else moved**

Run: `make test ARGS="tests/test_temporal.py tests/test_temporal_field.py tests/test_temporal_domain.py -q"`
Expected: PASS. `test_temporal_field_round_trips_generated_projections_and_query_helpers` inserts `"2024?"` expecting the database to refuse it — it no longer does. Change that literal to `"2024??"` (which the qualifier helper still raises on) and re-run.

- [ ] **Step 6: Verify a dump of this schema restores**

Run: `make verify-dump`
Expected: the restored copy migrates clean and is dropped. This is the check the `SET search_path` clauses exist for; a missing one passes `make check` and fails here.

If no production dump is available locally, skip this step and say so in the
commit body — but do not skip it silently.

- [ ] **Step 7: Lint, format, and commit**

```bash
make format
make lint
git add games/migrations/0038_temporal_qualifiers.py tests/test_temporal_domain.py tests/test_temporal_field.py
git commit -m "Split the symbol off before the database reads the atom"
```

---

### Task 4: Two models project the qualifier of each position

**Files:**
- Modify: `timetracker/temporal.py` (three `models.Func` wrappers, beside `TemporalEndPrecision`)
- Modify: `games/models.py` — `Game.original_release_date` block, `Release.release_date` block
- Modify: `games/migrations/0038_temporal_qualifiers.py` (append six `AddField` operations)
- Modify: `common/criteria.py:36-58`
- Test: `tests/test_catalog_hierarchy.py`

**Interfaces:**
- Consumes: the SQL functions from Task 3.
- Produces:
  - `TemporalQualifierValue`, `TemporalStartQualifier`, `TemporalEndQualifier` — `models.Func` subclasses in `timetracker/temporal.py`, each with `output_field = models.CharField(max_length=11, null=True)`.
  - Columns `original_release_date_qualifier`, `original_release_date_start_qualifier`, `original_release_date_end_qualifier` on `Game`; `release_date_qualifier`, `release_date_start_qualifier`, `release_date_end_qualifier` on `Release`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_catalog_hierarchy.py`:

```python
def test_qualifier_columns_project_beside_the_bounds_they_do_not_move(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Qualified Game",
        original_release_date=TemporalValue.parse("198X~"),
    )
    release = Release.objects.create(
        edition=Edition.objects.create(game=game),
        release_date=TemporalValue.parse("1984?/1986%"),
    )
    game.refresh_from_db()
    release.refresh_from_db()

    assert game.original_release_date_qualifier == "approximate"
    assert game.original_release_date_start_qualifier is None
    assert game.original_release_date_end_qualifier is None
    assert game.original_release_date_lower == date(1980, 1, 1)
    assert game.original_release_date_upper == date(1989, 12, 31)
    assert game.original_release_date_precision == "decade"

    assert release.release_date_qualifier is None
    assert release.release_date_start_qualifier == "uncertain"
    assert release.release_date_end_qualifier == "both"
```

The module already imports `date`, `Edition`, `Game`, `Release`, and
`TemporalValue`, and `owned_library` is a conftest fixture, so this test needs no
new import.

Then add `Release` to the parametrize on the comparable-column guard
(`tests/test_catalog_hierarchy.py:351`):

```text
@pytest.mark.parametrize("model", [Game, Session, Purchase, PlayEvent, Platform, Release])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_catalog_hierarchy.py -k qualifier_columns -q"`
Expected: FAIL with `AttributeError: 'Game' object has no attribute 'original_release_date_qualifier'`.

- [ ] **Step 3: Add the ORM wrappers**

In `timetracker/temporal.py`, after `TemporalEndPrecision`:

```python
class TemporalQualifierValue(models.Func):
    function = "timetracker_temporal_qualifier"
    output_field = models.CharField(max_length=11, null=True)


class TemporalStartQualifier(models.Func):
    function = "timetracker_temporal_start_qualifier"
    output_field = models.CharField(max_length=11, null=True)


class TemporalEndQualifier(models.Func):
    function = "timetracker_temporal_end_qualifier"
    output_field = models.CharField(max_length=11, null=True)
```

Eleven characters is the width of `approximate`, the longest word these
functions answer.

- [ ] **Step 4: Add the six generated columns**

In `games/models.py`, extend the import from `timetracker.temporal` with
`TemporalQualifierValue`, `TemporalStartQualifier`, and `TemporalEndQualifier`.

After the last `original_release_date_*` generated field on `Game`:

```text
    original_release_date_qualifier = models.GeneratedField(
        expression=TemporalQualifierValue("original_release_date"),
        output_field=models.CharField(max_length=11, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_start_qualifier = models.GeneratedField(
        expression=TemporalStartQualifier("original_release_date"),
        output_field=models.CharField(max_length=11, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_end_qualifier = models.GeneratedField(
        expression=TemporalEndQualifier("original_release_date"),
        output_field=models.CharField(max_length=11, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
```

After the last `release_date_*` generated field on `Release`:

```text
    release_date_qualifier = models.GeneratedField(
        expression=TemporalQualifierValue("release_date"),
        output_field=models.CharField(max_length=11, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_start_qualifier = models.GeneratedField(
        expression=TemporalStartQualifier("release_date"),
        output_field=models.CharField(max_length=11, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_end_qualifier = models.GeneratedField(
        expression=TemporalEndQualifier("release_date"),
        output_field=models.CharField(max_length=11, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
```

`serialize=False` is what keeps a generated column out of
`serializers.serialize`, which `tests/test_catalog_hierarchy.py:330` asserts.

- [ ] **Step 5: Generate the column operations and merge them into 0038**

Run: `make makemigrations ARGS="games --name temporal_qualifier_columns"`

This writes `games/migrations/0039_temporal_qualifier_columns.py` holding six
`AddField` operations. Move those six operations into the `operations` list of
`0038_temporal_qualifiers.py`, **after** the `RunSQL` — the columns cannot be
added before the functions they call exist — and remove the 0039 file.

The merged list reads:

```text
    operations = [
        migrations.RunSQL(
            sql=ADD_QUALIFIER_SUPPORT,
            reverse_sql=REMOVE_QUALIFIER_SUPPORT,
        ),
        migrations.AddField(
            model_name="game",
            name="original_release_date_qualifier",
            field=models.GeneratedField(
                db_persist=True,
                editable=False,
                expression=timetracker.temporal.TemporalQualifierValue(
                    "original_release_date"
                ),
                null=True,
                output_field=models.CharField(max_length=11, null=True),
            ),
        ),
        # ... the five remaining AddField operations, verbatim from 0039 ...
    ]
```

Keep whatever import header `makemigrations` wrote for
`timetracker.temporal`. Do not hand-edit the expressions; copy them.

- [ ] **Step 6: Verify no migration is left pending**

Run: `make makemigrations ARGS="--check --dry-run"`
Expected: exit 0, "No changes detected".

- [ ] **Step 7: Keep the new columns out of the filter picker**

In `common/criteria.py`, extend the `timetracker.temporal` import and the tuple:

```python
from timetracker.temporal import (
    TemporalEndKind,
    TemporalEndPrecision,
    TemporalEndQualifier,
    TemporalKind,
    TemporalLowerBound,
    TemporalPrecisionValue,
    TemporalQualifierValue,
    TemporalStartKind,
    TemporalStartPrecision,
    TemporalStartQualifier,
    TemporalUpperBound,
)
```

```python
_TEMPORAL_PROJECTION_EXPRESSIONS = (
    TemporalLowerBound,
    TemporalUpperBound,
    TemporalKind,
    TemporalPrecisionValue,
    TemporalStartKind,
    TemporalEndKind,
    TemporalStartPrecision,
    TemporalEndPrecision,
    TemporalQualifierValue,
    TemporalStartQualifier,
    TemporalEndQualifier,
)
```

A wrapper missing from this tuple becomes a comparable `CharField` that the
nested filter builder renders, which is a filter surface this issue excludes.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_catalog_hierarchy.py tests/test_criteria.py -q"`
Expected: PASS.

- [ ] **Step 9: Lint, format, type-check, and commit**

```bash
make format
make lint
make typecheck
git add timetracker/temporal.py games/models.py games/migrations/0038_temporal_qualifiers.py common/criteria.py tests/test_catalog_hierarchy.py
git commit -m "Project how sure a catalog date is, beside how precise it is"
```

---

### Task 5: A query can ask how sure a date is

**Files:**
- Modify: `timetracker/temporal.py` (after `temporal_exact_day_q`)
- Test: `tests/test_temporal_field.py`

**Interfaces:**
- Consumes: `TemporalQualifier` (Task 1), the qualifier columns (Task 4).
- Produces:
  - `temporal_is_approximate_q(field_name: str, *, endpoint: TemporalEndpointName | None = None) -> models.Q`
  - `temporal_is_uncertain_q(field_name: str, *, endpoint: TemporalEndpointName | None = None) -> models.Q`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_temporal_field.py`, and add `temporal_is_approximate_q`,
`temporal_is_uncertain_q` to the import block:

```python
@pytest.mark.parametrize(
    ("helper", "qualifiers"),
    [
        (temporal_is_approximate_q, ("approximate", "both")),
        (temporal_is_uncertain_q, ("uncertain", "both")),
    ],
)
def test_temporal_qualifier_query_helpers_carry_the_kind_guard(helper, qualifiers):
    assert helper("released") == models.Q(
        released_kind="atomic", released_qualifier__in=qualifiers
    )
    assert helper("released", endpoint="start") == models.Q(
        released_start_kind="known", released_start_qualifier__in=qualifiers
    )
    assert helper("released", endpoint="end") == models.Q(
        released_end_kind="known", released_end_qualifier__in=qualifiers
    )

    with pytest.raises(ValueError, match="start.*end"):
        helper("released", endpoint="middle")
    with pytest.raises(ValueError, match="field name"):
        helper("")
```

Then extend the round-trip probe. In
`test_temporal_field_round_trips_generated_projections_and_query_helpers`, add
three fields to the `Probe` model beside its other generated columns:

```text
        value_qualifier = models.GeneratedField(
            expression=TemporalQualifierValue("value"),
            output_field=models.CharField(max_length=11, null=True),
            db_persist=True,
        )
        value_start_qualifier = models.GeneratedField(
            expression=TemporalStartQualifier("value"),
            output_field=models.CharField(max_length=11, null=True),
            db_persist=True,
        )
        value_end_qualifier = models.GeneratedField(
            expression=TemporalEndQualifier("value"),
            output_field=models.CharField(max_length=11, null=True),
            db_persist=True,
        )
```

Add `TemporalQualifierValue`, `TemporalStartQualifier`, `TemporalEndQualifier`
to the module's import block, and append this test to the file:

```python
@pytest.mark.django_db(transaction=True)
@isolate_apps("games")
def test_temporal_qualifier_helpers_select_the_rows_they_name():
    class QualifierProbe(models.Model):
        value = TemporalValueField()
        value_kind = models.GeneratedField(
            expression=TemporalKind("value"),
            output_field=models.CharField(max_length=7),
            db_persist=True,
        )
        value_start_kind = models.GeneratedField(
            expression=TemporalStartKind("value"),
            output_field=models.CharField(max_length=7, null=True),
            db_persist=True,
        )
        value_end_kind = models.GeneratedField(
            expression=TemporalEndKind("value"),
            output_field=models.CharField(max_length=7, null=True),
            db_persist=True,
        )
        value_qualifier = models.GeneratedField(
            expression=TemporalQualifierValue("value"),
            output_field=models.CharField(max_length=11, null=True),
            db_persist=True,
        )
        value_start_qualifier = models.GeneratedField(
            expression=TemporalStartQualifier("value"),
            output_field=models.CharField(max_length=11, null=True),
            db_persist=True,
        )
        value_end_qualifier = models.GeneratedField(
            expression=TemporalEndQualifier("value"),
            output_field=models.CharField(max_length=11, null=True),
            db_persist=True,
        )

        class Meta:
            app_label = "games"
            db_table = "test_temporal_qualifier_probe"

    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(QualifierProbe)
    try:
        for canonical in ("1984", "1984~", "1984?", "1984%", "1984~/1986?", None):
            QualifierProbe.objects.create(value=TemporalValue.parse(canonical))

        def canonicals(condition):
            return sorted(
                row.value.canonical for row in QualifierProbe.objects.filter(condition)
            )

        assert canonicals(temporal_is_approximate_q("value")) == ["1984%", "1984~"]
        assert canonicals(temporal_is_uncertain_q("value")) == ["1984%", "1984?"]
        assert canonicals(temporal_is_approximate_q("value", endpoint="start")) == [
            "1984~/1986?"
        ]
        assert canonicals(temporal_is_uncertain_q("value", endpoint="end")) == [
            "1984~/1986?"
        ]
        assert canonicals(temporal_is_approximate_q("value", endpoint="end")) == []
    finally:
        with connection.schema_editor() as schema_editor:
            schema_editor.delete_model(QualifierProbe)
```

The last two assertions are the rule the spec states: the atom-level column is
`NULL` on every range, so "approximate anywhere" is three questions, not one.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_temporal_field.py -q"`
Expected: FAIL — `ImportError: cannot import name 'temporal_is_approximate_q'`.

- [ ] **Step 3: Add the helpers**

In `timetracker/temporal.py`, beside the precision tuples at lines 514-523:

```python
_APPROXIMATE_QUALIFIERS = (
    TemporalQualifier.APPROXIMATE.value,
    TemporalQualifier.BOTH.value,
)
_UNCERTAIN_QUALIFIERS = (
    TemporalQualifier.UNCERTAIN.value,
    TemporalQualifier.BOTH.value,
)
```

At the end of the module:

```python
def _temporal_qualifier_q(
    field_name: str,
    qualifiers: tuple[str, ...],
    *,
    endpoint: TemporalEndpointName | None,
) -> models.Q:
    if not isinstance(field_name, str) or not field_name:
        raise ValueError("A temporal field name is required.")
    if endpoint is None:
        return models.Q(
            **{
                f"{field_name}_kind": TemporalValueKind.ATOMIC.value,
                f"{field_name}_qualifier__in": qualifiers,
            }
        )
    if endpoint not in ("start", "end"):
        raise ValueError("endpoint must be 'start' or 'end'.")
    return models.Q(
        **{
            f"{field_name}_{endpoint}_kind": TemporalEndpointKind.KNOWN.value,
            f"{field_name}_{endpoint}_qualifier__in": qualifiers,
        }
    )


def temporal_is_approximate_q(
    field_name: str, *, endpoint: TemporalEndpointName | None = None
) -> models.Q:
    return _temporal_qualifier_q(field_name, _APPROXIMATE_QUALIFIERS, endpoint=endpoint)


def temporal_is_uncertain_q(
    field_name: str, *, endpoint: TemporalEndpointName | None = None
) -> models.Q:
    return _temporal_qualifier_q(field_name, _UNCERTAIN_QUALIFIERS, endpoint=endpoint)
```

The kind guard is what its three siblings carry, and it is what stops a negated
call from matching a range or an unknown value.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_temporal_field.py -q"`
Expected: PASS.

- [ ] **Step 5: Run the verification gate**

Run: `make check`
Expected: green — lint, format check, mypy, vale, ts-check, vitest, and the
entire pytest suite including `e2e/`.

Two failures are plausible here and are this task's to fix, not to route around:

- Any module that asserts the exact set of `Game` or `Release` columns (a
  migration-state test, a serializer test) now sees three more per model.
- `tests/test_iterator_guard.py` and the UUID identity audit are unaffected;
  if either fails, something in an earlier task went wrong.

- [ ] **Step 6: Commit**

```bash
git add timetracker/temporal.py tests/test_temporal_field.py
git commit -m "Ask how sure a stored date is, one position at a time"
```

---

## Out of scope, and stated so

The spec's boundary section names two facts this plan deliberately leaves true:

- `save_legacy_game_form()` in `games/catalog_compat.py:20-28` writes both
  temporal fields from the integer year columns on every legacy Game form save,
  through `TemporalValue.from_year()`, which states no symbol. A qualifier
  stored by #893 is erased by the next legacy save. Do not fix this here — it is
  #889's and #893's to retire, and a partial fix would leave two write paths
  disagreeing.
- `%` is reserved in a URL query string, so `198X%` cannot ride a `?filter=`
  parameter unencoded. Recorded in #601's cross-cutting section; the wave that
  writes the filter owns the encoding.

Also out: entry controls, presentation, criteria, filter dataclasses, quick
facets, TypeScript, and any migration of a legacy fact. `LibraryEvent.effective_time`
gains no column — it projects none today.

## Self-review notes

- **Spec coverage.** The grammar and the unqualified-token rule are Task 1; the
  refusal table is Task 1 Step 2; the Python value and constructors are Task 1;
  "reading a value apart" is Task 2; the database section — two private
  functions, three public, four replacements, the search-path rule, the
  no-rebuild argument, the real `reverse_sql` — is Task 3; the new columns, the
  `Func` wrappers, and `_TEMPORAL_PROJECTION_EXPRESSIONS` are Task 4; the query
  helpers are Task 5. The tests section is distributed across the task that owns
  each file. The boundary is restated above rather than implemented.
- **Names checked across tasks.** `TemporalQualifierValue` (not
  `TemporalQualifier`, which is the enum) is the atom wrapper, matching
  `TemporalPrecisionValue`. `_split_qualifier` is used in Tasks 1 and 3's
  reasoning only; `_qualifier_symbol` only by the constructors.
- **The one thing that must not be shortcut.** Task 3's `reverse_sql` is real
  SQL, not `RunSQL.noop`. A noop clears the `IrreversibleError` and leaves the
  widened functions behind, which lets
  `test_temporal_domain_migration_reverses_and_reapplies` pass for the wrong
  reason. The `PUBLIC_QUALIFIER_FUNCTIONS == {}` assertion added in Task 3
  Step 1 is what catches that.
