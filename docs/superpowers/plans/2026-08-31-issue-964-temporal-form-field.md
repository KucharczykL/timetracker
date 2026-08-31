# Temporal form field implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A form can hold the dimensions of a temporal value — kind, year, month,
day, decade, approximate, uncertain — as independently assignable fields, build a
`TemporalValue` from them with no JavaScript, and re-render exactly what a person
typed when the combination is refused.

**Architecture:** Three layers, each testable alone. `TemporalDraft` and
`TemporalEndpointDraft` join `timetracker/temporal.py`, beside the value, because
they must know the grammar; they are mutable dataclasses of typed parts with
`from_value()` and `build()`. `TemporalDraftData` — a `TypedDict` of the raw posted
strings — is the wire form, with converters both ways, so an invalid submission
re-renders the person's own text rather than a normalized guess.
`common/components/temporal_field.py` renders that data as native controls, and
`TemporalWidget`/`TemporalFormField` in `games/forms.py` bind it to Django.

**Tech Stack:** Python 3.14, Django 6, pytest + pytest-django, mypy, ruff, the
`common.components` node layer. No TypeScript.

**Spec:** `docs/superpowers/specs/2026-08-30-issue-964-temporal-form-field-design.md`

## Global Constraints

- Python 3.14. Run everything through `make`; never `uv run`, `pytest` or
  `direnv exec .` directly. Focused runs:
  `make test ARGS="tests/test_temporal_draft.py -k decade"`.
  `PYTEST_WORKERS=0` when debugging, so `-x` stops the whole run.
- `make check` is the gate and must be green before the branch is done. Use
  `make check-fast` while iterating; it is not the gate.
- Comments are seven words or fewer. Docstrings may be longer, but their first
  line is a seven-word sentence.
- `make vale` lints docstrings and comments as well as docs. It refuses `archive`,
  `fold`, `tombstone`, `delete` and `heal` in their domain sense.
- Unabbreviated identifiers: `value` not `v`, `qualifier` not `qual`, `endpoint`
  not `ep`, `element` not `el`.
- Build UI with Python components from `common.components`, never HTML strings.
  Builders take htpy form: static attributes as kwargs, children via `[]`.
- Never write to a `GeneratedField`.
- Forms render through `FormFields`/`AddForm`, never `form.as_div()`. A composite
  widget styles itself and must not take the native-control classes.
- ruff formats at 88 columns with the default rule set. Every code block below is
  already in that form; keep the magic trailing commas.
- **`ruff format` rewrites Python inside Markdown fences.** Every ```python fence
  in this plan is a complete top-level `def` or `class` for that reason. Run
  `make format-check` after editing this document.
- The branch is `claude/issue-964-temporal-form-field`, with this plan committed to
  it. The spec is already on `main`.
- Commit messages: imperative mood, no `feat:`/`fix:` prefixes — match the log
  (`Say the presenter in fewer words`). End every commit message with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

## File structure

| File | Responsibility | Task |
| --- | --- | --- |
| `timetracker/temporal.py` | `TemporalEndpointDraft`, `TemporalDraft`, `TemporalDraftKind`, `TemporalDraftData` and the two converters | 1–3 |
| `tests/test_temporal_draft.py` | Every draft rule, round-trip and refusal, with no database | 1–3 |
| `common/components/temporal_field.py` | The native markup: kind select, two endpoint groups, two checkboxes | 4 |
| `common/components/__init__.py` | Re-export `TemporalField` | 4 |
| `games/forms.py` | `TemporalWidget`, `TemporalFormField`, the composite widget list | 5 |
| `tests/test_temporal_form_field.py` | Markup contract, binding, refusal re-render, no JavaScript | 4–5 |

The draft goes in `timetracker/temporal.py` because the spec places it there: it
must know the grammar, and every refusal it writes is a grammar refusal. The wire
`TypedDict` and its two converters go beside it rather than beside the markup, so
the key names and the input suffixes cannot drift across a module boundary — the
component imports the table it renders from.

## What this plan does not do

- No custom element and no TypeScript. #965 owns the browser. The control here is
  complete with scripting off, which is the contract #965 enhances.
- No presenter. #963 already shipped `present_temporal_value` and `TemporalText`.
- No catalog form change. `GameForm` keeps its two integer year fields; #969 moves
  Platform and the release date onto the Release editor.
- No filter and no query-string encoding. A later wave owns those.
- No browser end-to-end test. There is no page hosting this control until #969, so
  "works with JavaScript disabled" is proven server-side: the field binds from a
  plain dictionary, and the rendered tree declares no `Media`.

## Five decisions this plan makes

1. **`build()`, not `to_value()`.** The spec's prose says `to_value()`; issue #964's
   acceptance says `from_value(v).build() == v`. The acceptance criterion is the
   gate, so `build()` wins and Task 2 corrects the one sentence in the spec.

2. **`TemporalDraftKind` carries openness, so no input is invented.** The spec
   enumerates the posted inputs and names no control for an open endpoint, yet
   `1984/..` and `../1986` must be reachable. The kind select therefore offers
   `Date`, `Range`, `Since`, `Until`, `Unknown`. `Since` opens the end, `Until`
   opens the start, and an empty endpoint of a plain `Range` is an unknown
   endpoint. Every shape is reachable through `{name}-kind` alone.

3. **A decade beside a year is refused, not ignored.** The spec derives precision
   down an else-chain, which would silently discard a filled decade whenever a year
   is also filled. The acceptance says `build()` "refuses a draft whose dimensions
   disagree and states why", so this combination raises with a sentence.

4. **The draft holds numbers; the wire holds text.** "Changing one dimension is a
   field assignment" wants `int | None` on the draft. "An invalid submission
   re-renders the user's own input" wants the literal characters back. So
   `value_from_datadict()` returns `TemporalDraftData` (all strings), the field
   converts it to a draft inside `to_python()`, and a refused conversion leaves the
   original strings on the bound field for `render()` to re-emit.

5. **`save_legacy_game_form` stays untouched here.** The ordering constraint
   recorded on this issue while #963 was implemented says the writer downgrades any
   non-year value "once this issue lands entry controls". It does not: #964's
   boundary forbids a catalog form change, so nothing wires this widget onto a form
   a person can reach. #969 is the first consumer and is the change that must carry
   the fix. Task 6 moves the constraint there rather than leaving it on an issue
   that cannot act on it.

## The wire contract

One field name yields eleven inputs. The first endpoint uses the bare part names;
the second sits behind `end-`.

| Draft data key | Posted input name | Control |
| --- | --- | --- |
| `kind` | `{name}-kind` | select |
| `start_year` | `{name}-year` | number |
| `start_month` | `{name}-month` | number |
| `start_day` | `{name}-day` | number |
| `start_decade` | `{name}-decade` | number |
| `end_year` | `{name}-end-year` | number |
| `end_month` | `{name}-end-month` | number |
| `end_day` | `{name}-end-day` | number |
| `end_decade` | `{name}-end-decade` | number |
| `approximate` | `{name}-approximate` | checkbox |
| `uncertain` | `{name}-uncertain` | checkbox |

---

### Task 1: One endpoint's dimensions build one atomic value

**Files:**
- Modify: `timetracker/temporal.py` (append after `parse_temporal_value`, before
  `validate_temporal_value`)
- Create: `tests/test_temporal_draft.py`

**Interfaces:**
- Consumes: `TemporalValue`, `TemporalPrecision`, `TemporalQualifier`,
  `TemporalValueParseError` — all already in `timetracker/temporal.py`.
- Produces: `TemporalEndpointDraft(year, month, day, decade_start_year, qualifier)`,
  a mutable slotted dataclass with `is_empty: bool`,
  `from_value(TemporalValue | None) -> TemporalEndpointDraft` and
  `build() -> TemporalValue | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_temporal_draft.py`:

```python
"""What a temporal draft holds, and what it builds."""

