# Playthrough detail read cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Game detail reads the Playthrough projection — the section, both
counts, and the edit and remove routes — so no screen it renders reads
`games_playevent`.

**Architecture:** Three read helpers land first (`numbered_for`,
`days_to_finish`, the two count reads), then one new row-builder module, then
the three surfaces flip onto them one at a time. The last flip moves the edit
and remove route ids from the legacy row to the run, which forces the
still-legacy list page to translate its own action ids through the provenance
map; those two changes are one task because neither is correct without the
other.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pytest + pytest-django,
the Python component system in `common/components/`.

**Spec:** `docs/superpowers/specs/2026-09-07-issue-1012-playthrough-detail-read-cutover-design.md`

## Global Constraints

- Python 3.14 only. Run everything through `make`; never bare `uv run`,
  `pytest` or `pnpm`.
- `make check-fast` while iterating. The gate before done is the full
  `make check`, `e2e/` included.
- Never write to a `GeneratedField`: `started_lower`, `started_upper`,
  `completed_lower`, `completed_upper`, `days_to_finish` on `PlayEvent`.
- Refused words, enforced by `make vale` over docs and comments: `fold`,
  `delete`, `archive`, `tombstone`, `heal`. A projector *replays*; the row it
  leaves is a *projection*.
- Unabbreviated identifiers in Python and TypeScript.
- Build UI with `common.components` builders in htpy form
  (`Builder(class_="x")[child]`), never HTML strings.
- One act, one verb. The column is `<act>_at`.
- Reads wider than one library name the read layer's verb; a command scopes a
  resolve through `games/commands/scope.py`. This issue adds no command.
- A test that POSTs through a dispatching view needs
  `@pytest.mark.django_db(transaction=True)`.
- Never `instance.delete()`. Never `QuerySet.iterator()`.

---

### Task 1: `numbered_for`, the numbering's first caller

`with_display_number` partitions over whatever the caller selected, so a
queryset already narrowed to one row numbers it 1. `numbered_for` takes the
tracked games and the library instead, so the partition cannot be narrowed by
the caller.

**Files:**
- Modify: `games/reads/playthrough_numbering.py`
- Test: `tests/test_playthrough_numbering.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `DISPLAY_ORDER: tuple[OrderBy | str, ...]` — the window's four order
    fields, reused as a screen's `order_by`.
  - `numbered_for(library: UserLibrary, player_game_ids: Iterable[PlayerGameId]) -> QuerySet[Playthrough]`
  - `type PlayerGameId = uuid.UUID`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_numbering.py`. The file already has
`tracked` and `make_run` fixtures at the top; read them before writing, and
add a second tracked game fixture beside them.

```python
def a_second_tracked_game(library, name="Tunic"):
    game = Game.objects.create(library=library, name=name)
    return PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=library,
        game=game,
        tracked_at=timezone.now(),
    )


def test_numbered_for_answers_the_same_number_asked_alone_or_beside_others(
    owned_library, tracked
):
    """The partition is the game, never the caller's selection."""
    other = a_second_tracked_game(owned_library)
    make_run(other, started=TemporalValue.from_day(date(2020, 1, 1)))
    first = make_run(tracked, started=TemporalValue.from_day(date(2021, 1, 1)))
    second = make_run(tracked, started=TemporalValue.from_day(date(2022, 1, 1)))

    alone = {
        run.pk: run.display_number for run in numbered_for(owned_library, [tracked.pk])
    }
    together = {
        run.pk: run.display_number
        for run in numbered_for(owned_library, [tracked.pk, other.pk])
    }

    assert alone == {first.pk: 1, second.pk: 2}
    assert together[first.pk] == 1
    assert together[second.pk] == 2


def test_numbered_for_counts_across_neither_a_removed_run_nor_a_bucket(
    owned_library, tracked
):
    first = make_run(tracked, started=TemporalValue.from_day(date(2021, 1, 1)))
    make_run(
        tracked,
        started=TemporalValue.from_day(date(2021, 6, 1)),
        removed_at=timezone.now(),
    )
    make_run(
        tracked,
        started=TemporalValue.from_day(date(2021, 7, 1)),
        kind=PlaythroughKind.IMPORTED_HISTORY,
    )
    last = make_run(tracked, started=TemporalValue.from_day(date(2022, 1, 1)))

    numbers = {
        run.pk: run.display_number for run in numbered_for(owned_library, [tracked.pk])
    }

    assert numbers == {first.pk: 1, last.pk: 2}


def test_numbered_for_counts_across_no_run_naming_another_librarys_game(
    owned_library, tracked, django_user_model
):
    """Drift belongs to neither partition.

    A run whose own library and whose parent's library
    disagree is what `audit_library_ownership` reports. The
    library holding the row filters it out by the parent;
    the library holding the parent never names the row.
    """
    stranger = django_user_model.objects.create_user(
        username="numbering-stranger", password="p"
    )
    drifted = make_run(tracked, started=TemporalValue.from_day(date(2021, 1, 1)))
    Playthrough.objects.filter(pk=drifted.pk).update(library=stranger.library)

    assert list(numbered_for(owned_library, [tracked.pk])) == []
    assert list(numbered_for(stranger.library, [tracked.pk])) == []


def test_numbered_for_renders_the_numbers_down_the_page_in_order(
    owned_library, tracked
):
    late = make_run(tracked, started=TemporalValue.from_day(date(2022, 1, 1)))
    early = make_run(tracked, started=TemporalValue.from_day(date(2021, 1, 1)))

    ordered = list(numbered_for(owned_library, [tracked.pk]))

    assert [run.pk for run in ordered] == [early.pk, late.pk]
    assert [run.display_number for run in ordered] == [1, 2]
```

Add `from datetime import date` and `numbered_for` to the existing imports.
`make_run` in that file passes `**columns` straight to
`Playthrough.objects.create`, so `removed_at=` and `kind=` ride through it;
confirm that when you read it, and pass the values the same way.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_numbering.py -k numbered_for"`
Expected: FAIL, `ImportError: cannot import name 'numbered_for'`.

- [ ] **Step 3: Write the implementation**

In `games/reads/playthrough_numbering.py`, lift the window's order tuple into
a module constant and add the new function. Replace the inline `order_by=(...)`
in `with_display_number` with `order_by=DISPLAY_ORDER`.

```python
"""Playthrough N, derived at read time."""

import uuid
from collections.abc import Iterable

from django.db.models import F, OrderBy, QuerySet, Window
from django.db.models.functions import RowNumber

from games.models import Playthrough, PlaythroughKind, UserLibrary

#: A tracked game's key, as a caller holds it.
type PlayerGameId = uuid.UUID

#: The window's order, and the order a screen renders in.
#: A screen that ordered by anything else would print 2 above 1.
DISPLAY_ORDER: tuple[OrderBy | str, ...] = (
    F("started_lower").asc(nulls_last=True),
    F("completed_lower").asc(nulls_last=True),
    "created_at",
    "id",
)
```

