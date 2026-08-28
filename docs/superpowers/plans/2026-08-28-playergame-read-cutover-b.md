# PlayerGame read cutover — child B implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `status` and `mastered` filters, the `status` sort key and
the status widget's option list read a library's `PlayerGame` row instead of
the `Game.status` and `Game.mastered` columns.

**Architecture:** `GameFilter.status` and `.mastered` stop naming a catalog
column and name the `tracked` alias child A added, so a game filter compiles to
`Q(tracked__status__in=[...])` and resolves only on a queryset that carries the
alias. Two consequences drive the rest of the plan. The widget's option list
and its nullability come from a second path, `player_games__status`, which
`FilterField.metadata_lookup` already names — but that path hops a reverse
relation, so nullability must come from the terminal column rather than the
whole path. And a queryset the filter compiles against must carry the alias
even when it selects nothing, which is what the validation-only context hands
out; a new `GameQuerySet.annotated_for_filtering()` supplies it.

**Tech Stack:** Django 6, PostgreSQL 18, Python 3.14, pytest + pytest-django +
pytest-playwright, the Python component system in `common/components/`.

**Spec:** `docs/superpowers/specs/2026-08-28-issue-678-playergame-read-cutover-design.md`

**Branch:** cut from `codex/playergame-read-cutover` (child A is merged there as
`8c9c822d`). One pull request back onto it.

## Global Constraints

- Python 3.14 only. PEP 758 `except A, B:` is in use; ruff 0.16.x formats to it.
- Run everything through `make`. Never `uv run` / `pytest` / `pnpm` directly.
- `make test ARGS="…"` *appends* to `pytest tests/`, so a node id still collects
  the whole directory. Isolate with `-k`.
- Never pipe a `make` target into `tail` — the pipeline masks the exit status.
  Use `make x >/tmp/log 2>&1 && echo CLEAN || tail -40 /tmp/log`.
- Iterate with `make check-fast`. The gate before "done" is the full
  `make check`, `e2e/` included.
- `make vale` refuses the word `fold`. A projector **replays** events; the row
  it leaves is the **projection**.
- Name variables with complete words, in Python and TypeScript.
- Name compound types explicitly (`TypedDict`, `NamedTuple`, PEP 695 alias).
- Never write to a `GeneratedField`.
- Never assign `Game.status` or `Game.mastered` outside the two places child A
  named (`GameForm.save()` on an insert, and `_mirror()`).
- `_mirror()` is still alive. Child D removes it. Until then the catalog columns
  agree with the projection for the five statuses a letter holds, which is what
  lets the parity suite and the stats predicates keep passing through B.

---

## Three corrections to the spec, found while planning

The spec's child-B paragraph is one sentence long. Applying it against the
merged child A turns up three things it does not say. Each was verified by
applying the change and running the suite, not reasoned about.

**1. The five `stats_links` builders move in B, not in C.** The spec assigns
them to C. They cannot wait. Those builders emit
`GameFilter(status=ChoiceCriterion(value=[Game.Status.FINISHED]))` — a letter.
The moment `GameFilter.status` compiles to `tracked__status`, that filter reads
`Q(tracked__status__in=["f"])`, which matches nothing, and
`tests/test_stats_content_links.py`'s parity tests fail: each asserts a link's
queryset count equals the stat it links from. Only the *link values* move here.
The stat *computation* in `stats_data.py` stays for C, and the two agree
because `_mirror()` is still alive.

**2. `FilterQueryContext.for_validation()` is a production 500, not a test
artifact.** It resolves `Game` to `Game.objects.none()`, which carries no
`tracked` alias. `filter_from_json()` validates every parsed filter by calling
`to_q()` against that context, and `relation_to_q()` builds a nested sub-filter
subquery from it. So a `?filter=` carrying a nested game status criterion —
`{"game_filter": {"status": …}}` from any purchase, session or platform list —
raises `FieldError: Cannot resolve keyword 'tracked' into field` on user input.
Task 2 fixes it. The six test modules that define their own unrestricted
context need the same treatment for the same reason.