import pytest

from timetracker.temporal import (
    TemporalEndpointDraft,
    TemporalQualifier,
    TemporalValue,
    TemporalValueParseError,
)


def test_an_empty_endpoint_builds_nothing() -> None:
    assert TemporalEndpointDraft().build() is None


def test_a_year_alone_builds_a_year() -> None:
    draft = TemporalEndpointDraft(year=1984)

    assert draft.build() == TemporalValue.from_year(1984)


def test_a_year_and_a_month_build_a_month() -> None:
    draft = TemporalEndpointDraft(year=1984, month=6)

    assert draft.build() == TemporalValue.from_month(1984, 6)


def test_every_part_builds_a_day() -> None:
    draft = TemporalEndpointDraft(year=1984, month=6, day=22)

    assert draft.build() == TemporalValue.parse("1984-06-22")


def test_a_decade_alone_builds_a_decade() -> None:
    draft = TemporalEndpointDraft(decade_start_year=1980)

    assert draft.build() == TemporalValue.from_decade(1980)


def test_a_qualifier_rides_on_the_built_value() -> None:
    draft = TemporalEndpointDraft(year=1984, qualifier=TemporalQualifier.BOTH)

    assert draft.build() == TemporalValue.parse("1984%")


def test_changing_one_dimension_is_an_assignment() -> None:
    draft = TemporalEndpointDraft(year=1984)
    draft.month = 6

    assert draft.build() == TemporalValue.from_month(1984, 6)


def test_a_day_without_a_month_is_refused() -> None:
    draft = TemporalEndpointDraft(year=1984, day=22)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "incomplete_day"


def test_a_month_without_a_year_is_refused() -> None:
    draft = TemporalEndpointDraft(month=6)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "incomplete_month"


def test_a_decade_beside_a_year_is_refused() -> None:
    """The else-chain would discard one of them silently."""
    draft = TemporalEndpointDraft(year=1984, decade_start_year=1980)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "decade_with_year"


def test_a_decade_off_the_boundary_is_refused() -> None:
    draft = TemporalEndpointDraft(decade_start_year=1984)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "invalid_decade"


def test_a_day_no_calendar_holds_is_refused() -> None:
    draft = TemporalEndpointDraft(year=1985, month=2, day=30)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "invalid_date"


def test_a_month_past_december_is_refused() -> None:
    draft = TemporalEndpointDraft(year=1984, month=13)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "invalid_date"


@pytest.mark.parametrize(
    "canonical",
    ["1984", "1984-06", "1984-06-22", "198X", "1984~", "1984-06%", "198X?"],
)
def test_an_atomic_value_round_trips_through_an_endpoint(canonical: str) -> None:
    value = TemporalValue.parse(canonical)

    assert TemporalEndpointDraft.from_value(value).build() == value


def test_nothing_reads_as_an_empty_endpoint() -> None:
    assert TemporalEndpointDraft.from_value(None).is_empty
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_temporal_draft.py"`
Expected: collection fails with
`ImportError: cannot import name 'TemporalEndpointDraft' from 'timetracker.temporal'`.

- [ ] **Step 3: Widen the imports at the top of `timetracker/temporal.py`**

Replace the two import lines:

```text
from dataclasses import dataclass
from typing import Literal
```

with:

```text
from dataclasses import dataclass, field
from typing import Final, Literal, TypedDict, assert_never
```

- [ ] **Step 4: Add the endpoint draft**

Append to `timetracker/temporal.py`, directly after `parse_temporal_value`:

```python
@dataclass(slots=True)
class TemporalEndpointDraft:
    """One position's dimensions, each independently assignable.

    Mutable on purpose. ``TemporalValue`` is frozen and parses from one
    canonical string, so changing a month there means string surgery.
    Here it is a field assignment, and ``build()`` reassembles the value.
    """

    year: int | None = None
    month: int | None = None
    day: int | None = None
    decade_start_year: int | None = None
    qualifier: TemporalQualifier | None = None

    @property
    def is_empty(self) -> bool:
        """No dimension states anything."""
        return (
            self.year is None
            and self.month is None
            and self.day is None
            and self.decade_start_year is None
        )

    @classmethod
    def from_value(cls, value: TemporalValue | None) -> TemporalEndpointDraft:
        """The dimensions an atomic value states."""
        if value is None:
            return cls()
        return cls(
            year=value.year,
            month=value.month,
            day=value.day,
            decade_start_year=value.decade_start_year,
            qualifier=value.qualifier,
        )

    def build(self) -> TemporalValue | None:
        """The value these dimensions state, or nothing.

        The precision is derived rather than stated: the deepest filled
        part decides it. A part with no shallower part to sit on is a
        disagreement, and a disagreement is refused with a sentence
        rather than completed with an invented part.
        """
        self._refuse_disagreement()
        if self.day is not None:
            assert self.year is not None and self.month is not None
            return _build_day(self.year, self.month, self.day, self.qualifier)
        if self.month is not None:
            assert self.year is not None
            return TemporalValue.from_month(
                self.year, self.month, qualifier=self.qualifier
            )
        if self.year is not None:
            return TemporalValue.from_year(self.year, qualifier=self.qualifier)
        if self.decade_start_year is not None:
            return _build_decade(self.decade_start_year, self.qualifier)
        return None

    def _refuse_disagreement(self) -> None:
        if self.day is not None and (self.year is None or self.month is None):
            raise TemporalValueParseError(
                "A day needs a year and a month beside it.",
                code="incomplete_day",
            )
        if self.month is not None and self.year is None:
            raise TemporalValueParseError(
                "A month needs a year beside it.", code="incomplete_month"
            )
        if self.decade_start_year is not None and not (
            self.year is None and self.month is None and self.day is None
        ):
            raise TemporalValueParseError(
                "State a decade or a date, not both.", code="decade_with_year"
            )
```

- [ ] **Step 5: Add the two refusal wrappers**

Append after the class. `TemporalValue.from_day` and `from_decade` raise a plain
`ValueError` for a bad calendar day and an off-boundary decade; a form needs a
`TemporalValueParseError` with a code and a sentence a person can read.

```python
def _build_day(
    year: int, month: int, day: int, qualifier: TemporalQualifier | None
) -> TemporalValue:
    """A refused calendar day carries a sentence."""
    try:
        return TemporalValue.from_day(date(year, month, day), qualifier=qualifier)
    except ValueError as error:
        raise TemporalValueParseError(
            f"{year}-{month}-{day} is not a day the calendar holds.",
            code="invalid_date",
        ) from error


def _build_decade(
    start_year: int, qualifier: TemporalQualifier | None
) -> TemporalValue:
    """A refused decade carries a sentence."""
    try:
        return TemporalValue.from_decade(start_year, qualifier=qualifier)
    except ValueError as error:
        raise TemporalValueParseError(
            "A decade starts on a ten-year boundary, such as 1980.",
            code="invalid_decade",
        ) from error
```

