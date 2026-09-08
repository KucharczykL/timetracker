# Finish-date statistics implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The statistics page computes every finish from the `Playthrough`
projection's bound columns, and reads no `games__playevents__ended` path.

**Architecture:** One read seam, `games/reads/playthrough_completions.py`, owns
the `PlaythroughFilter` a scope states, executes it against
`library_runs(library)`, and exposes an `Exists` and a `Subquery` shaped for a
Purchase queryset. `games/views/stats_links.py` imports that same filter object
back, so the stat and the link it carries compile one predicate.
`games/views/stats_data.py` reads membership through the `Exists` and the day
through the `Subquery`, one row per Purchase.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pytest + pytest-xdist,
`make` for every command.

**Spec:** `docs/superpowers/specs/2026-09-08-issue-1014-finish-date-statistics-design.md`

## Global Constraints

- Run every command through `make`. No raw `uv run`, `pytest` or `pnpm`.
- `make check-fast` while iterating; full `make check` before declaring done.
- Never write a `GeneratedField`: `completed_lower`, `completed_upper`,
  `started_lower`, `started_upper` are read-only.
- A read wider than one library states its own scope. `library_runs(library)`
  is the scope for every run this plan reads.
- Complete words in identifiers: `completion`, not `compl`; `value`, not `v`.
- `make vale` refuses some words in comments and docs. The act here is a
  **completion**; `finished` stays only where it already names a Purchase-side
  incumbent.
- A test that POSTs through a dispatching view needs
  `@pytest.mark.django_db(transaction=True)`. The read tests below use it
  because `track_game` dispatches a command.

---

### Task 1: The read seam

**Files:**
- Create: `games/reads/playthrough_completions.py`
- Create: `tests/test_playthrough_completions_read.py`

**Interfaces:**
- Consumes: `library_runs` from `games/reads/playthrough_runs.py`;
  `PlaythroughFilter` and `filter_query_context_for_library` from
  `games/filters.py`.
- Produces:
  - `completed_in_scope(year: int | None) -> PlaythroughFilter`
  - `completed_runs(library: UserLibrary, year: int | None) -> QuerySet[Playthrough]`
  - `completion_exists(library: UserLibrary, year: int | None) -> Exists`
  - `completion_day(library: UserLibrary, year: int | None) -> Subquery`

`year=None` means all-time in all four.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_playthrough_completions_read.py`:

```python
"""#1014: what a completion answers, for the statistics."""

import uuid
from datetime import UTC, date, datetime

import pytest
from django.utils import timezone

from games.models import Game, Playthrough, PlaythroughKind, Purchase
from games.reads.playthrough_completions import (
    completed_runs,
    completion_day,
    completion_exists,
)
from games.removal import remove
from games.writes.playergame import new_correlation_id, track_game
from timetracker.temporal import TemporalValue

#: track_game states the first run, which every test reads.
pytestmark = pytest.mark.untracked_games

YEAR = 2024


def _run_for(user, library, name: str) -> Playthrough:
    game = Game.objects.create(library=library, name=name)
    track_game(user, game, correlation_id=new_correlation_id())
    return Playthrough.objects.get(player_game__game=game)


def _complete(run: Playthrough, value: TemporalValue | None) -> Playthrough:
    """State the completion a command would state."""
    Playthrough.objects.filter(pk=run.pk).update(
        completed=value, completion_recorded_at=run.created_at
    )
    run.refresh_from_db()
    return run


def _second_run(run: Playthrough) -> Playthrough:
    """A second ordinary run at the same tracked game."""
    return Playthrough.objects.create(
        id=uuid.uuid7(),
        library=run.library,
        player_game=run.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )


def _purchase_of(library, game) -> Purchase:
    purchase = Purchase.objects.create(
        library=library,
        price_currency="CZK",
        type=Purchase.GAME,
        date_purchased=datetime(YEAR, 1, 5, tzinfo=UTC),
    )
    purchase.games.set([game])
    return purchase


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "day", [date(YEAR, 1, 1), date(YEAR, 6, 1), date(YEAR, 12, 31)]
)
def test_a_day_answers_its_own_year(owned_user, owned_library, day):
    run = _complete(
        _run_for(owned_user, owned_library, "Inside"), TemporalValue.from_day(day)
    )

    assert set(completed_runs(owned_library, YEAR)) == {run}
    assert set(completed_runs(owned_library, YEAR + 1)) == set()