```python
def numbered_for(
    library: UserLibrary, player_game_ids: Iterable[PlayerGameId]
) -> QuerySet[Playthrough]:
    """Every live ordinary run of these tracked games, numbered.

    The partition is whatever the caller selected, so
    `with_display_number` over a queryset narrowed to one row
    numbers it 1 and no exception marks it. This takes the
    games instead, so the caller narrows afterwards or not at
    all.

    The library is stated beside the games, never inferred,
    and scoped on the row and on its parent alike: a run
    naming another library's tracked game is the drift
    `audit_library_ownership` reports, and numbering it under
    either library would disagree with `live_ordinary_runs`,
    which is the partition a removal counts across.
    """
    return with_display_number(
        Playthrough.objects.filter(
            library=library,
            player_game__library=library,
            player_game_id__in=list(player_game_ids),
        )
    ).order_by(*DISPLAY_ORDER)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_numbering.py"`
Expected: PASS, the whole file.

- [ ] **Step 5: Commit**

```bash
git add games/reads/playthrough_numbering.py tests/test_playthrough_numbering.py
git commit -m "Number a game's runs without letting the caller narrow the partition"
```

---

### Task 2: The day span a run states

**Files:**
- Modify: `games/reads/playthrough_endpoints.py`
- Test: `tests/test_playthrough_endpoints_read.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `days_to_finish(run: Playthrough) -> int | None` — the widest span
  the two endpoints allow, or `None` for a pair that states no length.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_endpoints_read.py`. That file already has a
`run` fixture and a `_state(run, **values)` helper that `UPDATE`s columns a
command would state; read both before writing. Every case has to refresh the
row, because the two bound columns are generated.

```python
def _spanning(run, started, completed):
    """State both endpoints and read the row back."""
    _state(
        run,
        started=started,
        start_recorded_at=timezone.now(),
        completed=completed,
        completion_recorded_at=timezone.now(),
    )
    run.refresh_from_db()
    return run


@pytest.mark.django_db
def test_days_to_finish_reads_the_widest_span(run):
    spanning = _spanning(
        run,
        TemporalValue.from_day(date(2026, 1, 1)),
        TemporalValue.from_month(2026, 3),
    )

    assert days_to_finish(spanning) == 89


@pytest.mark.django_db
def test_days_to_finish_reads_one_for_a_run_begun_and_finished_on_a_day(run):
    day = TemporalValue.from_day(date(2026, 1, 1))
    spanning = _spanning(run, day, day)

    assert days_to_finish(spanning) == 1


@pytest.mark.django_db
def test_days_to_finish_states_nothing_where_a_bound_is_absent(run):
    #: The completion happened; nobody knows the day.
    _state(
        run,
        started=TemporalValue.from_day(date(2026, 1, 1)),
        start_recorded_at=timezone.now(),
        completed=None,
        completion_recorded_at=timezone.now(),
    )
    run.refresh_from_db()

    assert days_to_finish(run) is None


@pytest.mark.django_db
def test_days_to_finish_states_nothing_for_a_completion_before_the_start(run):
    """A backwards pair is not a length.

    The legacy column coalesced it to 0, which read as a real
    one. #684 converts such rows by appending events, past
    the command that would refuse them, so they reach a
    screen.
    """
    spanning = _spanning(
        run,
        TemporalValue.from_day(date(2026, 3, 1)),
        TemporalValue.from_day(date(2026, 1, 1)),
    )

    assert days_to_finish(spanning) is None
```

Add `from django.utils import timezone` and `days_to_finish` to the imports.
Verify the 89 by hand before running: 2026-01-01 to the last day of March 2026
is 2026-03-31, and `(date(2026, 3, 31) - date(2026, 1, 1)).days` is 89.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_endpoints_read.py -k days_to_finish"`
Expected: FAIL, `ImportError: cannot import name 'days_to_finish'`.

- [ ] **Step 3: Write the implementation**

Append to `games/reads/playthrough_endpoints.py`:

```python
def days_to_finish(run: Playthrough) -> int | None:
    """How long the run took, or nothing.

    The widest span the two endpoints allow: the completion's
    last possible day less the start's first. A run that
    states a month reports the days that month could hold
    rather than nothing.

    Equal bounds read 1, as the legacy column did for a run
    begun and finished on one day. Nothing where either bound
    is absent, which covers an endpoint with no act and an
    endpoint whose day nobody knows alike, and nothing where
    the completion precedes the start.
    """
    started = run.started_lower
    completed = run.completed_upper
    if started is None or completed is None:
        return None
    if completed == started:
        return 1
    span = (completed - started).days
    return span if span > 0 else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_endpoints_read.py"`
Expected: PASS, the whole file.

- [ ] **Step 5: Commit**

```bash
git add games/reads/playthrough_endpoints.py tests/test_playthrough_endpoints_read.py
git commit -m "Read the widest span two endpoints allow"
```

---

### Task 3: The tracked game, and how many times it was played through

**Files:**
- Modify: `games/reads/playthrough_runs.py`
- Test: `tests/test_playthrough_runs_read.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `tracked_game(library: UserLibrary, game: Game) -> PlayerGame | None`
  - `completed_run_count(library: UserLibrary, player_game: PlayerGame | None) -> int`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_runs_read.py`. It already has a `game`
fixture, an `a_tracked_game(owned_user, game)` helper and an
`a_second_run(owned_user, owned_library, game)` helper; read all three first.
The module carries `pytestmark = pytest.mark.untracked_games`, so a `Game`
here holds no run until something states one.

```python
@pytest.mark.django_db(transaction=True)
def test_tracked_game_answers_the_row_this_library_tracks(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)

    assert tracked_game(owned_library, game) == tracked


@pytest.mark.django_db
def test_tracked_game_answers_nothing_for_a_game_no_library_tracks(owned_library, game):
    assert tracked_game(owned_library, game) is None


@pytest.mark.django_db(transaction=True)
def test_completed_run_count_skips_the_run_tracking_states(
    owned_user, owned_library, game
):
    """#679 gives a tracked game a run nobody played."""
    tracked = a_tracked_game(owned_user, game)

    assert completed_run_count(owned_library, tracked) == 0


@pytest.mark.django_db(transaction=True)
def test_completed_run_count_counts_a_completion_whose_day_is_unknown(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)
    run = Playthrough.objects.get(player_game=tracked)
    Playthrough.objects.filter(pk=run.pk).update(
        completion_recorded_at=timezone.now(), completed=None
    )

    assert completed_run_count(owned_library, tracked) == 1


@pytest.mark.django_db(transaction=True)
def test_completed_run_count_skips_a_started_run_with_no_completion(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)
    run = Playthrough.objects.get(player_game=tracked)
    Playthrough.objects.filter(pk=run.pk).update(start_recorded_at=timezone.now())

    assert completed_run_count(owned_library, tracked) == 0


@pytest.mark.django_db(transaction=True)
def test_completed_run_count_skips_a_removed_run(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)
    a_second_run(owned_user, owned_library, game)
    for run in Playthrough.objects.filter(player_game=tracked):
        Playthrough.objects.filter(pk=run.pk).update(
            completion_recorded_at=timezone.now()
        )
    stale = Playthrough.objects.filter(player_game=tracked).first()
    Playthrough.objects.filter(pk=stale.pk).update(removed_at=timezone.now())

    assert completed_run_count(owned_library, tracked) == 1


@pytest.mark.django_db
def test_completed_run_count_answers_zero_for_a_game_no_library_tracks(owned_library):
    assert completed_run_count(owned_library, None) == 0
```