Note the month case needs no wrapper: `TemporalValue.from_month(1984, 13)` builds
`"1984-13"`, which the parser already refuses as `invalid_date`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_temporal_draft.py"`
Expected: 20 passed.

- [ ] **Step 7: Type-check and lint**

Run: `make typecheck && make lint && make format-check`
Expected: all clean.

- [ ] **Step 8: Commit**

```bash
git add timetracker/temporal.py tests/test_temporal_draft.py
git commit -m "Hold one position's dimensions and build a value from them

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The draft reads and rebuilds every shape

**Files:**
- Modify: `timetracker/temporal.py` (append after `_build_decade`)
- Modify: `tests/test_temporal_draft.py`
- Modify: `docs/superpowers/specs/2026-08-30-issue-964-temporal-form-field-design.md:17`

**Interfaces:**
- Consumes: `TemporalEndpointDraft` from Task 1.
- Produces: `TemporalDraftKind` (a `StrEnum` of `DATE`, `RANGE`, `SINCE`, `UNTIL`,
  `UNKNOWN`), `TEMPORAL_DRAFT_KIND_LABELS: Final[dict[TemporalDraftKind, str]]`,
  `temporal_qualifier(*, approximate: bool, uncertain: bool) -> TemporalQualifier |
  None`, and `TemporalDraft(kind, start, end)` with
  `from_value(TemporalValue | None) -> TemporalDraft`, `build() -> TemporalValue`,
  `is_approximate: bool` and `is_uncertain: bool`.

`build()` always answers a `TemporalValue`; an unknown draft answers
`TemporalValue.unknown()`. Task 5's field is what turns that into `None`, matching
the model field, which stores an unknown value as `NULL`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_temporal_draft.py`, and widen its import block to add
`TemporalDraft`, `TemporalDraftKind` and `temporal_qualifier`:

```python
class TemporalDraftShapes:
    """Namespaced so the plan's fence keeps the real indentation."""

    CANONICALS = (
        "1984",
        "1984-06",
        "1984-06-22",
        "198X",
        "1984~",
        "1984-06%",
        "1984/1986",
        "1984-06/1986",
        "1984~/1986~",
        "1984/..",
        "../1986",
        "1984/",
        "/1986",
    )
```

```python
@pytest.mark.parametrize("canonical", TemporalDraftShapes.CANONICALS)
def test_every_shape_round_trips(canonical: str) -> None:
    value = TemporalValue.parse(canonical)

    assert TemporalDraft.from_value(value).build() == value


def test_an_unknown_value_round_trips() -> None:
    value = TemporalValue.unknown()

    assert TemporalDraft.from_value(value).build() == value


def test_nothing_reads_as_an_unknown_draft() -> None:
    draft = TemporalDraft.from_value(None)

    assert draft.kind is TemporalDraftKind.UNKNOWN
    assert draft.build() == TemporalValue.unknown()


def test_an_open_end_reads_as_since() -> None:
    draft = TemporalDraft.from_value(TemporalValue.parse("1984/.."))

    assert draft.kind is TemporalDraftKind.SINCE
    assert draft.start.year == 1984


def test_an_open_start_reads_as_until() -> None:
    draft = TemporalDraft.from_value(TemporalValue.parse("../1986"))

    assert draft.kind is TemporalDraftKind.UNTIL
    assert draft.end.year == 1986


def test_an_unknown_endpoint_reads_as_a_plain_range() -> None:
    draft = TemporalDraft.from_value(TemporalValue.parse("1984/"))

    assert draft.kind is TemporalDraftKind.RANGE
    assert draft.end.is_empty


def test_since_needs_a_date_at_its_known_end() -> None:
    draft = TemporalDraft(kind=TemporalDraftKind.SINCE)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "invalid_range"


def test_a_range_with_no_known_endpoint_is_refused() -> None:
    draft = TemporalDraft(kind=TemporalDraftKind.RANGE)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "invalid_range"


def test_a_range_that_ends_before_it_starts_is_refused() -> None:
    draft = TemporalDraft(
        kind=TemporalDraftKind.RANGE,
        start=TemporalEndpointDraft(year=1986),
        end=TemporalEndpointDraft(year=1984),
    )

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "invalid_range"


def test_a_date_draft_with_no_part_builds_unknown() -> None:
    draft = TemporalDraft(kind=TemporalDraftKind.DATE)

    assert draft.build() == TemporalValue.unknown()


def test_an_asymmetric_range_survives_a_round_trip() -> None:
    """No control writes it, and nothing here loses it."""
    value = TemporalValue.parse("1984/1986~")

    assert TemporalDraft.from_value(value).build() == value


def test_either_endpoint_makes_the_whole_value_approximate() -> None:
    draft = TemporalDraft.from_value(TemporalValue.parse("1984/1986~"))

    assert draft.is_approximate
    assert not draft.is_uncertain


@pytest.mark.parametrize(
    ("approximate", "uncertain", "expected"),
    [
        (False, False, None),
        (True, False, TemporalQualifier.APPROXIMATE),
        (False, True, TemporalQualifier.UNCERTAIN),
        (True, True, TemporalQualifier.BOTH),
    ],
)
def test_two_checkboxes_name_one_qualifier(
    approximate: bool, uncertain: bool, expected: TemporalQualifier | None
) -> None:
    assert temporal_qualifier(approximate=approximate, uncertain=uncertain) is expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_temporal_draft.py"`
Expected: collection fails with
`ImportError: cannot import name 'TemporalDraft' from 'timetracker.temporal'`.

- [ ] **Step 3: Add the draft kind and the qualifier helper**

Append to `timetracker/temporal.py`:

```python
class TemporalDraftKind(StrEnum):
    """The shape a person picks. The precision is derived."""

    DATE = "date"
    RANGE = "range"
    SINCE = "since"
    UNTIL = "until"
    UNKNOWN = "unknown"


#: Ordered as the select offers them.
TEMPORAL_DRAFT_KIND_LABELS: Final[dict[TemporalDraftKind, str]] = {
    TemporalDraftKind.DATE: "Date",
    TemporalDraftKind.RANGE: "Range",
    TemporalDraftKind.SINCE: "Since",
    TemporalDraftKind.UNTIL: "Until",
    TemporalDraftKind.UNKNOWN: "Unknown",
}


def temporal_qualifier(
    *, approximate: bool, uncertain: bool
) -> TemporalQualifier | None:
    """The one qualifier two checkboxes name."""
    if approximate and uncertain:
        return TemporalQualifier.BOTH
    if approximate:
        return TemporalQualifier.APPROXIMATE
    if uncertain:
        return TemporalQualifier.UNCERTAIN
    return None


def _says_approximate(qualifier: TemporalQualifier | None) -> bool:
    return qualifier in (TemporalQualifier.APPROXIMATE, TemporalQualifier.BOTH)


def _says_uncertain(qualifier: TemporalQualifier | None) -> bool:
    return qualifier in (TemporalQualifier.UNCERTAIN, TemporalQualifier.BOTH)
```

- [ ] **Step 4: Add the draft**

Append to `timetracker/temporal.py`:

```python
@dataclass(slots=True)
class TemporalDraft:
    """A whole value's dimensions, held apart so a form can change one.

    ``start`` and ``end`` are positional. A ``DATE`` draft states its
    parts in ``start`` and leaves ``end`` empty; ``SINCE`` opens the end
    and ``UNTIL`` opens the start, so no separate openness control is
    needed and every shape is reachable through the kind alone.
    """

    kind: TemporalDraftKind = TemporalDraftKind.UNKNOWN
    start: TemporalEndpointDraft = field(default_factory=TemporalEndpointDraft)
    end: TemporalEndpointDraft = field(default_factory=TemporalEndpointDraft)

    @property
    def is_approximate(self) -> bool:
        """Either endpoint makes the whole value approximate."""
        return _says_approximate(self.start.qualifier) or _says_approximate(
            self.end.qualifier
        )

    @property
    def is_uncertain(self) -> bool:
        """Either endpoint makes the whole value uncertain."""
        return _says_uncertain(self.start.qualifier) or _says_uncertain(
            self.end.qualifier
        )

    @classmethod
    def from_value(cls, value: TemporalValue | None) -> TemporalDraft:
        """The dimensions a stored value states."""
        if value is None or value.is_unknown:
            return cls()
        if not value.is_range:
            return cls(
                kind=TemporalDraftKind.DATE,
                start=TemporalEndpointDraft.from_value(value),
            )
        start, end = value.start, value.end
        assert start is not None and end is not None
        return cls(
            kind=_range_draft_kind(start, end),
            start=TemporalEndpointDraft.from_value(start.value),
            end=TemporalEndpointDraft.from_value(end.value),
        )

    def build(self) -> TemporalValue:
        """The one value these dimensions state."""
        match self.kind:
            case TemporalDraftKind.UNKNOWN:
                return TemporalValue.unknown()
            case TemporalDraftKind.DATE:
                built = self.start.build()
                return TemporalValue.unknown() if built is None else built
            case TemporalDraftKind.SINCE:
                return TemporalValue.range(
                    start=_known_endpoint(self.start), end=TemporalEndpoint.open()
                )
            case TemporalDraftKind.UNTIL:
                return TemporalValue.range(
                    start=TemporalEndpoint.open(), end=_known_endpoint(self.end)
                )
            case TemporalDraftKind.RANGE:
                return TemporalValue.range(
                    start=_endpoint_or_unknown(self.start),
                    end=_endpoint_or_unknown(self.end),
                )
            case unhandled:
                assert_never(unhandled)


def _range_draft_kind(
    start: TemporalEndpoint, end: TemporalEndpoint
) -> TemporalDraftKind:
    if end.is_open:
        return TemporalDraftKind.SINCE
    if start.is_open:
        return TemporalDraftKind.UNTIL
    return TemporalDraftKind.RANGE


def _known_endpoint(draft: TemporalEndpointDraft) -> TemporalEndpoint:
    """An open range still needs a date at its other end."""
    built = draft.build()
    if built is None:
        raise TemporalValueParseError(
            "An open range needs a date at its other end.",
            code="invalid_range",
        )
    return TemporalEndpoint.known(built)


def _endpoint_or_unknown(draft: TemporalEndpointDraft) -> TemporalEndpoint:
    built = draft.build()
    if built is None:
        return TemporalEndpoint.unknown()
    return TemporalEndpoint.known(built)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_temporal_draft.py"`
Expected: 42 passed.

- [ ] **Step 6: Correct the one sentence in the spec**

In `docs/superpowers/specs/2026-08-30-issue-964-temporal-form-field-design.md`,
replace:

> `TemporalDraft.from_value(value)` reads a stored value, and `to_value()` builds
> one. `to_value()` raises `TemporalValueParseError` on a combination the grammar
> refuses, and the field turns that into a field error with a sentence.

with:

> `TemporalDraft.from_value(value)` reads a stored value, and `build()` builds one.
> `build()` raises `TemporalValueParseError` on a combination the grammar refuses,
> and the field turns that into a field error with a sentence.
>
> The kind is one of `Date`, `Range`, `Since`, `Until` and `Unknown`. `Since` opens
> the end and `Until` opens the start, so an open endpoint needs no control of its
> own and every storable shape is reachable.

- [ ] **Step 7: Type-check, lint and lint the prose**

Run: `make typecheck && make lint && make format-check && make vale`
Expected: all clean.

- [ ] **Step 8: Commit**

```bash
git add timetracker/temporal.py tests/test_temporal_draft.py docs/superpowers/specs/2026-08-30-issue-964-temporal-form-field-design.md
git commit -m "Read every stored shape into a draft and rebuild it

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Posted strings become a draft, and a draft becomes posted strings

**Files:**
- Modify: `timetracker/temporal.py` (append after `_endpoint_or_unknown`)
- Modify: `tests/test_temporal_draft.py`

**Interfaces:**
- Consumes: `TemporalDraft`, `TemporalEndpointDraft`, `temporal_qualifier`.
- Produces: `TemporalDraftData` (a `TypedDict` of eleven `str` keys),
  `TEMPORAL_INPUT_SUFFIXES: Final[dict[str, str]]`,
  `temporal_input_name(name: str, key: str) -> str`,
  `EMPTY_TEMPORAL_DRAFT_DATA: Final[TemporalDraftData]`,
  `temporal_draft_from_data(data: TemporalDraftData) -> TemporalDraft` and
  `temporal_draft_data(draft: TemporalDraft) -> TemporalDraftData`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_temporal_draft.py`, widening its import block to add
`EMPTY_TEMPORAL_DRAFT_DATA`, `TemporalDraftData`, `temporal_draft_data`,
`temporal_draft_from_data` and `temporal_input_name`:

```python
def posted(**overrides: str) -> TemporalDraftData:
    """Empty posted data with the named keys replaced."""
    return TemporalDraftData(**{**EMPTY_TEMPORAL_DRAFT_DATA, **overrides})


def test_an_empty_post_reads_as_an_unknown_draft() -> None:
    assert temporal_draft_from_data(posted()).build() == TemporalValue.unknown()


def test_posted_parts_read_as_numbers() -> None:
    data = posted(kind="date", start_year="1984", start_month="6")

    assert temporal_draft_from_data(data).build() == TemporalValue.from_month(1984, 6)


def test_surrounding_space_is_ignored() -> None:
    data = posted(kind="date", start_year=" 1984 ")

    assert temporal_draft_from_data(data).build() == TemporalValue.from_year(1984)


def test_a_part_that_is_not_a_number_is_refused() -> None:
    data = posted(kind="date", start_year="nineteen")

    with pytest.raises(TemporalValueParseError) as refusal:
        temporal_draft_from_data(data)

    assert refusal.value.code == "invalid_number"


def test_a_kind_the_form_does_not_offer_is_refused() -> None:
    data = posted(kind="season")

    with pytest.raises(TemporalValueParseError) as refusal:
        temporal_draft_from_data(data)

    assert refusal.value.code == "invalid_kind"


def test_a_checked_box_qualifies_both_endpoints() -> None:
    data = posted(
        kind="range",
        start_year="1984",
        end_year="1986",
        approximate="on",
        uncertain="on",
    )

    assert temporal_draft_from_data(data).build() == TemporalValue.parse("1984%/1986%")


def test_an_unchecked_box_qualifies_nothing() -> None:
    data = posted(kind="date", start_year="1984")

    assert temporal_draft_from_data(data).build() == TemporalValue.from_year(1984)


@pytest.mark.parametrize("canonical", TemporalDraftShapes.CANONICALS)
def test_a_stored_value_survives_the_wire(canonical: str) -> None:
    value = TemporalValue.parse(canonical)
    data = temporal_draft_data(TemporalDraft.from_value(value))

    assert temporal_draft_from_data(data).build() == value


def test_the_wire_names_every_input_after_the_field() -> None:
    assert temporal_input_name("release", "kind") == "release-kind"
    assert temporal_input_name("release", "start_year") == "release-year"
    assert temporal_input_name("release", "end_decade") == "release-end-decade"


def test_the_wire_carries_a_kind_for_an_unknown_draft() -> None:
    data = temporal_draft_data(TemporalDraft())

    assert data["kind"] == "unknown"
```

