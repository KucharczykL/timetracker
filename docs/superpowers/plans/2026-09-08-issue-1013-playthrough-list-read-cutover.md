# Playthrough list read cutover (#1013) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Playthrough list page, its filter, sorts, quick facets and saved
presets read the `Playthrough` projection, so no screen reads `games_playevent`.

**Architecture:** `PlayEventFilter` becomes `PlaythroughFilter` over the
projection. Two endpoints that state an interval are compared through a handler
over their generated bound columns; the day count between them is date
arithmetic in SQL against the same columns the Python read uses. The list view
reads one scope helper shared with the numbering read, so a page number equals
a Game-detail number. A data migration rewrites `ended` to `completed` in saved
presets, forward and backward.

**Tech Stack:** Django 6 + PostgreSQL 18, pytest/pytest-django, vitest for the
TypeScript filter-tree serializer contract.

**Spec:** `docs/superpowers/specs/2026-09-07-issue-1013-playthrough-list-read-cutover-design.md`

## Global Constraints

- Every command goes through `make`. No raw `uv run`, `pytest`, `pnpm`, `tsc`.
  Focused runs: `make test ARGS="tests/test_filters.py -k playthrough -x"`.
- Iterate with `make check-fast`. The gate before declaring done is the full
  `make check` (includes `e2e/`).
- Python 3.14. Unabbreviated identifiers in Python and TypeScript.
- Refused words are enforced by `make vale` over docs and code comments. A
  projector *replays* events; the row it leaves is a *projection*. Never
  `fold`. Never `delete` for the library's own removal.
- One act, one verb: an event type, its command and its projection column share
  one verb.
- Never write to a `GeneratedField`. Never open a server-side cursor
  (`.iterator()` is refused by `tests/test_iterator_guard.py`).
- `common/criteria.py` must not import from `games`. Model opt-ins reach it
  duck-typed, through `getattr`, the way `with_filter_aliases` reads
  `annotated_for_filtering`.
- Build UI with Python components; `render_page()` for full pages.
- Mutating links carry `origin=`; no route mutates on GET.
- TDD: write the failing test, watch it fail, implement, watch it pass, commit.

---

## File Structure

**Modified**

- `games/reads/playthrough_endpoints.py` — `days_to_finish` counts the days the
  run touched (Task 1).
- `games/reads/playthrough_runs.py` — gains `library_runs()`, the one scope the
  page, the filter seams and the numbering share (Task 5).
- `common/criteria.py` — the comparison-operand walk skips a projection's
  scoping relation and admits four allowlisted bound columns (Task 2);
  `metadata_lookup` is allowed beside a handler (Task 3); `AggregateSpec` gains
  `base_scope` (Task 4); two new handler factories (Task 5).
- `games/models.py` — `Playthrough` declares the two duck-typed class
  attributes the walk reads (Task 2).
- `games/filters.py` — `PlaythroughFilter` replaces `PlayEventFilter`; both
  scoping seams, `MODE_PARSERS`, `_FILTER_LIST_URL`, `GameFilter` (Task 5).
- `common/components/custom_elements.py` — `FILTER_MODE_MODELS` (Task 5).
- `games/sorting.py` — `PLAYTHROUGH_SORTS`, the widened `Annotations` alias
  (Task 6).
- `games/views/playthrough.py` — the list view; `create_playthrough_tabledata`
  and `_legacy_actions` go (Task 7).
- `games/views/playthrough_rows.py` — the caller states its sort keys (Task 7).
- `games/views/game.py` — the Playthrough section links `View all` (Task 7).
- `common/components/quick_filter.py` — the playthroughs facets (Task 8).
- `games/views/stats_links.py` — six construction sites (Task 10).
- `ts/elements/filter-tree/fixtures.json`,
  `tests/test_filter_tree_contract.py` — the cross-language contract (Task 11).
- `CLAUDE.md` — the Playthrough paragraph (Task 12).

**Created**

- `games/migrations/0047_playthrough_preset_completed.py` (Task 9).
- `tests/test_playthrough_filter.py` — the projection filter's own suite
  (Task 5), extended by Tasks 1, 4 and 11.

**Untouched on purpose**

- `games/reads/playthrough_provenance.py` — `runs_for_rows` stays for the API
  (#1015).
- `games/models.py::PlayEvent` and its filterable columns — #771 takes them.
- `GAME_SORTS["finished"]`, `PURCHASE_SORTS["finished"]` — #1026.

---

### Task 1: The day count reads the days a run touched

**Files:**
- Modify: `games/reads/playthrough_endpoints.py:41-55`
- Test: `tests/test_playthrough_endpoints_read.py`

**Interfaces:**
- Produces: `days_to_finish(run: Playthrough) -> int | None`, unchanged
  signature, new arithmetic: `completed_upper - started_lower + 1 day`, `None`
  for an absent bound and for a completion before the start. Task 5's filter
  and Task 6's sort state the same rule in SQL.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_endpoints_read.py` (follow the file's
existing fixtures for building a run; `TemporalValue` states an endpoint):

```python
@pytest.mark.parametrize(
    "started,completed,expected",
    [
        ("2025-03-01", "2025-03-01", 1),
        ("2025-03-01", "2025-03-02", 2),
        ("2025-03-01", "2025-03-30", 30),
        ("2025-03-02", "2025-03-01", None),
    ],
)
def test_the_count_includes_both_ends(run, started, completed, expected):
    """A same-day run touched one day, not zero."""
    Playthrough.objects.filter(pk=run.pk).update(
        started=TemporalValue.parse(started),
        completed=TemporalValue.parse(completed),
    )

    assert days_to_finish(Playthrough.objects.get(pk=run.pk)) == expected


def test_a_month_at_both_ends_counts_the_whole_month(run):
    """The widest span the two values allow, both ends counted."""
    Playthrough.objects.filter(pk=run.pk).update(
        started=TemporalValue.parse("2025-03"),
        completed=TemporalValue.parse("2025-03"),
    )

    assert days_to_finish(Playthrough.objects.get(pk=run.pk)) == 31
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_endpoints_read.py -k count -x"`
Expected: FAIL — the next-day case reads 1 and the month case reads 30.

- [ ] **Step 3: Rewrite the read**

```python
def days_to_finish(run: Playthrough) -> int | None:
    """How many days the run touched, or nothing.

    Both ends are counted: a same-day run reads 1 and a run
    finished the next day reads 2. An absent bound and a
    completion before the start read nothing, and the count
    never reads 0.
    """
    started = run.started_lower
    completed = run.completed_upper
    if started is None or completed is None:
        return None
    days = (completed - started).days + 1
    return days if days >= 1 else None
```

- [ ] **Step 4: Run the file**

Run: `make test ARGS="tests/test_playthrough_endpoints_read.py"`
Expected: PASS. Fix any older assertion in that file that pinned the plain
difference — the new number is one higher for every run longer than a day.

- [ ] **Step 5: Run every reader of the count**

Run: `make test ARGS="tests/test_playthrough_rows.py tests/test_game_detail_playthroughs.py"`
Expected: PASS. A row's `Days to finish` cell prints what the read answers.

- [ ] **Step 6: Commit**

```bash
git add games/reads/playthrough_endpoints.py tests/test_playthrough_endpoints_read.py
git commit -m "Count both ends of a run"
```

---

### Task 2: The operand walk skips scoping and admits four bounds

**Files:**
- Modify: `common/criteria.py:2069-2100` (`_maybe_group_for`),
  `common/criteria.py:2266-2290` (`_comparison_relations`),
  `common/criteria.py:2291-2330` (`_own_comparable_columns`)
- Modify: `games/models.py` (`ProjectionModel`, `Playthrough`)
- Test: `tests/test_filters.py` (the comparison-operand class), new cases

**Interfaces:**
- Produces: two duck-typed class attributes read through `getattr` — 
  `Model.comparison_scoping_relations: tuple[str, ...]` (relation names the
  operand walk never follows) and
  `Model.comparable_temporal_bounds: Mapping[str, str]` (a temporal generated
  column the walk admits, mapped to the words the picker prints).
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_filters.py`, in the comparison-columns test class:

```python
def test_a_projection_offers_no_column_through_its_library(self):
    """`library` is scoping, not data: 55 columns of another
    entity answer nothing about a run."""
    values = {column["value"] for column in comparable_columns(Playthrough)}

    assert not any(value.startswith("library__") for value in values)


def test_a_run_offers_its_four_bound_columns(self):
    """A temporal generated column is excluded until it is
    scoped in; these four are, and carry their own words."""
    columns = {
        column["value"]: column["label"] for column in comparable_columns(Playthrough)
    }

    assert columns["started_lower"] == "Started (earliest)"
    assert columns["started_upper"] == "Started (latest)"
    assert columns["completed_lower"] == "Completed (earliest)"
    assert columns["completed_upper"] == "Completed (latest)"


