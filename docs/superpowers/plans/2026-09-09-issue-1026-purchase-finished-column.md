# Purchase Finished Column Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Purchase list's Finished cell, `PURCHASE_SORTS["finished"]` and `GAME_SORTS["finished"]` read the `Playthrough` projection, and no finish is read from `games_playevent`.

**Architecture:** Three readers in `games/reads/playthrough_completions.py` answer "the completion this row reports" as correlated subqueries, parameterized by the lookup path from the outer row to its runs. The two list views annotate those subqueries onto their querysets; both `finished` sort keys name the resulting alias and carry no annotate dict, exactly as `filtered_playtime` already does. `apply_sort` is unchanged.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pytest + pytest-xdist, Playwright for e2e. Everything runs through `make`.

**Spec:** `docs/superpowers/specs/2026-09-09-issue-1026-purchase-finished-column-design.md`

## Global Constraints

- **Drive everything through `make`.** No raw `uv run`, `pytest`, `pnpm`. Focused runs: `make test ARGS="tests/test_x.py -k name -x"`.
- **`make check-fast` while iterating; full `make check` is the gate** before declaring done. Never verify with a hand-picked subset.
- **Never write to a `GeneratedField`**: `completed_lower`, `completed_upper`, `duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish`. Tests state `completed` through a command and let the database derive the bounds.
- **A completion is stated by a command**, never by assignment: `CompletePlaythrough` in `games/commands/playthrough.py`, dispatched through `games.events.dispatch.dispatch`.
- **No dispatch inside a transaction.** A test that dispatches needs `@pytest.mark.django_db(transaction=True)`.
- **Name variables with complete words** in Python and TypeScript (`presentation` not `pres`, `value` not `v`).
- **Name primitive roles** with a PEP 695 transparent alias when a bare `str`/`int` stands for a domain concept.
- **Refused words are enforced** by `make vale` over `.md` files and over `.py`/`.ts` comments: `fold`, `seam`, `tombstone`, `archive`, `delete` (next to a record noun), `heal`. See `docs/vocabulary.md`.
- **Comments are short** — roughly seven words — and say why, not what. Match the density of the file you are editing.
- **`make vale` treats a design record as history**: `docs/superpowers/**` is exempt from the rules added after it, so this plan may name words the code may not.

---

### Task 1: The three completion readers

**Files:**
- Modify: `games/reads/playthrough_completions.py:1-7` (docstring), append after line 61
- Test: `tests/test_playthrough_completion_reads.py` (create)

**Interfaces:**
- Consumes: `completed_runs(library, year)` and `library_runs(library)`, both already in the tree.
- Produces:
  - `type RunPath = str`
  - `PURCHASE_RUNS: RunPath = "player_game__game__purchases"`
  - `GAME_RUNS: RunPath = "player_game__game"`
  - `ranked_completions(library: UserLibrary, path: RunPath) -> QuerySet[Playthrough]`
  - `reported_completion(library: UserLibrary, path: RunPath) -> Subquery`
  - `reported_completion_day(library: UserLibrary, path: RunPath) -> Subquery`

- [ ] **Step 1: Write the failing test**

Create `tests/test_playthrough_completion_reads.py`:

```python
"""The completion a Purchase row reports."""

from datetime import UTC, date, datetime

import pytest
from django.db.models import Subquery

from games.commands.playergame import TrackGame
from games.commands.playthrough import CompletePlaythrough
from games.events.dispatch import dispatch
from games.models import Game, Playthrough, Purchase
from games.reads.playthrough_completions import (
    PURCHASE_RUNS,
    reported_completion,
    reported_completion_day,
)
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games


def make_purchase(library, name="Bundle"):
    return Purchase.objects.create(
        library=library,
        name=name,
        date_purchased=datetime(2020, 1, 1, tzinfo=UTC),
        price=0,
        price_currency="USD",
    )


def add_game(user, library, purchase, name, completed):
    """Track a game the purchase names, and state its completion."""
    game = Game.objects.create(library=library, name=name)
    purchase.games.add(game)
    dispatch(
        TrackGame(game_id=game.pk),
        actor=user,
        library=library,
        idempotency_key=f"track-{name}",
    )
    run = Playthrough.objects.get(player_game__game=game)
    if completed is not False:
        dispatch(
            CompletePlaythrough(playthrough_id=run.pk, when=completed, note=""),
            actor=user,
            library=library,
            idempotency_key=f"done-{name}",
        )
    return game, run


def read(library, purchase):
    """The value and the day the purchase reports."""
    row = (
        Purchase.objects.for_library(library)
        .annotate(
            value=reported_completion(library, PURCHASE_RUNS),
            day=reported_completion_day(library, PURCHASE_RUNS),
        )
        .get(pk=purchase.pk)
    )
    return row.value, row.day


@pytest.mark.django_db(transaction=True)
def test_the_latest_completion_is_reported(owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Early",
        TemporalValue.from_day(date(2020, 3, 4)),
    )
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Late",
        TemporalValue.from_day(date(2024, 7, 1)),
    )

    value, day = read(owned_library, purchase)

    assert value == TemporalValue.from_day(date(2024, 7, 1))
    assert day == date(2024, 7, 1)


@pytest.mark.django_db(transaction=True)
def test_a_dated_completion_outranks_a_dayless_one(owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Dated",
        TemporalValue.from_day(date(2020, 3, 4)),
    )
    add_game(owned_user, owned_library, purchase, "Dayless", None)

    value, day = read(owned_library, purchase)

    assert value == TemporalValue.from_day(date(2020, 3, 4))
    assert day == date(2020, 3, 4)


@pytest.mark.django_db(transaction=True)
def test_a_dayless_completion_alone_reports_no_day(owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(owned_user, owned_library, purchase, "Dayless", None)

    value, day = read(owned_library, purchase)

    assert value is None
    assert day is None


@pytest.mark.django_db(transaction=True)
def test_a_run_with_no_completion_reports_nothing(owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(owned_user, owned_library, purchase, "Playing", False)

    assert read(owned_library, purchase) == (None, None)


@pytest.mark.django_db(transaction=True)
def test_a_narrower_interval_wins_a_shared_lower_bound(owned_user, owned_library):
    """`2020-05-01` and `2020-05` both start on 1 May."""
    purchase = make_purchase(owned_library)
    add_game(
        owned_user, owned_library, purchase, "Month", TemporalValue.from_month(2020, 5)
    )
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Day",
        TemporalValue.from_day(date(2020, 5, 1)),
    )

    value, day = read(owned_library, purchase)

    assert value == TemporalValue.from_day(date(2020, 5, 1))
    assert day == date(2020, 5, 1)


@pytest.mark.django_db(transaction=True)
def test_an_open_start_range_reports_no_day(owned_user, owned_library):
    """A completion with no lower bound still states words."""
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Open",
        TemporalValue.parse("../2020-05-01"),
    )

    value, day = read(owned_library, purchase)

    assert value == TemporalValue.parse("../2020-05-01")
    assert day is None


@pytest.mark.django_db(transaction=True)
def test_a_removed_run_reports_nothing(owned_user, owned_library):
    from games.commands.playthrough import RemovePlaythrough

    purchase = make_purchase(owned_library)
    _, run = add_game(
        owned_user,
        owned_library,
        purchase,
        "Gone",
        TemporalValue.from_day(date(2020, 3, 4)),
    )
    dispatch(
        RemovePlaythrough(playthrough_id=run.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="remove",
    )

    assert read(owned_library, purchase) == (None, None)


@pytest.mark.django_db(transaction=True)
def test_a_removed_game_leaves_the_live_one_reporting(owned_user, owned_library):
    from games.removal import remove

    purchase = make_purchase(owned_library)
    gone, _ = add_game(
        owned_user,
        owned_library,
        purchase,
        "Gone",
        TemporalValue.from_day(date(2024, 7, 1)),
    )
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Live",
        TemporalValue.from_day(date(2020, 3, 4)),
    )
    remove(gone)

    value, day = read(owned_library, purchase)

    assert value == TemporalValue.from_day(date(2020, 3, 4))
    assert day == date(2020, 3, 4)


@pytest.mark.django_db(transaction=True)
def test_another_librarys_run_reports_nothing(
    owned_user, owned_library, django_user_model
):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Mine",
        TemporalValue.from_day(date(2020, 3, 4)),
    )

    row = (
        Purchase.objects.for_library(owned_library)
        .annotate(value=reported_completion(stranger.library, PURCHASE_RUNS))
        .get(pk=purchase.pk)
    )

    assert row.value is None


@pytest.mark.django_db(transaction=True)
def test_a_second_run_at_one_game_reports_the_later(owned_user, owned_library):
    from games.commands.playthrough import StartPlaythrough

    purchase = make_purchase(owned_library)
    game, first = add_game(
        owned_user,
        owned_library,
        purchase,
        "Twice",
        TemporalValue.from_day(date(2020, 3, 4)),
    )
    second = Playthrough.objects.create(
        id=__import__("uuid").uuid7(),
        library=owned_library,
        player_game=first.player_game,
        created_at=first.created_at,
    )
    dispatch(
        CompletePlaythrough(
            playthrough_id=second.pk,
            when=TemporalValue.from_day(date(2024, 7, 1)),
            note="",
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="done-second",
    )

    value, day = read(owned_library, purchase)

    assert value == TemporalValue.from_day(date(2024, 7, 1))
    assert day == date(2024, 7, 1)


@pytest.mark.django_db(transaction=True)
def test_the_readers_are_subqueries(owned_library):
    """A subquery shares no join, so a filter cannot narrow it."""
    assert isinstance(reported_completion(owned_library, PURCHASE_RUNS), Subquery)
    assert isinstance(reported_completion_day(owned_library, PURCHASE_RUNS), Subquery)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_playthrough_completion_reads.py -x"`
