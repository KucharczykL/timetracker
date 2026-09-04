# Report the legacy lifecycle rows before converting them — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only management command that says what #684's conversion will
meet in the legacy `PlayEvent` table — per library, how many rows convert
without a question, which ones carry one, which display numbers no recorded
date chose, and which #676 status events the conversion can pair with.

**Architecture:** A new `games/preflight/` package beside `games/backfill/`,
holding pure classifiers and one database walk, and a management command that
is only a printer over them. The walk is anchored on live `PlayerGame` rows,
not on catalog games, because a Playthrough belongs to an aggregate. #684
imports the classifiers, so the two issues agree on every verdict by
construction.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pytest, pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-09-04-issue-686-playthrough-preflight-design.md`

## Global Constraints

- **Drive everything through `make`.** Never `direnv exec .`, never a bare
  `uv run` / `pnpm` / `pytest`. Focused runs: `make test ARGS="…"`.
- **The verification gate is the full `make check`**, including `e2e/`. Use
  `make check-fast` while iterating; it is not the gate.
- **This code writes nothing.** No `save()`, no `create()`, no `remove()`, no
  event append, no migration. Every query is a read.
- **Nothing opens a server-side cursor.** No `QuerySet.iterator()` or
  `aiterator()`. Page with `keyset_pages()` from `common/keyset.py`, keyed on
  fields that lie in one index with a unique last field.
  `tests/test_iterator_guard.py` walks the syntax tree and fails on a new call.
- **Full words in identifiers**, Python and TypeScript: `element` not `el`,
  `event` not `e`, `option`/`value` not single letters in loops.
- **Name compound types explicitly** — a `tuple`/`dict` passed between
  functions gets a `NamedTuple`, `TypedDict` or `type` alias.
- **Name primitive roles** with a PEP 695 alias when a bare `str`/`int` stands
  for a domain concept.
- **Refused words** are enforced by `make vale` over docs *and code comments*:
  `fold`, `tombstone`, `archive`, `delete`, `heal`. See `docs/vocabulary.md`.
  Write "remove", "replay", "the projection".
- **`PlayerGame` has no manager.** `ProjectionModel` (`games/models.py:1508`)
  declares none, so there is no `for_library()` and no `.alive()`. Spell
  liveness out: `filter(library=…, removed_at__isnull=True)`.
- **Python 3.14.** PEP 758 unparenthesized `except A, B:` is the formatted
  form; a `SyntaxError` there means the wrong interpreter, not broken code.

---

## File Structure

**Created**

| Path | Responsibility |
|---|---|
| `games/preflight/__init__.py` | Opens the package. Empty. |
| `games/preflight/playthrough.py` | The verdicts, the ordering key, the pairing rule, the counts, and the one database walk |
| `games/management/commands/preflight_playthroughs.py` | Scope arguments and printing. No rule of its own. |
| `tests/test_playthrough_preflight.py` | Every classifier, the walk, and the command's output |

**Modified**

| Path | Change |
|---|---|
| `Makefile` | A `preflight-playthroughs: ensure-postgres` target taking `ARGS` |
| `CLAUDE.md` | One row in the Commands table |

---

## Task 1: One verdict and one order key per row

**Files:**
- Create: `games/preflight/__init__.py`, `games/preflight/playthrough.py`
- Test: `tests/test_playthrough_preflight.py`

**Interfaces:**
- Consumes: `games.models.PlayEvent`.
- Produces: `RowVerdict` (a `StrEnum` with `CLEAN_BOTH`, `CLEAN_START_ONLY`,
  `CLEAN_END_ONLY`, `NO_KNOWN_ENDPOINT`, `REVERSED_ENDPOINTS`),
  `classify_row(row: PlayEvent) -> RowVerdict`, `LegacyOrderKey` (a
  `NamedTuple`), and `legacy_order_key(row: PlayEvent) -> LegacyOrderKey`.
  Task 2 and Task 4 use all four, and #684 imports the two functions.

- [ ] **Step 1: Write the failing test**

Create `tests/test_playthrough_preflight.py`:

```python
"""What the legacy lifecycle rows hold, before #684 converts them."""

import uuid
from datetime import date

import pytest

from games.models import Game, PlayEvent
from games.preflight.playthrough import (
    LegacyOrderKey,
    RowVerdict,
    classify_row,
    legacy_order_key,
)

pytestmark = pytest.mark.django_db


def _row(started=None, ended=None, game=None):
    """A PlayEvent that is never saved: the classifiers read fields."""
    return PlayEvent(id=uuid.uuid7(), game=game, started=started, ended=ended)


def test_both_endpoints_convert_without_a_question():
    row = _row(started=date(2024, 1, 1), ended=date(2024, 1, 9))
    assert classify_row(row) is RowVerdict.CLEAN_BOTH


def test_one_day_is_not_a_reversal():
    #: days_to_finish already reads an equal pair as one day, and #681
    #: refuses only a completion earlier than its start.
    row = _row(started=date(2024, 1, 1), ended=date(2024, 1, 1))
    assert classify_row(row) is RowVerdict.CLEAN_BOTH


def test_a_start_with_no_completion():
    row = _row(started=date(2024, 1, 1))
    assert classify_row(row) is RowVerdict.CLEAN_START_ONLY


def test_a_completion_with_no_start():
    row = _row(ended=date(2024, 1, 9))
    assert classify_row(row) is RowVerdict.CLEAN_END_ONLY


def test_neither_endpoint_is_known():
    assert classify_row(_row()) is RowVerdict.NO_KNOWN_ENDPOINT


def test_a_completion_before_its_start_is_named():
    row = _row(started=date(2024, 1, 9), ended=date(2024, 1, 1))
    assert classify_row(row) is RowVerdict.REVERSED_ENDPOINTS


def test_a_known_start_sorts_before_an_unknown_one():
    known = _row(started=date(2024, 1, 1))
    unknown = _row()
    assert legacy_order_key(known) < legacy_order_key(unknown)


def test_an_unknown_completion_sorts_last_among_equal_starts():
    start = date(2024, 1, 1)
    dated = _row(started=start, ended=date(2024, 2, 1))
    open_ended = _row(started=start)
    assert legacy_order_key(dated) < legacy_order_key(open_ended)


def test_the_last_resort_is_the_primary_key():
    #: created_at is auto_now_add and loaddata rewrites it. The pk is a
    #: UUIDv7 the dump preserves, so it is the one stable insertion order.
    first = _row()
    second = _row()
    first.id, second.id = uuid.UUID(int=1), uuid.UUID(int=2)
    assert legacy_order_key(first) < legacy_order_key(second)


def test_the_key_names_its_parts():
    row = _row(started=date(2024, 1, 1))
    key = legacy_order_key(row)
    assert isinstance(key, LegacyOrderKey)
    assert key.start_unknown is False
    assert key.completion_unknown is True
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_preflight.py -x"`
Expected: FAIL — `ModuleNotFoundError: No module named 'games.preflight'`.

- [ ] **Step 3: Write the module**

Create `games/preflight/__init__.py` as an empty file.

Create `games/preflight/playthrough.py`:

