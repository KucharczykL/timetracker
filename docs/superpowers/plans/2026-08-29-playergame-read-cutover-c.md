# PlayerGame read cutover, child C: statistics and the API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The stats page reads a library's game status from its `PlayerGame`
row, the games API patches only a game the library tracks, and the seven dead
catalog readers go.

**Architecture:** A statistic is a Purchase query that names a game's status. A
queryset method holds no library, so each `games__status=` predicate becomes
membership over a library-scoped subquery of `Game.objects.tracked_by(library,
…)`. `tracked_by()` grows a keyword slot so the status condition rides in the
same `filter()` call, which opens one join instead of two.

**Tech Stack:** Django 6, PostgreSQL 18, pytest, pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-08-28-issue-678-playergame-read-cutover-design.md`

## What child A and child B already did

The spec's C list is four items long, and two of them landed early. Read this
before starting, or you will look for work that is not there.

| Spec item | State |
|---|---|
| The four `stats_data` predicates | **C does this** |
| The three `PurchaseQueryset` methods | **C does this** — one converted, two deleted |
| The five `stats_links` builders | Done in B. They build a `GameFilter`, and B re-pointed `GameFilter.status` at `tracked__status`, so the builders already name `PlayerGameStatus` words. C adds a test that they and `compute_stats` cannot drift apart. |
| `GameStatusUpdate` and `PATCH /api/games/{id}/status` | The schema took `PlayerGameStatus` in A. C moves the endpoint's lookup from `for_library()` to `tracked_by()`. |

## Global Constraints

- Branch `codex/playergame-read-cutover-c`, cut from
  `codex/playergame-read-cutover`. The pull request's base is the integration
  branch, never `main`.
- The mirror is alive through C. `_mirror()` keeps `Game.status` current, so a
  catalog letter is still readable and a test may still assert one. Child D
  deletes the mirror.
- Never assign `Game.status` or `Game.mastered` in application code. State the
  fact through `games/writes/playergame.py`. A test may use
  `Game.objects.filter(pk=…).update(…)` to force the catalog and the projection
  to disagree; that is the only reason to write the column.
- Unabbreviated identifiers in Python and TypeScript.
- A comment earns its place. One summary line, unless a plausible edit would
  break something quietly — then say what breaks.
- `make check-fast` while iterating. The full `make check`, green, before the
  pull request.
- Never pipe a `make` target into `tail`: the pipeline masks the exit status.
  Write `make check-fast >/tmp/c.log 2>&1 && echo CLEAN || tail -40 /tmp/c.log`.
- `PYTEST_WORKERS=0` when reading failure output; parallel output interleaves.
- Do not run `make format` on a Markdown file with an indented Python fragment
  in a fenced `python` block — ruff reformats fences and an indented fragment
  does not parse. This plan tags only module-level-valid snippets `python`.

---

## File structure

| File | Change |
|---|---|
| `games/models.py` | `GameQuerySet.tracked_by()` takes extra conditions. `PurchaseQueryset.finished()` takes a library. `PurchaseQueryset.abandoned()`, `.dropped()` and five `Game` instance methods are deleted. |
| `games/views/stats_data.py` | Four `games__status=` predicates become subquery membership; the private computation takes the library. |
| `games/api.py` | `partial_update_game` looks the game up with `tracked_by()`. |
| `tests/test_playergame_tracked_by.py` | The new keyword slot: it filters, and it opens one join. |
| `tests/test_playergame_read_parity.py` | Letter predicate against word predicate, per letter, positive and negated. Deleted by D with the rest of the file. |
| `tests/test_stats_reads_the_projection.py` | **New.** With the catalog and the projection disagreeing, a statistic follows the projection. Survives D. |
| `tests/test_stats_links.py` | The same disagreement, applied to the existing parity fixtures: a link's count still equals the number it was clicked from. |
| `tests/test_playergame_status_word_setters.py` | The endpoint refuses an untracked game and accepts a tracked shared one. |
| `docs/STATUSES.md` | The status table, the two purchase predicates and the query patterns. |

---

## Task 1: `tracked_by()` takes a condition

**Files:**
- Modify: `games/models.py:106-136` (`GameQuerySet.tracked_by`)
- Test: `tests/test_playergame_tracked_by.py`

**Interfaces:**
- Consumes: `GameQuerySet.annotated_for_filtering(library)` (child B).
- Produces: `tracked_by(library, **conditions)` — conditions are lookup
  keywords applied in the same `filter()` call as the tracked-row conditions.
  Task 2 and Task 4 call it.

**Why a keyword slot and not a second `.filter()`:** Django opens a join per
`filter()` call on a multi-valued relation, and B's review found exactly this
duplicate on the games list. Measured on a real database, the two shapes give:

Two calls — `tracked_by(library).filter(tracked__status=…)`:

```
INNER JOIN "games_playergame" U2 ON (U0."id" = U2."game_id" AND (U2."library_id" = …))
INNER JOIN "games_playergame" U4 ON (U0."id" = U4."game_id" AND (U4."library_id" = …))
WHERE (U0."tombstoned_at" IS NULL AND U2."archived_at" IS NULL
       AND U2."id" IS NOT NULL AND U4."status" = completed)
