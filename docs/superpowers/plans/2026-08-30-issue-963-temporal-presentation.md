# Temporal presentation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stored `TemporalValue` reads as a sentence at the precision it knows —
`June 1984`, `1980s`, `around 1984 (uncertain)`, `1984 – 1986` — instead of as the
canonical storage string `1984-06~`.

**Architecture:** One new module, `common/temporal_presentation.py`, beside
`common/date_time_presentation.py`. It holds two entry points:
`present_temporal_value(value, presentation)` answers text, and
`TemporalText(value, presentation)` answers a `Node` holding the same words. Both
delegate every calendar decision to the request's `DateTimePresentation`, and both
read `value.year` / `.month` / `.day` / `.decade_start_year` — never
`value.lower_bound` — so a value that knows no day can never print one. The
presenter reads; it writes nothing and adds no column.

**Tech Stack:** Python 3.14, Django 6, pytest + pytest-django, mypy, ruff, the
`common.components` node layer.

**Spec:** `docs/superpowers/specs/2026-08-30-issue-963-temporal-presentation-design.md`

## Global Constraints

- Python 3.14. Run everything through `make`; never `uv run`, `pytest` or
  `direnv exec .` directly. Focused runs:
  `make test ARGS="tests/test_temporal_presentation.py -k month"`.
  `PYTEST_WORKERS=0` when debugging, so `-x` stops the whole run.
- `make check` is the gate and must be green before the branch is done. Use
  `make check-fast` while iterating; it is not the gate.