```python
"""What the legacy PlayEvent rows hold, read and never written.

Issue #686. #684 converts these rows into Playthroughs; this says what
that conversion will meet. Nothing here appends an event or writes a
row, and #684 imports the classifiers so the two agree by construction.
"""

import uuid
from datetime import date
from enum import StrEnum
from typing import NamedTuple

from games.models import PlayEvent

#: Sorts before every real date, and only reached when the flag beside
#: it already sorted the unknown value last.
_ABSENT_DAY = date.min


class RowVerdict(StrEnum):
    """What one legacy row states, and whether #684 can state it back."""

    CLEAN_BOTH = "clean_both"
    CLEAN_START_ONLY = "clean_start_only"
    CLEAN_END_ONLY = "clean_end_only"
    NO_KNOWN_ENDPOINT = "no_known_endpoint"
    #: #681 refuses a completion earlier than its start, so #684 decides.
    REVERSED_ENDPOINTS = "reversed_endpoints"


def classify_row(row: PlayEvent) -> RowVerdict:
    """One verdict per row. The five partition the live rows."""
    if row.started is None and row.ended is None:
        return RowVerdict.NO_KNOWN_ENDPOINT
    if row.started is None:
        return RowVerdict.CLEAN_END_ONLY
    if row.ended is None:
        return RowVerdict.CLEAN_START_ONLY
    if row.ended < row.started:
        return RowVerdict.REVERSED_ENDPOINTS
    return RowVerdict.CLEAN_BOTH


class LegacyOrderKey(NamedTuple):
    """The wave's numbering rule, over the legacy columns.

    Known start first, then known completion, then insertion. The
    booleans carry NULLS LAST: False sorts before True.
    """

    start_unknown: bool
    start: date
    completion_unknown: bool
    completion: date
    inserted: uuid.UUID


def legacy_order_key(row: PlayEvent) -> LegacyOrderKey:
    """Order by known start, then known completion, then primary key.

    The primary key, never created_at: created_at is auto_now_add, so
    loaddata rewrites it, while the UUIDv7 key survives a dump.
    """
    return LegacyOrderKey(
        start_unknown=row.started is None,
        start=row.started or _ABSENT_DAY,
        completion_unknown=row.ended is None,
        completion=row.ended or _ABSENT_DAY,
        inserted=row.id,
    )
```

- [ ] **Step 4: Run it and watch it pass**

Run: `make test ARGS="tests/test_playthrough_preflight.py -x"`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add games/preflight/ tests/test_playthrough_preflight.py
git commit -m "Say what one legacy row holds, and where it sorts"
```

---

## Task 2: The counts, the samples, and the ordering axis

**Files:**
- Modify: `games/preflight/playthrough.py`
- Test: `tests/test_playthrough_preflight.py`

**Interfaces:**
- Consumes: `RowVerdict`, `legacy_order_key` from Task 1.
- Produces: `PreflightCounts` (a frozen slotted dataclass with an `__add__`
  and an `as_dict()`), `NO_COUNTS`, and
  `ordering_counts(rows: Sequence[PlayEvent]) -> OrderingVerdict`, where
  `OrderingVerdict` is a `NamedTuple` of three booleans. Task 4 sums the
  counts; #684 reports through the same dataclass.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_preflight.py`:

```python
from games.preflight.playthrough import (
    NO_COUNTS,
    OrderingVerdict,
    PreflightCounts,
    ordering_counts,
)


def test_counts_sum_field_by_field():
    left = PreflightCounts(live_rows=2, clean_both=1)
    right = PreflightCounts(live_rows=3, tie_broken=1)
    total = left + right
    assert total.live_rows == 5
    assert total.clean_both == 1
    assert total.tie_broken == 1


def test_the_empty_counts_are_an_identity():
    counts = PreflightCounts(live_rows=4)
    assert NO_COUNTS + counts == counts


def test_counts_render_every_field():
    rendered = PreflightCounts(live_rows=1).as_dict()
    assert rendered["live_rows"] == 1
    assert rendered["tie_broken"] == 0


def test_distinct_dates_order_a_game_on_their_own():
    rows = [
        _row(started=date(2024, 1, 1)),
        _row(started=date(2024, 3, 1)),
    ]
    assert ordering_counts(rows) == OrderingVerdict(
        ordered_by_date=True, tie_broken=False, date_order_differs=False
    )


def test_two_rows_sharing_a_date_pair_fall_to_insertion_order():
    rows = [
        _row(started=date(2024, 1, 1), ended=date(2024, 2, 1)),
        _row(started=date(2024, 1, 1), ended=date(2024, 2, 1)),
    ]
    verdict = ordering_counts(rows)
    assert verdict.tie_broken is True
    assert verdict.ordered_by_date is False


def test_two_undated_rows_tie_as_well():
    verdict = ordering_counts([_row(), _row()])
    assert verdict.tie_broken is True


def test_a_single_row_ties_with_nothing():
    verdict = ordering_counts([_row()])
    assert verdict.tie_broken is False
    assert verdict.ordered_by_date is True


def test_a_date_order_against_the_insertion_order_is_reported():
    #: Written second, played first: the display number moves.
    first_written = _row(started=date(2024, 3, 1))
    second_written = _row(started=date(2024, 1, 1))
    first_written.id, second_written.id = uuid.UUID(int=1), uuid.UUID(int=2)
    verdict = ordering_counts([first_written, second_written])
    assert verdict.date_order_differs is True
    assert verdict.tie_broken is False
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_preflight.py -x -k counts or ordering"`
Expected: FAIL — `ImportError: cannot import name 'PreflightCounts'`.

- [ ] **Step 3: Write the counts and the ordering rule**

Append to `games/preflight/playthrough.py`:

```python
from collections.abc import Sequence
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class PreflightCounts:
    """What one library holds, summable into a total.

    Twenty fields, so __add__ reads the field list rather than naming
    each one: a field added here would otherwise sum to itself.
    """

    tracked: int = 0
    tracked_without_rows: int = 0
    live_rows: int = 0
    clean_both: int = 0
    clean_start_only: int = 0
    clean_end_only: int = 0
    no_known_endpoint: int = 0
    reversed_endpoints: int = 0
    ordered_by_date: int = 0
    tie_broken: int = 0
    date_order_differs_from_insertion: int = 0
    rows_removed: int = 0
    rows_on_removed_game: int = 0
    rows_untracked: int = 0
    rows_without_projection: int = 0
    status_events_676: int = 0
    pairs_unambiguous: int = 0
    pairs_ambiguous: int = 0
    pairs_absent: int = 0
    unclaimed_events: int = 0

    def __add__(self, other: "PreflightCounts") -> "PreflightCounts":
        return PreflightCounts(
            **{
                field.name: getattr(self, field.name) + getattr(other, field.name)
                for field in fields(self)
            }
        )

    def as_dict(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


#: The value an accumulation starts from.
NO_COUNTS = PreflightCounts()

#: One verdict per RowVerdict member, so a new member fails loudly.
_VERDICT_FIELDS: dict[RowVerdict, str] = {
    RowVerdict.CLEAN_BOTH: "clean_both",
    RowVerdict.CLEAN_START_ONLY: "clean_start_only",
    RowVerdict.CLEAN_END_ONLY: "clean_end_only",
    RowVerdict.NO_KNOWN_ENDPOINT: "no_known_endpoint",
    RowVerdict.REVERSED_ENDPOINTS: "reversed_endpoints",
}


class OrderingVerdict(NamedTuple):
    """How one game's rows reached their display numbers.

    Not a partition: a game can be tie-broken and also reordered.
    """

    ordered_by_date: bool
    tie_broken: bool
    date_order_differs: bool


def ordering_counts(rows: Sequence[PlayEvent]) -> OrderingVerdict:
    """Read one tracked game's live rows against the numbering rule."""
    keys = [legacy_order_key(row) for row in rows]
    dated_parts = [key[:4] for key in keys]
    tie_broken = len(set(dated_parts)) != len(dated_parts)
    by_rule = [key.inserted for key in sorted(keys)]
    by_insertion = sorted(key.inserted for key in keys)
    return OrderingVerdict(
        ordered_by_date=not tie_broken,
        tie_broken=tie_broken,
        date_order_differs=by_rule != by_insertion,
    )
```