def test_the_catalog_still_hides_its_temporal_bounds(self):
    """Nobody scoped Release's bounds in, so they stay out."""
    values = {column["value"] for column in comparable_columns(Release)}

    assert not any(value.endswith("_lower") for value in values)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_filters.py -k 'projection_offers_no_column or four_bound_columns' -x"`
Expected: FAIL — `library__*` columns are present and `started_lower` is absent.

- [ ] **Step 3: Declare the two attributes on the models**

In `games/models.py`, on `ProjectionModel` (inside the class body, above
`class Meta`):

```python
    #: The operand walk never follows these. A projection's
    #: `library` is scoping, and every reverse relation of
    #: UserLibrary behind it answers nothing about the row.
    comparison_scoping_relations: ClassVar[tuple[str, ...]] = ("library",)
```

On `Playthrough` (below `removed_at`, above `class Meta`):

```python
    #: The bound columns a comparison may name, and the words
    #: for each. `_maybe_group_for` excludes a column generated
    #: from a temporal value; these four are scoped in, and
    #: carry their own words because `verbose_name` would read
    #: `Started Lower`.
    comparable_temporal_bounds: ClassVar[Mapping[str, str]] = {
        "started_lower": "Started (earliest)",
        "started_upper": "Started (latest)",
        "completed_lower": "Completed (earliest)",
        "completed_upper": "Completed (latest)",
    }
```

`ClassVar` and `Mapping` are already imported in `games/models.py`; add them to
the existing `typing` / `collections.abc` imports if either is missing.

- [ ] **Step 4: Read both attributes in the walk**

In `common/criteria.py`, `_comparison_relations`, skip the scoping relation —
this covers `_comparison_multivalued_sources` too, which enumerates its
`fk__multi` block from this same function:

```python
    scoping = getattr(model, "comparison_scoping_relations", ())
    relations: list[tuple[str, type[models.Model], str]] = []
    for model_field in model._meta.get_fields():
        if model_field.name in scoping:
            continue
        if (
```

In `_maybe_group_for`, let an allowlisted column through the temporal
exclusion:

```python
    #: A column generated from a temporal value is excluded until
    #: somebody scopes it in: the words and the operators are the
    #: model's to state, not the walk's to guess.
    allowlisted = column in getattr(model, "comparable_temporal_bounds", {})
    if (
        not allowlisted
        and isinstance(model_field, models.GeneratedField)
        and isinstance(
            getattr(model_field, "expression", None), _TEMPORAL_PROJECTION_EXPRESSIONS
        )
    ):
        return None
```

In `_own_comparable_columns`, prefer the allowlist's words:

```python
        bounds = getattr(model, "comparable_temporal_bounds", {})
        verbose_name = getattr(model_field, "verbose_name", column)
        raw_label: str = bounds.get(column) or verbose_name.title()
```

- [ ] **Step 5: Run the tests**

Run: `make test ARGS="tests/test_filters.py -k 'comparab or comparison' -x"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add common/criteria.py games/models.py tests/test_filters.py
git commit -m "Offer a run's bounds and no library column"
```

---

### Task 3: A handler field states its widget's column