```

One call — `tracked_by(library, tracked__status=…)`:

```
INNER JOIN "games_playergame" tracked ON ("games_game"."id" = tracked."game_id" AND …)
WHERE ("games_game"."tombstoned_at" IS NULL AND tracked."archived_at" IS NULL
       AND tracked."id" IS NOT NULL AND tracked."status" IN (completed))
```

Both are correct — every join carries the library condition and
`unique_library_player_game` allows one row per pair — but the second reads a
table once.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_tracked_by.py`:

```python
@pytest.mark.django_db
def test_a_condition_selects_the_matching_games(owned_library):
    completed = Game.objects.create(library=owned_library, name="Outer Wilds")
    Game.objects.create(library=owned_library, name="Tunic")
    PlayerGame.objects.filter(library=owned_library, game=completed).update(
        status=PlayerGameStatus.COMPLETED
    )

    matched = Game.objects.tracked_by(
        owned_library, tracked__status=PlayerGameStatus.COMPLETED
    )

    assert list(matched) == [completed]


@pytest.mark.django_db
def test_a_condition_opens_one_join(owned_library):
    """The condition rides in the tracked row's own filter() call.

    A second filter() call on a multi-valued relation opens a second
    join. Both joins would be library-scoped and could not disagree,
    so this reads the table once rather than fixing a wrong answer.
    """
    sql = str(
        Game.objects.tracked_by(
            owned_library, tracked__status=PlayerGameStatus.COMPLETED
        ).query
    )

    assert sql.count('JOIN "games_playergame"') == 1
```

- [ ] **Step 2: Run them and watch them fail**

```
make test ARGS="tests/test_playergame_tracked_by.py -x" PYTEST_WORKERS=0
```

Expected: `TypeError: tracked_by() got an unexpected keyword argument
'tracked__status'`.

- [ ] **Step 3: Take the conditions**

In `games/models.py`, change `tracked_by`'s signature to
`def tracked_by(self, library, **conditions):` and pass `**conditions` into the
existing `.filter(…)` call, after `tracked__archived_at__isnull=True`. Leave
the `annotate()` of `tracked_status`/`tracked_mastered` where it is — it must
stay after the filter, which is what B's join fix established.

Add one line to the docstring, under the existing paragraphs:

```
Extra conditions ride in that same filter() call, because a
second call on the relation opens a second join.
```

- [ ] **Step 4: Run them and watch them pass**

```
make test ARGS="tests/test_playergame_tracked_by.py" PYTEST_WORKERS=0
```

Expected: every test in the file passes, the six that were already there
included.

- [ ] **Step 5: Commit**