- [ ] **Step 4: Run it and watch it pass**

Run: `make test ARGS="tests/test_playthrough_preflight.py"`
Expected: PASS, 18 tests.

- [ ] **Step 5: Commit**

```bash
git add games/preflight/playthrough.py tests/test_playthrough_preflight.py
git commit -m "Count what a library holds, and how its rows reached their numbers"
```

---

## Task 3: The pairing rule, with no walk order in it

**Files:**
- Modify: `games/preflight/playthrough.py`
- Test: `tests/test_playthrough_preflight.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `EndpointKind` (`START`, `COMPLETION`), `Endpoint`, `CandidateKey`,
  `CandidateEvent`, `PairingVerdict` (`UNAMBIGUOUS`, `AMBIGUOUS`, `ABSENT`),
  `Pairing`, `PairingResult`, and
  `pair_endpoints(endpoints, candidates) -> PairingResult`. Task 4 calls it;
  #684 imports it to find the correlation id it adopts.

The rule is a property of a connected component of the endpoint-to-candidate
graph, so no iteration order can change an answer. Every endpoint reduces to
exactly one `CandidateKey`, so the components are the key groups and the
implementation is a group-by rather than a traversal.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_preflight.py`:

```python
from games.preflight.playthrough import (
    CandidateEvent,
    CandidateKey,
    Endpoint,
    EndpointKind,
    PairingVerdict,
    pair_endpoints,
)

AGGREGATE = uuid.UUID(int=100)


def _endpoint(row_id, kind=EndpointKind.COMPLETION, day=date(2024, 1, 9)):
    return Endpoint(
        row_id=uuid.UUID(int=row_id), kind=kind, day=day, aggregate_id=AGGREGATE
    )


def _candidate(correlation, kind=EndpointKind.COMPLETION, day=date(2024, 1, 9)):
    return CandidateEvent(
        key=CandidateKey(aggregate_id=AGGREGATE, kind=kind, day=day),
        correlation_id=uuid.UUID(int=correlation),
    )


def test_one_endpoint_and_one_event_pair_unambiguously():
    endpoint = _endpoint(1)
    candidate = _candidate(900)
    result = pair_endpoints([endpoint], [candidate])
    assert result.pairings[endpoint].verdict is PairingVerdict.UNAMBIGUOUS
    assert result.pairings[endpoint].correlation_id == candidate.correlation_id
    assert result.unclaimed_events == 0


def test_an_endpoint_with_no_event_is_absent():
    endpoint = _endpoint(1)
    result = pair_endpoints([endpoint], [])
    assert result.pairings[endpoint].verdict is PairingVerdict.ABSENT
    assert result.pairings[endpoint].correlation_id is None


def test_two_rows_ending_on_one_day_are_both_ambiguous():
    #: Neither may adopt the correlation id without the other losing it.
    first, second = _endpoint(1), _endpoint(2)
    result = pair_endpoints([first, second], [_candidate(900)])
    assert result.pairings[first].verdict is PairingVerdict.AMBIGUOUS
    assert result.pairings[second].verdict is PairingVerdict.AMBIGUOUS
    assert result.pairings[first].correlation_id is None


def test_one_endpoint_with_two_events_is_ambiguous():
    endpoint = _endpoint(1)
    result = pair_endpoints([endpoint], [_candidate(900), _candidate(901)])
    assert result.pairings[endpoint].verdict is PairingVerdict.AMBIGUOUS


def test_the_answer_does_not_depend_on_the_order_read():
    first, second = _endpoint(1), _endpoint(2)
    candidates = [_candidate(900), _candidate(901)]
    forward = pair_endpoints([first, second], candidates)
    backward = pair_endpoints([second, first], list(reversed(candidates)))
    assert forward.pairings == backward.pairings


def test_a_start_does_not_pair_with_a_completion_event():
    endpoint = _endpoint(1, kind=EndpointKind.START)
    result = pair_endpoints([endpoint], [_candidate(900)])
    assert result.pairings[endpoint].verdict is PairingVerdict.ABSENT


def test_a_different_day_does_not_pair():
    endpoint = _endpoint(1, day=date(2024, 1, 8))
    result = pair_endpoints([endpoint], [_candidate(900)])
    assert result.pairings[endpoint].verdict is PairingVerdict.ABSENT


def test_an_event_no_endpoint_matched_is_counted_unclaimed():
    result = pair_endpoints([], [_candidate(900), _candidate(901)])
    assert result.unclaimed_events == 2
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_preflight.py -x -k pair"`
Expected: FAIL — `ImportError: cannot import name 'CandidateEvent'`.

- [ ] **Step 3: Write the pairing rule**

Append to `games/preflight/playthrough.py`:

```python
from collections import defaultdict
from collections.abc import Iterable, Mapping


class EndpointKind(StrEnum):
    """Which of a row's two dates is being paired."""

    START = "start"
    COMPLETION = "completion"


class Endpoint(NamedTuple):
    """One known date on one live row."""

    row_id: uuid.UUID
    kind: EndpointKind
    day: date
    aggregate_id: uuid.UUID


class CandidateKey(NamedTuple):
    """Everything a #676 status event must match to be a candidate.

    An endpoint reduces to exactly one of these, which is why the
    components of the pairing graph are this key's groups.
    """

    aggregate_id: uuid.UUID
    kind: EndpointKind
    day: date


class CandidateEvent(NamedTuple):
    """One #676 status event, and the id #684 would adopt from it."""

    key: CandidateKey
    correlation_id: uuid.UUID


class PairingVerdict(StrEnum):
    UNAMBIGUOUS = "unambiguous"
    AMBIGUOUS = "ambiguous"
    ABSENT = "absent"


class Pairing(NamedTuple):
    """What one endpoint found. An id only when nothing contests it."""

    verdict: PairingVerdict
    correlation_id: uuid.UUID | None


class PairingResult(NamedTuple):
    pairings: Mapping[Endpoint, Pairing]
    unclaimed_events: int


def _endpoint_key(endpoint: Endpoint) -> CandidateKey:
    return CandidateKey(
        aggregate_id=endpoint.aggregate_id, kind=endpoint.kind, day=endpoint.day
    )


def pair_endpoints(
    endpoints: Iterable[Endpoint], candidates: Iterable[CandidateEvent]
) -> PairingResult:
    """Pair each endpoint with the #676 status event #684 would adopt.

    A component holding one endpoint and one event pairs. Any larger
    component pairs nothing: two rows completing on one day both match
    the single event, and neither may take it. Reading order cannot
    change an answer, because the verdict is a property of the group.
    """
    events_by_key: dict[CandidateKey, list[CandidateEvent]] = defaultdict(list)
    for candidate in candidates:
        events_by_key[candidate.key].append(candidate)

    endpoints_by_key: dict[CandidateKey, list[Endpoint]] = defaultdict(list)
    for endpoint in endpoints:
        endpoints_by_key[_endpoint_key(endpoint)].append(endpoint)

    pairings: dict[Endpoint, Pairing] = {}
    for key, group in endpoints_by_key.items():
        events = events_by_key.get(key, [])
        if not events:
            verdict, correlation_id = PairingVerdict.ABSENT, None
        elif len(group) == 1 and len(events) == 1:
            verdict, correlation_id = (
                PairingVerdict.UNAMBIGUOUS,
                events[0].correlation_id,
            )
        else:
            verdict, correlation_id = PairingVerdict.AMBIGUOUS, None
        for endpoint in group:
            pairings[endpoint] = Pairing(verdict, correlation_id)

    unclaimed = sum(
        len(events)
        for key, events in events_by_key.items()
        if key not in endpoints_by_key
    )
    return PairingResult(pairings=pairings, unclaimed_events=unclaimed)
```

- [ ] **Step 4: Run it and watch it pass**

Run: `make test ARGS="tests/test_playthrough_preflight.py"`
Expected: PASS, 26 tests.

- [ ] **Step 5: Commit**

```bash
git add games/preflight/playthrough.py tests/test_playthrough_preflight.py
git commit -m "Pair a legacy endpoint with the status event that shares its day"
```

---

## Task 4: The walk over one library

**Files:**
- Modify: `games/preflight/playthrough.py`
- Test: `tests/test_playthrough_preflight.py`

**Interfaces:**
- Consumes: everything from Tasks 1 to 3.
- Produces: `DEFAULT_SAMPLE_SIZE`, `Samples`, `LibraryPreflight` (with
  `as_dict()`), and
  `preflight_library(library, *, sample_size=DEFAULT_SAMPLE_SIZE) -> LibraryPreflight`.
  Task 6 prints it; #684 asserts its own population equals it.

The walk is anchored on live `PlayerGame` rows, not on
`Game.objects.filter(library=…)`: `TrackGame._visible_game` resolves shared
catalog games, so a library can track a game whose `library` is NULL.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_preflight.py`:

```python
from django.utils import timezone

from games.models import LibraryEvent, PlayerGame
from games.preflight.playthrough import LibraryPreflight, preflight_library
from games.removal import remove


def _game(library, name="Chrono Trigger"):
    return Game.objects.create(library=library, name=name)


def _saved_row(game, started=None, ended=None):
    return PlayEvent.objects.create(game=game, started=started, ended=ended)


def test_a_tracked_game_with_no_rows_receives_the_default(owned_library):
    _game(owned_library)
    counts = preflight_library(owned_library).counts
    assert counts.tracked == 1
    assert counts.tracked_without_rows == 1
    assert counts.live_rows == 0


def test_each_verdict_is_counted(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9))
    _saved_row(game, started=date(2024, 2, 1))
    _saved_row(game, ended=date(2024, 3, 9))
    _saved_row(game)
    _saved_row(game, started=date(2024, 5, 9), ended=date(2024, 5, 1))
    counts = preflight_library(owned_library).counts
    assert counts.live_rows == 5
    assert counts.clean_both == 1
    assert counts.clean_start_only == 1
    assert counts.clean_end_only == 1
    assert counts.no_known_endpoint == 1
    assert counts.reversed_endpoints == 1


def test_a_removed_row_leaves_the_live_count(owned_library):
    game = _game(owned_library)
    remove(_saved_row(game, started=date(2024, 1, 1)))
    counts = preflight_library(owned_library).counts
    assert counts.live_rows == 0
    assert counts.rows_removed == 1


def test_a_row_on_a_removed_game_is_counted_once(owned_library):
    game = _game(owned_library)
    row = _saved_row(game, started=date(2024, 1, 1))
    remove(row)
    remove(game)
    counts = preflight_library(owned_library).counts
    assert counts.rows_on_removed_game == 1
    assert counts.rows_removed == 0


def test_an_untracked_game_is_not_a_backfill_failure(owned_library):
    #: remove_game_for_request untracks and then removes, with no
    #: transaction around the pair. A failure between them lands here.
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 1, 1))
    PlayerGame.objects.filter(game=game).update(removed_at=timezone.now())
    counts = preflight_library(owned_library).counts
    assert counts.rows_untracked == 1
    assert counts.rows_without_projection == 0


@pytest.mark.untracked_games
def test_a_row_with_no_projection_row_is_the_backfill_signal(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 1, 1))
    counts = preflight_library(owned_library).counts
    assert counts.rows_without_projection == 1
    assert counts.tracked == 0


def test_the_ordering_axis_is_counted_per_game(owned_library):
    tied = _game(owned_library, name="Tied")
    _saved_row(tied, started=date(2024, 1, 1))
    _saved_row(tied, started=date(2024, 1, 1))
    dated = _game(owned_library, name="Dated")
    _saved_row(dated, started=date(2024, 1, 1))
    _saved_row(dated, started=date(2024, 2, 1))
    counts = preflight_library(owned_library).counts
    assert counts.tie_broken == 1
    assert counts.ordered_by_date == 1


def test_samples_are_capped_and_keep_their_count(owned_library):
    game = _game(owned_library)
    for day in (1, 2, 3):
        _saved_row(game, started=date(2024, 5, day + 8), ended=date(2024, 5, day))
    result = preflight_library(owned_library, sample_size=2)
    assert result.counts.reversed_endpoints == 3
    assert len(result.samples.reversed_endpoints) == 2


def test_a_sample_size_of_zero_keeps_only_the_counts(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 5, 9), ended=date(2024, 5, 1))
    result = preflight_library(owned_library, sample_size=0)
    assert result.counts.reversed_endpoints == 1
    assert result.samples.reversed_endpoints == ()


def test_one_library_never_counts_another(owned_library, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    _saved_row(_game(stranger.library), started=date(2024, 1, 1))
    counts = preflight_library(owned_library).counts
    assert counts.tracked == 0
    assert counts.live_rows == 0


def test_the_walk_writes_nothing(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 1, 1))
    before = (LibraryEvent.objects.count(), PlayEvent.objects.count())
    preflight_library(owned_library)
    assert (LibraryEvent.objects.count(), PlayEvent.objects.count()) == before


def test_the_result_renders_itself(owned_library):
    rendered = preflight_library(owned_library).as_dict()
    assert rendered["library_id"] == str(owned_library.pk)
    assert rendered["counts"]["tracked"] == 0
    assert rendered["samples"]["reversed_endpoints"] == []
    assert isinstance(preflight_library(owned_library), LibraryPreflight)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_preflight.py -x -k preflight_library or counted or sample"`