Expected: FAIL at collection — `ImportError: cannot import name 'PURCHASE_RUNS' from 'games.reads.playthrough_completions'`.

- [ ] **Step 3: Write the implementation**

Change the module docstring at `games/reads/playthrough_completions.py:1`, first line only:

```python
"""What a completion answers, for the statistics and the lists.
```

Add `F` to the `django.db.models` import at line 9:

```python
from django.db.models import Exists, F, Max, Min, OuterRef, QuerySet, Subquery
```

Append to the end of the file:

```python
#: A lookup path from the outer row to its runs.
type RunPath = str

PURCHASE_RUNS: RunPath = "player_game__game__purchases"
GAME_RUNS: RunPath = "player_game__game"


def ranked_completions(library: UserLibrary, path: RunPath) -> QuerySet[Playthrough]:
    """The row's completed runs, the reported one first.

    The latest finish leads. A tie on the lower bound goes to
    the narrower interval, so the more precise of two values
    that start on one day is the one reported. The last key is
    the identity, so the answer never varies.
    """
    return (
        completed_runs(library, None)
        .filter(**{path: OuterRef("pk")})
        .order_by(
            F("completed_lower").desc(nulls_last=True),
            F("completed_upper").asc(nulls_last=True),
            "-pk",
        )
    )


def reported_completion(library: UserLibrary, path: RunPath) -> Subquery:
    """The value the reported run states."""
    return Subquery(ranked_completions(library, path).values("completed")[:1])


def reported_completion_day(library: UserLibrary, path: RunPath) -> Subquery:
    """The day the reported run is ordered by."""
    return Subquery(ranked_completions(library, path).values("completed_lower")[:1])
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `make test ARGS="tests/test_playthrough_completion_reads.py"`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add games/reads/playthrough_completions.py tests/test_playthrough_completion_reads.py
git commit -m "Read the completion a row reports"
```

---

### Task 2: De-duplicate the game-filtered purchase list

This repairs a bug that predates the issue. `PurchaseFilter` compiles `game_filter` to a `games__id__in` join, and nothing on the list calls `.distinct()`, so a bundle answers once per matching game. `Max("games__playevents__ended")` groups by the purchase's primary key and hides it under `?sort=finished` only. Task 4 removes that aggregate, so this must land first.

**Files:**
- Modify: `games/views/purchase.py:199-206` (inside `list_purchases`)
- Test: `tests/test_purchase_list_fanout.py` (create)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: no new names. `list_purchases` answers one row per purchase under any filter.

- [ ] **Step 1: Write the failing test**

Create `tests/test_purchase_list_fanout.py`:

```python
"""One purchase, one row, whatever the filter joined."""

import json
from datetime import UTC, datetime

import pytest
from django.urls import reverse

from common.criteria import Modifier, StringCriterion
from games.filters import GameFilter, PurchaseFilter
from games.models import Game, Purchase


@pytest.fixture
def bundle(owned_library):
    """One purchase naming two games."""
    purchase = Purchase.objects.create(
        library=owned_library,
        name="Bundle",
        date_purchased=datetime(2020, 1, 1, tzinfo=UTC),
        price=0,
        price_currency="USD",
    )
    purchase.games.set(
        [
            Game.objects.create(library=owned_library, name="Early"),
            Game.objects.create(library=owned_library, name="Late"),
        ]
    )
    return purchase


def every_game_filter():
    """A `game_filter` that matches both games, so both join."""
    return json.dumps(
        PurchaseFilter(
            game_filter=GameFilter(
                name=StringCriterion(modifier=Modifier.NOT_EQUALS, value="zzz")
            )
        ).to_dict()
    )


@pytest.mark.django_db
@pytest.mark.parametrize("sort", ["purchased", "finished", "name"])
def test_a_game_filter_answers_one_row_per_purchase(logged_client, bundle, sort):
    response = logged_client.get(
        reverse("games:list_purchases"),
        {"filter": every_game_filter(), "sort": sort},
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert body.count(f'id="purchase-row-{bundle.pk}"') == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_purchase_list_fanout.py"`
Expected: `purchased` and `name` FAIL with `assert 2 == 1`; `finished` passes, because the `Max` aggregate hides the duplication today.