```bash
git add games/models.py tests/test_playergame_tracked_by.py
git commit -m "Let the tracked row take a condition of its own"
```

---

## Task 2: Statistics read the projection

**Files:**
- Modify: `games/models.py:778-782` (`PurchaseQueryset.finished`)
- Modify: `games/views/stats_data.py:102-149`, `:210-231`, `:254-266`
- Test: `tests/test_playergame_read_parity.py`
- Test: `tests/test_stats_reads_the_projection.py` (create)

**Interfaces:**
- Consumes: `tracked_by(library, **conditions)` from Task 1.
- Produces: `PurchaseQueryset.finished(library)`;
  `_games_at_status(library, *statuses)` in `stats_data.py`;
  `_compute_stats_from_scoped_querysets(…, library=…)`.

**The four predicates and their replacements:**

| Line | Today | After |
|---|---|---|
| 149 | `~Q(games__status=FINISHED) & ~ended_q` | `~Q(games__in=completed) & ~ended_q` |
| 217-219 | `~Q(games__status=RETIRED) & ~Q(games__status=ABANDONED)` | `~Q(games__in=_games_at_status(library, RETIRED, ABANDONED))` |
| 223 | `Q(games__status=ABANDONED) \| Q(date_refunded__isnull=False)` | `Q(games__in=abandoned) \| Q(date_refunded__isnull=False)` |
| 263 | `.filter(games__status=FINISHED)` | `.filter(games__in=completed)` |

Row 217-219 merges two negations into one. De Morgan holds over the join:
`NOT(∃ retired) AND NOT(∃ abandoned)` is `NOT(∃ retired OR abandoned)`, and
`__in` over a set of two statuses is that disjunction. The parity test in Step 1
pins it rather than trusting the algebra.

A negated membership compiles to `NOT EXISTS`, which is the same shape
`~Q(games__status=…)` compiles to — measured, not assumed:

```
NOT (EXISTS(SELECT 1 FROM "games_purchase_games" V1
            WHERE (V1."game_id" IN (SELECT … FROM "games_game" U0
                                    INNER JOIN "games_playergame" tracked …)
                   AND V1."purchase_id" = "games_purchase"."id") LIMIT 1))
```

- [ ] **Step 1: Write the failing parity test**

Append to `tests/test_playergame_read_parity.py`. It builds both sides by hand,
like every other case in that file, so it holds before and after the switch:

```python
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("legacy_status", "player_status"),
    sorted(LEGACY_STATUS_TO_PLAYER_STATUS.items()),
)
def test_a_purchase_predicate_selects_the_same_purchases(
    owned_library, a_library_of_every_status, legacy_status, player_status
):
    """A letter over the catalog, a word over the projection.

    Both directions: a statistic negates three of its four
    predicates, and a negation over a join is the shape most
    likely to differ.
    """
    for game in a_library_of_every_status:
        purchase = Purchase.objects.create(
            library=owned_library, price_currency="CZK", type=Purchase.GAME
        )
        purchase.games.set([game])

    purchases = Purchase.objects.for_library(owned_library)
    old = Q(games__status=legacy_status)
    new = Q(
        games__in=Game.objects.tracked_by(owned_library, tracked__status=player_status)
    )

    assert ids(purchases.filter(old)) == ids(purchases.filter(new))
    assert ids(purchases.filter(~old)) == ids(purchases.filter(~new))


@pytest.mark.django_db
def test_two_negated_statuses_merge_into_one(owned_library, a_library_of_every_status):
    """`~a & ~b` is `~(a or b)`, and the second reads one column."""
    for game in a_library_of_every_status:
        purchase = Purchase.objects.create(
            library=owned_library, price_currency="CZK", type=Purchase.GAME
        )
        purchase.games.set([game])

    purchases = Purchase.objects.for_library(owned_library)
    old = ~Q(games__status="r") & ~Q(games__status="a")
    new = ~Q(
        games__in=Game.objects.tracked_by(
            owned_library,
            tracked__status__in=[
                PlayerGameStatus.RETIRED,
                PlayerGameStatus.ABANDONED,
            ],
        )
    )

    assert ids(purchases.filter(old)) == ids(purchases.filter(new))
```