Add `tracked_game` and `completed_run_count` to the existing
`games.reads.playthrough_runs` import.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_runs_read.py -k tracked_game or completed_run_count"`
Expected: FAIL, `ImportError: cannot import name 'tracked_game'`.

- [ ] **Step 3: Write the implementation**

Append to `games/reads/playthrough_runs.py`:

```python
def tracked_game(library: UserLibrary, game: Game) -> PlayerGame | None:
    """The row this library tracks the game with, or nothing.

    One row per pair, by `unique_library_player_game`. A
    removed one is not tracked.
    """
    return PlayerGame.objects.filter(
        library=library, game=game, removed_at__isnull=True
    ).first()


def completed_run_count(library: UserLibrary, player_game: PlayerGame | None) -> int:
    """How many times the person played the game through.

    Runs whose completion is stated, the day known or unknown
    alike. #679 states a run at tracking time that states
    neither act, and nobody played that one; a run started
    and not finished is not a time played through either.

    This is the number the legacy row meant: #684 states a
    completion marker for every row it converts.
    """
    if player_game is None:
        return 0
    return (
        live_ordinary_runs(library, player_game)
        .filter(completion_recorded_at__isnull=False)
        .count()
    )
```

Add `Game` to the existing `games.models` import in that module.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_runs_read.py"`
Expected: PASS, the whole file.

- [ ] **Step 5: Commit**

```bash
git add games/reads/playthrough_runs.py tests/test_playthrough_runs_read.py
git commit -m "Count the runs a person played through"
```

---

### Task 4: The run-shaped row builder

The legacy builder in `games/views/playthrough.py` takes a `PlayEvent` and
stays there for the list page until #1013. This is its sibling, in its own
module beside the other run reads.

**Files:**
- Create: `games/views/playthrough_rows.py`
- Test: `tests/test_playthrough_rows.py`

**Interfaces:**
- Consumes: `days_to_finish` (Task 2), `numbered_for`'s `display_number`
  annotation (Task 1).
- Produces:
  `playthrough_tabledata(runs: Sequence[Playthrough], presentation: DateTimePresentation, exclude_columns: Sequence[str] = (), *, origin: OriginUrl | None) -> TableData`
  — columns `Playthrough, Game, Started, Completed, Days to finish, Note,
  Created, Actions`, caption `Playthroughs`, no sort keys.

- [ ] **Step 1: Write the failing test**

Create `tests/test_playthrough_rows.py`:

```python
"""#1012: one table row per run."""

from datetime import date

import pytest
from django.utils import timezone

from zoneinfo import ZoneInfo

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.models import Game, Playthrough
from games.reads.playthrough_numbering import numbered_for
from games.reads.playthrough_runs import tracked_game
from games.views.playthrough_rows import playthrough_tabledata
from games.writes.playergame import new_correlation_id, track_game
from timetracker.temporal import TemporalValue

#: Every test wants the run #679 states.
pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]


@pytest.fixture
def run(owned_user, owned_library) -> Playthrough:
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return Playthrough.objects.get(player_game__game=game)


@pytest.fixture
def presentation() -> DateTimePresentation:
    return DateTimePresentation(
        DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
    )


def cells_of(owned_library, run, presentation, **options) -> list[str]:
    """Every cell this run renders, each as its own string.

    `make_row` answers a TableRowData, whose `cell_data` holds
    the cells the table will render. A cell is a plain string
    or a node, so the assertions stringify each.
    """
    tracked = tracked_game(owned_library, run.player_game.game)
    runs = list(
        numbered_for(owned_library, [tracked.pk]).select_related("player_game__game")
    )
    data = playthrough_tabledata(runs, presentation, origin=None, **options)
    return [str(cell) for row in data["rows"] for cell in row["cell_data"]]


def test_an_act_that_never_happened_renders_a_dash(owned_library, run, presentation):
    """Both endpoints and the span between them."""
    cells = cells_of(owned_library, run, presentation)

    assert cells.count("-") == 3


def test_a_stated_act_with_no_day_renders_unknown(owned_library, run, presentation):
    Playthrough.objects.filter(pk=run.pk).update(
        start_recorded_at=timezone.now(), started=None
    )

    cells = cells_of(owned_library, run, presentation)

    assert "Unknown" in "".join(cells)
    assert cells.count("-") == 2


def test_a_stated_act_renders_its_day_at_its_own_precision(
    owned_library, run, presentation
):
    Playthrough.objects.filter(pk=run.pk).update(
        start_recorded_at=timezone.now(),
        started=TemporalValue.from_month(2026, 3),
    )

    cells = cells_of(owned_library, run, presentation)

    assert "2026-03" in "".join(cells)


def test_a_blank_name_renders_its_display_number(owned_library, run, presentation):
    cells = cells_of(owned_library, run, presentation)

    assert cells[0] == "Playthrough 1"


def test_the_actions_name_the_run(owned_library, run, presentation):
    cells = cells_of(owned_library, run, presentation)

    assert str(run.pk) in cells[-1]


def test_the_days_cell_reads_the_span(owned_library, run, presentation):
    Playthrough.objects.filter(pk=run.pk).update(
        start_recorded_at=timezone.now(),
        started=TemporalValue.from_day(date(2026, 1, 1)),
        completion_recorded_at=timezone.now(),
        completed=TemporalValue.from_day(date(2026, 1, 3)),
    )

    cells = cells_of(owned_library, run, presentation)

    assert "2" in cells


def test_excluding_the_game_column_drops_its_cell(owned_library, run, presentation):
    tracked = tracked_game(owned_library, run.player_game.game)
    runs = list(
        numbered_for(owned_library, [tracked.pk]).select_related("player_game__game")
    )

    data = playthrough_tabledata(
        runs, presentation, exclude_columns=["Game"], origin=None
    )

    labels = [column.label for column in data["columns"]]
    cells = [str(cell) for row in data["rows"] for cell in row["cell_data"]]
    assert "Game" not in labels
    assert "Outer Wilds" not in "".join(cells)
```