@pytest.mark.django_db(transaction=True)
def test_a_whole_year_answers_that_year(owned_user, owned_library):
    run = _complete(
        _run_for(owned_user, owned_library, "Coarse"), TemporalValue.from_year(YEAR)
    )

    assert set(completed_runs(owned_library, YEAR)) == {run}
    assert set(completed_runs(owned_library, YEAR - 1)) == set()


@pytest.mark.django_db(transaction=True)
def test_a_range_across_new_year_answers_both_years(owned_user, owned_library):
    run = _complete(
        _run_for(owned_user, owned_library, "Spanning"),
        TemporalValue.parse(f"{YEAR}-12-20/{YEAR + 1}-01-10"),
    )

    assert set(completed_runs(owned_library, YEAR)) == {run}
    assert set(completed_runs(owned_library, YEAR + 1)) == {run}


@pytest.mark.django_db(transaction=True)
def test_a_completion_with_no_known_day_answers_all_time_only(
    owned_user, owned_library
):
    run = _complete(_run_for(owned_user, owned_library, "Dayless"), None)

    assert set(completed_runs(owned_library, None)) == {run}
    assert set(completed_runs(owned_library, YEAR)) == set()


@pytest.mark.django_db(transaction=True)
def test_an_open_bound_is_unbounded_on_its_own_side(owned_user, owned_library):
    """The interval handler's rule, which the statistics inherit."""
    run = _complete(
        _run_for(owned_user, owned_library, "Open"),
        TemporalValue.parse(f"../{YEAR}-05-01"),
    )

    assert set(completed_runs(owned_library, YEAR)) == {run}
    assert set(completed_runs(owned_library, YEAR - 25)) == {run}
    assert set(completed_runs(owned_library, YEAR + 1)) == set()


@pytest.mark.django_db(transaction=True)
def test_a_run_with_no_completion_answers_neither_scope(owned_user, owned_library):
    _run_for(owned_user, owned_library, "Started only")

    assert set(completed_runs(owned_library, None)) == set()
    assert set(completed_runs(owned_library, YEAR)) == set()


@pytest.mark.django_db(transaction=True)
def test_a_removed_run_answers_nothing(owned_user, owned_library):
    run = _complete(
        _run_for(owned_user, owned_library, "Removed"),
        TemporalValue.from_day(date(YEAR, 6, 1)),
    )
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    assert set(completed_runs(owned_library, YEAR)) == set()


@pytest.mark.django_db(transaction=True)
def test_a_run_of_a_removed_game_answers_nothing(owned_user, owned_library):
    run = _complete(
        _run_for(owned_user, owned_library, "Gone"),
        TemporalValue.from_day(date(YEAR, 6, 1)),
    )
    remove(run.player_game.game)

    assert set(completed_runs(owned_library, YEAR)) == set()


@pytest.mark.django_db(transaction=True)
def test_a_purchase_answers_the_completion_of_its_game(owned_user, owned_library):
    run = _complete(
        _run_for(owned_user, owned_library, "Bought"),
        TemporalValue.from_day(date(YEAR, 6, 1)),
    )
    purchase = _purchase_of(owned_library, run.player_game.game)

    answered = Purchase.objects.filter(completion_exists(owned_library, YEAR))

    assert list(answered) == [purchase]
    assert not Purchase.objects.filter(completion_exists(owned_library, YEAR + 1))


@pytest.mark.django_db(transaction=True)
def test_a_year_reports_the_earliest_day_and_all_time_the_latest(
    owned_user, owned_library
):
    run = _complete(
        _run_for(owned_user, owned_library, "Twice"),
        TemporalValue.from_day(date(YEAR, 2, 1)),
    )
    _complete(_second_run(run), TemporalValue.from_day(date(YEAR, 11, 1)))
    _purchase_of(owned_library, run.player_game.game)

    in_year = Purchase.objects.annotate(day=completion_day(owned_library, YEAR)).get()
    all_time = Purchase.objects.annotate(day=completion_day(owned_library, None)).get()

    assert in_year.day == date(YEAR, 2, 1)
    assert all_time.day == date(YEAR, 11, 1)