- [ ] **Step 3: Write the implementation**

In `games/views/purchase.py`, inside `list_purchases`, in the `if purchase_filter is not None:` branch, after the `purchases = execute_filter(...)` assignment:

```python
        if purchase_filter is not None:
            purchases = execute_filter(
                purchase_filter,
                purchases,
                filter_query_context_for_library(library),
            )
            #: `game_filter` joins the games, so a bundle
            #: answers once per game it names.
            purchases = purchases.distinct()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `make test ARGS="tests/test_purchase_list_fanout.py"`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add games/views/purchase.py tests/test_purchase_list_fanout.py
git commit -m "Answer one row per purchase under a game filter"
```

---

### Task 3: The Finished cell reads the projection

**Files:**
- Modify: `games/views/purchase.py` — imports at 55-65, `_render_purchase_row` at 137-176, `list_purchases` at 185-189, `refund_purchase` at 553-555
- Test: `tests/test_purchase_finished_column.py` (create)

**Interfaces:**
- Consumes: `PURCHASE_RUNS`, `reported_completion`, `reported_completion_day` from Task 1; `completion_exists` already in the tree.
- Produces:
  - `_purchases_with_completions(library: UserLibrary) -> QuerySet[Purchase]` in `games/views/purchase.py`
  - three annotation aliases on that queryset: `has_completion` (bool), `completed_value` (`TemporalValue | None`), `completed_day` (`date | None`). Task 4 orders by `completed_day`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_purchase_finished_column.py`:

```python
"""What the Finished cell prints."""

from datetime import date

import pytest
from django.urls import reverse

from games.commands.playthrough import CompletePlaythrough
from games.events.dispatch import dispatch
from tests.test_playthrough_completion_reads import add_game, make_purchase
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games


def finished_cell(client, purchase):
    """The Finished cell's text for one row."""
    import re

    response = client.get(reverse("games:list_purchases"))
    assert response.status_code == 200
    body = response.content.decode()
    row = re.search(rf'id="purchase-row-{purchase.pk}".*?</tr>', body, re.DOTALL)
    assert row, "row not rendered"
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row.group(0), re.DOTALL)
    #: Name, Type, Price, Infinite, Purchased, Finished, …
    return re.sub(r"<[^>]+>", "", cells[5]).strip()