Expected: FAIL — `ImportError: cannot import name 'preflight_library'`.

- [ ] **Step 3: Write the walk**

Append to `games/preflight/playthrough.py`. Add these imports at the top of the
module:

```python
from itertools import batched

from common.keyset import keyset_pages
from games.backfill.playergame import PGAME_ISSUE
from games.events.playergame import PLAYERGAME_STATUS_CHANGED
from games.models import (
    Game,
    LibraryEvent,
    PlayerGame,
    PlayerGameStatus,
    UserLibrary,
)
```

Then the body:

```python
#: Aggregates per query, matching the backfill's page.
WALK_PAGE_SIZE = 200

#: Identifiers per sampled list.
DEFAULT_SAMPLE_SIZE = 20

#: The status a #676 event states for each endpoint.
_STATUS_FOR_KIND: dict[EndpointKind, PlayerGameStatus] = {
    EndpointKind.START: PlayerGameStatus.PLAYED,
    EndpointKind.COMPLETION: PlayerGameStatus.COMPLETED,
}
_KIND_FOR_STATUS = {status: kind for kind, status in _STATUS_FOR_KIND.items()}


@dataclass(frozen=True, slots=True)
class Samples:
    """The first few identifiers behind a count, never a random draw.

    First in the report's own order, so two runs over unchanged data
    print the same bytes and the JSON line diffs across a rehearsal.
    """

    reversed_endpoints: tuple[uuid.UUID, ...] = ()
    tie_broken: tuple[uuid.UUID, ...] = ()
    date_order_differs: tuple[uuid.UUID, ...] = ()
    ambiguous_endpoints: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, list[str]]:
        return {
            field.name: [str(value) for value in getattr(self, field.name)]
            for field in fields(self)
        }


@dataclass(frozen=True, slots=True)
class LibraryPreflight:
    """One library's whole report."""

    library_id: uuid.UUID
    username: str
    counts: PreflightCounts
    samples: Samples

    def as_dict(self) -> dict[str, object]:
        return {
            "library_id": str(self.library_id),
            "username": self.username,
            "counts": self.counts.as_dict(),
            "samples": self.samples.as_dict(),
        }


def _candidate_events(library: UserLibrary) -> list[CandidateEvent]:
    """Every dated #676 status event this library recorded.

    One query per run, not one per page: LibraryEvent indexes neither
    aggregate_id nor event_type, so the scan is paid once.

    The day is read in Python. effective_time carries no generated
    bound columns, so comparing it in SQL would be a per-row function
    call over that same unindexed scan.

    A day precision is demanded rather than assumed: lower_bound gives
    the first day of a month or a decade too, and that is not a day the
    legacy row could have stated.
    """
    rows = LibraryEvent.objects.filter(
        library=library,
        event_type=PLAYERGAME_STATUS_CHANGED.event_type,
        source_metadata__origin="backfill",
        source_metadata__issue=PGAME_ISSUE,
        payload__status__in=[status.value for status in _STATUS_FOR_KIND.values()],
        effective_time__isnull=False,
    ).values_list("aggregate_id", "payload", "effective_time", "correlation_id")

    candidates = []
    for aggregate_id, payload, effective_time, correlation_id in rows:
        if effective_time is None or not effective_time.has_known_day:
            continue
        day = effective_time.lower_bound
        kind = _KIND_FOR_STATUS[PlayerGameStatus(payload["status"])]
        candidates.append(
            CandidateEvent(
                key=CandidateKey(aggregate_id=aggregate_id, kind=kind, day=day),
                correlation_id=correlation_id,
            )
        )
    return candidates


def _excluded_counts(library: UserLibrary) -> PreflightCounts:
    """The rows the conversion never sees, counted once each.

    The order of the four is the order of the checks: a row on a
    removed game is that, whatever its own mark says.
    """
    owned = PlayEvent.objects.filter(game__library=library)
    on_removed_game = owned.filter(game__removed_at__isnull=False).count()
    live_game_rows = owned.filter(game__removed_at__isnull=True)
    removed_rows = live_game_rows.filter(removed_at__isnull=False).count()
    live = live_game_rows.filter(removed_at__isnull=True)
    untracked = live.filter(
        game__player_games__library=library,
        game__player_games__removed_at__isnull=False,
    ).count()
    without_projection = live.exclude(
        game__player_games__library=library,
    ).count()
    return PreflightCounts(
        rows_on_removed_game=on_removed_game,
        rows_removed=removed_rows,
        rows_untracked=untracked,
        rows_without_projection=without_projection,
    )


def preflight_library(
    library: UserLibrary, *, sample_size: int = DEFAULT_SAMPLE_SIZE
) -> LibraryPreflight:
    """Read one library's legacy rows and say what #684 will meet."""
    counts = _excluded_counts(library)
    candidates = _candidate_events(library)
    counts = counts + PreflightCounts(status_events_676=len(candidates))

    reversed_rows: list[uuid.UUID] = []
    tied_games: list[uuid.UUID] = []
    reordered_games: list[uuid.UUID] = []
    ambiguous: list[str] = []
    endpoints: list[Endpoint] = []

    tracked = PlayerGame.objects.filter(library=library, removed_at__isnull=True).only(
        "id", "game_id"
    )
    for batch in batched(
        keyset_pages(tracked, key=("id",), page_size=WALK_PAGE_SIZE), WALK_PAGE_SIZE
    ):
        aggregate_for_game = {row.game_id: row.pk for row in batch}
        live_games = set(
            Game.objects.filter(
                pk__in=aggregate_for_game, removed_at__isnull=True
            ).values_list("pk", flat=True)
        )
        rows_by_game: dict[uuid.UUID, list[PlayEvent]] = defaultdict(list)
        for row in PlayEvent.objects.filter(
            game_id__in=live_games, removed_at__isnull=True
        ).order_by("game_id", "id"):
            rows_by_game[row.game_id].append(row)

        for game_id, aggregate_id in sorted(
            aggregate_for_game.items(), key=lambda pair: pair[1]
        ):
            counts = counts + PreflightCounts(tracked=1)
            rows = rows_by_game.get(game_id, [])
            if not rows:
                counts = counts + PreflightCounts(tracked_without_rows=1)
                continue

            counts = counts + PreflightCounts(live_rows=len(rows))
            for row in sorted(rows, key=legacy_order_key):
                verdict = classify_row(row)
                counts = counts + PreflightCounts(**{_VERDICT_FIELDS[verdict]: 1})
                if verdict is RowVerdict.REVERSED_ENDPOINTS:
                    reversed_rows.append(row.id)
                for kind, day in (
                    (EndpointKind.START, row.started),
                    (EndpointKind.COMPLETION, row.ended),
                ):
                    if day is not None:
                        endpoints.append(
                            Endpoint(
                                row_id=row.id,
                                kind=kind,
                                day=day,
                                aggregate_id=aggregate_id,
                            )
                        )

            ordering = ordering_counts(rows)
            counts = counts + PreflightCounts(
                ordered_by_date=int(ordering.ordered_by_date),
                tie_broken=int(ordering.tie_broken),
                date_order_differs_from_insertion=int(ordering.date_order_differs),
            )
            if ordering.tie_broken:
                tied_games.append(game_id)
            if ordering.date_order_differs:
                reordered_games.append(game_id)

    pairing = pair_endpoints(endpoints, candidates)
    for endpoint in endpoints:
        verdict = pairing.pairings[endpoint].verdict
        counts = counts + PreflightCounts(**{f"pairs_{verdict.value}": 1})
        if verdict is PairingVerdict.AMBIGUOUS:
            ambiguous.append(f"{endpoint.row_id}:{endpoint.kind.value}")
    counts = counts + PreflightCounts(unclaimed_events=pairing.unclaimed_events)

    def capped[SampleT](values: list[SampleT]) -> tuple[SampleT, ...]:
        return tuple(values[:sample_size])

    return LibraryPreflight(
        library_id=library.pk,
        username=library.user.username,
        counts=counts,
        samples=Samples(
            reversed_endpoints=capped(reversed_rows),
            tie_broken=capped(tied_games),
            date_order_differs=capped(reordered_games),
            ambiguous_endpoints=capped(ambiguous),
        ),
    )
```