Add `Purchase` and `Q` to that file's imports.

Note: `a_library_of_every_status` gives the shelved game no catalog letter, so
it sits at the `unplayed` default. Both sides read that game the same way — the
letter side sees `u`, the word side sees `shelved` — and neither is selected by
any letter the parametrize walks. That is the same exclusion the file's other
cases make explicit.

- [ ] **Step 2: Run it and watch it pass**

```
make test ARGS="tests/test_playergame_read_parity.py" PYTEST_WORKERS=0
```

Expected: PASS. This test does not fail first, and that is deliberate: it
asserts the translation is faithful, so it must be green *before* the
translation is used and green after. If it is red here, the replacement in
Step 4 is wrong and no amount of stats work will fix it.

- [ ] **Step 3: Write the failing divergence test**

Create `tests/test_stats_reads_the_projection.py`:

```python
"""A statistic follows the row the library keeps, not the catalog column.

The mirror keeps the two in step, so only a direct column write can
tell them apart. #770 deletes the column and this file stops being
able to state the difference; until then it is the proof the read
moved.
"""

from datetime import UTC, datetime

import pytest
from django.contrib.auth import get_user_model

from games.models import Game, PlayerGame, PlayerGameStatus, Purchase
from games.views.stats_data import compute_stats

YEAR = 2024


@pytest.fixture
def a_bought_game(db):
    library = get_user_model().objects.create_user(username="stats-cutover").library
    game = Game.objects.create(library=library, name="Outer Wilds")
    purchase = Purchase.objects.create(
        library=library,
        price_currency="CZK",
        type=Purchase.GAME,
        date_purchased=datetime(YEAR, 1, 5, tzinfo=UTC),
    )
    purchase.games.set([game])
    return library, game


def test_a_completed_row_leaves_the_backlog(a_bought_game):
    library, game = a_bought_game
    assert compute_stats(library, YEAR)["purchased_unfinished_count"] == 1

    PlayerGame.objects.filter(library=library, game=game).update(
        status=PlayerGameStatus.COMPLETED
    )

    assert compute_stats(library, YEAR)["purchased_unfinished_count"] == 0


def test_a_completed_column_the_row_denies_counts_for_nothing(a_bought_game):
    library, game = a_bought_game
    #: The one place a test writes the column: no command states a
    #: fact the projection then disagrees with.
    Game.objects.filter(pk=game.pk).update(status="f")

    assert compute_stats(library, YEAR)["purchased_unfinished_count"] == 1


def test_an_abandoned_row_is_dropped(a_bought_game):
    library, game = a_bought_game
    PlayerGame.objects.filter(library=library, game=game).update(
        status=PlayerGameStatus.ABANDONED
    )

    assert compute_stats(library, YEAR)["dropped_count"] == 1
```

- [ ] **Step 4: Run it and watch two of the three fail**

```
make test ARGS="tests/test_stats_reads_the_projection.py" PYTEST_WORKERS=0
```

Expected: `test_a_completed_row_leaves_the_backlog` FAILS (the catalog still
says unplayed, so the purchase stays in the backlog),
`test_a_completed_column_the_row_denies_counts_for_nothing` FAILS (the catalog
says `f`, so the purchase leaves it), and `test_an_abandoned_row_is_dropped`
FAILS.

- [ ] **Step 5: Give `PurchaseQueryset.finished()` a library**

In `games/models.py`, replace the three-line `finished()` body. The two dead
neighbours — `abandoned()` and `dropped()` — are Task 3's; leave them for now so
this commit is one idea.

```
def finished(self, library):
    return self.filter(
        Q(
            games__in=Game.objects.tracked_by(
                library, tracked__status=PlayerGameStatus.COMPLETED
            )
        )
        | Q(games__playevents__ended__isnull=False)
    ).distinct()
```