@pytest.mark.django_db(transaction=True)
def test_a_purchase_with_no_completion_reports_no_day(owned_user, owned_library):
    run = _run_for(owned_user, owned_library, "Unfinished")
    _purchase_of(owned_library, run.player_game.game)

    assert (
        Purchase.objects.annotate(day=completion_day(owned_library, YEAR)).get().day
        is None
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_completions_read.py -x"`
Expected: collection error — `ModuleNotFoundError: No module named
'games.reads.playthrough_completions'`.

- [ ] **Step 3: Write the seam**

Create `games/reads/playthrough_completions.py`:

```python
"""What a completion answers, for the statistics.

One object per scope, so a statistic and the link it carries
compile one predicate. The interval handler states three
parts, and restating two of them would answer differently
for an open bound.
"""

from django.db.models import Exists, Max, Min, OuterRef, QuerySet, Subquery

from games.filters import PlaythroughFilter, filter_query_context_for_library
from games.models import Playthrough, UserLibrary
from games.reads.playthrough_runs import library_runs

#: A calendar year, or None for every year at once.
type YearScope = int | None


def completed_in_scope(year: YearScope) -> PlaythroughFilter:
    """The filter a scope states.

    All-time reads the act, not the day. A year reads the
    interval the endpoint states, which overlaps.
    """
    if year is None:
        return PlaythroughFilter.where(is_completed=True)
    return PlaythroughFilter.where(
        completed__between=(f"{year}-01-01", f"{year}-12-31")
    )


def completed_runs(library: UserLibrary, year: YearScope) -> QuerySet[Playthrough]:
    """The live ordinary runs a completion in scope names."""
    context = filter_query_context_for_library(library)
    return library_runs(library).filter(completed_in_scope(year).to_q(context))


def _runs_of_the_purchase(
    library: UserLibrary, year: YearScope
) -> QuerySet[Playthrough]:
    """Those runs, correlated to the Purchase being read."""
    return completed_runs(library, year).filter(
        player_game__game__purchases=OuterRef("pk")
    )


def completion_exists(library: UserLibrary, year: YearScope) -> Exists:
    """Whether a Purchase names a game completed in scope."""
    return Exists(_runs_of_the_purchase(library, year))


def completion_day(library: UserLibrary, year: YearScope) -> Subquery:
    """The day a Purchase reports for its completion in scope.

    A year reports its earliest completion and all-time its
    latest, so each table reports the finish its own order
    leads with. The day is the earliest one the value names.
    """
    reducer = Max("completed_lower") if year is None else Min("completed_lower")
    return Subquery(
        _runs_of_the_purchase(library, year)
        .values("player_game__game__purchases")
        .annotate(day=reducer)
        .values("day")[:1]
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_completions_read.py -x"`
Expected: PASS, 14 tests.

If `test_an_open_bound_is_unbounded_on_its_own_side` fails, do **not** relax it:
it states the handler's rule, and a failure means `completed_runs` is not
executing the handler.

- [ ] **Step 5: Commit**

```bash
git add games/reads/playthrough_completions.py tests/test_playthrough_completions_read.py
git commit -m "Read a completion in scope"
```

---

### Task 2: The link builder reads the seam

**Files:**
- Modify: `games/views/stats_links.py:134-144`
- Test: `tests/test_stats_links.py` (unchanged, must stay green)

**Interfaces:**
- Consumes: `completed_in_scope` from Task 1.
- Produces: no new name. `_completed_in_scope(year)` keeps its call sites in
  `stats_links.py`; only its body moves.

- [ ] **Step 1: Replace the body**

In `games/views/stats_links.py`, add to the imports:

```python
from games.reads.playthrough_completions import completed_in_scope
```

Replace the whole `_completed_in_scope` function with:

```python
def _completed_in_scope(year) -> PlaythroughFilter:
    """A finish: a run completed in scope.

    The scope's own word, read from the seam the statistics
    read. `year` carries the all-time sentinel here; the seam
    takes None for it.
    """
    return completed_in_scope(year if _is_year(year) else None)
```

- [ ] **Step 2: Run the parity tests**

Run: `make test ARGS="tests/test_stats_links.py tests/test_stats_content_links.py"`
Expected: PASS. The compiled predicate is unchanged, so a failure here means the
sentinel translation is wrong.

- [ ] **Step 3: Commit**

```bash
git add games/views/stats_links.py
git commit -m "Read the scope filter from the seam"
```

---

### Task 3: The finish predicates

**Files:**
- Modify: `games/models.py:929-938` (`PurchaseQueryset.finished`)
- Modify: `games/views/stats_data.py:138-160` (the scope block)
- Create: `tests/test_stats_finish_reads.py`

**Interfaces:**
- Consumes: `completion_exists` from Task 1.
- Produces: `completed_q`, a local `Q` in
  `_compute_stats_from_scoped_querysets` replacing `ended_q`. Task 4 reads it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stats_finish_reads.py`:

```python
"""#1014: the statistics read a run, not a legacy row."""

import uuid
from datetime import UTC, date, datetime

import pytest
from django.utils import timezone

from games.models import Game, PlayEvent, Playthrough, PlaythroughKind, Purchase
from games.removal import remove
from games.views.stats_data import compute_stats
from games.writes.playergame import new_correlation_id, track_game
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games

YEAR = 2024


def _bought_and_completed(
    user, library, name: str, day: date | None = None
) -> Playthrough:
    game = Game.objects.create(library=library, name=name)
    track_game(user, game, correlation_id=new_correlation_id())
    purchase = Purchase.objects.create(
        library=library,
        price_currency="CZK",
        type=Purchase.GAME,
        date_purchased=datetime(YEAR, 1, 5, tzinfo=UTC),
    )
    purchase.games.set([game])
    run = Playthrough.objects.get(player_game__game=game)
    if day is not None:
        Playthrough.objects.filter(pk=run.pk).update(
            completed=TemporalValue.from_day(day), completion_recorded_at=run.created_at
        )
        run.refresh_from_db()
    return run


@pytest.mark.django_db(transaction=True)
def test_a_completed_run_leaves_the_backlog(owned_user, owned_library):
    _bought_and_completed(owned_user, owned_library, "Done", date(YEAR, 6, 1))

    data = compute_stats(owned_library, YEAR)

    assert data["all_finished_this_year_count"] == 1
    assert data["purchased_unfinished_count"] == 0


@pytest.mark.django_db(transaction=True)
def test_a_legacy_row_alone_counts_for_nothing(owned_user, owned_library):
    """The only test that writes the legacy table."""
    run = _bought_and_completed(owned_user, owned_library, "Legacy only")
    PlayEvent.objects.create(
        game=run.player_game.game, ended=datetime(YEAR, 6, 1, tzinfo=UTC)
    )

    data = compute_stats(owned_library, YEAR)

    assert data["all_finished_this_year_count"] == 0
    assert data["purchased_unfinished_count"] == 1


@pytest.mark.django_db(transaction=True)
def test_a_removed_run_counts_for_nothing(owned_user, owned_library):
    run = _bought_and_completed(owned_user, owned_library, "Removed", date(YEAR, 6, 1))
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    data = compute_stats(owned_library, YEAR)

    assert data["all_finished_this_year_count"] == 0
    assert data["purchased_unfinished_count"] == 1


@pytest.mark.django_db(transaction=True)
def test_a_completion_with_no_known_day_counts_all_time_only(owned_user, owned_library):
    run = _bought_and_completed(owned_user, owned_library, "Dayless")
    Playthrough.objects.filter(pk=run.pk).update(completion_recorded_at=run.created_at)

    assert compute_stats(owned_library, YEAR)["all_finished_this_year_count"] == 0
    assert compute_stats(owned_library, None)["backlog_decrease_count"] == 1


@pytest.mark.django_db(transaction=True)
def test_a_removed_game_supplies_no_completion(owned_user, owned_library):
    run = _bought_and_completed(owned_user, owned_library, "Gone", date(YEAR, 6, 1))
    remove(run.player_game.game)

    assert compute_stats(owned_library, YEAR)["all_finished_this_year_count"] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_stats_finish_reads.py -x"`
Expected: FAIL. `test_a_legacy_row_alone_counts_for_nothing` asserts 0 and gets
1, because the statistics still read `games_playevent`.

- [ ] **Step 3: Switch `PurchaseQueryset.finished`**

In `games/models.py`, replace the `finished` method body with:

```python
def finished(self, library):
    #: The status lives on the library's row, the completion on its run.
    from games.reads.playthrough_completions import completion_exists

    return self.filter(
        Q(games__in=Game.objects.tracked_by(library, tracked__status__in=DONE_STATUSES))
        | Q(completion_exists(library, None))
    ).distinct()
```

The import is local because `games.filters` imports `games.models`. `distinct()`
stays: the done-status half still opens the M2M join and still fans a bundle
out.

- [ ] **Step 4: Switch the scope block**

In `games/views/stats_data.py`, add to the imports:

```python
from games.reads.playthrough_completions import completion_day, completion_exists
```

Delete the `ended_q = ...` line from **both** branches of the `if is_alltime:`
scope block, and put this immediately after that block, above `done = ...`:

```python
completed_q = Q(completion_exists(library, None if is_alltime else year))
```

Then change the `not_finished_q` line to read:

```python
not_finished_q = ~Q(games__in=done) & ~completed_q
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_stats_finish_reads.py tests/test_stats_reads_the_projection.py -x"`
Expected: PASS.

Then run the parity tests, which still hold their bridge fixture:
`make test ARGS="tests/test_stats.py tests/test_stats_links.py tests/test_stats_content_links.py"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add games/models.py games/views/stats_data.py tests/test_stats_finish_reads.py
git commit -m "Read the finish predicate from the projection"
```

---

### Task 4: The finished lists

**Files:**
- Modify: `games/views/stats_data.py:244-278` and `:360-381`
- Modify: `games/views/stats_content.py:101-111` (`_purchase_name`)
- Test: `tests/test_stats_finish_reads.py` (append)

**Interfaces:**
- Consumes: `completed_q` from Task 3, `completion_day` from Task 1.
- Produces: `date_finished`, an annotation on each finished queryset, holding a
  `date` or `None`. `game_name` is gone; nothing may read it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stats_finish_reads.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_a_year_reports_one_row_at_its_earliest_completion(owned_user, owned_library):
    """Two completions of one game were two rows, and are one."""
    run = _bought_and_completed(owned_user, owned_library, "Twice", date(YEAR, 2, 1))
    second = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )
    Playthrough.objects.filter(pk=second.pk).update(
        completed=TemporalValue.from_day(date(YEAR, 11, 1)),
        completion_recorded_at=second.created_at,
    )

    data = compute_stats(owned_library, YEAR)
    rows = list(data["all_finished_this_year"])

    assert data["all_finished_this_year_count"] == 1
    assert [row.date_finished for row in rows] == [date(YEAR, 2, 1)]