Read `tests/conftest.py` for the `owned_user` and `owned_library` fixtures and
for the `untracked_games` marker before running; the marker is what turns off
the autouse fixture that would otherwise track the game a second way.

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_playthrough_rows.py"`
Expected: FAIL, `ModuleNotFoundError: No module named 'games.views.playthrough_rows'`.

- [ ] **Step 3: Write the implementation**

Create `games/views/playthrough_rows.py`:

```python
"""One table row per run.

The sibling of `create_playthrough_tabledata`, which takes a
legacy row and stays in `games/views/playthrough.py` until
#1013 moves the list page.
"""

from collections.abc import Sequence

from common.components import (
    ICON_BUTTON_SIZE_CLASS,
    ButtonGroup,
    Cell,
    Column,
    Icon,
    TableData,
    TruncatedText,
    make_row,
)
from common.date_time_presentation import DateTimePresentation
from common.returns import OriginUrl, action_url
from common.temporal_presentation import TemporalText
from games.models import Playthrough
from games.reads.playthrough_endpoints import (
    StatedEndpoint,
    days_to_finish,
    stated_completion,
    stated_start,
)
from games.reads.playthrough_numbering import display_name


def playthrough_tabledata(
    runs: Sequence[Playthrough],
    presentation: DateTimePresentation,
    exclude_columns: Sequence[str] = (),
    *,
    origin: OriginUrl | None,
) -> TableData:
    """The runs, as rows.

    No sort keys: the one caller is an embedded section that
    handles no `?sort=`. #1013 states them when it moves the
    list page onto this builder.
    """
    column_list = [
        Column("Playthrough", shrinkable=True),
        Column("Game", shrinkable=True),
        Column("Started", priority=3),
        Column("Completed", priority=2),
        Column("Days to finish", priority=2),
        # Free text with no natural width: on one line a single long note
        # would widen the table past anything the other columns could
        # reclaim.
        Column("Note", wrap=True),
        Column("Created"),
        Column("Actions", align="right", priority=4),
    ]
    kept_columns = [
        column for column in column_list if column.label not in exclude_columns
    ]
    dropped_indexes = [
        index
        for index, column in enumerate(column_list)
        if column.label in exclude_columns
    ]

    row_list: list[list[Cell]] = [
        [
            display_name(run),
            TruncatedText(
                run.player_game.game.name,
                link=run.player_game.game.get_absolute_url(),
            ),
            _endpoint_cell(stated_start(run), presentation),
            _endpoint_cell(stated_completion(run), presentation),
            _days_cell(run),
            run.note,
            presentation.format(run.created_at, "date"),
            _actions(run, origin),
        ]
        for run in runs
    ]
    kept_rows = [
        [cell for index, cell in enumerate(row) if index not in dropped_indexes]
        for row in row_list
    ]
    return {
        "caption": "Playthroughs",
        "columns": kept_columns,
        "sort_terms": (),
        "rows": [make_row(*cells) for cells in kept_rows],
    }


def _endpoint_cell(
    stated: StatedEndpoint | None, presentation: DateTimePresentation
) -> Cell:
    """Three states where the legacy pair had two.

    No act reads a dash. An act whose day nobody knows reads
    `Unknown`, which `present_temporal_value` answers for a
    value of None.
    """
    if stated is None:
        return "-"
    return TemporalText(stated.when, presentation)


def _days_cell(run: Playthrough) -> Cell:
    days = days_to_finish(run)
    return "-" if days is None else str(days)


def _actions(run: Playthrough, origin: OriginUrl | None) -> Cell:
    """Edit and remove, naming the run.

    Remove renders on the game's last run too. The command
    refuses that one in its own sentence, and stating the
    rule here as well would be two places that can disagree.
    """
    return ButtonGroup(
        [
            {
                "href": action_url("games:edit_playthrough", run.pk, origin=origin),
                "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                "color": "gray",
            },
            {
                "href": action_url("games:remove_playthrough", run.pk, origin=origin),
                "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                "color": "red",
            },
        ]
    )
```

Check `Column`'s signature in `common/components/primitives.py` before
running: the legacy builder passes the sort key as the second positional
argument, so `Column("Started", priority=3)` must reach `priority` by keyword,
which it does.

- [ ] **Step 4: Run the test to verify it passes**

Run: `make test ARGS="tests/test_playthrough_rows.py"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/views/playthrough_rows.py tests/test_playthrough_rows.py
git commit -m "Build a table row from a run"
```

---

### Task 5: The section on Game detail reads runs

**Files:**
- Modify: `games/views/game.py` (`_playevents_section` at :941, `view_game` at
  :991)
- Test: `tests/test_rendered_pages.py` (:367, :449), `tests/test_game_detail_links.py` (:178)
- Test: `tests/test_game_detail_playthroughs.py` (create)

**Interfaces:**
- Consumes: `numbered_for` (Task 1), `tracked_game` (Task 3),
  `playthrough_tabledata` (Task 4).
- Produces: `_playthroughs_section(game, runs, presentation, origin)` and the
  container id `playthroughs-container`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_game_detail_playthroughs.py`:

```python
"""#1012: the Game detail section reads runs."""

import pytest
from django.urls import reverse
from django.utils import timezone

from games.models import Game, Playthrough

pytestmark = pytest.mark.django_db


@pytest.fixture
def game(owned_library) -> Game:
    #: tests/conftest.py tracks a created game and states
    #: the run #679 gives it, so this holds one already.
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def detail(logged_in, game) -> str:
    return logged_in.get(game.get_absolute_url()).content.decode()


def test_the_section_renders_the_run_a_tracked_game_holds(logged_in, game):
    """No act yet, and still a row.

    The row is the one the person is about to fill in, so it
    renders rather than an empty message.
    """
    body = detail(logged_in, game)

    assert "Playthroughs" in body
    assert "Playthrough 1" in body
    assert "No playthroughs yet." not in body


def test_the_section_badge_counts_every_live_ordinary_run(logged_in, game):
    body = detail(logged_in, game)

    assert 'id="playthroughs-container"' in body
    assert "View all" in body


def test_the_section_renders_unknown_for_a_stated_act_with_no_day(logged_in, game):
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(
        completion_recorded_at=timezone.now(), completed=None
    )

    body = detail(logged_in, game)

    assert "Unknown" in body


def test_the_section_links_its_actions_at_the_run(logged_in, game):
    run = Playthrough.objects.get(player_game__game=game)

    body = detail(logged_in, game)

    assert reverse("games:edit_playthrough", args=[run.pk]) in body
    assert reverse("games:remove_playthrough", args=[run.pk]) in body