`Game` and `PlayerGameStatus` are both defined after `PurchaseQueryset` in the
module; the names resolve when the method runs, which is why this needs no
import juggling.

- [ ] **Step 6: Move the four predicates**

In `games/views/stats_data.py`:

1. Import `PlayerGameStatus` from `games.models`, beside `Game`.
2. Add the helper, above `compute_stats`:

```python
def _games_at_status(library: UserLibrary, *statuses: PlayerGameStatus):
    """The library's tracked games at one of these statuses."""
    return Game.objects.tracked_by(library, tracked__status__in=statuses)
```

3. Pass the library through: add `library=library` to the
   `_compute_stats_from_scoped_querysets(…)` call in `compute_stats`, and
   `library: UserLibrary,` to that function's keyword-only parameter list.
4. Replace line 149 with two lines, so the subquery is built once and named:

```
completed = _games_at_status(library, PlayerGameStatus.COMPLETED)
not_finished_q = ~Q(games__in=completed) & ~ended_q
```

5. In `unfinished`, replace the trailing `.filter(…)` with
   `.filter(~Q(games__in=_games_at_status(library, PlayerGameStatus.RETIRED, PlayerGameStatus.ABANDONED)))`,
   wrapped by the formatter.
6. In `dropped`, replace `Q(games__status=Game.Status.ABANDONED)` with
   `Q(games__in=_games_at_status(library, PlayerGameStatus.ABANDONED))`.
7. In the per-year `backlog_decrease_count`, replace
   `.filter(games__status=Game.Status.FINISHED)` with
   `.filter(games__in=completed)`.
8. Both `library_purchases.finished()` calls become
   `library_purchases.finished(library)`.

- [ ] **Step 7: Run the stats tests**

```
make test ARGS="tests/test_stats_reads_the_projection.py tests/test_stats.py tests/test_stats_links.py tests/test_stats_content_links.py" PYTEST_WORKERS=0
```

Expected: PASS, all four files. `test_stats_links.py` passes because the autouse
fixture writes the projection row from the game's catalog letter, so the two
agree in every test that does not force them apart. Task 5 removes that comfort.

- [ ] **Step 8: Run the whole fast suite**

```
make check-fast >/tmp/c.log 2>&1 && echo CLEAN || tail -60 /tmp/c.log
```

Expected: CLEAN. `tests/test_library_conversion.py`,
`tests/test_library_reconciliation.py` and `tests/test_library_api_isolation.py`
all call `compute_stats`; if one of them breaks, the library it passes has games
with no projection row, and the fix is in that test's setup, not in
`stats_data.py`.

- [ ] **Step 9: Commit**

```bash
git add games/models.py games/views/stats_data.py tests/test_playergame_read_parity.py tests/test_stats_reads_the_projection.py
git commit -m "Count the statistics from the row the library keeps"
```

---

## Task 3: Delete the seven dead catalog readers

**Files:**
- Modify: `games/models.py:338-354` (five `Game` methods),
  `games/models.py:783-790` (`abandoned`, `dropped`)

**Interfaces:** removes only. Nothing consumes these.

Seven methods read `Game.status` and nothing calls them:
`Game.finished()`, `.abandoned()`, `.retired()`, `.played()`, `.unplayed()`,
`PurchaseQueryset.abandoned()` and `PurchaseQueryset.dropped()`. Converting a
dead predicate means maintaining it, and `PurchaseQueryset.dropped()` does not
even compute the `dropped` statistic it appears to name — `stats_data` adds
not-finished, not-infinite and games-or-DLC on top. Keeping it invites a wrong
reuse. #770 has seven fewer catalog readers to find.

`docs/STATUSES.md` documents four of them under "Query Patterns". Task 6 owns
the whole document; do not edit it here.

- [ ] **Step 1: Prove they are dead**