Note the shapes in `TemporalDraftShapes.CANONICALS` are all symmetric or
single-endpoint, so flattening the qualifier onto both endpoints loses nothing.
`1984/1986~` is deliberately absent: the control writes one pair of checkboxes,
so the wire cannot carry an asymmetric range. The draft still can, which is what
`test_an_asymmetric_range_survives_a_round_trip` in Task 2 proves.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_temporal_draft.py"`
Expected: collection fails with
`ImportError: cannot import name 'TemporalDraftData' from 'timetracker.temporal'`.

- [ ] **Step 3: Add the wire type and the name table**

Append to `timetracker/temporal.py`:

```python
class TemporalDraftData(TypedDict):
    """The raw strings one temporal control posts.

    Strings, not numbers, because a refused submission must re-render
    the characters a person typed rather than a normalized guess.
    """

    kind: str
    start_year: str
    start_month: str
    start_day: str
    start_decade: str
    end_year: str
    end_month: str
    end_day: str
    end_decade: str
    approximate: str
    uncertain: str


#: The first endpoint takes the bare part names.
TEMPORAL_INPUT_SUFFIXES: Final[dict[str, str]] = {
    "kind": "kind",
    "start_year": "year",
    "start_month": "month",
    "start_day": "day",
    "start_decade": "decade",
    "end_year": "end-year",
    "end_month": "end-month",
    "end_day": "end-day",
    "end_decade": "end-decade",
    "approximate": "approximate",
    "uncertain": "uncertain",
}

EMPTY_TEMPORAL_DRAFT_DATA: Final[TemporalDraftData] = TemporalDraftData(
    kind="",
    start_year="",
    start_month="",
    start_day="",
    start_decade="",
    end_year="",
    end_month="",
    end_day="",
    end_decade="",
    approximate="",
    uncertain="",
)


def temporal_input_name(name: str, key: str) -> str:
    """The posted input name one draft key travels under."""
    return f"{name}-{TEMPORAL_INPUT_SUFFIXES[key]}"
```

- [ ] **Step 4: Add the two converters**

Append to `timetracker/temporal.py`:

```python
def temporal_draft_from_data(data: TemporalDraftData) -> TemporalDraft:
    """The draft those posted strings state.

    The two checkboxes name one qualifier, which is written onto both
    endpoints. An asymmetric range stays storable and readable, and no
    control here reaches it.
    """
    qualifier = temporal_qualifier(
        approximate=bool(data["approximate"].strip()),
        uncertain=bool(data["uncertain"].strip()),
    )
    return TemporalDraft(
        kind=_draft_kind_from_text(data["kind"]),
        start=_endpoint_draft_from_text(
            year=data["start_year"],
            month=data["start_month"],
            day=data["start_day"],
            decade=data["start_decade"],
            qualifier=qualifier,
        ),
        end=_endpoint_draft_from_text(
            year=data["end_year"],
            month=data["end_month"],
            day=data["end_day"],
            decade=data["end_decade"],
            qualifier=qualifier,
        ),
    )


def temporal_draft_data(draft: TemporalDraft) -> TemporalDraftData:
    """The posted strings that state ``draft`` again."""
    return TemporalDraftData(
        kind=draft.kind.value,
        start_year=_part_text(draft.start.year),
        start_month=_part_text(draft.start.month),
        start_day=_part_text(draft.start.day),
        start_decade=_part_text(draft.start.decade_start_year),
        end_year=_part_text(draft.end.year),
        end_month=_part_text(draft.end.month),
        end_day=_part_text(draft.end.day),
        end_decade=_part_text(draft.end.decade_start_year),
        approximate="on" if draft.is_approximate else "",
        uncertain="on" if draft.is_uncertain else "",
    )


def _draft_kind_from_text(text: str) -> TemporalDraftKind:
    stripped = text.strip()
    if not stripped:
        return TemporalDraftKind.UNKNOWN
    try:
        return TemporalDraftKind(stripped)
    except ValueError as error:
        raise TemporalValueParseError(
            f"{stripped!r} is not a shape this form offers.", code="invalid_kind"
        ) from error


def _endpoint_draft_from_text(
    *,
    year: str,
    month: str,
    day: str,
    decade: str,
    qualifier: TemporalQualifier | None,
) -> TemporalEndpointDraft:
    return TemporalEndpointDraft(
        year=_part_number(year, "year"),
        month=_part_number(month, "month"),
        day=_part_number(day, "day"),
        decade_start_year=_part_number(decade, "decade"),
        qualifier=qualifier,
    )


def _part_number(text: str, part: str) -> int | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError as error:
        raise TemporalValueParseError(
            f"The {part} must be a whole number.", code="invalid_number"
        ) from error


def _part_text(part: int | None) -> str:
    return "" if part is None else str(part)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_temporal_draft.py"`
Expected: 65 passed.

- [ ] **Step 6: Type-check, lint and lint the prose**

Run: `make typecheck && make lint && make format-check && make vale`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add timetracker/temporal.py tests/test_temporal_draft.py
git commit -m "Carry a draft over the wire as the text a person typed

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The control renders as native markup

**Files:**
- Create: `common/components/temporal_field.py`
- Modify: `common/components/__init__.py`
- Create: `tests/test_temporal_form_field.py`

**Interfaces:**
- Consumes: `TemporalDraftData`, `TEMPORAL_DRAFT_KIND_LABELS`, `TemporalDraftKind`,
  `temporal_input_name` from Task 3.
- Produces: `TemporalField(*, name, data, label, input_id="", required=False,
  invalid=False) -> Node`, re-exported from `common.components`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_temporal_form_field.py`:

```python
"""What the temporal control renders, and what it binds."""

import pytest

from common.components import collect_media, render
from common.components.temporal_field import TemporalField
from timetracker.temporal import (
    EMPTY_TEMPORAL_DRAFT_DATA,
    TemporalDraft,
    TemporalDraftData,
    TemporalValue,
    temporal_draft_data,
)


def posted(**overrides: str) -> TemporalDraftData:
    return TemporalDraftData(**{**EMPTY_TEMPORAL_DRAFT_DATA, **overrides})


def markup(data: TemporalDraftData | None = None, **kwargs: object) -> str:
    node = TemporalField(
        name="release",
        data=data if data is not None else posted(kind="unknown"),
        label="Release date",
        input_id="id_release",
        **kwargs,
    )
    return str(render(node))


@pytest.mark.parametrize(
    "input_name",
    [
        "release-kind",
        "release-year",
        "release-month",
        "release-day",
        "release-decade",
        "release-end-year",
        "release-end-month",
        "release-end-day",
        "release-end-decade",
        "release-approximate",
        "release-uncertain",
    ],
)
def test_every_posted_input_is_rendered(input_name: str) -> None:
    assert f'name="{input_name}"' in markup()


def test_the_control_carries_no_script() -> None:
    """The whole point: this works with scripting off."""
    node = TemporalField(
        name="release",
        data=posted(kind="unknown"),
        label="Release date",
        input_id="id_release",
    )
    media = collect_media(node)

    assert media.js == ()
    assert media.js_external == ()