```

Check `tests/conftest.py` for the fixture that logs a client in — the name
used across the suite is `logged_in`, paired with `owned_user` and
`owned_library`. Use whatever that file actually provides.

Then fix the two tests the always-present row makes wrong.

In `tests/test_rendered_pages.py`, change the marker at :367 from
`"Play Events"` to `"Playthroughs"`, and rewrite
`test_view_game_empty_sections` — it must no longer expect
`"No play events yet."`, because a tracked game always holds a run:

```python
    def test_view_game_empty_sections(self):
        """A game with no sessions or purchases shows the empty messages.

        The Playthrough section has none to show: #679 gives a
        tracked game a run from the moment the library tracks
        it, so the section always has a row. The empty branch
        stays for a section with a count and no rows, which is
        worse than a sentence.
        """
        lonely = Game.objects.create(
            library=self.user.library, name="Lonely Game", platform=self.platform
        )
        html = self.client.get(lonely.get_absolute_url()).content.decode()
        for marker in ["No purchases yet.", "No sessions yet."]:
            self.assertIn(marker, html)
        self.assertNotIn("No playthroughs yet.", html)
        self.assertNoEscapedTags(html)
```

In `tests/test_game_detail_links.py`, rewrite
`test_no_view_all_for_empty_section` so it tests the two sections that can
still be empty:

```python
def test_no_view_all_for_empty_section(owned_user, rf):
    """A game with no sessions and no purchases shows no 'View all' for them.

    The Playthrough section always has one: a tracked game
    holds the run #679 states, so its link always renders.
    """
    platform = Platform.objects.create(name="PC")
    empty_game = Game.objects.create(
        library=owned_user.library, name="Empty", platform=platform
    )
    request = rf.get(f"/game/{empty_game.id}/")
    request.user = owned_user
    request.session = {}
    html = view_game(request, empty_game.id, empty_game.url_slug).content.decode()
    view_all_links = html.count("View all")
    assert view_all_links == 1, "only the Playthrough section links out"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_game_detail_playthroughs.py tests/test_game_detail_links.py::test_no_view_all_for_empty_section"`
Expected: FAIL — the new file asserts `Playthroughs` against a page still
rendering `Play Events`, and the links test counts two.

- [ ] **Step 3: Write the implementation**

In `games/views/game.py`, replace `_playevents_section` with:

```python
def _playthroughs_section(
    game: Game,
    runs: Sequence[Playthrough],
    presentation: DateTimePresentation,
    origin: OriginUrl | None,
) -> Node:
    data = playthrough_tabledata(
        runs, presentation, exclude_columns=["Game"], origin=origin
    )
    table = StyledTable(
        columns=data["columns"],
        rows=data["rows"],
        data_table=True,
        caption="Playthroughs of this game",
    )
    #: The empty branch is unreachable while every tracked
    #: game holds a run. A badge with no rows beneath it is
    #: worse than a sentence, so it stays.
    section = _game_section(
        "Playthroughs",
        len(runs),
        table,
        "No playthroughs yet.",
        #: The list page reads legacy rows until #1013, so a
        #: run stated after #687 is not on the page this
        #: reaches. #1013 closes it.
        view_all_url=filter_url(PlayEventFilter.where(game=[game.id])),
    )
    return Div(id_="playthroughs-container")[section]
```

The `plain_columns` step the legacy section did — stripping sort keys the
shared list builder set — goes away: `playthrough_tabledata` states none.

In `view_game`, replace the `playevents` line and the section call:

```python
    tracked = tracked_game(library, game)
    #: Scoped on the row and its parent alike, as
    #: `live_ordinary_runs` is: a run may name another
    #: library's tracked game.
    runs = list(
        numbered_for(library, [tracked.pk] if tracked else []).select_related(
            "player_game__game"
        )
    )
```

and

```python
(_playthroughs_section(game, runs, presentation, origin),)
```

Imports to add at the top of `games/views/game.py`:

```python
from games.models import Playthrough
from games.reads.playthrough_numbering import numbered_for
from games.reads.playthrough_runs import tracked_game
from games.views.playthrough_rows import playthrough_tabledata
```

Merge `Playthrough` into the existing `games.models` import rather than adding
a second line. Drop `create_playthrough_tabledata` from the
`games.views.playthrough` import if nothing else in the file uses it; keep
`PlayEventFilter`, which the `View all` link still needs. If `PlayEvent` and
`QuerySet` become unused, drop them — `make lint` will say so.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_game_detail_playthroughs.py tests/test_game_detail_links.py tests/test_rendered_pages.py"`
Expected: PASS, all three files.

- [ ] **Step 5: Commit**

```bash
git add games/views/game.py tests/test_game_detail_playthroughs.py tests/test_game_detail_links.py tests/test_rendered_pages.py
git commit -m "Render the Game detail Playthrough section from the projection"
```

---

### Task 6: Both counts read runs

**Files:**
- Modify: `games/views/game.py` (`_removed_with_game` at :361, `_played_row`
  at :440, `_game_header` at :765, `remove_game` at :346, `view_game`)
- Test: `tests/test_game_detail_playthroughs.py`

**Interfaces:**
- Consumes: `tracked_game`, `completed_run_count` (Task 3),
  `live_ordinary_runs`.
- Produces: `_played_row(game, origin, played)` and
  `_removed_with_game(game, library)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_game_detail_playthroughs.py`:

```python
def test_played_reads_zero_for_a_game_with_no_completion(logged_in, game):
    """The run tracking states is not a time played through."""
    body = detail(logged_in, game)

    assert '<span data-count="">0</span> times' in body


def test_played_counts_a_completion_whose_day_is_unknown(logged_in, game):
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(
        completion_recorded_at=timezone.now(), completed=None
    )

    body = detail(logged_in, game)

    assert '<span data-count="">1</span> times' in body


def test_played_skips_a_started_run_with_no_completion(logged_in, game):
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(start_recorded_at=timezone.now())

    body = detail(logged_in, game)

    assert '<span data-count="">0</span> times' in body


def test_the_removal_confirmation_counts_every_live_ordinary_run(logged_in, game):
    """The line says what leaves the screen.

    Every row does, the actless one included, so it counts by
    the section's rule rather than the completion's.
    """
    body = logged_in.get(reverse("games:remove_game", args=[game.id])).content.decode()

    assert "1 playthrough(s)" in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_game_detail_playthroughs.py -k played or removal_confirmation"`
Expected: FAIL — `played` still counts legacy rows (0 for all three, so two of
the three fail) and the confirmation says `play event(s)`.

- [ ] **Step 3: Write the implementation**

In `games/views/game.py`:

```python
def _removed_with_game(game: Game, library: UserLibrary) -> Node:
    tracked = tracked_game(library, game)
    runs = live_ordinary_runs(library, tracked).count() if tracked else 0
    counts = [
        (game.sessions.alive().count(), "session"),
        (game.purchases.alive().count(), "purchase"),
        #: Removal stamps the PlayerGame, not its runs, so
        #: this says what leaves the screen -- the same claim
        #: the session line already makes.
        (runs, "playthrough"),
    ]
    present = [Li()[f"{count} {label}(s)"] for count, label in counts if count]
    return Ul()[*(present or [Li()["No associated data"]])]
```

`remove_game` passes the library it already holds:

```python
details = (_removed_with_game(game, library),)
```

`_played_row` takes the count rather than reading one. Replace its
`played = game.playevents.alive().count()` line by taking the number as a
parameter, and restate the docstring:

```python
def _played_row(game: Game, origin: OriginUrl | None, played: int) -> Node:
    """'Played N times' split button.

    The count is the runs whose completion is stated, day
    known or unknown alike, which is the number the legacy
    row meant. A run nobody finished is not a time played
    through.

    #687 took the '+1' action and its element away: a
    click filled in the run a tracked game already holds,
    which only untracking the game took back. #1024 owns
    stating a count.
    """
```

`_game_header` grows a `played: int` parameter and passes it on:

```python
(_played_row(game, origin, played),)
```

`view_game` computes it beside the runs it already resolves, and passes it
into `_game_header`:

```python
    played = completed_run_count(library, tracked)
```

Add `completed_run_count` and `live_ordinary_runs` to the
`games.reads.playthrough_runs` import, and `UserLibrary` to the
`games.models` import if it is not there already.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_game_detail_playthroughs.py tests/test_rendered_pages.py"`
Expected: PASS. `test_played_row_count_link_is_a_single_anchor` and
`test_played_row_label_is_one_flex_item` in `test_rendered_pages.py` both use
a fresh game with no completion, so both still read 0.

- [ ] **Step 5: Commit**

```bash
git add games/views/game.py tests/test_game_detail_playthroughs.py
git commit -m "Count playthroughs, not legacy rows, beside a game"
```

---

### Task 7: The edit and remove routes name the run

One task, because the route flip and the list page's translation are not
correct apart: after the flip a link carrying a legacy id answers 404, and
before it a link carrying a run id does.

**Files:**
- Modify: `games/views/playthrough.py` (`create_playthrough_tabledata` at :79,
  `edit_playthrough` at :386, `remove_playthrough` at :444, `_no_run_here` at
  :351)
- Test: `tests/test_playthrough_view_cutover.py`,
  `tests/test_library_page_isolation.py`, `tests/test_html_validity.py`,
  `tests/test_playergame_view_cutover.py`, `tests/test_removal_confirmation.py`,
  `tests/test_session_playhistory_runtime_identity.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_editable_runs(library) -> QuerySet[Playthrough]`;
  `create_playthrough_tabledata(..., *, library: UserLibrary, origin)` — the
  `library` keyword is new and required.

- [ ] **Step 1: Write the failing tests**

Rewrite `tests/test_playthrough_view_cutover.py`'s route tests to pass run
ids. Each already resolves the run through `run_for_row`; move that call above
the request and reverse on `run.pk`. Five tests change the same way:

```python
@pytest.mark.django_db(transaction=True)
def test_editing_a_converted_row_states_the_difference(client, user, game):
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    convert_library(user.library)
    run = run_for_row(user.library, row.pk).run
    assert run is not None
    client.force_login(user)

    client.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {"game": str(game.pk), "started": "2026-01-02", "ended": "", "note": "read"},
    )

    run.refresh_from_db()
    assert run.note == "read"
    row.refresh_from_db()
    assert row.note == ""
```

Apply the same move to `test_a_second_edit_does_not_revert_the_first`,
`test_a_run_stating_more_than_a_day_leaves_the_edit_page`,
`test_removing_the_only_run_is_refused_on_the_confirmation` and
`test_removing_one_of_two_runs_stamps_the_projection_only` — in each, reverse
on the run's key instead of the row's.

Replace `test_a_row_with_no_run_is_refused_on_the_edit_page` with the three
cases the flip creates:

```python
@pytest.mark.django_db
def test_a_legacy_row_id_reaches_no_page(client, user, game):
    """#1012 moved the routes onto the run.

    Both keys are UUIDs in one path position, so no route can
    tell them apart. The run is the key that survives, and a
    bookmark naming a row answers 404.
    """
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    convert_library(user.library)
    client.force_login(user)

    response = client.get(reverse("games:edit_playthrough", args=[row.pk]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_a_removed_run_reaches_no_page(client, user, game):
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())
    client.force_login(user)

    assert (
        client.get(reverse("games:edit_playthrough", args=[run.pk])).status_code == 404
    )
    assert (
        client.get(reverse("games:remove_playthrough", args=[run.pk])).status_code
        == 404
    )


@pytest.mark.django_db
def test_a_run_naming_another_librarys_tracked_game_reaches_no_page(
    client, user, game, django_user_model
):
    """Drift must not render another library's game name.

    The row's own library is one scope and its parent's is
    another. Answering on either alone would put a stranger's
    game in the heading and redirect into their detail page.
    """
    stranger = django_user_model.objects.create_user(
        username="drift-stranger", password="p"
    )
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(library=stranger.library)
    client.force_login(stranger)

    response = client.get(reverse("games:edit_playthrough", args=[run.pk]))

    assert response.status_code == 404
```

Add `from django.utils import timezone` to that file's imports.

In `tests/test_library_page_isolation.py`, resolve both runs in `world` and
switch the parametrize entries. After the two `convert_library` calls, add:

```python
    #: #1012 moved the routes onto the run, so the
    #: isolation cases must name one. A legacy key now
    #: matches nothing at all, which would answer 404 for
    #: the wrong reason and test nothing.
    own_run = run_for_row(owner_library, own_playevent.pk).run
    foreign_run = run_for_row(foreign_library, foreign_playevent.pk).run
```

Then change three parametrize lists: `("games:edit_playthrough",
"foreign_playevent")` and `("games:remove_playthrough", "foreign_playevent")`
become `"foreign_run"`; `("games:edit_playthrough", "own_playevent")` and
`("games:remove_playthrough", "own_playevent")` become `"own_run"`; and
`("games:remove_playthrough", "foreign_playevent", PlayEvent)` becomes
`("games:remove_playthrough", "foreign_run", Playthrough)`. Add
`Playthrough` to the `games.models` import and
`from games.reads.playthrough_provenance import run_for_row`.

In `tests/test_session_playhistory_runtime_identity.py`, the games in
`runtime_world` are tracked by the conftest fixture, so each already holds the
run #679 states. Add it to the fixture, before the `return`:

```python
    #: #1012 moved the HTML routes onto the run. The API
    #: still takes the legacy key, until #1015.
    foreign_run = Playthrough.objects.get(player_game__game=foreign_game)
```