- [ ] **Step 4: Run it and watch it pass**

Run: `make test ARGS="tests/test_playthrough_preflight.py"`
Expected: PASS, 38 tests.

- [ ] **Step 5: Commit**

```bash
git add games/preflight/playthrough.py tests/test_playthrough_preflight.py
git commit -m "Walk one library's aggregates and report what they hold"
```

---

## Task 5: The pairing, end to end, and the catalog rows no library owns

**Files:**
- Modify: `games/preflight/playthrough.py`
- Test: `tests/test_playthrough_preflight.py`

**Interfaces:**
- Consumes: `preflight_library` from Task 4.
- Produces: `SharedCatalogCounts` (with `as_dict()`) and
  `shared_catalog_counts() -> SharedCatalogCounts`. Task 6 prints it once,
  outside every library heading.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_preflight.py`:

```python
from games.backfill.playergame import backfill_library
from games.models import GameStatusChange
from games.preflight.playthrough import SharedCatalogCounts, shared_catalog_counts


def _recorded_completion(game, day):
    """A legacy transition #676 turns into a dated status event."""
    return GameStatusChange.objects.create(
        game=game,
        old_status=Game.Status.PLAYED,
        new_status=Game.Status.FINISHED,
        timestamp=timezone.make_aware(datetime(day.year, day.month, day.day, 12)),
    )


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_an_endpoint_pairs_with_the_status_event_of_its_day(owned_library):
    completed = date(2024, 1, 9)
    game = _game(owned_library)
    game.status = Game.Status.FINISHED
    game.save()
    _recorded_completion(game, completed)
    _saved_row(game, started=date(2024, 1, 1), ended=completed)
    backfill_library(owned_library)
    counts = preflight_library(owned_library).counts
    assert counts.pairs_unambiguous == 1
    #: The start has no `played` transition behind it.
    assert counts.pairs_absent == 1


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_two_rows_completing_on_one_day_are_both_ambiguous(owned_library):
    completed = date(2024, 1, 9)
    game = _game(owned_library)
    game.status = Game.Status.FINISHED
    game.save()
    _recorded_completion(game, completed)
    _saved_row(game, started=date(2024, 1, 1), ended=completed)
    _saved_row(game, started=date(2023, 1, 1), ended=completed)
    backfill_library(owned_library)
    result = preflight_library(owned_library)
    assert result.counts.pairs_ambiguous == 2
    assert result.counts.pairs_unambiguous == 0
    assert len(result.samples.ambiguous_endpoints) == 2


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_a_status_event_no_endpoint_matched_is_unclaimed(owned_library):
    game = _game(owned_library)
    game.status = Game.Status.FINISHED
    game.save()
    _recorded_completion(game, date(2024, 1, 9))
    backfill_library(owned_library)
    counts = preflight_library(owned_library).counts
    assert counts.status_events_676 == 1
    assert counts.unclaimed_events == 1


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_an_undated_status_event_is_no_candidate(owned_library):
    #: #676 records the corrective event with an unknown effective
    #: time, so it carries no day and can pair with nothing.
    game = _game(owned_library)
    game.status = Game.Status.FINISHED
    game.save()
    _saved_row(game, ended=date(2024, 1, 9))
    backfill_library(owned_library)
    counts = preflight_library(owned_library).counts
    assert counts.status_events_676 == 0
    assert counts.pairs_absent == 1


def test_a_shared_game_is_counted_outside_every_library(owned_library):
    shared = Game.objects.create(library=None, name="Shared")
    _saved_row(shared, started=date(2024, 1, 1))
    counts = shared_catalog_counts()
    assert counts == SharedCatalogCounts(
        shared_games=1, shared_game_rows=1, contested_rows=0
    )


def test_a_shared_game_two_libraries_track_holds_contested_rows(
    owned_library, django_user_model
):
    shared = Game.objects.create(library=None, name="Shared")
    _saved_row(shared, started=date(2024, 1, 1))
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    for library in (owned_library, stranger.library):
        PlayerGame.objects.create(
            pk=uuid.uuid7(),
            library=library,
            game=shared,
            tracked_at=timezone.now(),
        )
    assert shared_catalog_counts().contested_rows == 1
```

Add `from datetime import date, datetime` to the module's imports.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_preflight.py -x -k shared or pair"`
Expected: FAIL — `ImportError: cannot import name 'shared_catalog_counts'`.

- [ ] **Step 3: Write the global counts**

Append to `games/preflight/playthrough.py`:

```python
from django.db.models import Count


@dataclass(frozen=True, slots=True)
class SharedCatalogCounts:
    """The catalog rows no library owns.

    Expected to be zero: GameForm.__init__ always stamps a library, so
    the production catalog holds no shared game. Counted anyway,
    because "expected zero" and "verified zero" are different claims.
    """

    shared_games: int = 0
    shared_game_rows: int = 0
    #: A row on a shared game more than one library tracks. It belongs
    #: to no single Playthrough, and #684 decides what that means.
    contested_rows: int = 0

    def as_dict(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


def shared_catalog_counts() -> SharedCatalogCounts:
    """Count the shared games, their rows, and the contested ones."""
    shared = Game.objects.filter(library__isnull=True, removed_at__isnull=True)
    contested_games = (
        shared.filter(player_games__removed_at__isnull=True)
        .annotate(trackers=Count("player_games__library", distinct=True))
        .filter(trackers__gt=1)
    )
    return SharedCatalogCounts(
        shared_games=shared.count(),
        shared_game_rows=PlayEvent.objects.filter(
            game__in=shared, removed_at__isnull=True
        ).count(),
        contested_rows=PlayEvent.objects.filter(
            game__in=contested_games, removed_at__isnull=True
        ).count(),
    )
```

- [ ] **Step 4: Run it and watch it pass**

Run: `make test ARGS="tests/test_playthrough_preflight.py"`
Expected: PASS, 44 tests.

- [ ] **Step 5: Commit**