@pytest.mark.django_db(transaction=True)
def test_a_bundle_reports_one_row_for_two_completed_games(owned_user, owned_library):
    first = _bought_and_completed(
        owned_user, owned_library, "Bundle A", date(YEAR, 3, 1)
    )
    second_game = Game.objects.create(library=owned_library, name="Bundle B")
    track_game(owned_user, second_game, correlation_id=new_correlation_id())
    second = Playthrough.objects.get(player_game__game=second_game)
    Playthrough.objects.filter(pk=second.pk).update(
        completed=TemporalValue.from_day(date(YEAR, 9, 1)),
        completion_recorded_at=second.created_at,
    )
    purchase = Purchase.objects.get(games=first.player_game.game)
    purchase.games.add(second_game)

    data = compute_stats(owned_library, YEAR)

    assert data["all_finished_this_year_count"] == 1
    assert [row.date_finished for row in data["all_finished_this_year"]] == [
        date(YEAR, 3, 1)
    ]


@pytest.mark.django_db(transaction=True)
def test_a_row_with_no_day_sorts_last(owned_user, owned_library):
    """A year's table ascends, and a dateless row trails it."""
    dated = _bought_and_completed(owned_user, owned_library, "Dated", date(YEAR, 6, 1))
    dayless = _bought_and_completed(owned_user, owned_library, "Dayless", None)
    Playthrough.objects.filter(pk=dayless.pk).update(
        completion_recorded_at=dayless.created_at
    )
    assert dated.completed_lower == date(YEAR, 6, 1)

    rows = list(compute_stats(owned_library, YEAR)["all_finished_this_year"])

    assert [row.date_finished for row in rows] == [date(YEAR, 6, 1)]