**Files:**
- Modify: `common/criteria.py:1030-1039` (`FilterField.__post_init__`),
  `common/criteria.py:2715-2730` (`field_metadata`'s resolution gate)
- Test: `tests/test_filter_widgets.py`

**Interfaces:**
- Produces: `FilterField(handler=…, metadata_lookup="started_lower")` is legal.
  `field_metadata` resolves the column named by `metadata_lookup` even where a
  handler is set, and reads nullability from that terminal column. Task 5's
  `started` and `completed` fields depend on this.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_filter_widgets.py`:

```python
def test_a_handler_field_states_its_widgets_column():
    """A handler resolves no column, so the picker reads the
    one the field names instead — otherwise a date field
    offers no `is null`."""

    @dataclass
    class HandlerFilter(OperatorFilter):
        started: DateCriterion | None = None

        fields: ClassVar[dict[str, FilterField]] = {
            "started": FilterField(
                handler=lambda criterion: Q(),
                metadata_lookup="started_lower",
            ),
        }

        @classmethod
        def _comparison_model(cls):
            from games.models import Playthrough

            return Playthrough

    meta = {entry["name"]: entry for entry in field_metadata(HandlerFilter)}

    assert meta["started"]["kind"] == "date"
    assert meta["started"]["nullable"] is True
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_filter_widgets.py -k handler_field_states -x"`
Expected: FAIL — `ValueError: FilterField metadata_lookup has no effect on a
handler-mapped field`.

- [ ] **Step 3: Take the refusal out and open the gate**

Delete this block from `FilterField.__post_init__`:

```python
        if self.metadata_lookup is not None and self.handler is not None:
            # Handler-mapped fields skip column resolution, so metadata_lookup
            # has no consumer.
            raise ValueError(
                "FilterField metadata_lookup has no effect on a handler-mapped field"
            )
```

and amend the `metadata_lookup` docstring line on the dataclass:

```python
    # The path ``field_metadata`` walks, when it differs from the path ``to_q``
    # emits. A query may read an annotation alias (``tracked__status``), which
    # names no model column, or a handler over two bound columns, which names
    # none either; the widget still needs a real column's choices and
    # nullability (``player_games__status``, ``started_lower``). Ignored by
    # ``to_q``.
    metadata_lookup: ORMLookup | None = None
```

In `field_metadata`, widen the resolution gate:

```python
            if (
                field_spec is not None
                and (field_spec.handler is None or field_spec.metadata_lookup is not None)
                and model is not None
            ):
```

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_filter_widgets.py tests/test_filters.py -k 'metadata or handler' -x"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/criteria.py tests/test_filter_widgets.py
git commit -m "Let a handler field name its widget's column"
```

---

### Task 4: An aggregate states its own base scope

**Files:**
- Modify: `common/criteria.py:1302-1335` (`AggregateSpec`),
  `common/criteria.py:3063-3110` (`aggregate_to_q`)
- Modify: `tests/test_filters.py:4855-4868` (the accessor drift guard)
- Test: `tests/test_filters.py`

**Interfaces:**
- Produces: `AggregateSpec(..., base_scope: OperatorFilter | None = None)` — a
  static sub-filter of the spec's own `scope_filter` class, resolved through
  `context.queryset_for(<scope model>)` and composed with a criterion's own
  scope. Task 5's `playthrough_count` is the only spec that states one.
- Produces: the drift guard walks a `__`-separated accessor path, so
  `player_games__playthroughs` resolves.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_filters.py`, beside the other aggregate tests:

```python
def test_a_base_scope_narrows_every_reduction(self, owned_library):
    """The spec's own scope rides along with the criterion's."""
    spec = AggregateSpec(
        "count",
        "sessions",
        SessionFilter,
        base_scope=SessionFilter(note=StringCriterion(value="counted")),
    )
    counted = Session.objects.create(...)  # note="counted", on `game`
    Session.objects.create(...)  # note="ignored", on the same game

    matching = Game.objects.filter(
        aggregate_to_q(
            AggregateCriterion(value=1, modifier=Modifier.EQUALS),
            model=Game,
            spec=spec,
            context=filter_query_context_for_library(owned_library),
        )
    )

    assert list(matching) == [counted.game]


def test_a_base_scope_must_match_the_scope_filter(self):
    with pytest.raises(TypeError):
        AggregateSpec("count", "sessions", SessionFilter, base_scope=GameFilter())
```

(Build the two sessions with the file's existing helpers; the assertion is that
the game whose only *counted* session matches reads exactly 1.)

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_filters.py -k base_scope -x"`
Expected: FAIL — `TypeError: AggregateSpec.__init__() got an unexpected keyword
argument 'base_scope'`.

- [ ] **Step 3: Declare it on the spec**

In `AggregateSpec`, after `unit`:

```python
    #: A scope the spec states itself, on top of whatever the
    #: criterion states. `playthrough_count` counts the runs
    #: whose completion is stated, so a count of 0 means a game
    #: nobody finished rather than a game nobody tracks.
    base_scope: OperatorFilter | None = None
```

and, at the end of `__post_init__`:

```python
if self.base_scope is not None and not isinstance(self.base_scope, self.scope_filter):
    raise TypeError(
        f"a base scope must be a {self.scope_filter.__name__},"
        f" got {type(self.base_scope).__name__}"
    )
```

- [ ] **Step 4: Compose both scopes in `aggregate_to_q`**

Replace the `scope_condition` block:

```python
    scope_condition: Q | None = None
    if criterion.scope is not None:
        # A hand-assembled criterion could carry a wrong-typed scope; its Q would
        # be built in the wrong model's namespace and produce a silently-wrong
        # (or FieldError-ing) subquery, so guard the type loudly. Never user
        # input — from_json always builds the scope from the spec's class.
        if not isinstance(criterion.scope, spec.scope_filter):
            raise RuntimeError(
                f"aggregate scope must be a {spec.scope_filter.__name__},"
                f" got {type(criterion.scope).__name__}"
            )
    scopes = [scope for scope in (spec.base_scope, criterion.scope) if scope is not None]
    if scopes:
        related_model: ModelClass = spec.scope_filter._comparison_model()
        if related_model is None:
            raise RuntimeError(
                f"{spec.scope_filter.__name__} has no comparison model"
                f" to scope a {spec.accessor!r} aggregate"
            )
        matching = context.queryset_for(related_model)
        for scope in scopes:
            matching = matching.filter(scope.to_q(context))
        scope_condition = Q(**{f"{spec.accessor}__in": matching})
```

- [ ] **Step 5: Teach the drift guard to walk a path**

In `tests/test_filters.py::test_aggregate_accessor_reaches_the_scope_filter_model`:

```python
        parent_model = filter_cls._comparison_model()
        for name, spec in filter_cls.aggregates.items():
            related_model = parent_model
            #: An accessor may be a path: a run hangs off the
            #: tracked game, not the catalog row.
            for hop in spec.accessor.split("__"):
                related_model = related_model._meta.get_field(hop).related_model
            assert related_model is spec.scope_filter._comparison_model(), name
```

- [ ] **Step 6: Run the tests**

Run: `make test ARGS="tests/test_filters.py -k 'aggregate' -x"`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add common/criteria.py tests/test_filters.py
git commit -m "Let an aggregate state its own scope"
```

---

### Task 5: PlaythroughFilter

The biggest task, and one deliverable: after it, `?filter=` over the
projection answers, and `PlayEventFilter` is gone from the codebase.

**Files:**
- Modify: `games/reads/playthrough_runs.py` (add `library_runs`)
- Modify: `common/criteria.py` (two handler factories, near
  `bool_isnull_handler` at 2897-2933)
- Modify: `games/filters.py` (the filter class, `GameFilter`, the aggregate
  table, both scoping seams, `MODE_PARSERS`, `_FILTER_LIST_URL`)
- Modify: `common/components/custom_elements.py:79-93` (`FILTER_MODE_MODELS`)
- Create: `tests/test_playthrough_filter.py`
- Modify: every test naming `PlayEventFilter` / `parse_playthrough_filter`
  (`tests/test_filters.py`, `tests/test_filter_paths.py`,
  `tests/test_game_detail_links.py`, `tests/test_playhistory_fk_uuid.py`,
  `tests/test_filter_builder_page.py`, `tests/test_library_page_isolation.py`)

**Interfaces:**
- Consumes: Task 2's bound columns (the builder page offers them), Task 3's
  `metadata_lookup`-beside-a-handler, Task 4's `AggregateSpec.base_scope`.
- Produces:
  - `games.reads.playthrough_runs.library_runs(library: UserLibrary) -> QuerySet[Playthrough]`
    — live ordinary runs of one library, scoped four ways. Task 7's page reads it.
  - `common.criteria.temporal_interval_handler(value_field: str, lower_field: str, upper_field: str) -> FieldHandler`
  - `common.criteria.days_touched_handler(lower_field: str, upper_field: str) -> FieldHandler`
  - `games.filters.PlaythroughFilter`, `parse_playthrough_filter(json_str) -> PlaythroughFilter | None`
  - `GameFilter.playthrough_filter: PlaythroughFilter | None`
  - `GameFilter.aggregates["playthrough_count"]` counting
    `player_games__playthroughs` with a completion base scope.

- [ ] **Step 1: Write the failing scope test**

Create `tests/test_playthrough_filter.py`:

```python
"""#1013: the filter reads the projection."""

import pytest

from games.models import Game, Playthrough, PlaythroughKind
from games.reads.playthrough_runs import library_runs

pytestmark = pytest.mark.django_db


def test_the_scope_states_all_four_things(owned_library, other_library):
    """A removed run, an imported one and another library's
    reach no page and no count."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    run = Playthrough.objects.get(player_game__game=game)
    imported = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED,
        created_at=timezone.now(),
    )

    scoped = set(library_runs(owned_library).values_list("pk", flat=True))

    assert run.pk in scoped
    assert imported.pk not in scoped
```

(Extend with a removed run and a run of `other_library`; the repo's conftest
provides both library fixtures. `PlaythroughKind.IMPORTED` — read the enum in
`games/models.py` and use its real member name.)

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_filter.py -x"`
Expected: FAIL — `ImportError: cannot import name 'library_runs'`.

- [ ] **Step 3: Add the shared scope**

In `games/reads/playthrough_runs.py`, above `live_ordinary_runs`:

```python
def library_runs(library: UserLibrary) -> QuerySet[Playthrough]:
    """Every live ordinary run this library holds.

    The one scope the page, the filter seams and the numbering
    share. `display_name` refuses a live ordinary row no number
    was counted across, so a page reading wider than
    `numbered_for` reads would raise on its first blank name.

    The library is stated beside the parent, never inferred: a
    run may name another library's PlayerGame, which is the
    drift `audit_library_ownership` reports.
    """
    return Playthrough.objects.filter(
        library=library,
        player_game__library=library,
        removed_at__isnull=True,
        kind=PlaythroughKind.ORDINARY,
    )
```

and read it from `live_ordinary_runs`, which states the same four things today:

```python
def live_ordinary_runs(
    library: UserLibrary, player_game: PlayerGame
) -> QuerySet[Playthrough]:
    """This game's live ordinary runs, oldest first."""
    return (
        library_runs(library)
        .filter(player_game=player_game)
        .order_by("created_at", "id")
    )
```

- [ ] **Step 4: Run it and commit the scope**

Run: `make test ARGS="tests/test_playthrough_filter.py tests/test_playthrough_runs_read.py -x"`
Expected: PASS.

```bash
git add games/reads/playthrough_runs.py tests/test_playthrough_filter.py
git commit -m "State one scope for a library's runs"
```

- [ ] **Step 5: Write the failing endpoint-comparison tests**

Append to `tests/test_playthrough_filter.py` a table-driven suite. Build one
run per shape and assert the matched set per modifier:

```python
#: One run per shape the endpoint can state.
SHAPES = {
    "day": "2025-03-15",
    "month": "2025-03",
    "year": "2025",
    "decade": "202X",
    "range": "2025-03-10/2025-03-20",
    "open start": "/2025-03-20",
    "open end": "2025-03-10/",
}


@pytest.fixture
def runs_by_shape(owned_library) -> dict[str, Playthrough]:
    """One run per shape, each with its start stated."""
    made = {}
    for shape, text in SHAPES.items():
        game = Game.objects.create(library=owned_library, name=f"Game {shape}")
        run = Playthrough.objects.get(player_game__game=game)
        Playthrough.objects.filter(pk=run.pk).update(
            start_recorded_at=timezone.now(), started=TemporalValue.parse(text)
        )
        made[shape] = Playthrough.objects.get(pk=run.pk)
    return made


def matched(owned_library, filter_object) -> set[str]:
    """The shapes this filter answers."""
    queryset = library_runs(owned_library).filter(
        filter_object.to_q(filter_query_context_for_library(owned_library))
    )
    return {
        run.player_game.game.name.removeprefix("Game ")
        for run in queryset.select_related("player_game__game")
    }


def test_equality_overlaps(owned_library, runs_by_shape):
    """A run stated as 2025 may well have started that day."""
    assert matched(owned_library, PlaythroughFilter.where(started="2025-03-15")) == {
        "day",
        "month",
        "year",
        "decade",
        "range",
        "open start",
        "open end",
    }


def test_equality_outside_every_interval_answers_nothing(owned_library, runs_by_shape):
    assert matched(owned_library, PlaythroughFilter.where(started="2024-01-01")) == {
        "decade",
        "open start",
    }


def test_after_is_certain(owned_library, runs_by_shape):
    """A run is after March only where the earliest day it can
    name is after March."""
    assert (
        matched(owned_library, PlaythroughFilter.where(started__gt="2025-03-31"))
        == set()
    )


def test_before_is_certain(owned_library, runs_by_shape):
    assert (
        matched(owned_library, PlaythroughFilter.where(started__lt="2025-03-01"))
        == set()
    )


def test_negation_is_certain(owned_library, runs_by_shape):
    """Not that day means no day it can name is that day."""
    assert (
        matched(owned_library, PlaythroughFilter.where(started__ne="2025-03-15"))
        == set()
    )


def test_between_overlaps(owned_library, runs_by_shape):
    assert "day" in matched(
        owned_library,
        PlaythroughFilter.where(started__between=("2025-03-01", "2025-03-31")),
    )


def test_an_act_with_no_day_answers_neither_side(owned_library):
    """It answers `is null`, and the marker answers the act."""
    game = Game.objects.create(library=owned_library, name="No day")
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(
        start_recorded_at=timezone.now(), started=None
    )

    assert (
        matched(owned_library, PlaythroughFilter.where(started="2025-03-15")) == set()
    )
    assert (
        matched(owned_library, PlaythroughFilter.where(started__ne="2025-03-15"))
        == set()
    )
    assert matched(owned_library, PlaythroughFilter.where(started__isnull=True)) == {
        "day"
    }  # rename
    assert matched(owned_library, PlaythroughFilter.where(is_started=True)) == {
        "day"
    }  # rename
```

(The last two assertions name the game this test creates — use its own name
rather than the shape names; the placeholder comment marks the two lines to
finish.) Mirror the whole suite for `completed`; a parametrized
`endpoint` argument over `("started", "completed")` keeps it one suite.

- [ ] **Step 6: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_filter.py -x"`
Expected: FAIL — `ImportError: cannot import name 'PlaythroughFilter'`.

- [ ] **Step 7: Write the two handler factories**

In `common/criteria.py`, after `bool_nonzero_duration_handler`:

```python
def _bound_at_most(field_name: str, value: Any) -> Q:
    """The bound is at or before the day, or is unbounded."""
    return Q(**{f"{field_name}__lte": value}) | Q(**{f"{field_name}__isnull": True})


def _bound_at_least(field_name: str, value: Any) -> Q:
    """The bound is at or after the day, or is unbounded."""
    return Q(**{f"{field_name}__gte": value}) | Q(**{f"{field_name}__isnull": True})


def temporal_interval_handler(
    value_field: str, lower_field: str, upper_field: str
) -> FieldHandler:
    """Compare a day against an endpoint that states an interval.

    A day, a month, a year, a decade or a range: the two
    generated bound columns hold the earliest day the value can
    name and the latest, both inclusive, and an absent bound
    reads as unbounded. Every comparison first states that the
    endpoint holds a value, so an act recorded with no day
    answers neither an equality nor its negation. `is null`
    reads the endpoint's own value, not a bound: an open range
    states a value while leaving one bound null.
    """

    def handler(criterion: _Criterion) -> Q:
        modifier = criterion.modifier
        if modifier == Modifier.IS_NULL:
            return Q(**{f"{value_field}__isnull": True})
        if modifier == Modifier.NOT_NULL:
            return Q(**{f"{value_field}__isnull": False})
        stated = Q(**{f"{value_field}__isnull": False})
        value = criterion.value
        value2 = getattr(criterion, "value2", None)
        if modifier == Modifier.EQUALS:
            return (
                stated
                & _bound_at_most(lower_field, value)
                & _bound_at_least(upper_field, value)
            )
        if modifier == Modifier.NOT_EQUALS:
            return stated & (
                Q(**{f"{lower_field}__gt": value}) | Q(**{f"{upper_field}__lt": value})
            )
        if modifier == Modifier.GREATER_THAN:
            return stated & Q(**{f"{lower_field}__gt": value})
        if modifier == Modifier.LESS_THAN:
            return stated & Q(**{f"{upper_field}__lt": value})
        if modifier in (Modifier.BETWEEN, Modifier.NOT_BETWEEN):
            if value is None or value2 is None:
                raise FilterError(f"{modifier} requires two bounds (value and value2)")
            low, high = min(value, value2), max(value, value2)
            if modifier == Modifier.BETWEEN:
                return (
                    stated
                    & _bound_at_most(lower_field, high)
                    & _bound_at_least(upper_field, low)
                )
            return stated & (
                Q(**{f"{lower_field}__gt": high}) | Q(**{f"{upper_field}__lt": low})
            )
        raise FilterError(f"Unsupported modifier {modifier} for a temporal endpoint")

    return handler


def days_touched_handler(lower_field: str, upper_field: str) -> FieldHandler:
    """Compare a day count against two bound columns.

    The count is the days the run touched, both ends included,
    which is what `games/reads/playthrough_endpoints.py` reads:
    `N` days means the later bound is `N - 1` days after the
    earlier one. Every comparison states that both bounds are
    known and the span is not negative, so a run with no answer
    matches nothing and a count below 1 matches nothing. The
    field names no column, so it offers no `is null`.
    """
    from datetime import timedelta

    def span_end(count: Any) -> Any:
        return F(lower_field) + timedelta(days=int(count) - 1)

    def handler(criterion: _Criterion) -> Q:
        modifier = criterion.modifier
        known = (
            Q(**{f"{lower_field}__isnull": False})
            & Q(**{f"{upper_field}__isnull": False})
            & Q(**{f"{upper_field}__gte": F(lower_field)})
        )
        value = criterion.value
        value2 = getattr(criterion, "value2", None)
        if modifier == Modifier.EQUALS:
            return known & Q(**{upper_field: span_end(value)})
        if modifier == Modifier.NOT_EQUALS:
            return known & ~Q(**{upper_field: span_end(value)})
        if modifier == Modifier.GREATER_THAN:
            return known & Q(**{f"{upper_field}__gt": span_end(value)})
        if modifier == Modifier.LESS_THAN:
            return known & Q(**{f"{upper_field}__lt": span_end(value)})
        if modifier in (Modifier.BETWEEN, Modifier.NOT_BETWEEN):
            if value is None or value2 is None:
                raise FilterError(f"{modifier} requires two bounds (value and value2)")
            low, high = min(value, value2), max(value, value2)
            if modifier == Modifier.BETWEEN:
                return (
                    known
                    & Q(**{f"{upper_field}__gte": span_end(low)})
                    & Q(**{f"{upper_field}__lte": span_end(high)})
                )
            return known & (
                Q(**{f"{upper_field}__lt": span_end(low)})
                | Q(**{f"{upper_field}__gt": span_end(high)})
            )
        raise FilterError(f"Unsupported modifier {modifier} for a day count")

    return handler
```

`F` is already imported in `common/criteria.py`; add it to the `django.db.models`
import if it is not.

- [ ] **Step 8: Write the filter class**

In `games/filters.py`, replace the whole `PlayEventFilter` block:

```python
# ── PlaythroughFilter ──────────────────────────────────────────────────────


@dataclass
class PlaythroughFilter(OperatorFilter):
    """Filter for the Playthrough projection."""

    AND: list[PlaythroughFilter] = field(default_factory=list)
    OR: list[PlaythroughFilter] = field(default_factory=list)
    NOT: list[PlaythroughFilter] = field(default_factory=list)

    game: UUIDMultiCriterion | None = None  # player_game__game__id
    name: StringCriterion | None = None
    started: DateCriterion | None = None  # the interval the endpoint states
    completed: DateCriterion | None = None
    is_started: BoolCriterion | None = None  # the act, day or no day
    is_completed: BoolCriterion | None = None
    days_to_finish: IntCriterion | None = None  # date arithmetic, no column
    note: StringCriterion | None = None
    start_note: StringCriterion | None = None
    completion_note: StringCriterion | None = None
    created_at: DateCriterion | None = None  # compared via __date

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: runs at games matching these criteria
    game_filter: GameFilter | None = None

    #: #1013 renamed the endpoint to the word the column, the
    #: command and the screen use. A saved preset is rewritten by
    #: migration 0047, but a bookmarked ``?filter=`` is not.
    renamed_fields: ClassVar[Mapping[str, str]] = {"ended": "completed"}

    fields: ClassVar[dict[str, FilterField]] = {
        "game": FilterField("player_game__game__id", search_url="/api/games/search"),
        "name": FilterField(),
        "started": FilterField(
            handler=temporal_interval_handler(
                "started", "started_lower", "started_upper"
            ),
            metadata_lookup="started_lower",
        ),
        "completed": FilterField(
            handler=temporal_interval_handler(
                "completed", "completed_lower", "completed_upper"
            ),
            metadata_lookup="completed_lower",
        ),
        "is_started": FilterField(
            handler=bool_isnull_handler("start_recorded_at", invert=True),
            label="Has a start",
        ),
        "is_completed": FilterField(
            handler=bool_isnull_handler("completion_recorded_at", invert=True),
            label="Has a completion",
        ),
        "days_to_finish": FilterField(
            handler=days_touched_handler("started_lower", "completed_upper"),
            label="Days to finish",
        ),
        "note": FilterField(),
        "start_note": FilterField(),
        "completion_note": FilterField(),
        "created_at": FilterField("created_at__date"),
    }

    @classmethod
    def _comparison_model(cls) -> type[Playthrough]:
        from games.models import Playthrough

        return Playthrough

    def _extra_q(self, context: FilterQueryContext | None = None) -> Q:
        q = Q()

        #: A blank name renders as `Playthrough N`, which is
        #: counted at read time and stored nowhere, so that text
        #: answers no search.
        if self.search is not None:
            q &= search_q(
                self.search,
                "player_game__game__name",
                "name",
                "note",
                "start_note",
                "completion_note",
            )

        if self.game_filter is not None:
            from games.models import Game

            q &= relation_to_q(
                self.game_filter,
                context=context,
                related_model=Game,
                related_lookup="id",
                parent_field="player_game__game__id",
            )

        return q
```

Import `temporal_interval_handler` and `days_touched_handler` from
`common.criteria` at the top of `games/filters.py`, beside `bool_isnull_handler`.

- [ ] **Step 9: Rewire every reference**

In `games/filters.py`:

```python
    playthrough_filter: PlaythroughFilter | None = None
```

```python
        if self.playthrough_filter is not None:
            from games.models import Playthrough

            q &= relation_to_q(
                self.playthrough_filter,
                context=context,
                related_model=Playthrough,
                related_lookup="player_game__game__id",
            )
```

```python
    "playthrough_count": AggregateSpec(
        "count",
        "player_games__playthroughs",
        PlaythroughFilter,
        #: Every tracked game holds at least one run, so a plain
        #: count reads 1 for a game nobody played. This counts the
        #: runs whose completion is stated, which is the number
        #: `Played N times` prints.
        base_scope=PlaythroughFilter(is_completed=BoolCriterion(value=True)),
    ),
```

```python
def parse_playthrough_filter(json_str: str) -> PlaythroughFilter | None:
    return filter_from_json(PlaythroughFilter, json_str)
```

```python
    PlaythroughFilter: "games:list_playthroughs",
```

Both scoping seams — `filter_queryset_for_library` gains a second special case
and `filter_query_context_for_library` swaps its entry:

```python
    from games.models import Game, Playthrough
    from games.reads.playthrough_runs import library_runs

    model = apps.get_model("games", model_name)
    if model is Game:
        return Game.objects.tracked_by(library)
    #: The projection declares no manager, so it answers no
    #: `for_library`: every read states its own scope.
    if model is Playthrough:
        return library_runs(library)
    return model.objects.for_library(library)
```

```python
        Playthrough: library_runs(library),
```

— dropping the `PlayEvent` entry and its import from both functions, and
amending `filter_queryset_for_library`'s docstring, which today says every
model implements `for_library`.

In `common/components/custom_elements.py`:

```python
    "playthroughs": "playthrough",
```

— deleting the `#771 renames it` comment above it.

- [ ] **Step 10: Run the new suite**

Run: `make test ARGS="tests/test_playthrough_filter.py -x"`
Expected: PASS.

- [ ] **Step 11: Write the days-to-finish parity test**

Append to `tests/test_playthrough_filter.py` — one test drives the read and the
filter over the same rows, so the two cannot drift:

```python
@pytest.mark.parametrize("count", [1, 2, 30, 31])
def test_the_filter_answers_what_the_read_counts(owned_library, spans, count):
    """`spans` holds runs of -1, 0, 1, 2 and 30 days and one
    month-precision run, keyed by the game name."""
    by_read = {
        run.player_game.game.name
        for run in library_runs(owned_library).select_related("player_game__game")
        if days_to_finish(run) == count
    }

    assert (
        matched(owned_library, PlaythroughFilter.where(days_to_finish=count)) == by_read
    )


def test_a_count_below_one_answers_nothing(owned_library, spans):
    assert matched(owned_library, PlaythroughFilter.where(days_to_finish=0)) == set()


def test_a_run_with_one_bound_answers_no_comparison(owned_library, spans):
    """A started run nobody completed has no count."""
    assert "unfinished" not in matched(
        owned_library, PlaythroughFilter.where(days_to_finish__gt=0)
    )
```

- [ ] **Step 12: Run it**

Run: `make test ARGS="tests/test_playthrough_filter.py -k days -x"`
Expected: PASS.

- [ ] **Step 13: Sweep every remaining reference**

```bash
grep -rn "PlayEventFilter" --include=*.py --include=*.json --include=*.ts .
```

Rewrite each. In `tests/test_filters.py` this means:

- the imports and `ALL_FILTERS` / `_ALL_FILTERS` membership,
- `SEARCH_COLUMNS[PlaythroughFilter] = ("player_game__game__name", "name",
  "note", "start_note", "completion_note")`,
- `test_comparison_model` asserting `Playthrough`,
- every date test built on `PlayEvent` rows — rebuild them on runs, stating an
  endpoint with `Playthrough.objects.filter(pk=…).update(started=…)`,
- `tests/test_playhistory_fk_uuid.py`'s five construction sites,
- `tests/test_filter_paths.py`'s `_BarCase("playthroughs", PlaythroughFilter)`,
- `tests/test_game_detail_links.py`'s two sites, which now build
  `PlaythroughFilter.where(game=[game.id])`.

`tests/test_filter_tree_contract.py` and `fixtures.json` are Task 11 — leave
them failing until then if they are the only red left, and say so in the commit.

- [ ] **Step 14: Run the aggregate and builder suites**

Run: `make test ARGS="tests/test_filters.py tests/test_filter_builder_page.py tests/test_filter_widgets.py -x"`
Expected: PASS. `playthrough_count` reads 0 for a tracked game nobody finished
— add that assertion to `tests/test_playthrough_filter.py` if no existing test
states it, and assert it equals `completed_run_count(library, tracked)`.

- [ ] **Step 15: Commit**

```bash
git add games/filters.py common/criteria.py common/components/custom_elements.py \
        games/reads/playthrough_runs.py tests/
git commit -m "Filter the Playthrough projection"
```

---

### Task 6: The sorts read the projection

**Files:**
- Modify: `games/sorting.py:62` (the `Annotations` alias), `games/sorting.py:120-129`
  (`PLAYTHROUGH_SORTS`)
- Test: `tests/test_sorting.py`

**Interfaces:**
- Consumes: nothing from Task 5 at import time (the sort map names columns, not
  filter classes).
- Produces: `PLAYTHROUGH_SORTS` keys `name`, `started`, `completed`, `days`,
  `created`; default `-created`. `type Annotations = dict[AnnotationName, Expression]`.
  Task 7's row builder maps a column label to one of these keys.

- [ ] **Step 1: Write the failing test**

In `tests/test_sorting.py`:

```python
def test_the_run_sorts_read_the_projection(self):
    assert set(PLAYTHROUGH_SORTS) == {"name", "started", "completed", "days", "created"}


@pytest.mark.django_db
def test_sorting_by_days_puts_the_runs_with_no_answer_last(self, owned_library, spans):
    """A missing bound and a negative span read no answer, in
    both directions."""
    for descending in (False, True):
        find = FindFilter(sort=("-days" if descending else "days"))
        result = apply_sort(
            library_runs(owned_library),
            find,
            PLAYTHROUGH_SORTS,
            PLAYTHROUGH_DEFAULT_SORT,
        )
        answers = [days_to_finish(run) for run in result.queryset]
        assert [answer for answer in answers if answer is None] == [
            None for answer in answers if answer is None
        ]
        assert answers.index(None) == len([a for a in answers if a is not None])
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_sorting.py -k 'run_sorts or days' -x"`
Expected: FAIL — the key set still holds `ended`.

- [ ] **Step 3: Widen the alias and rewrite the map**

```python
# alias name -> the ORM expression that computes it, applied via
# queryset.annotate() — an aggregate (Sum, Max) or a plain expression
# e.g. {"total_playtime": Sum("sessions__duration_total")}
type Annotations = dict[AnnotationName, Expression]
```

Import `Case`, `DurationField`, `Expression`, `ExpressionWrapper` and `When`
from `django.db.models` beside the existing `Aggregate, F, Max, Min, QuerySet,
Sum`; drop `Aggregate` if nothing else names it.

```python
#: The span the two bounds state. The read adds one to it and
#: this does not, which is a constant, so the order is the same.
#: A negative span reads no answer, and `Case` leaves it null, so
#: it sorts last in both directions -- where the legacy persisted
#: column put its zeros first.
_DAYS_SPAN = Case(
    When(
        completed_upper__gte=F("started_lower"),
        then=ExpressionWrapper(
            F("completed_upper") - F("started_lower"),
            output_field=DurationField(),
        ),
    ),
    default=None,
    output_field=DurationField(),
)

#: Every key but `days` is a direct field path on the projection
#: or one hop to the catalog row. The Playthrough column carries
#: no key: a number is counted across one game's runs, so
#: ordering every row by it means nothing.
PLAYTHROUGH_SORTS: SortMap = {
    "name": SortSpec("player_game__game__sort_name"),
    "started": SortSpec("started_lower"),
    "completed": SortSpec("completed_lower"),
    "days": SortSpec("days_span", {"days_span": _DAYS_SPAN}),
    "created": SortSpec("created_at"),
}
PLAYTHROUGH_DEFAULT_SORT: SortString = "-created"
```

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_sorting.py -x"`
Expected: PASS.

- [ ] **Step 5: Type-check**

Run: `make typecheck`
Expected: clean — the widened alias must still accept `Sum(...)` and `Max(...)`.

- [ ] **Step 6: Commit**

```bash
git add games/sorting.py tests/test_sorting.py
git commit -m "Sort runs by the projection's columns"
```

---

### Task 7: The page, the rows and the link

**Files:**
- Modify: `games/views/playthrough.py:86-173` (both functions go), `212-269`
  (the view)
- Modify: `games/views/playthrough_rows.py`
- Modify: `games/views/game.py:947-975` (`_playthroughs_section`) and its call
  site
- Test: `tests/test_playthrough_view_cutover.py`,
  `tests/test_game_detail_playthroughs.py`, `tests/test_playthrough_rows.py`,
  `tests/test_sort_header_parity.py`

**Interfaces:**
- Consumes: `library_runs` (Task 5), `PLAYTHROUGH_SORTS` (Task 6),
  `PlaythroughFilter` (Task 5).
- Produces: `playthrough_tabledata(runs, presentation, exclude_columns=(), *,
  origin, sort_terms=(), sortable=False) -> TableData` — the caller states
  whether its columns sort.

- [ ] **Step 1: Write the failing test**

Rewrite `tests/test_playthrough_view_cutover.py`'s two legacy-row tests and add
the numbering test:

```python
def test_the_page_numbers_a_run_as_game_detail_does(client, owned_user, owned_library):
    """Under any filter, sort or page: the number is counted
    across every live ordinary run of the game, not across the
    rows this page happens to render."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    tracked = tracked_game(owned_library, game)
    second = record_run(owned_library, tracked)  # the file's own helper

    client.force_login(owned_user)
    listed = client.get(
        reverse("games:list_playthroughs") + "?sort=-created"
    ).content.decode()
    detail = client.get(game.get_absolute_url()).content.decode()

    assert "Playthrough 2" in listed
    assert "Playthrough 2" in detail


def test_the_page_names_the_run_in_its_actions(client, owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    run = Playthrough.objects.get(player_game__game=game)

    client.force_login(owned_user)
    body = client.get(reverse("games:list_playthroughs")).content.decode()

    assert reverse("games:edit_playthrough", args=[run.pk]) in body
```

and flip `tests/test_game_detail_playthroughs.py::test_the_section_links_no_view_all`:

```python
def test_the_section_links_view_all(client, owned_user, owned_library):
    """#1013 gave the list page the projection, so the section
    links to it, filtered to this game."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    client.force_login(owned_user)
    body = client.get(game.get_absolute_url()).content.decode()

    assert escape(filter_url(PlaythroughFilter.where(game=[game.id]))) in body
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_view_cutover.py tests/test_game_detail_playthroughs.py -x"`
Expected: FAIL — the page still renders legacy rows and the section links
nothing.

- [ ] **Step 3: Let the row builder take its caller's sort keys**

In `games/views/playthrough_rows.py`:

```python
#: The list page's sort keys, by column label. Game detail
#: states none: it reads no `?sort=`, so a clickable header
#: there reloads the page and changes nothing.
_SORT_KEYS: Mapping[str, SortKey] = {
    "Game": "name",
    "Started": "started",
    "Completed": "completed",
    "Days to finish": "days",
    "Created": "created",
}


def playthrough_tabledata(
    runs: Sequence[Playthrough],
    presentation: DateTimePresentation,
    exclude_columns: Sequence[str] = (),
    *,
    origin: OriginUrl | None,
    sort_terms: Sequence[SortTerm] = (),
    sortable: bool = False,
) -> TableData:
    """The runs, as rows. The caller states whether they sort."""

    def column(label: str, **options: Any) -> Column:
        return Column(label, _SORT_KEYS.get(label) if sortable else None, **options)

    column_list = [
        column("Playthrough", shrinkable=True),
        column("Game", shrinkable=True),
        column("Started", priority=3),
        column("Completed", priority=2),
        column("Days to finish", priority=2),
        # One long note on one line widens everything.
        column("Note", wrap=True),
        column("Created"),
        column("Actions", align="right", priority=4),
    ]
```

and return `"sort_terms": sort_terms` instead of `()`. Import `SortKey` and
`SortTerm` from `common.sorting`, `Mapping` from `collections.abc`, `Any` from
`typing`.

- [ ] **Step 4: Rewrite the view**

In `games/views/playthrough.py`, delete `_legacy_actions` and
`create_playthrough_tabledata` whole, and rewrite the view:

```python
@login_required
@regex_timeout_view
def list_playthroughs(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    origin = request.get_full_path()
    runs = library_runs(library).select_related("player_game__game")

    filter_json = request.GET.get("filter", "")
    if filter_json:
        playthrough_filter = apply_structured_filter(
            request, parse_playthrough_filter, filter_json
        )
        if playthrough_filter is not None:
            runs = execute_filter(
                playthrough_filter,
                runs,
                filter_query_context_for_library(library),
            )

    find = parse_find_filter(request)
    sort = apply_sort(runs, find, PLAYTHROUGH_SORTS, PLAYTHROUGH_DEFAULT_SORT)
    warn_unknown_sort(request, sort.unknown, entity="playthrough")
    page_runs, page_obj, elided_page_range = paginate(sort.queryset, find)
    page_runs = list(page_runs)
    #: One more query for the page: a number is counted across
    #: every live ordinary run of the games the page names, so it
    #: reads the same here as on Game detail, under any filter,
    #: sort or page.
    numbers = dict(
        numbered_for(library, {run.player_game_id for run in page_runs}).values_list(
            "pk", "display_number"
        )
    )
    for run in page_runs:
        run.display_number = numbers.get(run.pk)
    data = playthrough_tabledata(
        page_runs,
        presentation,
        sort_terms=sort.terms,
        sortable=True,
        origin=origin,
    )
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
        page_size=find.per_page,
    )
    builder_url = builder_url_for(
        "playthroughs", filter_json, find.sort, find.per_page_override
    )
    parsed_filter = parse_filter_dict(filter_json)
    quick_bar = QuickFilterBar(
        presentation=presentation,
        mode="playthroughs",
        existing=parsed_filter,
        builder_url=builder_url,
        preset_api_url=reverse("api-1.0.0:list_presets"),
        per_page_override=find.per_page_override,
    )
    content = ContentContainer()[quick_bar, content]
    return render_page(
        request,
        content,
        title="Manage playthroughs",
    )
```

Fix the imports: add `library_runs` and `numbered_for`, drop `PlayEvent`,
`runs_for_rows`, `TableData`, `Column`, `make_row`, `TruncatedText`,
`ButtonGroup`, `Icon`, `ICON_BUTTON_SIZE_CLASS`, `BaseManager`, `SortTerm` and
anything else the two deleted functions owned — let `make lint` name them.

- [ ] **Step 5: Link View all from Game detail**

In `games/views/game.py`, give `_playthroughs_section` the game and pass the
link, replacing the three-line `#: No link:` comment:

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
    # This embedded mini-table isn't a sortable list view (no ?sort= handling on
    # the detail page), so it states no sort keys.
    table = StyledTable(
        columns=data["columns"],
        rows=data["rows"],
        data_table=True,
        caption="Playthroughs of this game",
    )
    section = _game_section(
        "Playthroughs",
        len(runs),
        table,
        #: Reachable: conversion skipped a tracked game
        #: whose catalog row was removed.
        "No playthroughs yet.",
        view_all_url=filter_url(PlaythroughFilter.where(game=[game.id])),
    )
    return Div(id_="playthroughs-container")[section]
```

Update the call site to pass `game`, and import `PlaythroughFilter` beside the
`PurchaseFilter` / `SessionFilter` already imported there.

- [ ] **Step 6: Run the page tests**

Run: `make test ARGS="tests/test_playthrough_view_cutover.py tests/test_game_detail_playthroughs.py tests/test_playthrough_rows.py tests/test_sort_header_parity.py -x"`
Expected: PASS. `test_sort_header_parity` asserts every key in
`PLAYTHROUGH_SORTS` has a header on the page and the reverse.

- [ ] **Step 7: Run the page-shape guards**

Run: `make test ARGS="tests/test_paths_return_200.py tests/test_rendered_pages.py tests/test_column_priority_contract.py tests/test_table_width_policy.py tests/test_html_validity.py -x"`
Expected: PASS. These pin the caption and the column set — update the pinned
values, not the page, where the difference is the new `Playthrough` column or
the `Completed` header.

- [ ] **Step 8: Commit**

```bash
git add games/views/playthrough.py games/views/playthrough_rows.py games/views/game.py tests/
git commit -m "Read runs on the list page"
```

---

### Task 8: The quick facets

**Files:**
- Modify: `common/components/quick_filter.py:130-142`
- Test: `tests/test_filter_paths.py` (the quick-bar round trip)

**Interfaces:**
- Consumes: `PlaythroughFilter`'s field names (Task 5).
- Produces: `QUICK_FACETS["playthroughs"]` over `game`, `started`, `completed`,
  `days_to_finish`, `note`, `created_at`.

- [ ] **Step 1: Write the failing test**

In `tests/test_filter_paths.py`, beside the existing per-mode bar cases:

```python
def test_the_run_bar_round_trips_completed(self, client, owned_user):
    """Every facet the bar emits parses back into a filter the
    bar may edit again."""
    filter_object = PlaythroughFilter.where(
        completed__between=("2025-01-01", "2025-12-31")
    )
    parsed = parse_filter_dict(filter_to_json(filter_object))

    assert is_quick_editable(
        parsed, {facet.field for facet in QUICK_FACETS["playthroughs"]}
    )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_filter_paths.py -k run_bar -x"`
Expected: FAIL — `completed` is no facet, so the bar degrades to the read-only
pill.

- [ ] **Step 3: Rewrite the facet list**

```python
    "playthroughs": [
        QuickFacet("game"),
        QuickFacet("started"),
        QuickFacet("completed"),
        QuickFacet(
            "days_to_finish",
            "Days to finish",
            placeholder="e.g. 1",
            placeholder2="e.g. 30",
        ),
        QuickFacet("note", placeholder="e.g. second run"),
        QuickFacet("created_at", "Created"),
    ],
```

- [ ] **Step 4: Run the bar suites**

Run: `make test ARGS="tests/test_filter_paths.py tests/test_filter_widgets.py -x"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/components/quick_filter.py tests/test_filter_paths.py
git commit -m "Offer the run's facets"
```

---

### Task 9: Migration 0047 rewrites a saved preset

**Files:**
- Create: `games/migrations/0047_playthrough_preset_completed.py`
- Test: `tests/test_filter_presets.py` (or a new
  `tests/test_playthrough_preset_migration.py`, following whichever file
  already tests 0046)

**Interfaces:**
- Consumes: nothing at runtime — the migration reads the historical
  `FilterPreset` model only.
- Produces: `ended` → `completed`, forward and backward, in a playthroughs-mode
  criterion blob, in the `playthrough_filter` subtree of a games-mode blob, and
  in a playthroughs-mode `find_filter["sort"]` token, sign kept.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_the_migration_rewrites_both_places_and_the_sort(migrator):
    """A bookmarked word in three shapes."""
    old = migrator.apply_initial_migration(("games", "0046_playthrough_preset_mode"))
    Preset = old.apps.get_model("games", "FilterPreset")
    Preset.objects.create(
        user_id=…, mode="playthroughs", name="Finished",
        object_filter={"ended": {"value": "2025-01-01", "modifier": "EQUALS"}},
        find_filter={"sort": "-ended,name"},
    )
    Preset.objects.create(
        user_id=…, mode="games", name="Finished games",
        object_filter={"playthrough_filter": {"ended": {"value": "2025-01-01", "modifier": "EQUALS"}}},
        find_filter={},
    )

    new = migrator.apply_tested_migration(
        ("games", "0047_playthrough_preset_completed")
    )
    Preset = new.apps.get_model("games", "FilterPreset")

    assert Preset.objects.get(name="Finished").object_filter == {
        "completed": {"value": "2025-01-01", "modifier": "EQUALS"}
    }
    assert Preset.objects.get(name="Finished").find_filter == {"sort": "-completed,name"}
    assert Preset.objects.get(name="Finished games").object_filter == {
        "playthrough_filter": {"completed": {"value": "2025-01-01", "modifier": "EQUALS"}}
    }
```

Add the backward case as its own test, asserting `completed` returns to
`ended`. If the repo has no migration-test helper, drive it the way 0046's
tests already do — read them first and match that shape rather than adding a
dependency.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_preset_migration.py -x"`
Expected: FAIL — no migration 0047.

- [ ] **Step 3: Write the migration**

`games/migrations/0047_playthrough_preset_completed.py`:

```python
"""#1013 renamed the endpoint.

A saved preset stores the old word, in a criterion and in a
sort. `ended` is a common word, so the walk is scoped to the
two places a run's filter can sit rather than applied at any
depth, as 0046 could safely be.
"""

from django.db import migrations

#: The one key, forward.
_KEYS = {"ended": "completed"}

#: The keys a nested filter travels under.
_OPERATORS = ("AND", "OR", "NOT")


def _rename_run_keys(node, mapping):
    """Rewrite one run filter and every node under its operators."""
    if not isinstance(node, dict):
        return node
    renamed = {mapping.get(key, key): value for key, value in node.items()}
    for operator in _OPERATORS:
        children = renamed.get(operator)
        if isinstance(children, list):
            renamed[operator] = [_rename_run_keys(child, mapping) for child in children]
    return renamed


def _rename_in_games(node, mapping):
    """Reach every run subtree of a games filter, and no other key."""
    if not isinstance(node, dict):
        return node
    result = dict(node)
    subtree = result.get("playthrough_filter")
    if isinstance(subtree, dict):
        result["playthrough_filter"] = _rename_run_keys(subtree, mapping)
    for operator in _OPERATORS:
        children = result.get(operator)
        if isinstance(children, list):
            result[operator] = [_rename_in_games(child, mapping) for child in children]
    return result


def _rename_sort(find_filter, mapping):
    """Rewrite the sort tokens, keeping each sign.

    `renamed_fields` is read by `from_json` over the criterion
    blob alone, while a sort travels here and is matched against
    the sort map. A preset nobody rewrites loads with an
    unknown-sort toast every time and falls back to the default.
    """
    if not isinstance(find_filter, dict):
        return find_filter
    sort = find_filter.get("sort")
    if not isinstance(sort, str) or not sort:
        return find_filter
    tokens = []
    for token in sort.split(","):
        descending = token.startswith("-")
        key = token[1:] if descending else token
        tokens.append(("-" if descending else "") + mapping.get(key, key))
    return {**find_filter, "sort": ",".join(tokens)}


def _rename(apps, mapping):
    """Rewrite every preset naming the old word.

    A plain walk, not `.iterator()`: a server-side cursor is
    refused, and a preset table holds tens of rows.

    The count is printed, so an operator can tell a run that
    touched nothing from one against the wrong database, which
    looks the same otherwise.
    """
    preset_model = apps.get_model("games", "FilterPreset")
    presets = list(preset_model.objects.all())
    rewritten_count = 0
    for preset in presets:
        if preset.mode == "playthroughs":
            object_filter = _rename_run_keys(preset.object_filter, mapping)
            find_filter = _rename_sort(preset.find_filter, mapping)
        elif preset.mode == "games":
            object_filter = _rename_in_games(preset.object_filter, mapping)
            find_filter = preset.find_filter
        else:
            continue
        if (object_filter, find_filter) == (preset.object_filter, preset.find_filter):
            continue
        preset.object_filter = object_filter
        preset.find_filter = find_filter
        preset.save(update_fields=["object_filter", "find_filter"])
        rewritten_count += 1
    print(f"  presets rewritten: {rewritten_count}/{len(presets)}")


def rename_forward(apps, schema_editor):
    """ended -> completed, in the criterion and in the sort."""
    _rename(apps, _KEYS)


def rename_backward(apps, schema_editor):
    """The inverse, so a downgrade reads them."""
    _rename(apps, {new: old for old, new in _KEYS.items()})


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0046_playthrough_preset_mode"),
    ]

    operations = [
        migrations.RunPython(rename_forward, rename_backward),
    ]
```

Confirm `FilterPreset.find_filter` is the real field name before writing
`update_fields`; read the model first.

- [ ] **Step 4: Run the migration tests**

Run: `make test ARGS="tests/test_playthrough_preset_migration.py -x"`
Expected: PASS.

- [ ] **Step 5: Check nothing else drifted**

Run: `make makemigrations ARGS="--check --dry-run"`
Expected: no changes detected — 0047 alters no schema.

- [ ] **Step 6: Commit**

```bash
git add games/migrations/0047_playthrough_preset_completed.py tests/
git commit -m "Rewrite a saved preset's endpoint word"
```

---

### Task 10: The statistics links

**Files:**
- Modify: `games/views/stats_links.py:29-34, 134-230`
- Test: `tests/test_stats_links.py` (the parity suite already there)

**Interfaces:**
- Consumes: `PlaythroughFilter` (Task 5).
- Produces: `_completed_in_scope(year) -> PlaythroughFilter`, read by
  `_not_finished_game`, `purchases_finished`, `purchases_finished_released`,
  `purchases_bought_and_finished` and `purchases_backlog_decrease`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_all_time_link_reads_the_act(self):
    """A completion recorded with an unknown day is a finish."""
    built = purchases_finished("Alltime")

    assert built.OR[0].game_filter is None  # keep the file's own shape assertions
    assert _completed_in_scope("Alltime").is_completed.value is True


def test_the_per_year_link_overlaps(self):
    """A run stated as a whole year answers for every year it
    touches."""
    scoped = _completed_in_scope(2025)

    assert scoped.completed.modifier is Modifier.BETWEEN
    assert scoped.completed.value == "2025-01-01"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_stats_links.py -k 'all_time_link or per_year' -x"`
Expected: FAIL — `_completed_in_scope` does not exist.

- [ ] **Step 3: Rewrite the builder and its five callers**

```python
def _completed_in_scope(year) -> PlaythroughFilter:
    """A game's finish: a run completed in scope (any, all-time).

    All-time reads the act, not the day: a completion recorded
    with an unknown day is a finish. The per-year read overlaps,
    so a run stated as a whole year answers for every year it
    touches. #1014 moves the statistics queries and owns proving
    both definitions -- the parity fixture states a converted
    legacy row, which is day-precision at both ends and so sees
    neither.
    """
    if _is_year(year):
        return PlaythroughFilter.where(completed__between=_year_range(year))
    return PlaythroughFilter.where(is_completed=True)
```

Rename each call from `_ended_in_scope(year)` to `_completed_in_scope(year)`
and swap the import from `PlayEventFilter` to `PlaythroughFilter`.

- [ ] **Step 4: Run the parity suite**

Run: `make test ARGS="tests/test_stats_links.py -x"`
Expected: PASS — each builder's queryset count still equals the stat it links
from.

- [ ] **Step 5: Commit**

```bash
git add games/views/stats_links.py tests/test_stats_links.py
git commit -m "Link statistics rows at the projection"
```

---

### Task 11: The cross-language contract and the percent round trip

**Files:**
- Modify: `ts/elements/filter-tree/fixtures.json`
- Modify: `tests/test_filter_tree_contract.py:18-30`
- Test: `tests/test_filters.py` (the URL round trip)

**Interfaces:**
- Consumes: `PlaythroughFilter` (Task 5).
- Produces: `FILTER_FOR_MODEL["playthrough"] = PlaythroughFilter`, and fixture
  cases over the projection's fields, so the TypeScript serializer cannot drift.

- [ ] **Step 1: Rewrite the registry entry and the cases**

In `ts/elements/filter-tree/fixtures.json`, replace the `playevent` registry
entry:

```json
    "playthrough": {
      "fields": ["started", "completed", "days_to_finish", "note", "created_at"],
      "relations": { "game_filter": "game" },
      "scopes": {}
    }
```

Replace the one `playevent` case and add three:

```json
    {
      "description": "playthrough date-space: started vs created_at (date-vs-datetime)",
      "model": "playthrough",
      "filter": {
        "started": { "value": "2025-03-15", "modifier": "EQUALS" },
        "created_at": { "value": "2025-03-15", "modifier": "EQUALS" }
      }
    },
    {
      "description": "playthrough endpoints: completed between, days greater than",
      "model": "playthrough",
      "filter": {
        "completed": { "value": "2025-01-01", "value2": "2025-12-31", "modifier": "BETWEEN" },
        "days_to_finish": { "value": 3, "modifier": "GREATER_THAN" }
      }
    },
    {
      "description": "playthrough relation: runs at games matching a name",
      "model": "playthrough",
      "filter": {
        "game_filter": { "name": { "value": "zelda", "modifier": "INCLUDES" } }
      }
    },
    {
      "description": "a percent in a text criterion survives the serializer",
      "model": "playthrough",
      "filter": { "note": { "value": "100% run", "modifier": "INCLUDES" } }
    }
```

The `game__playevents__ended` field-comparison cases stay: `PlayEvent` is still
a model until #771, and those cases are Session's.

- [ ] **Step 2: Map the model key**

```python
FILTER_FOR_MODEL = {
    "game": GameFilter,
    "session": SessionFilter,
    "purchase": PurchaseFilter,
    "playthrough": PlaythroughFilter,
}
```

- [ ] **Step 3: Run the contract**

Run: `make test-ts` then `make test ARGS="tests/test_filter_tree_contract.py -x"`
Expected: PASS — vitest writes `fixtures.canonical.json` first; the pytest side
skips when that artifact is absent, so run them in that order.

- [ ] **Step 4: Write the URL round trip**

In `tests/test_playthrough_filter.py`:

```python
def test_a_percent_survives_the_url(owned_library):
    """#656 left the encoding to the wave that writes the
    filter: a value is a plain ISO day and a qualifier is no
    operand, so the only symbol left is a person's own `%`."""
    original = PlaythroughFilter.where(note__contains="100% run")

    url = filter_url(original)
    query = parse_qs(urlparse(url).query)
    parsed = parse_playthrough_filter(query["filter"][0])

    assert parsed == original
    assert "100%25" in url
```

- [ ] **Step 5: Run it**

Run: `make test ARGS="tests/test_playthrough_filter.py -k percent -x"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ts/elements/filter-tree/fixtures.json tests/
git commit -m "Pin the run filter's contract"
```

---

### Task 12: The gate

**Files:**
- Modify: `CLAUDE.md` (the `Playthrough` model paragraph)
- Verify: everything

**Interfaces:**
- Consumes: every task above.

- [ ] **Step 1: Rewrite the documentation the cutover falsifies**

In `CLAUDE.md`'s `Playthrough` bullet, replace the closing two sentences —
`The list page reads legacy rows until #1013, and translates its own action ids
through runs_for_rows` — with what is now true:

```
  #1013 gives the list page the same rows: it reads the projection, and so do
  the filter (`PlaythroughFilter` over eleven fields, with each endpoint
  compared as the interval its two bound columns state), the sorts, the quick
  facets and the saved presets, which migration 0047 rewrites from `ended` to
  `completed`. `playthrough_count` counts the runs whose completion is stated,
  which is the number `Played N times` prints. No screen reads
  `games_playevent`; `runs_for_rows` stays for the API, which #1015 owns
```

Check the same bullet's `PlayerGame` and `FilterPreset` lines for a claim this
issue falsified, and the API section's `/api/playthrough/` note, which still
names the legacy row — that one is still true until #1015.

- [ ] **Step 2: Lint the prose**

Run: `make vale`
Expected: no error-level finding. A domain word beside an event, a projector or
a projection row is the graded one.

- [ ] **Step 3: Run the whole gate**

Run: `make check`
Expected: green — lint, format, mypy, vale, ts-check, vitest, and the entire
pytest suite including `e2e/`. `e2e/test_responsive_table_e2e.py` and
`e2e/test_table_width_e2e.py` both load the playthroughs list; a column-set
change lands there.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "Say the list page reads the projection"
```

---

## Self-Review

**Spec coverage**

| spec section | task |
|---|---|
| The filter names its model | 5 |
| The fields | 5 |
| An endpoint is an interval | 5 |
| Days to finish (read) | 1 |
| Days to finish (filter, parity test) | 5 |
| Scoping (both seams, `library_runs`) | 5 |
| The count of playthroughs (`base_scope`, drift guard) | 4, 5 |
| The page (numbering, deletions, `View all`) | 7 |
| Sorts | 6 |
| Quick facets | 8 |
| Presets (0047, criterion blob and sort token) | 9 |
| Comparison operands (no `library` hop, four bounds) | 2 |
| Widget metadata for a handler field (both gates) | 3 |
| Encoding (`%` round trip, Python and TypeScript) | 11 |
| The statistics links | 10 |
| The contract | 11 |
| Tests (twelve bullets) | 1, 5, 6, 7, 8, 9, 11 |
| Rollback (one revert) | the branch |

**Placeholder scan**

Two steps carry a marked gap rather than finished code, both because the exact
shape belongs to a file the executor must read first: Task 5 Step 5's last two
assertions (the name of the game that test creates) and Task 9 Step 1's
`user_id=…` (the preset fixture's own user). Both are marked in place. Task 10
Step 1 keeps `# keep the file's own shape assertions` for the same reason. Every
other step carries the real content.

**Type consistency**

- `library_runs(library) -> QuerySet[Playthrough]` — Task 5 defines it, Tasks 5,
  6 and 7 call it with that one argument.
- `playthrough_tabledata(..., *, origin, sort_terms=(), sortable=False)` — Task
  7 widens it; Game detail keeps the old call plus nothing, the list page passes
  both new keywords.
- `temporal_interval_handler(value_field, lower_field, upper_field)` and
  `days_touched_handler(lower_field, upper_field)` — three and two positional
  strings, matching every call in Task 5 Step 8.
- `AggregateSpec.base_scope: OperatorFilter | None` (Task 4), stated once in
  Task 5's aggregate table.
- `comparison_scoping_relations: tuple[str, ...]` and
  `comparable_temporal_bounds: Mapping[str, str]` (Task 2), read by `getattr`
  with the same names in `common/criteria.py`.
- Sort keys `name/started/completed/days/created` (Task 6) are exactly the
  values in `_SORT_KEYS` (Task 7).