```
grep -rn "\.finished(\|\.abandoned(\|\.dropped(\|\.retired(\|\.played(\|\.unplayed(" --include=*.py --include=*.html --include=*.ts . | grep -v "^./.git"
```

Expected: only `games/views/stats_data.py` (two `finished(library)` calls from
Task 2) and comment or docstring text. If anything else appears, stop — a
caller exists and this task's premise is wrong.

- [ ] **Step 2: Delete them**

Remove the five `Game` instance methods and the two `PurchaseQueryset` methods.
Keep `PurchaseQueryset.refunded()`, `.not_refunded()`, `.games_only()` and
`.finished()`.

- [ ] **Step 3: Run the fast suite**

```
make check-fast >/tmp/c.log 2>&1 && echo CLEAN || tail -60 /tmp/c.log
```

Expected: CLEAN. A red test here names a caller the grep missed.

- [ ] **Step 4: Commit**

```bash
git add games/models.py
git commit -m "Drop seven status readers nothing reads"
```

---

## Task 4: The API patches a game the library tracks

**Files:**
- Modify: `games/api.py:200-211` (`partial_update_game`)
- Test: `tests/test_playergame_status_word_setters.py`

**Interfaces:** none produced.

The endpoint looks the game up with `Game.objects.for_library(library)`.
`view_game` and `list_games` both use `tracked_by()` since A, and the selector
that sends this PATCH is rendered from a `tracked_by()` list, so the endpoint is
the last authenticated game read on the catalog's terms.

Two effects, both wanted. A shared catalog game the library tracks becomes
patchable, matching the list that shows it. An own game with no projection row
stops being patchable and answers 404 — that state is reachable only in a test,
because the form dispatches `TrackGame`, migration
`0033_playergame_baseline_backfill` covers a restored dump, and
`load_sample_data` calls `backfill_library()`. The `PlayerGameNotTracked` retry
inside `record_facts()` stays for the form path, which creates a game and tracks
it in two commits.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_status_word_setters.py`:

```python
@pytest.mark.django_db(transaction=True)
@pytest.mark.untracked_games
def test_the_endpoint_refuses_a_game_no_row_names(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    response = logged_in.patch(
        f"/api/games/{game.pk}/status",
        {"status": "played"},
        content_type="application/json",
    )

    assert response.status_code == 404
    assert not PlayerGame.objects.filter(game=game).exists()


@pytest.mark.django_db(transaction=True)
def test_the_endpoint_takes_a_shared_game_this_library_tracks(logged_in, owned_library):
    shared = Game.objects.create(library=None, name="Shared")
    PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        game=shared,
        tracked_at=timezone.now(),
    )

    response = logged_in.patch(
        f"/api/games/{shared.pk}/status",
        {"status": "played"},
        content_type="application/json",
    )

    assert response.status_code == 204
    row = PlayerGame.objects.get(library=owned_library, game=shared)
    assert row.status == PlayerGameStatus.PLAYED