```

The dateless completion answers all-time and answers no year, so the per-year
table holds one row. To see the ordering rule itself, state the second
completion as a day in the year and read the pair back:

```python
@pytest.mark.django_db(transaction=True)
def test_a_year_ascends_from_its_first_finish(owned_user, owned_library):
    _bought_and_completed(owned_user, owned_library, "Later", date(YEAR, 9, 1))
    _bought_and_completed(owned_user, owned_library, "Earlier", date(YEAR, 2, 1))

    rows = list(compute_stats(owned_library, YEAR)["all_finished_this_year"])

    assert [row.date_finished for row in rows] == [date(YEAR, 2, 1), date(YEAR, 9, 1)]
```

The `nulls_last` rule bites on the one row a year can hold with no day: a
completion whose lower bound is open answers the year and reports nothing.

```python
@pytest.mark.django_db(transaction=True)
def test_a_row_with_an_open_lower_bound_sorts_last(owned_user, owned_library):
    _bought_and_completed(owned_user, owned_library, "Dated", date(YEAR, 6, 1))
    open_run = _bought_and_completed(owned_user, owned_library, "Open", None)
    Playthrough.objects.filter(pk=open_run.pk).update(
        completed=TemporalValue.parse(f"../{YEAR}-05-01"),
        completion_recorded_at=open_run.created_at,
    )

    rows = list(compute_stats(owned_library, YEAR)["all_finished_this_year"])

    assert [row.date_finished for row in rows] == [date(YEAR, 6, 1), None]