```bash
git add games/preflight/playthrough.py tests/test_playthrough_preflight.py
git commit -m "Pair against the recorded status events, and count the rows nobody owns"
```

---

## Task 6: The command, its target, and its two outputs

**Files:**
- Create: `games/management/commands/preflight_playthroughs.py`
- Modify: `Makefile:333-334` (add the target beside `audit-uuid-identity`),
  `CLAUDE.md` (the Commands table)
- Test: `tests/test_playthrough_preflight.py`

**Interfaces:**
- Consumes: `preflight_library`, `shared_catalog_counts`,
  `DEFAULT_SAMPLE_SIZE`.
- Produces: `MACHINE_PREFIX = "PLAYTHROUGH_PREFLIGHT_JSON="`. Nothing imports
  the command.

The machine line prints **first**, as
`0033_playergame_baseline_backfill.py:32-37` does, with
`sort_keys=True, separators=(",", ":")`. The command always exits 0: a
preflight reports and does not gate, and what is read is the line.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_preflight.py`:

```python
import json
from io import StringIO

from django.core.management import CommandError, call_command

from games.management.commands.preflight_playthroughs import MACHINE_PREFIX


def _run(*args):
    output = StringIO()
    call_command("preflight_playthroughs", *args, stdout=output)
    return output.getvalue()


def _machine_line(text):
    line = next(l for l in text.splitlines() if l.startswith(MACHINE_PREFIX))
    return json.loads(line[len(MACHINE_PREFIX) :])


def test_a_scope_is_named_rather_than_defaulted(owned_library):
    with pytest.raises(CommandError):
        _run()


def test_the_machine_line_comes_first(owned_library):
    text = _run("--all-libraries")
    assert text.splitlines()[0].startswith(MACHINE_PREFIX)


def test_the_machine_line_carries_every_count(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 5, 9), ended=date(2024, 5, 1))
    payload = _machine_line(_run("--user", owned_library.user.username))
    assert payload["schema_version"] == 1
    assert payload["summary"]["reversed_endpoints"] == 1
    assert payload["libraries"][0]["counts"]["reversed_endpoints"] == 1
    assert payload["shared_catalog"]["shared_games"] == 0


def test_the_summary_is_the_sum_of_the_libraries(owned_library, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    for library in (owned_library, stranger.library):
        _saved_row(_game(library), started=date(2024, 1, 1))
    payload = _machine_line(_run("--all-libraries"))
    assert payload["summary"]["live_rows"] == 2
    assert (
        sum(entry["counts"]["live_rows"] for entry in payload["libraries"])
        == payload["summary"]["live_rows"]
    )


def test_the_machine_line_sorts_its_keys(owned_library):
    line = next(
        l for l in _run("--all-libraries").splitlines() if l.startswith(MACHINE_PREFIX)
    )
    body = line[len(MACHINE_PREFIX) :]
    assert body == json.dumps(json.loads(body), sort_keys=True, separators=(",", ":"))


def test_the_human_section_names_the_library(owned_library):
    text = _run("--user", owned_library.user.username)
    assert f"library {owned_library.pk}" in text
    assert "tracked games: 0" in text


def test_a_run_over_every_anomaly_still_exits_zero(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 5, 9), ended=date(2024, 5, 1))
    _saved_row(game)
    #: call_command raises SystemExit on a nonzero code.
    _run("--all-libraries")


def test_two_runs_print_the_same_bytes(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 1, 1))
    _saved_row(game, started=date(2024, 1, 1))
    assert _run("--all-libraries") == _run("--all-libraries")


def test_the_sample_cap_reaches_the_output(owned_library):
    game = _game(owned_library)
    for day in (1, 2, 3):
        _saved_row(game, started=date(2024, 5, day + 8), ended=date(2024, 5, day))
    payload = _machine_line(_run("--all-libraries", "--sample-size", "1"))
    entry = payload["libraries"][0]
    assert entry["counts"]["reversed_endpoints"] == 3
    assert len(entry["samples"]["reversed_endpoints"]) == 1


def test_an_unknown_user_is_refused_by_name(owned_library):
    with pytest.raises(CommandError, match="nobody"):
        _run("--user", "nobody")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_preflight.py -x -k machine or scope"`
Expected: FAIL — `ModuleNotFoundError: games.management.commands.preflight_playthroughs`.

- [ ] **Step 3: Write the command**

Create `games/management/commands/preflight_playthroughs.py`:

```python
"""Report the legacy lifecycle rows, before #684 converts them.

Issue #686. Read-only: no event is appended and no row is written.
The exit code is always 0, because a preflight reports and does not
gate. What is read is the machine line.
"""

import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from games.models import UserLibrary
from games.preflight.playthrough import (
    DEFAULT_SAMPLE_SIZE,
    NO_COUNTS,
    LibraryPreflight,
    preflight_library,
    shared_catalog_counts,
)

MACHINE_PREFIX = "PLAYTHROUGH_PREFLIGHT_JSON="


class Command(BaseCommand):
    help = "Report what #684 will meet in the legacy PlayEvent rows."

    def add_arguments(self, parser):
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--user", help="Report the library owned by USERNAME.")
        scope.add_argument(
            "--library", dest="library_id", help="Report one library UUID."
        )
        scope.add_argument(
            "--all-libraries",
            action="store_true",
            help="Explicitly report every library.",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=DEFAULT_SAMPLE_SIZE,
            help="Identifiers printed beside each count. 0 keeps the counts only.",
        )

    def handle(self, *args, **options):
        libraries = self._resolve_libraries(options)
        sample_size = options["sample_size"]
        if sample_size < 0:
            raise CommandError(
                "A sample size counts identifiers, so it is not negative."
            )

        reports = [
            preflight_library(library, sample_size=sample_size) for library in libraries
        ]
        shared = shared_catalog_counts()
        summary = sum((report.counts for report in reports), NO_COUNTS)

        payload = {
            "schema_version": 1,
            "summary": summary.as_dict(),
            "libraries": [report.as_dict() for report in reports],
            "shared_catalog": shared.as_dict(),
        }
        self.stdout.write(
            MACHINE_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )
        for report in reports:
            self._write_report(report)
        self.stdout.write(f"Shared catalog games: {shared.shared_games}")
        self.stdout.write(f"  live play events on them: {shared.shared_game_rows}")
        self.stdout.write(
            f"  rows more than one library tracks: {shared.contested_rows}"
        )

    def _write_report(self, report: LibraryPreflight) -> None:
        counts = report.counts
        write = self.stdout.write
        write(
            f"Playthrough preflight - library {report.library_id} ({report.username})"
        )
        write(f"  tracked games: {counts.tracked}")
        write(f"    holding no play events: {counts.tracked_without_rows}")
        write(f"  live play events: {counts.live_rows}")
        write(f"    clean, both endpoints: {counts.clean_both}")
        write(f"    clean, start only: {counts.clean_start_only}")
        write(f"    clean, completion only: {counts.clean_end_only}")
        write(f"    no known endpoint: {counts.no_known_endpoint}")
        write(f"    completion before start: {counts.reversed_endpoints}")
        self._write_sample(report.samples.reversed_endpoints)
        write("  not converted:")
        write(f"    removed rows: {counts.rows_removed}")
        write(f"    on a removed game: {counts.rows_on_removed_game}")
        write(f"    on an untracked game: {counts.rows_untracked}")
        write(f"    with no projection row: {counts.rows_without_projection}")
        write("  ordering:")
        write(f"    ordered by date alone: {counts.ordered_by_date}")
        write(f"    display number decided by insertion order: {counts.tie_broken}")
        self._write_sample(report.samples.tie_broken)
        write(
            f"    date order differs from insertion order: "
            f"{counts.date_order_differs_from_insertion}"
        )
        self._write_sample(report.samples.date_order_differs)
        write(f"  #676 status events found: {counts.status_events_676}")
        write(f"    endpoints with one unambiguous pair: {counts.pairs_unambiguous}")
        write(f"    endpoints with an ambiguous pair: {counts.pairs_ambiguous}")
        self._write_sample(report.samples.ambiguous_endpoints)
        write(f"    endpoints with no candidate: {counts.pairs_absent}")
        write(f"    status events no endpoint claimed: {counts.unclaimed_events}")

    def _write_sample(self, values) -> None:
        if values:
            self.stdout.write("      " + " ".join(str(value) for value in values))

    def _resolve_libraries(self, options):
        libraries = UserLibrary.objects.select_related("user").order_by("pk")
        if options["all_libraries"]:
            return list(libraries)
        if options["user"]:
            user_model = get_user_model()
            try:
                user = user_model.objects.get(username=options["user"])
                return [libraries.get(user=user)]
            except (user_model.DoesNotExist, UserLibrary.DoesNotExist) as error:
                raise CommandError(
                    f"User {options['user']!r} or their library does not exist."
                ) from error
        try:
            return [libraries.get(pk=options["library_id"])]
        except (UserLibrary.DoesNotExist, ValidationError, ValueError) as error:
            raise CommandError(
                f"Library {options['library_id']!r} does not exist."
            ) from error
```