def test_the_kind_select_offers_every_shape() -> None:
    html = markup()

    for kind in ("date", "range", "since", "until", "unknown"):
        assert f'value="{kind}"' in html


def test_the_stored_kind_is_the_selected_one() -> None:
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("198X")))

    assert '<option value="date" selected' in markup(data)


def test_a_stored_part_is_the_input_value() -> None:
    data = temporal_draft_data(
        TemporalDraft.from_value(TemporalValue.parse("1984-06-22"))
    )
    html = markup(data)

    assert 'name="release-year" value="1984"' in html
    assert 'name="release-month" value="6"' in html
    assert 'name="release-day" value="22"' in html


def test_a_qualifier_checks_its_box() -> None:
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("1984%")))
    html = markup(data)

    assert 'name="release-approximate" value="on" checked' in html
    assert 'name="release-uncertain" value="on" checked' in html


def test_the_first_control_takes_the_label_target() -> None:
    assert 'id="id_release"' in markup()


def test_the_group_names_itself_after_the_row_label() -> None:
    assert 'aria-labelledby="id_release-label"' in markup()


def test_an_invalid_field_says_so() -> None:
    assert 'aria-invalid="true"' in markup(invalid=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_temporal_form_field.py"`
Expected: collection fails with
`ModuleNotFoundError: No module named 'common.components.temporal_field'`.

- [ ] **Step 3: Write the component**

Create `common/components/temporal_field.py`:

```python
"""TemporalField: native controls for a date at any precision.

A person states a shape, the parts they know, and whether the date is
approximate or uncertain. Nothing here needs a script: the controls are
a select, four number inputs per endpoint, and two checkboxes, and the
server rebuilds the value from what they post. That is the contract
issue #965's custom element enhances, and removing the script leaves
this working.

The precision is never picked from a menu. It is derived from which
parts a person filled, which is why there is no precision control here.
"""

from common.components.core import Node
from common.components.elements import Div, Label, Option, Select
from common.components.primitives import Checkbox, Input, field_label_id
from timetracker.temporal import (
    TEMPORAL_DRAFT_KIND_LABELS,
    TemporalDraftData,
    TemporalDraftKind,
    temporal_input_name,
)

_GROUP_CLASS = "flex flex-col gap-3"
_ROW_CLASS = "flex flex-row flex-wrap items-end gap-3"
_PART_LABEL_CLASS = "flex flex-col gap-1 text-type-label text-heading"
_LEGEND_CLASS = "text-type-label text-body"


def TemporalField(
    *,
    name: str,
    data: TemporalDraftData,
    label: str,
    input_id: str = "",
    required: bool = False,
    invalid: bool = False,
) -> Node:
    """The whole control: a shape, two endpoints, two qualifiers.

    ``input_id`` goes on the kind select, so the form row's
    ``<label for>`` focuses the first control. The container is
    additionally a named ``role="group"``, because the part inputs carry
    their own labels and the row label would otherwise name nothing.
    """
    label_id = field_label_id(input_id)
    return Div(
        role="group",
        aria_labelledby=label_id or None,
        aria_label=None if label_id else label,
        aria_required="true" if required else None,
        aria_invalid="true" if invalid else None,
        data_temporal_field="",
        class_=_GROUP_CLASS,
    )[
        _kind_select(name=name, kind=data["kind"], input_id=input_id),
        _endpoint_row(
            name=name,
            endpoint="start",
            legend="Start",
            year=data["start_year"],
            month=data["start_month"],
            day=data["start_day"],
            decade=data["start_decade"],
        ),
        _endpoint_row(
            name=name,
            endpoint="end",
            legend="End",
            year=data["end_year"],
            month=data["end_month"],
            day=data["end_day"],
            decade=data["end_decade"],
        ),
        _qualifier_row(
            name=name,
            approximate=data["approximate"],
            uncertain=data["uncertain"],
        ),
    ]


def _kind_select(*, name: str, kind: str, input_id: str) -> Node:
    # Imported here: games.forms imports this module.
    from games.forms import SELECT_CLASS

    selected = kind.strip() or TemporalDraftKind.UNKNOWN.value
    options = [
        Option(value=draft_kind.value, selected=draft_kind.value == selected)[text]
        for draft_kind, text in TEMPORAL_DRAFT_KIND_LABELS.items()
    ]
    return Select(
        name=temporal_input_name(name, "kind"),
        id_=input_id or None,
        class_=SELECT_CLASS,
    )[*options]


def _endpoint_row(
    *,
    name: str,
    endpoint: str,
    legend: str,
    year: str,
    month: str,
    day: str,
    decade: str,
) -> Node:
    return Div(class_=_ROW_CLASS, data_temporal_endpoint=endpoint)[
        Div(class_=_LEGEND_CLASS)[legend],
        _part_input(
            name=name,
            key=f"{endpoint}_year",
            text=year,
            label="Year",
            minimum=1,
            maximum=9999,
            step=1,
        ),
        _part_input(
            name=name,
            key=f"{endpoint}_month",
            text=month,
            label="Month",
            minimum=1,
            maximum=12,
            step=1,
        ),
        _part_input(
            name=name,
            key=f"{endpoint}_day",
            text=day,
            label="Day",
            minimum=1,
            maximum=31,
            step=1,
        ),
        _part_input(
            name=name,
            key=f"{endpoint}_decade",
            text=decade,
            label="Decade",
            minimum=10,
            maximum=9990,
            step=10,
        ),
    ]


def _part_input(
    *,
    name: str,
    key: str,
    text: str,
    label: str,
    minimum: int,
    maximum: int,
    step: int,
) -> Node:
    """A number input inside its own label. No id needed.

    The browser range is a courtesy, not the rule. The server refuses
    every disagreement itself, so a control the browser lets through is
    answered with a sentence rather than stored.
    """
    from games.forms import INPUT_CLASS

    return Label(class_=_PART_LABEL_CLASS)[
        label,
        Input(
            type="number",
            name=temporal_input_name(name, key),
            value=text,
            min=str(minimum),
            max=str(maximum),
            step=str(step),
            inputmode="numeric",
            class_=INPUT_CLASS,
        ),
    ]


def _qualifier_row(*, name: str, approximate: str, uncertain: str) -> Node:
    """One pair of boxes for the whole value."""
    return Div(class_=_ROW_CLASS)[
        Checkbox(
            name=temporal_input_name(name, "approximate"),
            label="Approximate",
            checked=bool(approximate.strip()),
            value="on",
        ),
        Checkbox(
            name=temporal_input_name(name, "uncertain"),
            label="Uncertain",
            checked=bool(uncertain.strip()),
            value="on",
        ),
    ]
```

- [ ] **Step 4: Re-export the component**

In `common/components/__init__.py`, add the import after the
`from common.components.settings_kit import ...` block (keeping the existing
alphabetical module order):

```text
from common.components.temporal_field import TemporalField
```

and add `"TemporalField"` to `__all__`, directly after `"Template"`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_temporal_form_field.py"`
Expected: 19 passed.

If an attribute-order assertion fails, read the rendered HTML from the failure
output and correct the assertion to the order the node layer emits — do not
reorder the component's kwargs to satisfy a test.

- [ ] **Step 6: Type-check, lint and lint the prose**

Run: `make typecheck && make lint && make format-check && make vale`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add common/components/temporal_field.py common/components/__init__.py tests/test_temporal_form_field.py
git commit -m "Render a date's dimensions as controls a browser needs no script for

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The Django field and widget bind it

**Files:**
- Modify: `games/forms.py` (widget and field after `DatePickerWidget`, around
  line 340; the composite widget list at `games/forms.py:120-129`)
- Modify: `tests/test_temporal_form_field.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: `TemporalWidget(*, label: str, attrs=None)` and
  `TemporalFormField(*, label: str = "Date", **kwargs)`, which cleans to
  `TemporalValue | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_temporal_form_field.py`, widening its import block to add
`from django import forms`, `from games.forms import TemporalFormField,
TemporalWidget, apply_primitive_widget_classes, INPUT_CLASS` and
`from timetracker.temporal import TemporalQualifier`:

```python
class ReleaseForm(forms.Form):
    """A plain form, so the field is tested and not a page."""

    released = TemporalFormField(label="Release date", required=False)
```

```python
def post(**overrides: str) -> dict[str, str]:
    """A POST body naming the form's one field."""
    return {f"released-{suffix}": text for suffix, text in overrides.items()}


def test_an_empty_post_cleans_to_nothing() -> None:
    form = ReleaseForm(data={"released-kind": "unknown"})

    assert form.is_valid()
    assert form.cleaned_data["released"] is None


def test_a_posted_month_cleans_to_a_month_value() -> None:
    form = ReleaseForm(data=post(kind="date", year="1984", month="6"))

    assert form.is_valid()
    assert form.cleaned_data["released"] == TemporalValue.from_month(1984, 6)


def test_a_posted_range_cleans_to_a_range_value() -> None:
    form = ReleaseForm(data=post(kind="range", year="1984", **{"end-year": "1986"}))

    assert form.is_valid()
    assert form.cleaned_data["released"] == TemporalValue.parse("1984/1986")


def test_a_posted_since_cleans_to_an_open_end() -> None:
    form = ReleaseForm(data=post(kind="since", year="1984"))

    assert form.is_valid()
    assert form.cleaned_data["released"] == TemporalValue.parse("1984/..")


def test_a_posted_qualifier_cleans_onto_the_value() -> None:
    form = ReleaseForm(data=post(kind="date", year="1984", approximate="on"))

    assert form.is_valid()
    assert form.cleaned_data["released"] == TemporalValue.from_year(
        1984, qualifier=TemporalQualifier.APPROXIMATE
    )


def test_a_disagreement_is_a_field_error_with_a_sentence() -> None:
    form = ReleaseForm(data=post(kind="date", month="6"))

    assert not form.is_valid()
    assert form.errors["released"] == ["A month needs a year beside it."]


def test_a_refused_submission_re_renders_what_was_typed() -> None:
    """Not a normalized guess. The characters a person typed."""
    form = ReleaseForm(data=post(kind="date", year="nineteen", month="6"))

    assert not form.is_valid()
    html = str(form["released"])

    assert 'name="released-year" value="nineteen"' in html
    assert 'name="released-month" value="6"' in html


def test_a_stored_value_renders_as_its_parts() -> None:
    form = ReleaseForm(initial={"released": TemporalValue.parse("198X")})
    html = str(form["released"])

    assert 'name="released-decade" value="1980"' in html
    assert '<option value="date" selected' in html


def test_an_omitted_control_is_reported_as_omitted() -> None:
    widget = TemporalWidget(label="Release date")

    assert widget.value_omitted_from_data({}, {}, "released")
    assert not widget.value_omitted_from_data({"released-kind": "date"}, {}, "released")


def test_an_untouched_field_has_not_changed() -> None:
    field = TemporalFormField(label="Release date", required=False)
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("1984")))

    assert not field.has_changed(TemporalValue.parse("1984"), data)