Change the HTML parametrize entry `("get", "games:edit_playthrough",
"foreign_playevent")` to `"foreign_run"`, and leave the API entry
`("get", "/api/playthrough/{identity}", "foreign_playevent", None)` alone. Add
`Playthrough` to the `games.models` import.

In `tests/test_html_validity.py:166`, the game is tracked, so reverse on its
run. Resolve it where the other fixtures are built and use it in the URL list:

```python
        cls.playthrough = Playthrough.objects.get(player_game__game=cls.long_game)
```

then `reverse("games:remove_playthrough", args=[self.playthrough.id])`. Read
the surrounding setup first — if `self.playevent` belongs to a different game,
resolve the run of that game instead.

In `tests/test_playergame_view_cutover.py:309`, resolve the converted run
after `convert_library(owned_library)` and reverse on it:

```python
    run = run_for_row(owned_library, play_event.pk).run
    assert run is not None

    logged_in.post(
        reverse("games:edit_playthrough", args=[run.pk]),
```

Add `from games.reads.playthrough_provenance import run_for_row`.

In `tests/test_removal_confirmation.py:135`, the run is already resolved on
the line above; change the URL to `args=[run.pk]`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_view_cutover.py tests/test_library_page_isolation.py"`
Expected: FAIL — the run ids reach the legacy resolver and answer 404 where
200 is expected.

- [ ] **Step 3: Write the implementation**

In `games/views/playthrough.py`, add the scoped queryset:

```python
def _editable_runs(library: UserLibrary) -> QuerySet[Playthrough]:
    """This library's live runs, their game read with them.

    Scoped on the row and on its parent alike, as
    `live_ordinary_runs` is: a run naming another library's
    tracked game is the drift `audit_library_ownership`
    reports, and answering it here would render that
    library's game name and redirect into their page.

    Live only, which is what the legacy routes answered for a
    removed row.
    """
    return Playthrough.objects.select_related("player_game__game").filter(
        library=library,
        player_game__library=library,
        removed_at__isnull=True,
    )
```

Rewrite the head of `edit_playthrough`:

```python
@login_required
def edit_playthrough(request: HttpRequest, playthrough_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    run = owned_or_404(_editable_runs(library), library, id=playthrough_id)
    game = run.player_game.game
    #: Seeded from the run, never from a legacy row:
    #: nothing writes that row any more, so a second edit
    #: would restate its frozen days over the first one.
    days = restatable_days(run)
    if days is None:
        return _no_run_here(request, game, RICHER_THAN_A_DAY)
```

The rest of the body already uses `run`; replace every remaining
`playevent.game` with `game`.

Rewrite `remove_playthrough`:

```python
@login_required
def remove_playthrough(request: HttpRequest, playthrough_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    run = owned_or_404(_editable_runs(library), library, id=playthrough_id)
    game = run.player_game.game

    def act() -> None:
        remove_run_for_request(request, run, correlation_id=new_correlation_id())

    return confirm_and_apply(
        request,
        action=act,
        title="Remove playthrough",
        message=f"Remove this playthrough of {game}?",
        confirm_label="Remove",
        fallback="games:view_game",
        fallback_args=[game.id, game.url_slug],
    )
```

`_no_run_here` takes the game rather than a row:

```python
def _no_run_here(request: HttpRequest, game: Game, sentence: str) -> HttpResponse:
    """Toast the sentence and leave the page."""
    messages.error(request, sentence)
    return redirect(
        return_url(
            request,
            fallback="games:view_game",
            fallback_args=[game.id, game.url_slug],
        )
    )
```

Then translate the legacy list page's own action ids.
`create_playthrough_tabledata` gains a required `library` keyword and builds
its actions from the map:

```python
def create_playthrough_tabledata(
    playevents: list[PlayEvent] | BaseManager[PlayEvent] | QuerySet[PlayEvent],
    presentation: DateTimePresentation,
    exclude_columns: Sequence[str] = (),
    request: HttpRequest | None = None,
    sort_terms: Sequence[SortTerm] = (),
    *,
    library: UserLibrary,
    origin: OriginUrl | None,
) -> TableData:
    if isinstance(playevents, BaseManager):
        playevents = playevents.all()
    rows = list(playevents)
    #: #1012 moved the routes onto the run, and this page
    #: still lists rows until #1013. One batch, one query.
    runs = runs_for_rows(library, [row.pk for row in rows])
```

and inside the row comprehension, iterate `rows` and replace the inline
`ButtonGroup(...)` with `_legacy_actions(runs.get(playevent.pk), origin)`:

```python
def _legacy_actions(run_id: PlaythroughId | None, origin: OriginUrl | None) -> Cell:
    """No actions for a row that became no run.

    The map is partial: a row whose game the library stopped
    tracking was never converted. #771 takes the row with its
    table.
    """
    if run_id is None:
        return ""
    return ButtonGroup(
        [
            {
                "href": action_url("games:edit_playthrough", run_id, origin=origin),
                "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                "color": "gray",
            },
            {
                "href": action_url("games:remove_playthrough", run_id, origin=origin),
                "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                "color": "red",
            },
        ]
    )
```

`list_playthroughs` is the one caller left; pass `library=library` at its call
site.

Imports in `games/views/playthrough.py`: swap `run_for_row` for
`runs_for_rows` and `PlaythroughId` from
`games.reads.playthrough_provenance`; add `Playthrough` and `UserLibrary` to
the `games.models` import; add `Cell` to the `common.components` import. Drop
`CONFLICT_STATUS` and `CommandFailed` if nothing else in the file uses them —
`make lint` will say. Keep the module importing `playthrough_provenance`:
`tests/test_playthrough_api_writes.py::test_only_two_modules_read_the_bridge`
pins the readers to exactly `games/api.py` and `games/views/playthrough.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_view_cutover.py tests/test_library_page_isolation.py tests/test_html_validity.py tests/test_playergame_view_cutover.py tests/test_removal_confirmation.py tests/test_session_playhistory_runtime_identity.py tests/test_playthrough_api_writes.py"`
Expected: PASS, all seven files.

- [ ] **Step 5: Commit**

```bash
git add games/views/playthrough.py tests/
git commit -m "Name the run in the edit and remove routes"
```

---

### Task 8: The Add-playthrough prefill reads runs

The last legacy read on a path Game detail reaches. It is owned by no other
issue in the wave.

**Files:**
- Modify: `games/views/playthrough.py` (`add_playthrough` at :252)
- Test: `tests/test_playthrough_view_cutover.py`