- [ ] **Step 4: Add the make target**

In `Makefile`, immediately after the `audit-uuid-identity` target:

```make
# Usage: make preflight-playthroughs ARGS="--all-libraries"
preflight-playthroughs: ensure-postgres
	uv run --frozen python manage.py preflight_playthroughs $(ARGS)
```

In `CLAUDE.md`, in the Commands table, after the `make audit-uuid-identity`
row:

```markdown
| Report the legacy lifecycle rows before converting them | `make preflight-playthroughs ARGS="--all-libraries"` (read-only; always exits 0) |
```

- [ ] **Step 5: Run the tests and the prose lint**

Run: `make test ARGS="tests/test_playthrough_preflight.py"`
Expected: PASS, 54 tests.

Run: `make vale`
Expected: `no errors`. A refused word in a docstring or a comment fails here.

- [ ] **Step 6: Commit**

```bash
git add games/management/commands/preflight_playthroughs.py Makefile CLAUDE.md tests/test_playthrough_preflight.py
git commit -m "Print the preflight, for a log and for a person"
```

---

## Task 7: The fixture run, and the gate

**Files:**
- Test: `tests/test_playthrough_preflight.py`

**Interfaces:**
- Consumes: everything above. Produces nothing.

The fixture proves the walk survives production-shaped data. It cannot prove
the pairing: `anonymize_sample.py:35-36` omits `GameStatusChange`, so
`load_sample_data.py:153`'s backfill appends only the corrective
current-status event, which carries `TemporalValue.unknown()` and therefore no
day. Every endpoint in a fixture-loaded database is `absent`. The test asserts
that outcome rather than a bare zero that would also pass with a broken query.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_preflight.py`:

```python
@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_the_sample_fixture_walks_and_states_why_it_cannot_pair(django_user_model):
    """The fixture holds no legacy status rows, so nothing can pair."""
    owner = django_user_model.objects.create_user(username="sample-owner", password="p")
    call_command("load_sample_data", "--user", owner.username, verbosity=0)

    report = preflight_library(owner.library)
    counts = report.counts
    assert counts.tracked > 0
    assert counts.live_rows > 0
    assert (
        counts.clean_both
        + counts.clean_start_only
        + counts.clean_end_only
        + counts.no_known_endpoint
        + counts.reversed_endpoints
        == counts.live_rows
    )
    #: anonymize_sample omits GameStatusChange, so #676 recorded only
    #: corrective events, and those carry no day.
    assert GameStatusChange.objects.count() == 0
    assert counts.status_events_676 == 0
    assert counts.pairs_unambiguous == 0
    assert counts.pairs_ambiguous == 0
    assert counts.unclaimed_events == 0
    assert counts.pairs_absent > 0
```

- [ ] **Step 2: Run it**

Run: `make test ARGS="tests/test_playthrough_preflight.py -k fixture"`
Expected: PASS. If `counts.pairs_absent` is 0, the fixture holds no dated
`PlayEvent` at all — check `PlayEvent.objects.exclude(started=None, ended=None)`
before changing the assertion.

- [ ] **Step 3: Run the whole gate**

Run: `make check`
Expected: green — lint, format-check, mypy, vale, ts-check, vitest, and the
entire pytest suite including `e2e/`. `tests/test_iterator_guard.py` must pass:
it walks the syntax tree of `games/` and fails on a `.iterator()` call.

- [ ] **Step 4: Commit**

```bash
git add tests/test_playthrough_preflight.py
git commit -m "Walk the sample fixture, and say why it cannot pair"
```

- [ ] **Step 5: Record the production rehearsal on #684**

Not code. Run the command against a restored production copy and post its
machine line on #684, which is what that issue's reconciliation is measured
against:

```bash
make verify-dump KEEP=1
# then, against the printed DATABASE_URL, after `make migrate`:
make preflight-playthroughs ARGS="--all-libraries"
```

The `#676 status events found` line is the check that the run happened after
migration 0033. A zero there against a real library means the backfill has not
run, not that the library has no history.

---

## Self-Review

**Spec coverage.** Convertibility → Task 1. Ordering, including the primary-key
tiebreak → Tasks 1 and 2. Population and its four exclusions → Task 4. The
aggregate anchor → Task 4. Shared and contested rows → Task 5. Pairing, the
component rule and the Python day comparison → Tasks 3 and 5. Output, ordering
of the two halves, `sort_keys`, sample caps and determinism → Task 6.
Command scope arguments, the Makefile target and the CLAUDE.md row → Task 6.
The fixture's stated limit → Task 7. The rehearsal → Task 7, Step 5. The #684
handoff is documented in the spec and needs no code here; the cross-check test
is #684's, and the spec says so.

**Types.** `PreflightCounts` field names are the same strings in
`_VERDICT_FIELDS`, in `f"pairs_{verdict.value}"` and in `PairingVerdict`'s
members — `unambiguous`, `ambiguous`, `absent` — which is what makes that
lookup legal. `Samples` field names match `LibraryPreflight.as_dict()` through
`fields()`. `Endpoint` and `CandidateKey` share `aggregate_id`, `kind` and
`day`, which is what `_endpoint_key` relies on.

**Not deferred.** No step says "add error handling" or "write tests for the
above": every test body and every implementation body is written out.