@pytest.mark.django_db(transaction=True)
def test_no_completion_prints_a_dash(logged_client, owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(owned_user, owned_library, purchase, "Playing", False)

    assert finished_cell(logged_client, purchase) == "-"


@pytest.mark.django_db(transaction=True)
def test_a_purchase_naming_no_game_prints_a_dash(logged_client, owned_library):
    purchase = make_purchase(owned_library)

    assert finished_cell(logged_client, purchase) == "-"


@pytest.mark.django_db(transaction=True)
def test_a_dayless_completion_prints_unknown(logged_client, owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(owned_user, owned_library, purchase, "Dayless", None)

    assert finished_cell(logged_client, purchase) == "Unknown"


@pytest.mark.django_db(transaction=True)
def test_a_dated_completion_prints_its_day(logged_client, owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Dated",
        TemporalValue.from_day(date(2024, 7, 1)),
    )

    assert finished_cell(logged_client, purchase) == "2024-07-01"


@pytest.mark.django_db(transaction=True)
def test_a_decade_prints_its_words(logged_client, owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(owned_user, owned_library, purchase, "Coarse", TemporalValue.parse("202X"))

    assert finished_cell(logged_client, purchase) == "2020s"


@pytest.mark.django_db(transaction=True)
def test_an_open_start_range_prints_its_words(logged_client, owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Open",
        TemporalValue.parse("../2020-05-01"),
    )

    assert finished_cell(logged_client, purchase) == "until 2020-05-01"


@pytest.mark.django_db(transaction=True)
def test_the_refunded_row_keeps_its_cell(logged_client, owned_user, owned_library):
    """The swap after a refund reads what the list reads."""
    import re

    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Dated",
        TemporalValue.from_day(date(2024, 7, 1)),
    )

    response = logged_client.post(reverse("games:refund_purchase", args=[purchase.pk]))

    assert response.status_code == 200
    body = response.content.decode()
    cells = re.findall(r"<td[^>]*>(.*?)</td>", body, re.DOTALL)
    assert re.sub(r"<[^>]+>", "", cells[5]).strip() == "2024-07-01"


@pytest.mark.django_db(transaction=True)
def test_the_list_costs_no_query_per_row(
    logged_client, owned_user, owned_library, django_assert_num_queries
):
    """Ten purchases cost what one does."""
    for index in range(10):
        purchase = make_purchase(owned_library, name=f"Bundle {index}")
        add_game(
            owned_user,
            owned_library,
            purchase,
            f"Game {index}",
            TemporalValue.from_day(date(2024, 7, 1)),
        )

    with django_assert_num_queries(PURCHASE_LIST_QUERIES):
        logged_client.get(reverse("games:list_purchases"))


#: Measured, not guessed. Step 4 states the number this holds.
PURCHASE_LIST_QUERIES = 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_purchase_finished_column.py -x"`
Expected: FAIL. `test_a_dayless_completion_prints_unknown` reports `-` where `Unknown` is wanted, because the column reads `PlayEvent` today.

- [ ] **Step 3: Write the implementation**

In `games/views/purchase.py`, drop `PlayEvent` from the model import at line 60:

```python
from games.models import Game, PlayerGameStatus, Purchase
```

Add beside the other `games.` imports:

```python
from common.temporal_presentation import TemporalText
from games.models import UserLibrary
from games.reads.playthrough_completions import (
    PURCHASE_RUNS,
    completion_exists,
    reported_completion,
    reported_completion_day,
)
```

Add above `_render_purchase_row`:

```python
def _purchases_with_completions(library: UserLibrary) -> QuerySet[Purchase]:
    """The list's rows, carrying the Finished cell's two facts.

    Both render paths read through this, so the row a refund
    swaps in answers what the list's row answers.
    """
    return (
        Purchase.objects.for_library(library)
        .select_related("platform")
        .prefetch_related("games", "games__platform")
        .annotate(
            has_completion=completion_exists(library, None),
            completed_value=reported_completion(library, PURCHASE_RUNS),
            completed_day=reported_completion_day(library, PURCHASE_RUNS),
        )
    )
```

Replace the body of `_render_purchase_row` from `date_finished = "-"` through `except PlayEvent.DoesNotExist: pass` (lines 141-155) with:

```python
    #: A null value is a completion nobody dated, which
    #: TemporalText prints as Unknown. No completion is a dash.
    date_finished = (
        TemporalText(purchase.completed_value, presentation)
        if purchase.has_completion
        else "-"
    )
```

Delete the `# TODO: simplify if multiple purchases are no longer allowed` comment above it; it described the loop that just went away.

In `list_purchases`, replace the queryset construction at lines 185-189:

```python
    purchases: QuerySet[Purchase] = _purchases_with_completions(library)
```

In `refund_purchase`, replace the read at lines 553-555:

```python
purchase = owned_or_404(_purchases_with_completions(library), library, id=purchase_id)
```

- [ ] **Step 4: Run the test and state the query count**

Run: `make test ARGS="tests/test_purchase_finished_column.py"`
Expected: every test but the query-count one passes. That one fails with a number in the message, for example `Expected to perform 0 queries but 7 were done`.

Set `PURCHASE_LIST_QUERIES` to the number reported, then re-run:

Run: `make test ARGS="tests/test_purchase_finished_column.py"`
Expected: PASS, 8 tests.

Then prove the number does not grow with the rows: change `range(10)` to `range(3)` temporarily, re-run, confirm the same count, and change it back.

- [ ] **Step 5: Commit**

```bash
git add games/views/purchase.py tests/test_purchase_finished_column.py
git commit -m "Print the run's completion in the Finished column"
```

---

### Task 4: Both finished sorts order by the projection

**Files:**
- Modify: `games/sorting.py:11-22` (imports), `:103`, `:123-125`
- Modify: `games/views/game.py` — imports near line 101, annotation near line 175
- Modify: `tests/test_sorting.py:163-191`
- Test: `tests/test_finished_sorts.py` (create)

**Interfaces:**
- Consumes: `GAME_RUNS` and `reported_completion_day` from Task 1; the `completed_day` alias `_purchases_with_completions` adds in Task 3.
- Produces: `GAME_SORTS["finished"]` and `PURCHASE_SORTS["finished"]` both become `SortSpec("completed_day")`, with no annotate dict. `apply_sort` is untouched.

- [ ] **Step 1: Write the failing test**

Create `tests/test_finished_sorts.py`:

```python
"""Both finished sorts read the runs."""

import json
from datetime import date

import pytest
from django.urls import reverse

from common.criteria import Modifier, StringCriterion
from games.filters import GameFilter, PurchaseFilter
from tests.test_playthrough_completion_reads import add_game, make_purchase
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games


def row_order(body, purchases):
    """The purchases in the order the body prints them."""
    positions = {
        purchase.pk: body.index(f'id="purchase-row-{purchase.pk}"')
        for purchase in purchases
        if f'id="purchase-row-{purchase.pk}"' in body
    }
    return [pk for pk, _ in sorted(positions.items(), key=lambda pair: pair[1])]


@pytest.fixture
def three_purchases(owned_user, owned_library):
    """Late, early and one with no completion."""
    late = make_purchase(owned_library, name="Late")
    add_game(
        owned_user, owned_library, late, "L", TemporalValue.from_day(date(2024, 7, 1))
    )
    early = make_purchase(owned_library, name="Early")
    add_game(
        owned_user, owned_library, early, "E", TemporalValue.from_day(date(2020, 3, 4))
    )
    none = make_purchase(owned_library, name="None")
    add_game(owned_user, owned_library, none, "N", False)
    return late, early, none


@pytest.mark.django_db(transaction=True)
def test_purchases_descending_put_nulls_last(logged_client, three_purchases):
    late, early, none = three_purchases

    body = logged_client.get(
        reverse("games:list_purchases"), {"sort": "-finished"}
    ).content.decode()

    assert row_order(body, three_purchases) == [late.pk, early.pk, none.pk]


@pytest.mark.django_db(transaction=True)
def test_purchases_ascending_put_nulls_last(logged_client, three_purchases):
    late, early, none = three_purchases

    body = logged_client.get(
        reverse("games:list_purchases"), {"sort": "finished"}
    ).content.decode()

    assert row_order(body, three_purchases) == [early.pk, late.pk, none.pk]


@pytest.mark.django_db(transaction=True)
def test_a_dayless_completion_sorts_with_the_undated(
    logged_client, owned_user, owned_library
):
    """The cell says Unknown; the sort has no day for it."""
    dated = make_purchase(owned_library, name="Dated")
    add_game(
        owned_user, owned_library, dated, "D", TemporalValue.from_day(date(2020, 3, 4))
    )
    dayless = make_purchase(owned_library, name="Dayless")
    add_game(owned_user, owned_library, dayless, "U", None)

    body = logged_client.get(
        reverse("games:list_purchases"), {"sort": "-finished"}
    ).content.decode()

    assert row_order(body, (dated, dayless)) == [dated.pk, dayless.pk]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("sort", ["finished", "-finished"])
def test_the_game_list_sorts_by_finished(
    logged_client, owned_user, owned_library, sort
):
    """No column renders it, so only the URL reaches it."""
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "G",
        TemporalValue.from_day(date(2024, 7, 1)),
    )

    response = logged_client.get(reverse("games:list_games"), {"sort": sort})

    assert response.status_code == 200


@pytest.mark.django_db(transaction=True)
def test_a_filter_does_not_narrow_the_reported_completion(
    logged_client, owned_user, owned_library
):
    """The whole purchase reports, not the matched part."""
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Early",
        TemporalValue.from_day(date(2020, 3, 4)),
    )
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Late",
        TemporalValue.from_day(date(2024, 7, 1)),
    )

    body = logged_client.get(
        reverse("games:list_purchases"),
        {
            "filter": json.dumps(
                PurchaseFilter(
                    game_filter=GameFilter(
                        name=StringCriterion(modifier=Modifier.EQUALS, value="Early")
                    )
                ).to_dict()
            ),
            "sort": "-finished",
        },
    ).content.decode()

    #: The bundle reports 2024 even though the filter named the 2020 game.
    assert "2024-07-01" in body


@pytest.mark.django_db(transaction=True)
def test_a_saved_sort_of_finished_still_runs(logged_client, three_purchases):
    """A preset carries the key with no column behind it."""
    late, early, none = three_purchases

    response = logged_client.get(
        reverse("games:list_purchases"), {"sort": "-finished,name"}
    )

    assert response.status_code == 200
    assert row_order(response.content.decode(), three_purchases)[0] == late.pk
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_finished_sorts.py -x"`
Expected: FAIL — the sorts still read `games_playevent`, so every purchase reports no finish and the order is the default.

- [ ] **Step 3: Write the implementation**

In `games/sorting.py`, remove `Max` from the `django.db.models` import at lines 11-22; nothing else uses it:

```python
from django.db.models import (
    Case,
    DurationField,
    Expression,
    ExpressionWrapper,
    F,
    Min,
    QuerySet,
    Sum,
    When,
)
```

Replace `GAME_SORTS["finished"]` at line 103:

```python
    # No annotate dict: list_games pre-annotates `completed_day`, the day the
    # reported run states. Same reason as `filtered_playtime` above.
    "finished": SortSpec("completed_day"),
```

Replace `PURCHASE_SORTS["finished"]` at lines 123-125:

```python
    # No annotate dict: _purchases_with_completions annotates `completed_day`.
    "finished": SortSpec("completed_day"),
```

In `games/views/game.py`, add to the imports:

```python
from games.reads.playthrough_completions import GAME_RUNS, reported_completion_day
```

and extend the annotation at line 175:

```python
    games = games.annotate(
        filtered_playtime=Subquery(windowed_playtime),
        #: The Game list renders no Finished column; `?sort=finished`
        #: is the only thing that reads this.
        completed_day=reported_completion_day(library, GAME_RUNS),
    )
```

In `tests/test_sorting.py`, rewrite `test_nullable_aggregate_sort_keeps_null_last_in_both_directions` at lines 163-191. It seeds `PlayEvent` rows and calls `apply_sort` on a bare `Game.objects.all()`, which no longer carries the alias. Replace the whole method with:

```python
def test_nullable_aggregate_sort_keeps_null_last_in_both_directions(
    self, owned_library
):
    """Changing aggregate NULL ordering would break this contract."""
    platform = Platform.objects.create(name="P", icon="p")
    unfinished = Game.objects.create(
        library=owned_library, name="Unfinished", platform=platform
    )
    early = Game.objects.create(library=owned_library, name="Early", platform=platform)
    late = Game.objects.create(library=owned_library, name="Late", platform=platform)
    #: The view annotates the day; this mirrors what list_games does.
    days = {early.pk: date(2024, 1, 1), late.pk: date(2024, 1, 2)}
    annotated = Game.objects.annotate(
        completed_day=Case(
            *(
                When(pk=pk, then=Value(day, output_field=DateField()))
                for pk, day in days.items()
            ),
            default=Value(None, output_field=DateField()),
        )
    )

    ascending = apply_sort(annotated, _find("finished"), GAME_SORTS, GAME_DEFAULT_SORT)
    descending = apply_sort(
        annotated, _find("-finished"), GAME_SORTS, GAME_DEFAULT_SORT
    )

    assert list(ascending.queryset) == [early, late, unfinished]
    assert list(descending.queryset) == [late, early, unfinished]
```

Add `Case`, `DateField`, `Value` and `When` to the `django.db.models` import in `tests/test_sorting.py`, and remove the `PlayEvent` import if this was its last use in the file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_finished_sorts.py tests/test_sorting.py tests/test_sort_header_parity.py"`
Expected: PASS. `TestEverySortKeyReturns200` is the guard that a key naming an alias always meets a queryset carrying it.

- [ ] **Step 5: Commit**

```bash
git add games/sorting.py games/views/game.py tests/test_sorting.py tests/test_finished_sorts.py
git commit -m "Order both finished sorts by the reported run"
```

---

### Task 5: The statistics links, and no finish left in the table

**Files:**
- Test: `tests/test_stats_finished_links.py` (create)
- Modify: `CLAUDE.md` — the `Playthrough` bullet's sentence about `games_playevent`
- Verify: no `PlayEvent` read remains for a finish

**Interfaces:**
- Consumes: everything from Tasks 1 to 4.
- Produces: no new names.

- [ ] **Step 1: Write the failing test**

Create `tests/test_stats_finished_links.py`:

```python
"""The links the statistics carry order by the runs."""

from datetime import date

import pytest
from django.urls import reverse

from games.views import stats_links
from tests.test_finished_sorts import row_order
from tests.test_playthrough_completion_reads import add_game, make_purchase
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "builder",
    [
        stats_links.purchases_finished_released,
        stats_links.purchases_bought_and_finished,
    ],
)
def test_the_link_orders_by_the_reported_completion(
    logged_client, owned_user, owned_library, builder
):
    """Cell and sort report one number, all-time."""
    import json

    late = make_purchase(owned_library, name="Late")
    add_game(
        owned_user, owned_library, late, "L", TemporalValue.from_day(date(2024, 12, 1))
    )
    early = make_purchase(owned_library, name="Early")
    add_game(
        owned_user, owned_library, early, "E", TemporalValue.from_day(date(2024, 1, 5))
    )

    response = logged_client.get(
        reverse("games:list_purchases"),
        {"filter": json.dumps(builder(2024).to_dict()), "sort": "-finished"},
    )

    assert response.status_code == 200
    body = response.content.decode()
    order = row_order(body, (late, early))
    #: Every rendered row appears once, and the later finish leads.
    assert body.count(f'id="purchase-row-{late.pk}"') == 1
    if order:
        assert order[0] == late.pk
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_stats_finished_links.py"`
Expected: it should already PASS once Tasks 1 to 4 are in. If it fails, the filter the builder returns does not reach these purchases — read the builder in `games/views/stats_links.py` and adjust the fixture's dates so both purchases fall in its scope. Do not weaken the assertions.

- [ ] **Step 3: Confirm no finish is read from `games_playevent`**

Run:

```bash
grep -rn "playevents__ended\|PlayEvent.objects" --include=*.py games/ common/ | grep -v migrations
```

Expected: no hit inside `games/views/purchase.py` or `games/sorting.py`. Remaining hits belong to `games/models.py`, the backfill and #684's converter, which this issue does not touch.

Update the `Playthrough` bullet in `CLAUDE.md`. Find the sentence:

> No run is read out of `games_playevent` any more, though the table is still read for a finish day elsewhere — the Purchase list's Finished column and the `finished` sort on Game and Purchase, both #1026's, and #771 takes the table.

Replace it with:

> No run is read out of `games_playevent` any more, and since #1026 no finish is either: the Purchase list's Finished column and the `finished` sort on Game and Purchase read the projection, through the three readers in `games/reads/playthrough_completions.py`. #771 takes the table.

- [ ] **Step 4: Run the whole gate**

Run: `make check`
Expected: green. This includes `e2e/`, `make vale`, mypy and the vitest suite.

If mypy complains that `Purchase` has no attribute `has_completion` or `completed_value`, check how `game.filtered_playtime` passes at `games/views/game.py:201` and mirror it — the annotation attribute is read the same way there with no cast.

If `make vale` reports a finding, read `docs/vocabulary.md` for the replacement. Comments in the code are in scope; identifiers are not.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md tests/test_stats_finished_links.py
git commit -m "Sweep the #1026 docs"
```

---

## Self-Review

**Spec coverage.**

| Spec section | Task |
|---|---|
| The completion a row reports — three readers, `RunPath`, three-key order | 1 |
| `completion_exists` stays purchase-only | 1 (not extended) |
| What the cell prints — four rows | 3 |
| The refunded row's cell | 3 |
| No query per row | 3 |
| What the sorts order by — nulls last, both directions | 4 |
| Where the annotation comes from — view annotates, `apply_sort` untouched | 4 |
| The fan-out this unmasks — `.distinct()` | 2 |
| What the statistics links reorder | 5 |
| Five values change | 1 (readers), 3 (cell) |
| What stays as it is — no game, refunded, `finished()` divergence | 3 (no game, refunded); `finished()` divergence is stated in the spec and left alone by design |
| Verification — every bullet | 1 to 5 |

**Ordering.** Task 2 precedes Task 4 because Task 4 removes the aggregate that hides the fan-out today. Task 3 precedes Task 4 because `PURCHASE_SORTS["finished"]` names the `completed_day` alias that `_purchases_with_completions` adds.

**Names used consistently.** `RunPath`, `PURCHASE_RUNS`, `GAME_RUNS`, `ranked_completions`, `reported_completion`, `reported_completion_day`, `_purchases_with_completions`, and the three aliases `has_completion` / `completed_value` / `completed_day`. The sort maps name `completed_day` and both views annotate it.

**One number is measured, not guessed.** `PURCHASE_LIST_QUERIES` starts at `0` and Task 3 Step 4 states the real figure, then proves it does not grow with the row count.