```

The per-year tables are the only ones that render rows: the all-time scope sets
`this_year_finished_this_year_count` and `backlog_decrease_count` and no row
list. Its `-date_finished` ordering therefore reaches no screen, and the
annotation costs nothing, because Django strips an annotation `count()` does not
read.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_stats_finish_reads.py -x -k 'earliest or bundle or dateless'"`
Expected: FAIL — `AttributeError: 'Purchase' object has no attribute
'date_finished'` for the year branch, or a count of 2 where 1 is asserted.

- [ ] **Step 3: Rewrite the finished block**

In `games/views/stats_data.py`, replace the whole
`# ── Finished purchases (scope-divergent) ──` block with:

```python
if is_alltime:
    finished = library_purchases.finished(library).annotate(
        date_finished=completion_day(library, None)
    )
    finished_released = finished.order_by(F("date_finished").desc(nulls_last=True))
    backlog_decrease_count = finished.count()
else:
    finished = library_purchases.filter(completed_q).annotate(
        date_finished=completion_day(library, year)
    )
    finished_released = (
        finished.filter(games__year_released=year)
        .distinct()
        .order_by(F("date_finished").asc(nulls_last=True))
    )
    purchased_finished = (
        without_refunded.filter(completed_q)
        .annotate(date_finished=completion_day(library, year))
        .order_by(F("date_finished").asc(nulls_last=True))
    )
    backlog_decrease_count = (
        library_purchases.filter(date_purchased__year__lt=year)
        .filter(games__in=done)
        .filter(completed_q)
        .count()
    )
```

Three things to see in that block:

- the `game_name` annotation is gone from both querysets, because a value read
  off a joined row is what fans the row out;
- the per-year branch drops the `.finished(library)` prefix. A completion in the
  year is a completion all-time, so the prefix was implied, and it opened an M2M
  join for nothing;
- `finished_released` states `.distinct()` of its own. Its
  `games__year_released` filter opens that join again, and a bundle of two games
  released in the year would otherwise report two rows. It inherited the
  `distinct()` from the dropped prefix before.

`backlog_decrease_count` keeps its `games__in=done` join and states no
`distinct()`, exactly as today. That join's duplication is the bundle
disagreement #765 owns, and this issue neither closes it nor widens it.

- [ ] **Step 4: Rewrite the per-year data entries**

In the same file, in the `if not is_alltime:` tail, replace the three ordered
entries with:

```python
data["all_finished_this_year"] = finished.prefetch_related("games").order_by(
    F("date_finished").asc(nulls_last=True)
)
data["all_finished_this_year_count"] = finished.count()
data["this_year_finished_this_year"] = finished_released.prefetch_related("games")
data["purchased_this_year_finished_this_year"] = purchased_finished.prefetch_related(
    "games"
)
```