**3. The two test tracking fixtures must mirror the facts they drop.** Child A
added an autouse `post_save` fixture in `tests/conftest.py` and `e2e/conftest.py`
that writes a `PlayerGame` row for every game a test creates. It writes the
defaults, so every projection row says `unplayed`, not mastered. Once the
filters read the projection, every test that creates a game with a status and
then filters on it selects nothing. Task 1 makes the fixture copy the two facts
across. That is a fixture, not production behaviour: production writes the
projection through `track_game()`, which child A already wired.

**Out of scope, and belonging to no child.** `comparable_columns` /
`field_comparisons` still exposes `Game.status` as a raw comparable column, so a
field-comparison filter reads the catalog after B. No child issue owns it, and
`#770` would break it. Flag it; do not fix it here.

---

## File Structure

**Production, five files:**

- `games/models.py` — `GameQuerySet.annotated_for_filtering(library=None)`, a
  new method holding the alias and the two annotations that `tracked_by()`
  already builds. `tracked_by()` is rebuilt on it and keeps its behaviour
  exactly.
- `common/criteria.py` — `with_filter_aliases(queryset)`, a module-level
  function that asks a queryset to annotate itself; `for_validation()` routes
  through it; the nullability branch in `field_metadata()` reads the terminal
  column when `metadata_lookup` is set.
- `games/filters.py` — two `FilterField` entries in `GameFilter.fields`.
- `games/sorting.py` — one `SortSpec` in `GAME_SORTS`.
- `games/views/stats_links.py` — five builders emit words, not letters.

**Tests, thirteen files.** Two conftests (Task 1), six unrestricted-context
modules (Task 2), `test_sorting.py` and the parity suite (Task 3),
`test_filters.py`, `test_field_widget.py`, `test_quick_filter_bar.py` and four
`e2e/` modules (Task 4).

---

### Task 1: A test's projection row states the game's facts

**Files:**
- Modify: `tests/conftest.py:121-141`
- Modify: `e2e/conftest.py:63-83`

**Interfaces:**
- Consumes: `games.playergame_status.player_status_for(legacy_status)`, added by
  child A. It maps one `Game.Status` letter to a `PlayerGameStatus` and raises
  `UnmappedLegacyStatus` for a letter it lacks.
- Produces: every `PlayerGame` a test's game creation writes now carries that
  game's `status` and `mastered`. Tasks 3 and 4 depend on this.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_playergame_game_views.py`:

```python
@pytest.mark.django_db
def test_the_tracking_fixture_states_the_games_facts(owned_library):
    """A test's projection row says what the game it was created for says.

    The fixture stands in for `track_game()`, which production calls.
    A row that took the column defaults would say `unplayed` for a
    finished game, and every filter reading the projection would then
    select nothing in every test that sets a status.
    """
    game = Game.objects.create(
        library=owned_library,
        name="Outer Wilds",
        status=Game.Status.FINISHED,
        mastered=True,
    )

    tracked = PlayerGame.objects.get(library=owned_library, game=game)

    assert tracked.status == PlayerGameStatus.COMPLETED
    assert tracked.mastered is True
```

The module already imports `Game`, `PlayerGame` and `PlayerGameStatus`.

- [ ] **Step 2: Run it and watch it fail**

```
make test-fast ARGS="-k the_tracking_fixture_states"
```

Expected: FAIL, `assert 'unplayed' == 'completed'`.

- [ ] **Step 3: Make the fixture copy the two facts**

In `tests/conftest.py`, inside `_track_created_games`, extend the function-local
import:

```python
    from games.models import Game, PlayerGame
    from games.playergame_status import player_status_for
```

and the `get_or_create` defaults:

```python
        PlayerGame.objects.get_or_create(
            library_id=instance.library_id,
            game=instance,
            defaults={
                "pk": uuid.uuid7(),
                "tracked_at": timezone.now(),
                "status": player_status_for(instance.status),
                "mastered": instance.mastered,
            },
        )
```

Apply the identical two edits to `e2e/conftest.py`. The two fixtures are
deliberate duplicates — the docstring there says importing across the suites
would make `e2e/` depend on the unit suite's collection.