**Interfaces:**
- Consumes: `tracked_game`, `live_ordinary_runs` (Task 3).
- Produces: nothing other tasks read.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_view_cutover.py`:

```python
@pytest.mark.django_db
def test_the_prefill_seeds_from_the_greatest_stated_completion(
    client, user, owned_library, game
):
    """The day after the last run finished.

    Read off the projection: nothing writes the legacy row
    any more, so seeding from it would offer a day the person
    already corrected.
    """
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 5, 1, 10, tzinfo=UTC),
        timestamp_end=datetime(2026, 5, 1, 12, tzinfo=UTC),
    )
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(
        completion_recorded_at=timezone.now(),
        completed=TemporalValue.from_day(date(2026, 1, 10)),
    )
    client.force_login(user)

    body = client.get(
        reverse("games:add_playthrough_for_game", args=[game.pk])
    ).content.decode()

    assert "2026-01-11" in body


@pytest.mark.django_db
def test_the_prefill_seeds_nothing_from_a_completion_with_no_day(client, user, game):
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 5, 1, 10, tzinfo=UTC),
        timestamp_end=datetime(2026, 5, 1, 12, tzinfo=UTC),
    )
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(
        completion_recorded_at=timezone.now(), completed=None
    )
    client.force_login(user)

    body = client.get(
        reverse("games:add_playthrough_for_game", args=[game.pk])
    ).content.decode()

    #: No completion states a day, so the seed falls back to
    #: the earliest session, as it does for a game with no
    #: finished run at all.
    assert "2026-05-01" in body
```

Add `from datetime import UTC, datetime` and `Session` to that file's
imports, alongside the `date`, `timezone` and `TemporalValue` names it already
has. Confirm the route name for the per-game entry point in `games/urls.py`
before running — the view takes an optional `game_id`, and the name used here
is the one that supplies it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_view_cutover.py -k prefill"`
Expected: FAIL — the seed still reads `game.playevents`, which holds nothing,
so the first test falls back to the session date.

- [ ] **Step 3: Write the implementation**

In `add_playthrough`, replace the `latest_playevent` block. The surrounding
`try` on `Session.DoesNotExist` and the note calculation stay exactly as they
are; only the source of the previous finish changes:

```python
#: The greatest day a run of this game states it
#: finished on. A completion whose day nobody
#: knows states none, so it seeds nothing and the
#: earliest session takes over, as it does for a
#: game with no finished run at all.
tracked = tracked_game(library, game)
last_finish = (
    live_ordinary_runs(library, tracked).aggregate(latest=Max("completed_upper"))[
        "latest"
    ]
    if tracked is not None
    else None
)

if last_finish is not None:
    new_playthrough_start_date = last_finish + timedelta(days=1)
    initial["started"] = new_playthrough_start_date
    playtime_calc_start_ts = datetime.combine(
        new_playthrough_start_date, datetime.min.time()
    )
else:
    #: No finished run, so the new one starts from
    #: the earliest session.
    earliest_session_ts = (
        game.sessions.alive().earliest("timestamp_start").timestamp_start
    )
    initial["started"] = earliest_session_ts.date()
    playtime_calc_start_ts = earliest_session_ts
```

Add `from django.db.models import Max` (merge into the existing
`django.db.models` import) and `tracked_game` and `live_ordinary_runs` from
`games.reads.playthrough_runs`. Drop `PlayEvent` from the imports only if the
list page no longer needs it — it does, so keep it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_view_cutover.py"`
Expected: PASS, the whole file.

- [ ] **Step 5: Commit**

```bash
git add games/views/playthrough.py tests/test_playthrough_view_cutover.py
git commit -m "Seed the Add playthrough form from the last run that finished"
```

---

### Task 9: The documentation sweep and the gate

**Files:**
- Modify: `CLAUDE.md` (the `Playthrough` model paragraph)
- Delete: `docs/superpowers/plans/2026-09-07-issue-1012-playthrough-detail-read-cutover.md`

**Interfaces:**
- Consumes: every task above.
- Produces: nothing.

- [ ] **Step 1: Update the architecture note**

In `CLAUDE.md`, the `Playthrough` bullet ends: "No screen calls any of it yet:
#1011 delivered commands alone, #1012 renders first screen". Replace that
sentence with what is now true:

```markdown
  #1012 renders the first screen: Game detail lists every live ordinary run,
  numbered by `games/reads/playthrough_numbering.py`, and its edit and remove
  routes name the run rather than the legacy row. `Played N times` beside it
  counts only the runs whose completion is stated, which is the number the
  legacy row meant; the section badge counts every row it renders. The list
  page reads legacy rows until #1013, and translates its own action ids
  through `runs_for_rows`.
```

- [ ] **Step 2: Lint the prose**

Run: `make vale`
Expected: no findings. A refused word in a new comment fails here.

- [ ] **Step 3: Drop the plan document**

The spec stays; the plan is scaffolding.

```bash
git rm docs/superpowers/plans/2026-09-07-issue-1012-playthrough-detail-read-cutover.md
```

- [ ] **Step 4: Run the full gate**

Run: `make check`
Expected: PASS — lint, format check, mypy, vale, ts-check, vitest, and the
whole pytest suite including `e2e/`.

The e2e fixture in `e2e/conftest.py` states a `PlayerGame` for a created game
and no `Playthrough` beside it, unlike `tests/conftest.py`. A tracked game
there therefore holds no run, which is the one place the section's empty
branch is reached. If an e2e test fails on a missing row rather than on the
empty message, read the failure before changing the fixture: the branch is
meant to survive.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "Say what Game detail reads now"
```

---

## Self-Review

**Spec coverage.** Each section of the spec maps to a task: the three endpoint
states and the precision rendering to Task 4; the column table to Task 4; the
scoping and the always-present row to Task 5; the numbering and `numbered_for`
to Task 1; the days rule, negative span included, to Task 2; the two counts
and the removal line to Tasks 3 and 6; the route flip, its scope, its 404s and
the list translation to Task 7; the row builder split to Tasks 4 and 7; the
prefill to Task 8. The window paragraph and the rollback paragraph describe
state, not work. The purchase Finished column belongs to #1026 and appears in
no task.

**Verification coverage.** The spec's ten verification items map to: 1 → Task
4; 2 → Task 4; 3 → Task 2; 4 → Task 1; 5 → Task 5; 6 → Tasks 3 and 6; 7 →
Task 6; 8 → the existing
`test_removing_the_only_run_is_refused_on_the_confirmation`, moved onto a run
id in Task 7, plus `_actions`' unconditional remove button covered by Task 4's
`test_the_actions_name_the_run`; 9 → Task 7; 10 → Task 8.

**Type consistency.** `numbered_for(library, player_game_ids)` is called with
that signature in Tasks 4 and 5. `days_to_finish(run)` is called in Task 4.
`tracked_game(library, game)` and `completed_run_count(library, player_game)`
are called in Tasks 5, 6 and 8. `playthrough_tabledata(runs, presentation,
exclude_columns, *, origin)` is called in Tasks 4 and 5.
`create_playthrough_tabledata(..., *, library, origin)` gains its keyword in
Task 7, after Task 5 removed the caller that would not have passed it.