- [ ] **Step 5: Remove the dead imports**

`Subquery` and `OuterRef` are no longer used in `stats_data.py`. Take both out
of the `django.db.models` import list. `Max` stays — the spending aggregate
reads it.

Run: `make lint`
Expected: no unused-import finding.

- [ ] **Step 6: Repair the row name**

In `games/views/stats_content.py`, in `_purchase_name`, change the non-game
branch to read:

```python
if purchase.type != "game":
    name = game_name or purchase.standardized_name
    link = GameLink(first_game, name)
    suffix = f" ({first_game.name} {purchase.get_type_display()})"
    return Safe(str(link) + conditional_escape(suffix))
```

Only the second line changes; keep the branch at its function indentation.

`purchase.name` is blank by default, so without this the DLC row renders an
empty link. `standardized_name` is the Purchase's own name or its first game's.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_stats_finish_reads.py tests/test_stats.py tests/test_stats_links.py tests/test_stats_content_links.py tests/test_rendered_pages.py -x"`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add games/views/stats_data.py games/views/stats_content.py tests/test_stats_finish_reads.py
git commit -m "Report a finish day from the projection"
```

---

### Task 5: Drop the bridge

**Files:**
- Modify: `tests/test_stats_links.py:64-71` and `:502-507`
- Modify: `tests/test_stats_content_links.py:96`

**Interfaces:**
- Consumes: nothing. This task removes the last legacy write from the stats
  fixtures.
- Produces: fixtures whose only record of a finish is the projection.

- [ ] **Step 1: Take the legacy writes out of `tests/test_stats_links.py`**

Delete the `PlayEvent.objects.create(...)` call and its comment in both places,
keeping the `Playthrough.objects.filter(...).update(...)` beside each. The first
becomes:

```python
#: The run a conversion leaves, day-precision.
Playthrough.objects.filter(player_game__game=finished_game).update(
    completion_recorded_at=timezone.now(),
    completed=TemporalValue.from_day(date(YEAR, 8, 1)),
)
```

Keep the fixture's own indentation. Then take `PlayEvent` out of the
`games.models` import line.

- [ ] **Step 2: Give `tests/test_stats_content_links.py` a completion**

Replace its `PlayEvent.objects.create(game=finished_game, ended=_dt(8, 1))` line
with the projection statement, and drop `PlayEvent` from its imports:

```python
Playthrough.objects.filter(player_game__game=finished_game).update(
    completion_recorded_at=timezone.now(),
    completed=TemporalValue.from_day(date(YEAR, 8, 1)),
)
```

Add whatever of `date`, `timezone`, `Playthrough` and `TemporalValue` that file
does not already import.

- [ ] **Step 3: Run both files**

Run: `make test ARGS="tests/test_stats_links.py tests/test_stats_content_links.py"`
Expected: PASS. Eight parity tests in the first file failed on this fixture
before Task 3; they pass now because both sides read one source.

- [ ] **Step 4: Confirm the statistics read no legacy path**

Run: `grep -rn "playevents" games/views/ games/models.py`
Expected: no hit in `stats_data.py`, `stats_links.py`, `stats_content.py` or
`PurchaseQueryset`. The remaining hits are `games/views/purchase.py` and
`games/sorting.py`, both #1026's.

- [ ] **Step 5: Commit**

```bash
git add tests/test_stats_links.py tests/test_stats_content_links.py
git commit -m "Drop the stats fixtures' legacy half"
```

---

### Task 6: The evidence and the gate

**Files:**
- Create: `/tmp/dump_finish_stats.py` (throwaway, never committed)

**Interfaces:**
- Consumes: everything above.
- Produces: the pull-request evidence the wave's verification contract asks for.

- [ ] **Step 1: Run the full gate**

Run: `make check`
Expected: green, including `e2e/`. A hand-picked subset is not the gate.

- [ ] **Step 2: Restore a production copy**

Run: `make restore-dump`
It prints a `DATABASE_URL`. Use that database for the next step, and run
`make migrate` against it first so the projection tables and the #684 conversion
are present.

- [ ] **Step 3: Write the throwaway dump script**

One script, run on both revisions, so neither side is a hand-copied query.
Create `/tmp/dump_finish_stats.py`:

```python
"""Throwaway (#1014): dump the finish statistics for a diff."""