- [ ] **Step 4: Run it and watch it pass**

```
make test-fast ARGS="-k the_tracking_fixture_states"
```

Expected: PASS.

- [ ] **Step 5: Run the whole fast suite**

```
make check-fast >/tmp/b1.log 2>&1 && echo CLEAN || tail -40 /tmp/b1.log
```

Expected: CLEAN. Nothing reads the projection's two facts yet, so this task
changes no other test's outcome.

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py e2e/conftest.py tests/test_playergame_game_views.py
git commit -m "State a game's facts on the row a test tracks it with"
```

---

### Task 2: A filter resolves its aliases on a queryset that selects nothing

**Files:**
- Modify: `games/models.py:88` (add `annotated_for_filtering`, rebuild
  `tracked_by` on it)
- Modify: `common/criteria.py:1329` (add `with_filter_aliases`), `:1353`
  (`for_validation`)
- Modify: `tests/test_filters.py:75`, `tests/test_relation_algebra.py:29`,
  `tests/test_filter_tree_contract.py:34`, `tests/test_playhistory_fk_uuid.py:23`,
  `tests/test_session_fk_uuid.py:26`, `tests/test_filter_cross_entity.py:30`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: `GameQuerySet.tracked_by()` and its `tracked` / `tracked_status` /
  `tracked_mastered` names, from child A.
- Produces:
  - `GameQuerySet.annotated_for_filtering(library=None) -> GameQuerySet` — the
    alias and both annotations, no row dropped. `library=None` states every
    library.
  - `common.criteria.with_filter_aliases(queryset) -> QuerySet` — returns
    `queryset.annotated_for_filtering()` if the queryset defines that method,
    otherwise the queryset unchanged.
  Task 4 depends on both: without them its `FilterField` change is a 500.

- [ ] **Step 1: Write the failing test**

Add one method to `TestGameFilterToQ` in `tests/test_filters.py`. The class
header is shown so the snippet reads as the file does; only the method is new:

```python
class TestGameFilterToQ:
    def test_a_nested_game_status_validates(self):
        """A nested game status compiles against the validation context.

        `filter_from_json` validates every parsed filter by calling
        `to_q()` with `FilterQueryContext.for_validation()`, and a
        relation criterion builds its subquery from the queryset that
        context hands out. The status lookup is an alias, so an
        unannotated queryset cannot resolve it and the parse raises —
        on user input, in every list view that accepts a nested game
        filter.
        """
        from common.criteria import filter_from_json
        from games.filters import PurchaseFilter

        parsed = filter_from_json(
            PurchaseFilter,
            '{"game_filter": {"status": {"value": ["completed"],'
            ' "modifier": "INCLUDES"}}}',
        )

        assert parsed is not None
```

The module imports `PurchaseFilter` inside function bodies elsewhere, which is
why this one does too.

This test passes today — `status` is still a plain column. It fails the moment
Task 4 lands, which is the point: it is the guard that says why Task 2 exists.
Prove it now by temporarily pointing the field at the alias.

- [ ] **Step 2: Run it and watch it fail**

Temporarily edit `games/filters.py` so `"status": FilterField("tracked__status")`,
then:

```
make test-fast ARGS="-k a_nested_game_status_validates"
```

Expected: FAIL with `FieldError: Cannot resolve keyword 'tracked' into field`.
**Revert that one-line edit before Step 3** — it belongs to Task 4.

- [ ] **Step 3: Add the queryset method**

In `games/models.py`, insert before `tracked_by`:

```python
    def annotated_for_filtering(self, library=None):
        """The `tracked` alias and the two facts, with no row dropped.

        Separate from `tracked_by()` because a filter needs the names
        it reads to resolve on a queryset that selects nothing: a
        validation-only context and a test that builds its own
        queryset both compile `tracked__status` without executing it.
        No library states every library, which is what an unscoped
        caller means.
        """
        condition = Q() if library is None else Q(player_games__library=library)
        return self.annotate(
            tracked=FilteredRelation("player_games", condition=condition)
        ).annotate(
            tracked_status=F("tracked__status"),
            tracked_mastered=F("tracked__mastered"),
        )