```

Add `import uuid` to that file if it is absent.

- [ ] **Step 2: Run them and watch them fail**

```
make test ARGS="tests/test_playergame_status_word_setters.py" PYTEST_WORKERS=0
```

Expected: the untracked case returns 204 and writes a row (`for_library` finds
the game, and `record_facts` tracks it on the retry); the shared case returns
404.

- [ ] **Step 3: Look the game up through the join**

In `games/api.py`, in `partial_update_game`, change
`Game.objects.for_library(library)` to `Game.objects.tracked_by(library)`.

- [ ] **Step 4: Run them and watch them pass**

```
make test ARGS="tests/test_playergame_status_word_setters.py tests/test_library_api_isolation.py" PYTEST_WORKERS=0
```

Expected: PASS.
`test_shared_and_foreign_game_status_ids_are_undisclosed_and_unchanged` must
stay green — its shared game has `library=None`, the autouse fixture writes a
row only for a game that names a library, so no library tracks it and 404 is
still the answer.

- [ ] **Step 5: Commit**

```bash
git add games/api.py tests/test_playergame_status_word_setters.py
git commit -m "Patch the status of a game the library tracks"
```

---

## Task 5: Scramble the catalog and the links still land

**Files:**
- Test: `tests/test_stats_links.py`

**Interfaces:** none produced.

`tests/test_stats_links.py` asserts every builder's count equals the stat it
links from. It passes today for a reason that hides the cutover: the autouse
fixture writes each projection row from the game's catalog letter, so both sides
see the same value whichever column they read. Force them apart and the file
becomes a real cross-check — `compute_stats` and the `stats_links` builders must
both be reading the projection, because a reader still on the catalog gives a
different number.

- [ ] **Step 1: Write the test**

Append to `tests/test_stats_links.py`:

```python
@pytest.mark.parametrize(
    ("builder", "stat_key"),
    [
        ("purchases_dropped", "dropped_count"),
        ("purchases_unfinished", "purchased_unfinished_count"),
        ("purchases_backlog_decrease", "backlog_decrease_count"),
    ],
)
def test_a_link_lands_when_the_catalog_disagrees(world, builder, stat_key):
    """Both sides read the projection, so a wrong column changes nothing.

    The fixture writes each row from the game's letter, which would
    let a catalog reader pass. Setting every letter to `u` leaves
    only the projection saying anything true.
    """
    library = world["library"]
    Game.objects.filter(library=library).update(status=Game.Status.UNPLAYED)

    stats = compute_stats(library, YEAR)
    assert (
        _count(getattr(stats_links, builder)(YEAR), Purchase, library)
        == stats[stat_key]
    )