def test_a_changed_part_has_changed() -> None:
    field = TemporalFormField(label="Release date", required=False)
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("1984-06")))

    assert field.has_changed(TemporalValue.parse("1984"), data)


def test_the_composite_widget_keeps_its_own_classes() -> None:
    """A native-control class on a composite is styling at a distance."""
    form = ReleaseForm()
    apply_primitive_widget_classes(form.fields)

    assert INPUT_CLASS not in form.fields["released"].widget.attrs.get("class", "")


def test_a_required_field_refuses_an_unknown_value() -> None:
    class RequiredReleaseForm(forms.Form):
        released = TemporalFormField(label="Release date", required=True)

    form = RequiredReleaseForm(data={"released-kind": "unknown"})

    assert not form.is_valid()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_temporal_form_field.py"`
Expected: collection fails with
`ImportError: cannot import name 'TemporalFormField' from 'games.forms'`.

- [ ] **Step 3: Widen `games/forms.py`'s imports**

Add `TemporalField` to the `from common.components import (...)` block (after
`SearchSelectOption`), and add this import block after
`from games.models import (...)`:

```text
from timetracker.temporal import (
    EMPTY_TEMPORAL_DRAFT_DATA,
    TemporalDraft,
    TemporalDraftData,
    TemporalValue,
    TemporalValueParseError,
    parse_temporal_value,
    temporal_draft_data,
    temporal_draft_from_data,
    temporal_input_name,
)
```

- [ ] **Step 4: Add the widget**

Insert into `games/forms.py` directly after `DatePickerWidget`:

```python
class TemporalWidget(forms.Widget):
    """Renders a `TemporalField()` component in place of a native control.

    Follows `DatePickerWidget`: one field name yields several inputs, and
    `value_from_datadict` reads them all back. What it returns is the raw
    posted text, not a parsed draft, so a submission the grammar refuses
    re-renders the characters a person typed.
    """

    def __init__(self, *, label: str, attrs=None) -> None:
        super().__init__(attrs)
        self.label = label

    def _data(self, value) -> TemporalDraftData:
        if isinstance(value, dict):
            return cast(TemporalDraftData, value)
        if value in (None, ""):
            return temporal_draft_data(TemporalDraft())
        stored = parse_temporal_value(value)
        return temporal_draft_data(TemporalDraft.from_value(stored))

    def render(self, name, value, attrs=None, renderer=None):
        final_attrs = self.build_attrs(self.attrs, attrs)
        # render() returns a safe string (Django widgets must not be autoescaped).
        return render(
            TemporalField(
                name=name,
                data=self._data(value),
                label=self.label,
                input_id=str(final_attrs.get("id", "")),
                required=bool(final_attrs.get("required")),
                invalid=final_attrs.get("aria-invalid") == "true",
            )
        )

    def value_from_datadict(self, data, files, name) -> TemporalDraftData:
        return TemporalDraftData(
            kind=data.get(temporal_input_name(name, "kind"), ""),
            start_year=data.get(temporal_input_name(name, "start_year"), ""),
            start_month=data.get(temporal_input_name(name, "start_month"), ""),
            start_day=data.get(temporal_input_name(name, "start_day"), ""),
            start_decade=data.get(temporal_input_name(name, "start_decade"), ""),
            end_year=data.get(temporal_input_name(name, "end_year"), ""),
            end_month=data.get(temporal_input_name(name, "end_month"), ""),
            end_day=data.get(temporal_input_name(name, "end_day"), ""),
            end_decade=data.get(temporal_input_name(name, "end_decade"), ""),
            approximate=data.get(temporal_input_name(name, "approximate"), ""),
            uncertain=data.get(temporal_input_name(name, "uncertain"), ""),
        )

    def value_omitted_from_data(self, data, files, name) -> bool:
        """The real name is in no POST body. The kind is."""
        return temporal_input_name(name, "kind") not in data
```