```

Then rebuild `tracked_by` on it. Its docstring stays exactly as child A wrote
it; only the body's last statement changes:

```python
        return (
            self.alive()
            .annotated_for_filtering(library)
            .filter(tracked__isnull=False, tracked__archived_at__isnull=True)
        )
```

- [ ] **Step 4: Add the criteria-layer function**

In `common/criteria.py`, directly after the `QuerysetResolver` alias:

```python
def with_filter_aliases[M: models.Model](
    queryset: models.QuerySet[M],
) -> models.QuerySet[M]:
    """Add whatever aliases this model's filter fields name.

    A lookup a FilterField emits may be an annotation rather than a
    column, and then it resolves on an annotated queryset alone. A
    queryset states its own by defining `annotated_for_filtering()`;
    one that defines nothing names only columns and is returned as
    it came.
    """
    annotate = getattr(queryset, "annotated_for_filtering", None)
    return queryset if annotate is None else annotate()
```

and route the validation context through it:

```python
    @classmethod
    def for_validation(cls) -> Self:
        return cls(
            lambda model: with_filter_aliases(model._default_manager.none()),
            authorization_scoped=False,
        )
```

`common/criteria.py` is the generic layer and must not import `games`. The
duck-typed hook is why: the queryset states its own aliases, and a model with
none needs no entry anywhere.

- [ ] **Step 5: Give the six test contexts the same treatment**

Each of these six modules defines its own unrestricted context. Change every
one from

```python
UNRESTRICTED_FILTER_CONTEXT = FilterQueryContext(
    lambda model: model._default_manager.all()
)
```

to

```python
UNRESTRICTED_FILTER_CONTEXT = FilterQueryContext(
    lambda model: with_filter_aliases(model._default_manager.all())
)
```

and add `with_filter_aliases` to each module's `from common.criteria import`
(it sorts last — ruff orders uppercase before lowercase).

- `tests/test_filters.py:75`
- `tests/test_relation_algebra.py:29`
- `tests/test_filter_tree_contract.py:34`
- `tests/test_playhistory_fk_uuid.py:23`
- `tests/test_session_fk_uuid.py:26`
- `tests/test_filter_cross_entity.py:30`

Two of those import on one line and need wrapping:

```python
from common.criteria import (
    FilterQueryContext,
    Modifier,
    RelationMatch,
    StringCriterion,
    with_filter_aliases,
)
```

(`tests/test_session_fk_uuid.py:13` and `tests/test_playhistory_fk_uuid.py:10`.)
The other two single-line forms stay on one line:

```python
from common.criteria import FilterQueryContext, with_filter_aliases
from common.criteria import FilterQueryContext, filter_from_json, with_filter_aliases
```

- [ ] **Step 6: Prove the new method**

Add to `tests/test_playergame_read_parity.py`:

```python
@pytest.mark.django_db
def test_an_unscoped_annotation_drops_no_game(owned_library, a_library_of_every_status):
    """`annotated_for_filtering()` annotates; it does not select.

    `tracked_by()` is the one that filters. The unscoped form exists
    so a filter can compile its lookups against a queryset that
    executes nothing, which means it must leave the row set alone.
    """
    annotated = Game.objects.annotated_for_filtering()

    assert ids(annotated) == ids(Game.objects.all())