```

- [ ] **Step 2: Run it**

```
make test ARGS="tests/test_stats_links.py" PYTEST_WORKERS=0
```

Expected: PASS, and the values are the same ones the unscrambled tests assert.
A failure here means one of the two sides still reads `Game.status`; find it
with `grep -n "games__status\|Game.Status" games/views/stats_data.py
games/views/stats_links.py games/filters.py`.

- [ ] **Step 3: Guard against the reverse mistake**

Confirm the test would fail if a reader went back to the catalog: temporarily
change `_games_at_status` to `Game.objects.filter(status="a")`, run the file,
watch it go red, then revert. Do not commit the temporary change.

- [ ] **Step 4: Commit**

```bash
git add tests/test_stats_links.py
git commit -m "Scramble the letters and check the links still land"
```

---

## Task 6: Documentation and the gate

**Files:**
- Modify: `docs/STATUSES.md`
- Modify: `games/views/stats_data.py:1-11` (module docstring)

**Interfaces:** none produced.

`docs/STATUSES.md` is now wrong in four ways C created and one it inherited:

1. The Game Statuses table lists five letters as the field. The projection holds
   six words and the letters are a mirror #770 removes.
2. "Finished" and "Dropped" are defined as `Game.status == "f"` / `"a"`.
3. "Query Patterns" shows `game.finished()`, `game.abandoned()` and
   `Purchase.objects.dropped()`, all deleted, and `Purchase.objects.finished()`
   without its library.
4. Inherited and false, independent of this work: the Summary Table's **Dropped**
   row says "Finished OR Abandoned/Retired". Dropped is *not* finished. Fix it
   while the surrounding lines are being rewritten rather than leave a known
   contradiction two paragraphs from its own correct definition; say so in the
   pull request body.

Rewrite those sections. Do not rewrite the document — the transition-state
discussion, the edge cases and the unfinished-versus-dropped comparison are
still accurate and belong to no task here.

- [ ] **Step 1: Update the status table**

Replace the five-letter table with the six words of `PlayerGameStatus`:

| Status | Value | Description |
|---|---|---|
| **Unplayed** | `unplayed` | Tracked but never played |
| **Played** | `played` | Played, not completed |
| **Completed** | `completed` | Played to a finish |
| **Retired** | `retired` | Set aside on purpose — no longer reachable, or a collector's item |
| **Shelved** | `shelved` | Paused, possibly to return to |
| **Abandoned** | `abandoned` | Played and given up on |

Under it: the status lives on `PlayerGame`, one row per library per game, so two
libraries can hold different statuses for one catalog game. `Game.status` is a
mirror of that row, kept current by `games/writes/playergame.py` and removed by
#770. `shelved` has no letter, so nothing can set it until the mirror goes
(#678 D). Replace the "Setting game status" bullet naming `GameStatusChange`
with one naming the command path; the audit table stops being the record in
#678 D and its storage goes in #771.

- [ ] **Step 2: Update the two predicates**

"Finished" becomes `PlayerGame.status == "completed"` OR a PlayEvent with an
`ended` date. "Dropped" becomes `PlayerGame.status == "abandoned"` OR
`Purchase.date_refunded IS NOT NULL`.

- [ ] **Step 3: Update the query patterns**

Delete the `game.finished()` and `game.abandoned()` sections and the
`Purchase.objects.dropped()` one. Show the two shapes that exist:

```python
Purchase.objects.for_library(library).finished(library)
Game.objects.tracked_by(library, tracked__status=PlayerGameStatus.ABANDONED)
```

- [ ] **Step 4: Fix the summary table's Dropped row**

`NOT finished, AND (abandoned OR refunded)`.

- [ ] **Step 5: Say `stats_data`'s first paragraph in normal words**

The module docstring calls `compute_stats` "the documented seam between
computing metrics and rendering them". Say what it is: the function that
computes the metrics, and `stats_content` renders them. While there, say that it
takes the library because a status now lives on the library's own row.

- [ ] **Step 6: Lint the prose**

```
make vale >/tmp/vale.log 2>&1 && echo CLEAN || cat /tmp/vale.log
```

Expected: CLEAN, or warnings only. An **error** names a refused word with one
replacement; take the replacement.

- [ ] **Step 7: Run the gate**

```
make check >/tmp/check.log 2>&1 && echo CLEAN || tail -80 /tmp/check.log
```

This is the full aggregate, `e2e/` included, and it takes about six and a half
minutes serially. Run it in the background and poll rather than letting a tool
call time out.

Expected: CLEAN. Two failures are known to be unrelated to this work and are
filed as #949 — `tests/test_library_page_isolation.py::test_navbar_playtime_is_scoped_to_the_authenticated_library`
and `e2e/test_quick_filter_e2e.py::test_date_dropdown_facet_preset_flow`. Both
depend on the wall clock and on the display time zone. Confirm any failure is
one of those two by stashing and re-running it; never assume.

- [ ] **Step 8: Commit**

```bash
git add docs/STATUSES.md games/views/stats_data.py
git commit -m "Say what a status is where the docs still say a letter"
```

---

## After the tasks

1. **Docs sweep.** Every comment and docstring added by C gets cut to a summary
   line, unless a plausible edit would break something quietly — then it says
   what breaks, and the pull request lists the exceptions with reasons. Delete
   this plan document in the same commit. The #678 spec stays: child D still
   reads it.
2. **File the issue**, then open the pull request against
   `codex/playergame-read-cutover` with `Implements #<issue>` in the body. The
   base is not the default branch, so GitHub will not close the issue on merge
   — close it by hand, with a comment saying why.
3. **Say what diverged from the spec** in the pull request body: the five
   `stats_links` builders were already word-based after B, the API schema was
   already word-based after A, and two of the three `PurchaseQueryset` methods
   were deleted rather than converted because nothing called them.

## What C does not touch

- `_mirror()` and `games/views/playergame_writes.py`. Child D.
- `Game.objects.filter(sessions__in=sessions)` in `stats_data.py`, three places.
  Those read playtime, not status; routing them through `tracked_by()` would
  drop an untracked game from the top-ten list, which is a scoping change with
  no reader asking for it.
- `GameStatusChange` and the History section. Child D.
- `Game.status` and `Game.mastered` themselves. #770.