- [ ] **Step 5: Add the field**

Insert directly after `TemporalWidget`:

```python
class TemporalFormField(forms.Field):
    """Cleans a temporal control's inputs to one `TemporalValue`.

    An unknown value cleans to ``None``, which is what the model field
    stores for one — so a form and a column agree on what nothing is.
    """

    def __init__(self, *, label: str = "Date", **kwargs) -> None:
        kwargs.setdefault("widget", TemporalWidget(label=label))
        kwargs.setdefault("required", False)
        super().__init__(label=label, **kwargs)

    def to_python(self, value) -> TemporalValue | None:
        try:
            built = temporal_draft_from_data(self._data(value)).build()
        except TemporalValueParseError as error:
            raise forms.ValidationError(str(error), code=error.code) from error
        return None if built.is_unknown else built

    def has_changed(self, initial, data) -> bool:
        try:
            submitted = self.to_python(data)
        except forms.ValidationError:
            return True
        return submitted != self._stored(initial)

    @staticmethod
    def _data(value) -> TemporalDraftData:
        if isinstance(value, dict):
            return cast(TemporalDraftData, value)
        if value in (None, ""):
            return EMPTY_TEMPORAL_DRAFT_DATA
        return temporal_draft_data(
            TemporalDraft.from_value(parse_temporal_value(value))
        )

    @staticmethod
    def _stored(initial) -> TemporalValue | None:
        if initial in (None, ""):
            return None
        stored = parse_temporal_value(initial)
        return None if stored.is_unknown else stored
```

- [ ] **Step 6: Keep the native-control classes off it**

In `games/forms.py:120-129`, add `TemporalWidget` to the composite widget tuple and
extend the comment above it. The tuple becomes:

```text
        if isinstance(
            widget,
            (
                SearchSelectWidget,
                DatePickerWidget,
                DateTimeFieldWidget,
                TimeZoneRowWidget,
                TemporalWidget,
            ),
        ):
            continue
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_temporal_form_field.py"`
Expected: 32 passed.

- [ ] **Step 8: Type-check, lint and lint the prose**

Run: `make typecheck && make lint && make format-check && make vale`
Expected: all clean.

- [ ] **Step 9: Commit**

```bash
git add games/forms.py tests/test_temporal_form_field.py
git commit -m "Bind a date's dimensions through one form field

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: The gate, and the writer's ordering constraint moves to #969

**Files:**
- Remove: `docs/superpowers/plans/2026-08-31-issue-964-temporal-form-field.md`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: nothing in code. A recorded verdict, and a green gate.

- [ ] **Step 1: Move the ordering constraint onto #969**

The comment on #964 says `save_legacy_game_form` downgrades any non-year value
"once this issue lands entry controls". #964 lands no control onto a form a person
can reach, so nothing downgrades yet. #969 is the change that wires the control onto
the catalog, and #969 is where the fix must land.

Post this comment on issue #969:

```bash
gh issue comment 969 --body 'Ordering constraint inherited from #964.

`games/catalog_compat.py:24`, `save_legacy_game_form`, writes the temporal columns from the legacy integer columns on every save:

```python
original_release_date=_year_value(game.original_year_released),
release_date=_year_value(game.year_released),
```

Today that is lossless: every stored value is year precision, and `GameForm` is the only writer. #964 shipped `TemporalFormField` and `TemporalWidget`, which can state a month, a decade or a range, but wired them onto no form — its boundary forbids a catalog form change. So this issue is the first one that can reach the loss, and the first that must answer it.

The moment the Release editor writes a temporal value, that line downgrades it to a bare year the next time anybody saves the Game form, and to `Unknown` where the legacy column is NULL. It is silent: no error, no validation message.

This issue already owns "moving Platform and the release date off the Game form onto the Release editor", which is the second of the two ways out:

1. `save_legacy_game_form` reads the temporal field from the form when the form states one, and falls back to `_year_value(...)` only for a form that does not.
2. The legacy integer columns stop being the source, and `_year_value` goes away with them.

Recorded on #964 first, while implementing #963 (PR #971), and moved here because #964 could not act on it.'
```

Then add a short note on #964 saying the constraint moved, so the two issues do not
disagree:

```bash
gh issue comment 964 --body 'The ordering constraint above moved to #969.

#964 adds no catalog form change, so nothing it ships can reach `save_legacy_game_form`. #969 is the first issue that wires the control onto a form a person can reach, and it already owns moving the release date off the Game form. Recorded there in full.'
```

- [ ] **Step 2: Run the full gate**

Remove this plan document first — the gate runs `ruff format --check` over the whole
repository, and a plan full of Python fences is a file it formats.

```bash
git rm docs/superpowers/plans/2026-08-31-issue-964-temporal-form-field.md
make check
```

Expected: green. Lint, format-check, mypy, vale, ts-check, check-icons,
check-migrations, vitest, and the whole pytest suite including `e2e/`. Use the
default parallel worker configuration, as the acceptance requires.

- [ ] **Step 3: Commit and open the pull request**

```bash
git add -A
git commit -m "Drop the implementation plan for the temporal form field

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push -u origin claude/issue-964-temporal-form-field
gh pr create --fill
```

The pull request body must say `Closes #964`.

---

## Self-review

**Spec coverage.**

| Spec requirement | Task |
| --- | --- |
| A mutable dataclass holding a kind and, per endpoint, year, month, day, decade start year, qualifier | 1, 2 |
| `from_value()` reads a stored value | 1, 2 |
| `build()` raises `TemporalValueParseError` on a refused combination | 1, 2 |
| The field turns that into a field error with a sentence | 5 |
| The precision is derived, never picked from a menu | 1 |
| The draft holds a qualifier per endpoint; the controls expose one pair and write both | 3 |
| An asymmetric range stays storable, readable, presentable, unreachable | 2, 3 |
| `TemporalFormField(forms.Field)` cleans to `TemporalValue \| None` | 5 |
| `TemporalWidget(forms.Widget)` follows `DatePickerWidget` | 5 |
| The eleven input names | 3, 4 |
| `value_from_datadict()` builds the draft, `clean()` turns it into the value | 5 |
| The widget joins the composite list in `apply_primitive_widget_classes()` | 5 |
| Native controls only: a select, number inputs, two checkboxes | 4 |
| Every combination round-trips with scripting off | 3, 4, 5 |
| No custom element, no presenter, no model change | none, by construction |

Issue acceptance: round-trip for every shape (Task 2), refusal with a reason
(Tasks 1–2), a form that posts and validates with no JavaScript and re-renders the
person's own input (Tasks 4–5), the control generates the canonical value and no
field accepts raw EDTF text (Task 4 renders no text input), one dimension is one
assignment (Task 1), the full gate (Task 6).

**Placeholders.** None. Every step names its file, its command and its expected
output, and every code step carries the code.

**Type consistency.** `build()` on `TemporalEndpointDraft` answers
`TemporalValue | None`; on `TemporalDraft` it answers `TemporalValue`. `from_value`
takes `TemporalValue | None` on both. `temporal_draft_data` and
`temporal_draft_from_data` are inverses over `TemporalDraftData`.
`temporal_input_name(name, key)` takes a `TemporalDraftData` key, and Task 4's
`_endpoint_row` builds those keys as `f"{endpoint}_year"` from `"start"`/`"end"` —
which is why `TEMPORAL_INPUT_SUFFIXES` is keyed by the data key rather than by the
suffix.