```

- [ ] **Step 7: Run the fast suite**

```
make check-fast >/tmp/b2.log 2>&1 && echo CLEAN || tail -40 /tmp/b2.log
```

Expected: CLEAN. Nothing emits an alias lookup yet, so this task is inert
except for the two new tests.

- [ ] **Step 8: Commit**

```bash
git add games/models.py common/criteria.py tests/
git commit -m "Let a filter resolve an alias on a queryset that selects nothing"
```

---

### Task 3: The status sort orders by the projection

**Files:**
- Modify: `games/sorting.py:83`
- Modify: `tests/test_sorting.py:142-160`
- Modify: `tests/test_playergame_read_parity.py:105-136`

**Interfaces:**
- Consumes: `tracked_status`, the annotation `tracked_by()` and
  `annotated_for_filtering()` both add.
- Produces: `GAME_SORTS["status"].expression == "tracked_status"`. Task 4 does
  not depend on it; they are independent and either order works.

The two orders agree, so `?sort=status` returns the same page: `a, f, p, r, u`
against `abandoned, completed, played, retired, unplayed`. `shelved` takes its
place between `retired` and `unplayed` and no letter holds it, which is why the
parity suite excludes the shelved game from both sides.

`list_games` already builds its queryset from `tracked_by()` (child A), so the
alias is present wherever this sort is applied.

- [ ] **Step 1: Point the parity suite's old side at its own map**

`test_a_sort_returns_the_same_order` currently derives the *old* expression
from `GAME_SORTS`, which is the map under test. Once the map names the
projection, both sides of the comparison read the projection and the test
proves nothing. State the catalog side separately.

Add above `def ids(queryset):` in `tests/test_playergame_read_parity.py`:

```python
#: The catalog column each projection alias replaced. GAME_SORTS
#: names the projection from #678 B on, so the old side is stated
#: here rather than read back out of the map under test.
CATALOG_SORT_EXPRESSIONS = {"tracked_status": "status"}
```

and replace the three lines in the test body:

```python
    spec = GAME_SORTS[sort_key]
    new_expression = spec.expression
    old_expression = CATALOG_SORT_EXPRESSIONS.get(new_expression, new_expression)
```

- [ ] **Step 2: Run it and confirm it still passes, vacuously**

```
make test-fast ARGS="-k a_sort_returns_the_same_order"
```

Expected: PASS. `GAME_SORTS` still says `status`, the map has no entry for it,
so both sides read the catalog and the two `status` cases assert nothing. That
is the state Step 3 breaks: the map is what makes the comparison real once the
spec names the projection.

- [ ] **Step 3: Change the sort spec**

In `games/sorting.py`, in `GAME_SORTS`:

```python
    "status": SortSpec("tracked_status"),
```

- [ ] **Step 4: Fix the one sort test that builds its own queryset**

`tests/test_sorting.py::TestApplySortGames::test_equal_sort_values_use_primary_key_tiebreaker`
sorts by `status` on a bare `Game.objects.filter(...)`, which has no alias.
Give it the annotated queryset:

```python
        result = apply_sort(
            Game.objects.tracked_by(owned_library).filter(pk__in=[second.pk, first.pk]),
            _find("status"),
            GAME_SORTS,
            GAME_DEFAULT_SORT,
        )
```

The rest of the test is unchanged: it still asserts
`list(result.queryset) == [first, second]` and
`result.terms == [SortTerm("status", False)]`. Both games take the fixture's
mirrored status (`unplayed`, from Task 1), so the sort values stay equal and
the primary-key tiebreaker is still what decides — which is the contract the
test guards.

- [ ] **Step 5: Run the sort and parity tests**

```
make test-fast ARGS="-k 'sort or read_parity'" >/tmp/b3.log 2>&1 && echo CLEAN || tail -40 /tmp/b3.log
```

Expected: CLEAN. The parity test now compares `status` against
`tracked_status`, which is the comparison it was written for.

- [ ] **Step 6: Run the fast suite**

```
make check-fast >/tmp/b4.log 2>&1 && echo CLEAN || tail -40 /tmp/b4.log
```

Expected: CLEAN.

- [ ] **Step 7: Commit**

```bash
git add games/sorting.py tests/test_sorting.py tests/test_playergame_read_parity.py
git commit -m "Order the games list by the status the library tracks"
```

---

### Task 4: The status and mastered filters read the projection

This is one task and one commit. The `FilterField` change, the widget's
nullability rule, the five `stats_links` builders and every literal in the
tests break or heal together — a reviewer cannot approve half of it, and no
intermediate state is green.

**Files:**
- Modify: `games/filters.py:148-149`
- Modify: `common/criteria.py:2687-2691`
- Modify: `games/views/stats_links.py:35,161,186,200,214,232`
- Modify: `tests/test_filters.py`, `tests/test_field_widget.py`,
  `tests/test_quick_filter_bar.py`
- Modify: `e2e/test_filter_builder_e2e.py`, `e2e/test_quick_filter_e2e.py`,
  `e2e/test_widgets_e2e.py`, `e2e/test_return_to_origin_e2e.py`

**Interfaces:**
- Consumes: `FilterField(lookup, …, metadata_lookup=…)` from child A —
  `metadata_lookup` is the path `field_metadata` walks when it differs from the
  path `to_q` emits. `with_filter_aliases` and `annotated_for_filtering` from
  Task 2. The mirrored fixture from Task 1.
- Produces: `GameFilter(status=…).to_q()` is `Q(tracked__status__in=[…])` over
  `PlayerGameStatus` words. Child C's stats predicates and child D's history
  both build on this.

- [ ] **Step 1: Write the failing tests**

Change the three existing assertions in `tests/test_filters.py` to state the
target. Two of them live in `TestGameFilterToQ`; the class header is shown so
the snippet reads as the file does, but only the two methods change:

```python
class TestGameFilterToQ:
    def test_status_choice_includes(self):
        gf = GameFilter.from_json(
            {"status": {"value": ["completed", "played"], "modifier": "INCLUDES"}}
        )
        q = gf.to_q()
        assert q == Q(tracked__status__in=["completed", "played"])

    def test_status_not_null(self):
        gf = GameFilter.from_json({"status": {"modifier": "NOT_NULL"}})
        q = gf.to_q()
        assert q == Q(tracked__status__isnull=False)