import json
import os

from common.time import available_stats_year_range
from games.models import UserLibrary
from games.views.stats_data import compute_stats

KEYS = (
    "all_finished_this_year_count",
    "this_year_finished_this_year_count",
    "purchased_unfinished_count",
    "dropped_count",
    "backlog_decrease_count",
    "unfinished_purchases_percent",
)


def dump_finish_statistics() -> dict:
    report: dict = {}
    for library in UserLibrary.objects.order_by("pk"):
        per_scope: dict = {}
        for year in [None, *available_stats_year_range()]:
            data = compute_stats(library, year)
            per_scope[str(year)] = {key: data.get(key) for key in KEYS}
        report[str(library.pk)] = per_scope
    return report


with open(os.environ["FINISH_STATS_OUT"], "w") as output:
    json.dump(dump_finish_statistics(), output, indent=2, sort_keys=True)
```

It writes a file rather than printing, so the shell's banner stays out of the
JSON. `available_stats_year_range()` runs back to 2000, so expect about 27
scopes per library.

- [ ] **Step 4: Run it on both revisions**

Point both runs at the one restored database, whose `DATABASE_URL` Step 2
printed. Take the new numbers first:

```bash
DATABASE_URL=<restored> FINISH_STATS_OUT=/tmp/finish-stats-new.json \
  make shell < /tmp/dump_finish_stats.py
```

Then the legacy numbers, from a worktree at the branch point, which reads the
same database and the same script:

```bash
git worktree add /tmp/legacy-1014 "$(git merge-base HEAD main)"
cd /tmp/legacy-1014 && DATABASE_URL=<restored> \
  FINISH_STATS_OUT=/tmp/finish-stats-legacy.json \
  make shell < /tmp/dump_finish_stats.py
```

Diff them: `diff -u /tmp/finish-stats-legacy.json /tmp/finish-stats-new.json`.

Remove the worktree afterwards: `git worktree remove /tmp/legacy-1014`.

- [ ] **Step 5: Classify every difference**

Each one must belong to a class the spec states, and the legacy number is the
higher one in all three:

1. a Purchase whose games hold more than one completion in the scope — two
   completions of one game, or a bundle with a completion on two games;
2. a removed run supplied the legacy number;
3. a removed Game supplied the legacy number.

Name the Purchase behind a difference with this, in `make shell` against the
restored database, reading the library and year the diff points at:

```python
from django.db.models import Count, Q

from games.models import Purchase

year = 2023
candidates = (
    Purchase.objects.for_library(library)
    .annotate(
        completions=Count(
            "games__playevents",
            filter=Q(games__playevents__ended__year=year),
        ),
        removed_runs=Count(
            "games__playevents",
            filter=Q(
                games__playevents__ended__year=year, games__removed_at__isnull=False
            ),
        ),
    )
    .filter(Q(completions__gt=1) | Q(removed_runs__gt=0))
)
for purchase in candidates:
    print(
        purchase.pk,
        purchase.standardized_name,
        purchase.completions,
        purchase.removed_runs,
    )
```

A difference no Purchase in that list explains is a defect: stop, and find it
before opening the pull request.

- [ ] **Step 6: Drop the restored copy**

Run: `make verify-dump`
It restores, migrates and drops on success. Use `KEEP=1` only while still
investigating.

- [ ] **Step 7: Open the pull request**

Body states: what moved, the three value classes, the compare output per class,
and the two disagreements this issue does not close (a bundle's quantifier, an
untracked game), each with its owning issue. Link the spec.

---

## Notes for the executor

- **Do not** widen this into `games/sorting.py`, `games/views/purchase.py` or
  `games/api.py`. #1026 and #1015 own those, and they run in parallel with this
  one.
- **Do not** try to make the stat and its link agree for a bundle or for an
  untracked game. Both divergences predate this issue, both are measured in the
  spec, and the filter audit (#765 to #767) owns them.
- If a test needs a second run at one game, build the projection row directly as
  Task 1's `_second_run` does. A read-level test states the row a command would
  write; it does not have to dispatch one.
- `pytest.mark.untracked_games` is what lets a test create a `Game` and then
  call `track_game` itself. Without it the suite tracks every game for you.