- Comments are seven words or fewer
  ([Vocabulary](../../vocabulary.md#not-enforced-here)). Docstrings may be longer.
- `make vale` lints docstrings and comments as well as docs. It refuses `archive`,
  `fold`, `tombstone`, `delete` and `heal` in their domain sense.
- Unabbreviated identifiers: `value` not `v`, `presentation` not `pres`,
  `endpoint` not `ep`.
- Build UI with Python components from `common.components`, never HTML strings.
  Every string child is escaped; only a `Node` renders unescaped.
- Never write to a `GeneratedField`
  (`original_release_date_lower`, `_kind`, `_precision`, `_qualifier`, …).
- ruff formats at 88 columns with the default rule set. Every code block below is
  already in that form; keep the magic trailing commas.
- The branch is `claude/issue-963-temporal-presentation`, already created, with
  this plan already committed. The spec is already on `main`.
- Commit messages: imperative mood, no `feat:`/`fix:` prefixes — match the log
  (`Say the qualifier in fewer words`). End every commit message with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

## File structure

| File | Responsibility | Task |
| --- | --- | --- |
| `common/temporal_presentation.py` | The whole presenter: precision words, qualifier words, range join, the node | 1–4 |
| `tests/test_temporal_presentation.py` | Every rule of the presenter, with no database | 1–4 |
| `games/views/game.py:625-631` | The first caller: the Game's original release date | 5 |
| `tests/test_rendered_pages.py:340-372` | The renamed meta row and the rendered value | 5 |

One module, because every rule here is one decision — which words a stored value
gets — and splitting the qualifier from the precision would put half a sentence in
each file.

## What this plan does not do

- No entry control. #964 owns the form field, #965 owns the browser element.
- No hierarchy section on Game detail, and no removal of the Platform or
  release-year meta rows. #968 owns the read cutover.
- No filter and no query-string encoding. A later wave owns those.
- No change to `timetracker/temporal.py`. The primitive already answers every
  part this presenter reads.

## One boundary the spec leaves open

#963 says its first caller is `games/views/game.py`. #968 says the original release
date "now reads through the presenter of #963 rather than through `str()`". Task 5
makes that one substitution here, so the presenter lands with a real call site
rather than none — the same reasoning that deferred the Release selector to #690.
#968 keeps the rest of its own work: the hierarchy section, and moving the Platform
and release-year rows out of the Game meta list.

---

### Task 1: The precision decides the words

**Files:**
- Create: `common/temporal_presentation.py`
- Create: `tests/test_temporal_presentation.py`

**Interfaces:**
- Consumes: `TemporalValue`, `TemporalPrecision` from `timetracker.temporal`;
  `DateTimePresentation` from `common.date_time_presentation`.
- Produces:
  `present_temporal_value(value: TemporalValue | None, presentation: DateTimePresentation) -> str`
  and the module constant `UNKNOWN_TEXT = "Unknown"`. Tasks 2–4 extend this same
  function; Task 5 calls it through `TemporalText`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_temporal_presentation.py`:

```python
"""The words a stored temporal value reads as."""

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from common.date_time_presentation import (
    DateTimePresentation,
    date_time_format_profile,
)
from common.temporal_presentation import present_temporal_value
from timetracker.temporal import TemporalValue


def presentation(profile_id: str = "iso_8601") -> DateTimePresentation:
    return DateTimePresentation(
        profile=date_time_format_profile(profile_id),
        locale="en-us",
        timezone=ZoneInfo("UTC"),
    )


@pytest.mark.parametrize(
    ("profile_id", "expected"),
    [
        ("iso_8601", "1984-06-22"),
        ("dmy_24h", "22/06/1984"),
        ("mdy_12h", "06/22/1984"),
    ],
)
def test_a_day_reads_in_the_account_order(profile_id: str, expected: str) -> None:
    value = TemporalValue.from_day(date(1984, 6, 22))

    assert present_temporal_value(value, presentation(profile_id)) == expected


def test_a_month_reads_as_a_month_and_a_year() -> None:
    value = TemporalValue.from_month(1984, 6)

    assert present_temporal_value(value, presentation()) == "June 1984"


def test_a_month_never_prints_a_day() -> None:
    value = TemporalValue.from_month(1984, 6)

    words = present_temporal_value(value, presentation("iso_8601"))

    assert "01" not in words


def test_a_year_reads_as_four_digits() -> None:
    value = TemporalValue.from_year(1984)

    assert present_temporal_value(value, presentation()) == "1984"


def test_a_decade_reads_with_a_trailing_letter() -> None:
    value = TemporalValue.from_decade(1980)

    assert present_temporal_value(value, presentation()) == "1980s"


@pytest.mark.parametrize(
    "value",
    [None, TemporalValue.unknown()],
)
def test_nothing_stored_reads_as_unknown(value: TemporalValue | None) -> None:
    assert present_temporal_value(value, presentation()) == "Unknown"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_temporal_presentation.py -x"`
Expected: FAIL at collection with
`ModuleNotFoundError: No module named 'common.temporal_presentation'`.

- [ ] **Step 3: Write the module**

Create `common/temporal_presentation.py`:

```python
"""Words for a stored temporal value, at the precision it knows.

``str(value)`` prints the canonical string, ``1984-06~``. That is the storage
form and not a sentence: it hides the precision behind punctuation and states
the qualifier as a symbol. This module answers words instead.

Every calendar decision belongs to :class:`DateTimePresentation` — the account
owns the order of the parts. This module decides only which parts there are.
"""

from datetime import date

from common.date_time_presentation import DateTimePresentation
from timetracker.temporal import TemporalPrecision, TemporalValue

UNKNOWN_TEXT = "Unknown"


def present_temporal_value(
    value: TemporalValue | None, presentation: DateTimePresentation
) -> str:
    """The words for ``value``, or ``Unknown`` where it states nothing."""
    if value is None or value.is_unknown:
        return UNKNOWN_TEXT
    return _at_precision(value, presentation)


def _at_precision(value: TemporalValue, presentation: DateTimePresentation) -> str:
    match value.precision:
        case TemporalPrecision.DAY:
            return presentation.format(_day_date(value), "date")
        case TemporalPrecision.MONTH:
            return presentation.format(_month_date(value), "month_year")
        case TemporalPrecision.YEAR:
            return _four_digits(value.year)
        case TemporalPrecision.DECADE:
            return f"{_four_digits(value.decade_start_year)}s"
        case _:
            return UNKNOWN_TEXT


def _day_date(value: TemporalValue) -> date:
    """The stored day. Every part is present at this precision."""
    year, month, day = value.year, value.month, value.day
    if year is None or month is None or day is None:
        raise ValueError("A day temporal value states every part.")
    return date(year, month, day)


def _month_date(value: TemporalValue) -> date:
    """A carrier for the month style. The day never reaches a reader."""
    year, month = value.year, value.month
    if year is None or month is None:
        raise ValueError("A month temporal value states both parts.")
    return date(year, month, 1)


def _four_digits(year: int | None) -> str:
    return UNKNOWN_TEXT if year is None else f"{year:04d}"
```

Why `value.year` / `.month` / `.day` and never `value.lower_bound`: `1984-06` has
a lower bound of `1984-06-01`, and 1 is not a stored day. Each property answers
`None` where the precision knows no such part, which is the guard against a
fabricated exact date. `_month_date` builds a day only as a carrier for the
`month_year` style, which discards it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_temporal_presentation.py -x"`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add common/temporal_presentation.py tests/test_temporal_presentation.py
git commit -m "$(cat <<'EOF'
Read a stored date at the precision it knows

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The qualifier is said in words

**Files:**
- Modify: `common/temporal_presentation.py`
- Test: `tests/test_temporal_presentation.py`

**Interfaces:**
- Consumes: `present_temporal_value` and `UNKNOWN_TEXT` from Task 1;
  `TemporalQualifier` from `timetracker.temporal`.
- Produces: no new public name. `present_temporal_value` now prefixes `around `
  for an approximate value and suffixes ` (uncertain)` for an uncertain one, and
  does both for `TemporalQualifier.BOTH`. Task 3 reuses the same private
  `_present_atomic` per endpoint.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_temporal_presentation.py`:

```python
@pytest.mark.parametrize(
    ("qualifier", "expected"),
    [
        (TemporalQualifier.APPROXIMATE, "around 1984"),
        (TemporalQualifier.UNCERTAIN, "1984 (uncertain)"),
        (TemporalQualifier.BOTH, "around 1984 (uncertain)"),
    ],
)
def test_a_qualifier_reads_in_words(
    qualifier: TemporalQualifier, expected: str
) -> None:
    value = TemporalValue.from_year(1984, qualifier=qualifier)

    assert present_temporal_value(value, presentation()) == expected


def test_a_qualifier_wraps_the_words_of_any_precision() -> None:
    value = TemporalValue.from_month(1984, 6, qualifier=TemporalQualifier.BOTH)

    words = present_temporal_value(value, presentation())

    assert words == "around June 1984 (uncertain)"


def test_no_qualifier_adds_no_words() -> None:
    value = TemporalValue.from_decade(1980)

    words = present_temporal_value(value, presentation())

    assert words == "1980s"
```

Extend the existing import so it reads:

```python
from timetracker.temporal import TemporalQualifier, TemporalValue
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_temporal_presentation.py -k qualifier -x"`
Expected: FAIL with `AssertionError: assert '1984' == 'around 1984'`.

- [ ] **Step 3: Say the qualifier**

In `common/temporal_presentation.py`, extend the import:

```python
from timetracker.temporal import TemporalPrecision, TemporalQualifier, TemporalValue
```

Add the two constants under `UNKNOWN_TEXT`:

```python
_APPROXIMATE_PREFIX = "around "
_UNCERTAIN_SUFFIX = " (uncertain)"
```

Replace the body of `present_temporal_value` and add `_present_atomic` and
`_qualified` beneath it:

```python
def present_temporal_value(
    value: TemporalValue | None, presentation: DateTimePresentation
) -> str:
    """The words for ``value``, or ``Unknown`` where it states nothing."""
    if value is None or value.is_unknown:
        return UNKNOWN_TEXT
    return _present_atomic(value, presentation)


def _present_atomic(value: TemporalValue, presentation: DateTimePresentation) -> str:
    return _qualified(_at_precision(value, presentation), value.qualifier)


def _qualified(words: str, qualifier: TemporalQualifier | None) -> str:
    """A symbol is storage. A reader gets words."""
    if qualifier is None:
        return words
    if qualifier is TemporalQualifier.APPROXIMATE:
        return f"{_APPROXIMATE_PREFIX}{words}"
    if qualifier is TemporalQualifier.UNCERTAIN:
        return f"{words}{_UNCERTAIN_SUFFIX}"
    return f"{_APPROXIMATE_PREFIX}{words}{_UNCERTAIN_SUFFIX}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_temporal_presentation.py -x"`
Expected: PASS, 14 tests.

- [ ] **Step 5: Commit**

```bash
git add common/temporal_presentation.py tests/test_temporal_presentation.py
git commit -m "$(cat <<'EOF'
Say a stored qualifier in words rather than a symbol

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: A range says each endpoint

**Files:**
- Modify: `common/temporal_presentation.py`
- Test: `tests/test_temporal_presentation.py`

**Interfaces:**
- Consumes: `_present_atomic` from Task 2; `TemporalEndpoint` from
  `timetracker.temporal`.
- Produces: no new public name. `present_temporal_value` now answers a two-part
  sentence for a range value: `1984 – 1986` (en dash, U+2013, spaced),
  `until 1986` for an open start, `since 1984` for an open end, and `Unknown` in
  the place of an unknown endpoint.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_temporal_presentation.py`:

```python
@pytest.mark.parametrize(
    ("canonical", "expected"),
    [
        ("1984/1986", "1984 – 1986"),
        ("1984-06/1986", "June 1984 – 1986"),
        ("../1986", "until 1986"),
        ("1984/..", "since 1984"),
        ("/1986", "Unknown – 1986"),
        ("1984/", "1984 – Unknown"),
    ],
)
def test_a_range_says_each_endpoint(canonical: str, expected: str) -> None:
    value = TemporalValue.parse(canonical)

    assert present_temporal_value(value, presentation()) == expected


def test_each_endpoint_keeps_its_own_qualifier() -> None:
    value = TemporalValue.parse("1984~/1986?")

    words = present_temporal_value(value, presentation())

    assert words == "around 1984 – 1986 (uncertain)"
```

The second test is the point of the endpoint loop: the primitive qualifies each
endpoint separately, and #964's controls write one pair. The presenter must read a
value those controls cannot write.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_temporal_presentation.py -k range -x"`
Expected: FAIL with `AssertionError: assert 'Unknown' == '1984 – 1986'` — a range
value has no precision, so Task 1's `case _` arm answers it.

- [ ] **Step 3: Join the endpoints**

In `common/temporal_presentation.py`, extend the import:

```python
from timetracker.temporal import (
    TemporalEndpoint,
    TemporalPrecision,
    TemporalQualifier,
    TemporalValue,
)
```

Add the joiner beside the other constants:

```python
_RANGE_JOINER = " – "
```

Give `present_temporal_value` the range branch:

```python
def present_temporal_value(
    value: TemporalValue | None, presentation: DateTimePresentation
) -> str:
    """The words for ``value``, or ``Unknown`` where it states nothing."""
    if value is None or value.is_unknown:
        return UNKNOWN_TEXT
    if value.is_range:
        return _present_range(value, presentation)
    return _present_atomic(value, presentation)
```

Add the two functions beneath `_present_atomic`:

```python
def _present_range(value: TemporalValue, presentation: DateTimePresentation) -> str:
    start, end = value.start, value.end
    if start is None or end is None:
        return UNKNOWN_TEXT
    if start.is_open:
        return f"until {_present_endpoint(end, presentation)}"
    if end.is_open:
        return f"since {_present_endpoint(start, presentation)}"
    start_words = _present_endpoint(start, presentation)
    end_words = _present_endpoint(end, presentation)
    return f"{start_words}{_RANGE_JOINER}{end_words}"


def _present_endpoint(
    endpoint: TemporalEndpoint, presentation: DateTimePresentation
) -> str:
    if endpoint.value is None:
        return UNKNOWN_TEXT
    return _present_atomic(endpoint.value, presentation)
```

The primitive refuses a range whose endpoints are both unqualified for a date, so
at most one endpoint here is open or unknown. `_present_range` answers
`UNKNOWN_TEXT` for a range that somehow carries no endpoints rather than raising:
this is a read path, and a display value must not answer a page with a 500.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_temporal_presentation.py -x"`
Expected: PASS, 21 tests.

- [ ] **Step 5: Commit**

```bash
git add common/temporal_presentation.py tests/test_temporal_presentation.py
git commit -m "$(cat <<'EOF'
Read a stored range as two endpoints, each at its own precision

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The node a page places

**Files:**
- Modify: `common/temporal_presentation.py`
- Test: `tests/test_temporal_presentation.py`

**Interfaces:**
- Consumes: `present_temporal_value` from Tasks 1–3; `Node` from
  `common.components.core`; `Span` from `common.components.elements`.
- Produces:
  `TemporalText(value: TemporalValue | None, presentation: DateTimePresentation, *, class_: str = "") -> Node`.
  Task 5 calls it with `class_=grey_value_class`.

Import `Span` from `common.components.elements` and `Node` from
`common.components.core`, the way `common/layout.py` does. `elements` imports only
`core`, so a non-component module can reach the builders with no import cycle.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_temporal_presentation.py`:

```python
def test_temporal_text_holds_the_same_words() -> None:
    value = TemporalValue.from_year(1984)

    assert str(TemporalText(value, presentation())) == "<span>1984</span>"


def test_temporal_text_takes_the_caller_classes() -> None:
    value = TemporalValue.from_year(1984)

    node = TemporalText(value, presentation(), class_="text-slate-300")

    assert str(node) == '<span class="text-slate-300">1984</span>'


def test_temporal_text_says_unknown_for_nothing_stored() -> None:
    assert str(TemporalText(None, presentation())) == "<span>Unknown</span>"
```

Extend the existing import so it reads:

```python
from common.temporal_presentation import TemporalText, present_temporal_value
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_temporal_presentation.py -k temporal_text -x"`
Expected: FAIL at collection with
`ImportError: cannot import name 'TemporalText' from 'common.temporal_presentation'`.

- [ ] **Step 3: Add the node**

In `common/temporal_presentation.py`, add the two imports above the existing ones:

```python
from common.components.core import Node
from common.components.elements import Span
```

Add the function directly beneath `present_temporal_value`:

```python
def TemporalText(
    value: TemporalValue | None,
    presentation: DateTimePresentation,
    *,
    class_: str = "",
) -> Node:
    """The same words, as a span a page can place.

    The words carry no markup of their own, so a screen reader says what a
    sighted reader sees. This adds the element and the classes, and it adds no
    second wording — a title attribute, a log line or an API answer calls
    :func:`present_temporal_value` instead.
    """
    return Span(class_=class_)[present_temporal_value(value, presentation)]
```

An empty `class_` is dropped by `normalize_attributes`, so the default renders a
bare `<span>` with no empty attribute. The caller passes its own classes rather
than wrapping the node in a second span.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_temporal_presentation.py -x"`
Expected: PASS, 24 tests.

- [ ] **Step 5: Check the whole aggregate so far**

Run: `make check-fast`
Expected: green. `make vale` reads the new docstrings; `make typecheck` reads the
new signatures.

- [ ] **Step 6: Commit**

```bash
git add common/temporal_presentation.py tests/test_temporal_presentation.py
git commit -m "$(cat <<'EOF'
Place a stored date on a page as a node

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: The first caller reads the stored value

**Files:**
- Modify: `games/views/game.py:625-631` (the `metadata` block inside `_game_header`)
- Modify: `tests/test_rendered_pages.py:357` (the `test_view_game` marker list)
- Test: `tests/test_rendered_pages.py`, inside `RenderedPagesTest`

**Interfaces:**
- Consumes: `TemporalText` from Task 4. `_game_header` already holds
  `presentation: DateTimePresentation`, so nothing new is threaded through.
- Produces: the Game detail meta row labelled `Original release`, whose value is
  `game.original_release_date` read through the presenter. #968 finds this row
  already converted and keeps its own work: the hierarchy section, and moving the
  Platform and release-year rows out.

The column is safe to read. Migration `0020_catalog_hierarchy_backfill` filled
`Game.original_release_date` from `original_year_released` for every row, and
`save_legacy_game_form` in `games/catalog_compat.py` keeps writing it on every save
through `save_private_game`. A row with no stored value now reads `Unknown` where
it previously read the string `None`.

The label changes because the value no longer has to be a year: a stored month
under a label saying "year" is a wrong label, and `original_release_date` accepts a
month, a decade and a range.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_rendered_pages.py`, inside `RenderedPagesTest`, directly after
`test_view_game`:

```python
    def test_view_game_reads_the_original_release_date(self):
        self.game.original_release_date = TemporalValue.from_month(1984, 6)
        self.game.save()

        html = self.client.get(self.game.get_absolute_url()).content.decode()

        self.assertIn("Original release", html)
        self.assertIn("June 1984", html)
        self.assertNotIn("1984-06", html)

    def test_view_game_says_unknown_for_no_original_release_date(self):
        html = self.client.get(self.game.get_absolute_url()).content.decode()

        self.assertIn(
            '<span class="text-black dark:text-slate-300">Unknown</span>', html
        )
```

The second assertion is the exact span, not a bare `assertNotIn("None", html)`:
the word `Unknown` appears in other places on a page, and `None` appears inside
markup that has nothing to do with this row. The class string is
`grey_value_class` from `_game_header`; if that constant changes, this assertion
is right to fail.

Add the import at the top of the file, beside the existing model import:

```python
from timetracker.temporal import TemporalValue
```

Then change the marker in `test_view_game` from `"Original year",` to
`"Original release",`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_rendered_pages.py -k view_game -x"`
Expected: FAIL — `AssertionError: 'Original release' not found in ...`, because the
row still says `Original year` and still renders `str(game.original_year_released)`.

- [ ] **Step 3: Read the stored value**

In `games/views/game.py`, add the import beside the other `common` imports:

```python
from common.temporal_presentation import TemporalText
```

Replace the first `_meta_row(...)` call inside `metadata` in `_game_header`:

```python
        _meta_row(
            "Original release",
            TemporalText(
                game.original_release_date, presentation, class_=grey_value_class
            ),
        ),
```

Leave every other row of `metadata` alone. The Platform row and the title's
release-year popover are #968's to move.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_rendered_pages.py -k view_game -x"`
Expected: PASS.

- [ ] **Step 5: Run the gate**

Run: `make check`
Expected: green, including `e2e/`. `make vale` reports three pre-existing `archive`
warnings in `scripts/db_dump.py`, `scripts/ensure_postgres.py` and
`tests/test_ensure_postgres.py`; those are warnings, not errors, and are not this
branch's to fix.

If an e2e test asserts the string `Original year` on Game detail, change the
assertion — the label is the thing that moved, and the test is right to notice.

- [ ] **Step 6: Commit**

```bash
git add games/views/game.py tests/test_rendered_pages.py
git commit -m "$(cat <<'EOF'
Show a game's original release at the precision it was stored

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Done when

- `common/temporal_presentation.py` answers text and a node for every precision,
  every qualifier and every range shape the primitive can hold.
- Game detail reads `Game.original_release_date` through the presenter.
- `make check` is green.
- Nothing in `timetracker/temporal.py`, no migration, and no new column.