```

The third is in `TestFieldMetadata`:

```python
class TestFieldMetadata:
    def test_static_choices_game_status(self):
        from games.models import PlayerGame

        entry = self._by_name(GameFilter)["status"]
        assert entry["kind"] == "set"
        assert entry["choices"] == self._expected_choices(PlayerGame, "status")
```

- [ ] **Step 2: Run them and watch them fail**

```
make test-fast ARGS="-k 'status_choice_includes or status_not_null or static_choices_game_status'"
```

Expected: three FAILs — `Q(status__in=…) != Q(tracked__status__in=…)` and a
five-entry choices list against a six-entry one.

- [ ] **Step 3: Point the two fields at the projection**

In `games/filters.py`, in `GameFilter.fields`:

```python
        "status": FilterField(
            "tracked__status", metadata_lookup="player_games__status"
        ),
        "mastered": FilterField(
            "tracked__mastered", metadata_lookup="player_games__mastered"
        ),
```

The two paths differ on purpose. `to_q` emits `tracked__*`, the alias, which is
the only path that carries the library condition. `field_metadata` cannot walk
an alias — it is not a model field — so it walks `player_games__*`, the real
reverse relation, and finds the same terminal column with the same six choices.

- [ ] **Step 4: Take nullability from the terminal column when the paths differ**

`field_metadata` computes `nullable` from the whole lookup path, because a hop
through a nullable relation leaves the fields beyond it absent —
`platform__group` is nullable even though `Platform.group` is not. A reverse
relation hop has `ForeignObjectRel.null is True`, so `player_games__status`
reports nullable and the widget grows IS_NULL / NOT_NULL presence modifiers
that the six-word enum should not have.

The rule: when `metadata_lookup` is set, nullability comes from the terminal
column. `metadata_lookup` exists precisely to name a path the query does not
take, so the path's own hops say nothing about what the query can return.

In `common/criteria.py`, in `field_metadata`, replace the `nullable`
assignment. Keep the comment above it — it still explains the general case:

```python
            if field_spec is not None and field_spec.metadata_lookup is not None:
                nullable = bool(getattr(model_field, "null", False))
            elif resolved_lookup is not None:
                nullable = _lookup_is_nullable(model, resolved_lookup)
            else:
                nullable = False
```

`tests/test_field_widget.py::TestFieldWidgetNullableModifiers::test_non_nullable_enum_omits_is_null`
already guards this and must stay green.

- [ ] **Step 5: Emit words from the stats links**

`games/views/stats_links.py` builds `GameFilter`s that now compile against the
projection, so its five status values must be words. Change the import:

```python
from games.models import PlayerGameStatus, Purchase
```

(`Game` becomes unused — ruff will say so.) Then the five sites:

```python
    game_filter = GameFilter(status=ChoiceCriterion(value=[PlayerGameStatus.COMPLETED]))
```

```python
def _abandoned_or_refunded() -> PurchaseFilter:
    purchase_filter = PurchaseFilter(
        game_filter=GameFilter(
            status=ChoiceCriterion(value=[PlayerGameStatus.ABANDONED])
        )
    )
    purchase_filter.OR = [PurchaseFilter(is_refunded=BoolCriterion(value=True))]
    return purchase_filter
```

```python
    purchase_filter.game_filter = _not_finished_game(year, [PlayerGameStatus.COMPLETED])
```

```python
    purchase_filter.game_filter = _not_finished_game(
        year,
        [
            PlayerGameStatus.COMPLETED,
            PlayerGameStatus.RETIRED,
            PlayerGameStatus.ABANDONED,
        ],
    )
```

```python
    purchase_filter.game_filter = GameFilter(
        status=ChoiceCriterion(value=[PlayerGameStatus.COMPLETED]),
        playevent_filter=_ended_in_scope(year),
    )
```

in `purchases_finished`, `_abandoned_or_refunded`, `purchases_dropped`,
`purchases_unfinished` and `purchases_backlog_decrease` respectively. Only the
link values move. `stats_data.py` still computes from `Game.status`, and
`tests/test_stats_content_links.py` keeps passing because `_mirror()` keeps the
two in agreement. Child C moves the computation.

- [ ] **Step 6: Move the remaining literals**

Every one of these is a letter that must become a word, or a label that changes
with it (`Finished` → `Completed`, `f` → `completed`, `p` → `played`).

`tests/test_filters.py`, in `test_platform_filter_and_cross_entity` — only the
`from_json` argument changes:

```python
class TestExpandedFiltersAgainstDB:
    def test_platform_filter_and_cross_entity(self):
        from games.filters import PlatformFilter
        from games.models import Platform

        data = self._setup_entities()
        # Find platforms with games that are finished
        pf = PlatformFilter.from_json(
            {
                "game_filter": {
                    "status": {"value": ["completed"], "modifier": "INCLUDES"}
                }
            }
        )
        results = list(Platform.objects.filter(pf.to_q(UNRESTRICTED_FILTER_CONTEXT)))
        assert data["plat"] in results
```

`tests/test_filters.py`, in `test_status_prefilled`:

```python
                    "status": {
                        "value": [{"id": "completed", "label": "Completed"}],
                        "modifier": "INCLUDES",
                    }
```

with the two assertions below it becoming `'data-value="completed"' in html`
and `"Completed" in html`.

`tests/test_field_widget.py::test_enum_options_render_in_model_choice_order` —
the widget's options now come from `PlayerGameStatus`:

```python
    def test_enum_options_render_in_model_choice_order(self):
        # The enum widget's options come from FieldMeta["choices"] (the model
        # field's choices). Assert all PlayerGameStatus options render, in order,
        # with their labels — a regression in choice sourcing/order would slip
        # past the bare data-kind check.
        from games.models import PlayerGameStatus

        html = str(field_widget(GameFilter, "status"))
        positions = []
        for value, label in PlayerGameStatus.choices:
```

The rest of the loop body is unchanged.

`tests/test_quick_filter_bar.py::test_facet_prefill_renders_include_pill` —
`{"id": "completed", "label": "Completed"}` in the filter JSON, and
`self.assertIn("Completed", html)`.

`e2e/test_return_to_origin_e2e.py:61` —
`{"status": {"modifier": "INCLUDES", "value": ["played"]}}`.

`e2e/test_widgets_e2e.py:80-84` — the option click targets
`data-label="Completed"` and the pill assertion reads `"Completed"`.

`e2e/test_quick_filter_e2e.py` — the option click targets
`data-label="Completed"` (line 67); the round-tripped URL filter is
`{"id": "completed", "label": "Completed"}` (line 73); the pill assertion at
the end of `test_quick_facet_apply_filters_the_list` reads `"Completed"` (line
89); and `test_advanced_filter_shows_degraded_pill`'s nested JSON carries
`{"id": "completed", "label": "Completed"}` (line 142).

`e2e/test_filter_builder_e2e.py` — four `filter_json` literals become
`{"status": {"modifier": "INCLUDES", "value": ["completed"]}}` (lines 82, 148,
193, 227); the nested prefill at line 435 becomes
`{"AND": [{"status": {"value": ["played"], "modifier": "INCLUDES"}}]}`; and the
option selector at line 474 targets `data-value='completed'`. Update the three
comments and the docstring that name the letters — line 81, line 122, line 226
and the `to_q()` sentence at line 177, which becomes:

```
    The JSON {"status": {"modifier": "INCLUDES", "value": ["completed"]}} is a
    valid GameFilter JSON whose to_q() produces
    Q(tracked__status__in=["completed"]), matching only games the library
    tracks as completed.
```

The `Game.objects.create(..., status="f")` calls in those e2e modules stay as
they are: Task 1's fixture reads them and writes the matching word onto the
projection row.

- [ ] **Step 7: Run the fast suite**

```
make check-fast >/tmp/b5.log 2>&1 && echo CLEAN || tail -40 /tmp/b5.log
```

Expected: CLEAN. If `make format-check` complains, run `make format` — three of
these edits change a line's length enough for ruff to re-wrap it.

- [ ] **Step 8: Run the browser suite**

```
make test-e2e >/tmp/b6.log 2>&1 && echo CLEAN || grep -E "^(FAILED|ERROR)" /tmp/b6.log
```

Expected: CLEAN.

- [ ] **Step 9: Commit**

```bash
git add games/filters.py common/criteria.py games/views/stats_links.py tests/ e2e/
git commit -m "Filter the games list by the status the library tracks"
```

---

### Task 5: The gate

**Files:** none. This task runs the verification and opens the pull request.

- [ ] **Step 1: Run the full gate**

```
make check >/tmp/b7.log 2>&1 && echo CLEAN || tail -60 /tmp/b7.log
```

Expected: CLEAN. Not `check-fast` — only the full run collects `e2e/`, and four
of this plan's files are browser tests.

- [ ] **Step 2: Check the cosmetic leftovers**

These pass either way, because nothing reads them as a `Game.Status` any more,
but they now say something untrue. Fix them in this commit or state why not:

- `tests/test_filter_where.py:26-27` — a comment naming the status letters.
- `ts/elements/filter-tree/fixtures.json` — ten status values (lines 28, 35,
  36, 45, 52, 53, 63, 64, 75, 102). The cross-language contract test asserts
  `to_q()` equivalence between the TypeScript serializer and the Python
  backend, and both sides now compile the same alias, so the letters round-trip
  as opaque strings. They are still misleading. Change them to words and
  re-run `make test-ts` and `make test-fast ARGS="-k filter_tree_contract"`.

- [ ] **Step 3: Open the pull request**

Base `codex/playergame-read-cutover`, not `main`.

```bash
git push -u origin <branch>
gh pr create --base codex/playergame-read-cutover \
  --title "Filter and sort the games list by the tracked status" \
  --body "…"
```

The body states: the three spec corrections above; that
`comparable_columns` / `field_comparisons` still reads `Game.status` and
belongs to no child; and that `make check` is green.

---

## What child B leaves behind

For child C: `stats_data.py`'s four predicates and `PurchaseQuerySet`'s three
methods still read `Game.status`; `GameStatusUpdate` and
`PATCH /api/games/{id}/status` still take a letter. The `stats_links` builders
are already moved, so C's parity tests hold on both sides throughout.

For child D: `_mirror()`, the reverse half of `games/playergame_status.py`,
`SETTABLE_PLAYER_STATUSES`, and `tests/test_playergame_read_parity.py` —
including the `CATALOG_SORT_EXPRESSIONS` map Task 3 adds, which dies with the
file.

Owned by nobody: `comparable_columns` / `field_comparisons` over
`Game.status`.
