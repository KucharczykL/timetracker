# PlayerGame read cutover — child A implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the games list and the game detail page read a library's private
game state from its `PlayerGame` row instead of the `Game.status` and
`Game.mastered` columns.

**Architecture:** `GameQuerySet.tracked_by(library)` joins the library's
projection row with a `FilteredRelation` and selects its two facts as
annotations. Every surface A moves reads `tracked_status` and
`tracked_mastered` from that queryset. A status stops travelling as a
`Game.Status` letter and travels as a `PlayerGameStatus` word from the widget
through the write path; `_mirror()` still converts the word back to a letter,
so the surfaces A leaves behind keep working. An autouse fixture writes a
projection row for every game a test creates, because the join is an inner one.

**Tech Stack:** Django 6, PostgreSQL 18, Python 3.14, pytest + pytest-django +
pytest-playwright, Django Ninja, the Python component system in
`common/components/`.

**Spec:** `docs/superpowers/specs/2026-08-28-issue-678-playergame-read-cutover-design.md`

## Global Constraints

- Python 3.14 only. PEP 758 `except A, B:` is in use; ruff 0.16.x formats to it.
- Run everything through `make`. Never `uv run` / `pytest` / `pnpm` directly.
- Iterate with `make check-fast`. The gate before "done" is the full
  `make check`, `e2e/` included.
- `make vale` refuses the word `fold`. A projector **replays** events; the row
  it leaves is the **projection**.
- One act, one verb. An event type, its command and its projection column share
  one verb.
- Name variables with complete words, in Python and TypeScript.
- Name compound types explicitly (`TypedDict`, `NamedTuple`, PEP 695 alias).
- Never write to a `GeneratedField`.
- Never assign `Game.status` or `Game.mastered` outside the two places this plan
  names (`GameForm.save()` on an insert, and `_mirror()`).
- Build UI with the Python components, htpy form: `Builder(attr=...)[children]`.
- No dispatch inside a transaction. A test that POSTs through a dispatching view
  needs `@pytest.mark.django_db(transaction=True)`.
- Every task ends on a commit. Branch: `codex/playergame-read-cutover-a`, opened
  against `codex/playergame-read-cutover`.

---

## Three corrections to the spec, found while planning

Each was measured, not reasoned. Apply them; they are why some tasks below do
more than the spec's child-A sentence lists.

**1. A `FilteredRelation` alias is not readable as an attribute.** The alias
only enables `filter()` and `order_by()`. Measured against the development
database, `.annotate(tracked=FilteredRelation(...))` adds no column to the
`SELECT` and the loaded instance has no `tracked`. Display therefore needs two
more annotations, `F("tracked__status")` and `F("tracked__mastered")`, which the
same probe confirmed emit `tracked."status" AS "tracked_status"`. `tracked_by()`
adds them, so display is free at every call site.

**2. The status selector and the status endpoint are one contract, so they move
together.** The spec puts `GameStatusSelector` in A and `GameStatusUpdate` plus
`PATCH /api/games/{id}/status` in C. The selector's option values are exactly
what the endpoint receives, so splitting them would make A ship a translation
between two vocabularies inside one component. Both move in A. Child C keeps
`stats_data`, the three `PurchaseQuerySet` methods and the five `stats_links`
builders.

**3. `shelved` can be filtered for but not set until child D.** `_mirror()`
calls `legacy_status_for()`, which raises `UnmappedPlayerStatus` for `shelved`
because no `Game.Status` letter states it. The mirror lives until D. So every
*setter* in A — the form, the selector, the endpoint — offers the five words a
letter holds, and `record_facts()` refuses the sixth with a sentence rather than
letting the projection and the catalog disagree. The *filter* widget still
reports all six from the column (child B), which matches nothing and is
harmless.

---

## File Structure

**Created**

| File | Responsibility |
|---|---|
| `tests/test_playergame_tracked_by.py` | `tracked_by()` alone: scoping, tombstones, the two-join case, the readable annotations. |
| `tests/test_playergame_read_parity.py` | The throwaway guard. Old catalog query against new projection query, over statuses, mastery and every `GAME_SORTS` entry. Child D deletes it. |
| `e2e/test_games_list_projection_e2e.py` | The browser check: a tracked game is listed, a removed one is not, a set status survives a reload. |

**Modified**

| File | Change |
|---|---|
| `tests/conftest.py` | Autouse `post_save` receiver that tracks every created game; the `untracked_games` opt-out. |
| `e2e/conftest.py` | The same receiver, same marker. |
| `pyproject.toml` | Register the `untracked_games` marker. |
| `games/models.py` | `GameQuerySet.tracked_by()`. |
| `common/criteria.py` | `FilterField.metadata_lookup`, consumed by `field_metadata`. |
| `games/playergame_status.py` | `SETTABLE_PLAYER_STATUSES`, derived from the map. |
| `games/writes/playergame.py` | `record_facts()` takes a word and refuses an unsettable one. |
| `games/views/playergame_writes.py` | The same type change. |
| `games/api.py` | `GameStatusUpdate.status` is a `PlayerGameStatus`. |
| `games/forms.py` | `GameForm.status` choices are words; `save()` converts on an insert. |
| `common/components/domain.py` | `_STATUS_COLORS` keyed on words, `shelved` added; `GameStatusSelector` takes the current word. |
| `games/views/game.py` | `list_games`, `view_game`, `add_game`, `_game_history`. |
| `games/views/session.py` | `_record_played` reads the projection. |
| `games/filters.py` | `filter_query_context_for_library()` returns `tracked_by()` for `Game`. |
| `tests/test_custom_elements.py` | The selector render test's arguments. |
| 13 event-path test modules | The `untracked_games` marker. |

---

### Task 1: Track every game a test creates

The join in Task 2 is an inner join. 117 test files call `Game.objects.create`
and none of them leaves a projection row, so without this task every later task
reads an empty list and the failures say nothing useful. This task lands first
and on its own: the suite must be green with the fixture in place and no
production code changed yet.

The receiver writes the row directly rather than calling `backfill_game()`. The
backfill needs an actor and a run time, opens its own transaction and appends
events; inside a `post_save` on a game a test just created, that is a second
transaction and a stream the test never asked for. The row is what the join
wants, so the row is what the fixture writes. The cost is stated plainly: the
fixture leaves a projection row with no event behind it, which production never
does. `tests/test_playergame_write_path.py` covers the real path, event log
included, and is the reason the divergence is affordable.

The modules that exercise the event path opt out. For them a pre-existing row is
the bug: `TrackGame` finds one and returns `Unchanged`, so no
`PLAYERGAME_CREATED` event is recorded and their event-count assertions fail.

**Files:**
- Modify: `tests/conftest.py`
- Modify: `e2e/conftest.py`
- Modify: `pyproject.toml` (`[tool.pytest.ini_options] markers`)
- Modify: 13 test modules, one `pytestmark` line each

**Interfaces:**
- Produces: `pytest.mark.untracked_games` — a module-level or test-level marker
  that suppresses the receiver.
- Produces: the invariant every later task relies on — after
  `Game.objects.create(library=some_library, ...)` in a test, exactly one
  `PlayerGame` row exists for `(some_library, that_game)`.

- [ ] **Step 1: Register the marker**

In `pyproject.toml`, under `[tool.pytest.ini_options]`, add a `markers` entry
(extend the list if one is already there):

```toml
markers = [
    "untracked_games: do not auto-create a PlayerGame row for a game this test creates. For the modules that exercise TrackGame, the backfill or a rebuild, where a pre-existing row is the bug.",
]
```

- [ ] **Step 2: Write the failing test**

Append to `tests/conftest.py`'s sibling — put this in a new file
`tests/test_playergame_test_fixture.py`, because it tests the fixture itself:

```python
"""The autouse fixture that tracks a created game."""

import pytest

from games.models import Game, PlayerGame, PlayerGameStatus


@pytest.mark.django_db
def test_a_created_game_is_tracked(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert row.status == PlayerGameStatus.UNPLAYED
    assert row.tracked_at is not None


@pytest.mark.django_db
def test_a_shared_game_is_tracked_by_nobody():
    game = Game.objects.create(library=None, name="Shared")

    assert not PlayerGame.objects.filter(game=game).exists()


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_the_marker_suppresses_the_row(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    assert not PlayerGame.objects.filter(game=game).exists()
```

- [ ] **Step 3: Run it and watch it fail**

Run: `make test ARGS="tests/test_playergame_test_fixture.py -p no:randomly"`
Expected: the first two fail with `PlayerGame.DoesNotExist` / an unexpected row;
the third passes for the wrong reason.

- [ ] **Step 4: Add the receiver to `tests/conftest.py`**

Add the imports at the top of the file and the fixture at the end:

```python
import uuid

from django.db.models.signals import post_save
from django.utils import timezone


@pytest.fixture(autouse=True)
def _track_created_games(request):
    """Give every game a test creates the projection row a read needs.

    games/views/game.py dispatches TrackGame, migration
    0033_playergame_baseline_backfill covers a restored dump, and
    load_sample_data calls backfill_library(). A test is the fourth
    source of a game and leaves no row, so the inner join in
    GameQuerySet.tracked_by() would hide it.

    A direct write, not backfill_game(): the backfill needs an actor
    and a run time, opens its own transaction and appends events. The
    row is what the join wants, so the row is what this writes. The
    divergence from production is real and deliberate;
    tests/test_playergame_write_path.py covers the event path.
    """
    from games.models import Game, PlayerGame

    if "untracked_games" in request.keywords:
        yield
        return

    def track(sender, instance, created, raw, **kwargs):
        #: raw is a loaddata row: the library may not exist yet.
        if raw or not created or instance.library_id is None:
            return
        PlayerGame.objects.get_or_create(
            library_id=instance.library_id,
            game=instance,
            defaults={"pk": uuid.uuid7(), "tracked_at": timezone.now()},
        )

    post_save.connect(track, sender=Game, dispatch_uid="test-track-created-games")
    try:
        yield
    finally:
        post_save.disconnect(sender=Game, dispatch_uid="test-track-created-games")
```

- [ ] **Step 5: Run it and watch it pass**

Run: `make test ARGS="tests/test_playergame_test_fixture.py -p no:randomly"`
Expected: 3 passed.

- [ ] **Step 6: Copy the receiver into `e2e/conftest.py`**

The e2e suite has its own `conftest.py` with no import of the unit one, so the
fixture is duplicated rather than shared. Paste the same imports and the same
`_track_created_games` fixture verbatim, and add one line to its docstring:

```python
    Duplicated from tests/conftest.py: the two suites share no
    conftest, and importing across them would make e2e depend on the
    unit suite's collection.
```

- [ ] **Step 7: Mark the event-path modules**

Add this line directly under the module docstring of each file listed below:

```python
pytestmark = pytest.mark.untracked_games
```

Files:

```
tests/test_playergame_view_cutover.py
tests/test_playergame_backfill_migration.py
tests/test_playergame_backfill.py
tests/test_playergame_command.py
tests/test_playergame_projection.py
tests/test_playergame_events.py
tests/test_playergame_write_path.py
tests/test_playergame_status_map.py
tests/test_projection_model.py
tests/test_projection_rebuild.py
tests/test_retention.py
tests/test_event_benchmark.py
tests/test_uuid_identity_audit.py
```

Where a module already assigns `pytestmark`, combine rather than replace:
`pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]`. Where a
module has no `import pytest`, add one.

- [ ] **Step 8: Run the whole unit suite**

Run: `make test-fast`
Expected: green. A failure here names a module that also needs the marker — add
it and rerun. Do not "fix" a failing assertion; the marker is the answer for any
test whose subject is the projection row's creation.

- [ ] **Step 9: Run the browser suite**

Run: `make test-e2e`
Expected: green.

- [ ] **Step 10: Commit**

```bash
git add tests/conftest.py e2e/conftest.py pyproject.toml tests/test_playergame_test_fixture.py tests/test_playergame_*.py tests/test_projection_*.py tests/test_retention.py tests/test_event_benchmark.py tests/test_uuid_identity_audit.py
git commit -m "Give a test's game the row a read will need"
```

---

### Task 2: `GameQuerySet.tracked_by()`

**Files:**
- Modify: `games/models.py` (`GameQuerySet`, around line 75)
- Test: `tests/test_playergame_tracked_by.py`

**Interfaces:**
- Produces: `GameQuerySet.tracked_by(library) -> GameQuerySet`. Every row it
  returns carries `tracked_status: str` (a `PlayerGameStatus` value) and
  `tracked_mastered: bool`. The alias `tracked` is filterable and sortable as
  `tracked__status`, `tracked__mastered`, `tracked__archived_at`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_playergame_tracked_by.py`:

```python
"""GameQuerySet.tracked_by(): the join every authenticated game read uses."""

import uuid

import pytest
from django.utils import timezone

from games.models import Game, PlayerGame, PlayerGameStatus


@pytest.fixture
def other_library(django_user_model):
    return django_user_model.objects.create_user(
        username="other-owner", password="p"
    ).library


@pytest.mark.django_db
def test_a_tracked_game_is_listed(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    assert list(Game.objects.tracked_by(owned_library)) == [game]


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_an_untracked_game_is_absent(owned_library):
    Game.objects.create(library=owned_library, name="Outer Wilds")

    assert not Game.objects.tracked_by(owned_library).exists()


@pytest.mark.django_db
def test_a_removed_game_is_absent(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    Game.objects.filter(pk=game.pk).update(tombstoned_at=timezone.now())

    assert not Game.objects.tracked_by(owned_library).exists()


@pytest.mark.django_db
def test_another_library_sees_nothing(owned_library, other_library):
    Game.objects.create(library=owned_library, name="Outer Wilds")

    assert not Game.objects.tracked_by(other_library).exists()


@pytest.mark.django_db
def test_the_two_facts_are_readable(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    PlayerGame.objects.filter(library=owned_library, game=game).update(
        status=PlayerGameStatus.COMPLETED, mastered=True
    )

    row = Game.objects.tracked_by(owned_library).get()
    assert row.tracked_status == PlayerGameStatus.COMPLETED
    assert row.tracked_mastered is True


@pytest.mark.django_db
def test_a_shared_game_this_library_tracks_is_listed(owned_library):
    #: for_library() hides it; tracked_by() does not, because a list
    #: of tracked games is what the page claims to be.
    shared = Game.objects.create(library=None, name="Shared")
    PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        game=shared,
        tracked_at=timezone.now(),
        status=PlayerGameStatus.PLAYED,
    )

    assert list(Game.objects.tracked_by(owned_library)) == [shared]


@pytest.mark.django_db
def test_two_filter_calls_stay_in_one_library(owned_library, other_library):
    #: Django opens a join per filter() call on a multi-valued
    #: relation. On a plain path the second join carries no library
    #: condition and this shared game comes back on the strength of
    #: another library's row.
    shared = Game.objects.create(library=None, name="Shared")
    PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        game=shared,
        tracked_at=timezone.now(),
        status=PlayerGameStatus.UNPLAYED,
        mastered=False,
    )
    PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=other_library,
        game=shared,
        tracked_at=timezone.now(),
        status=PlayerGameStatus.PLAYED,
        mastered=True,
    )

    matched = (
        Game.objects.tracked_by(owned_library)
        .filter(tracked__status=PlayerGameStatus.PLAYED)
        .filter(tracked__mastered=True)
    )
    assert not matched.exists()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playergame_tracked_by.py"`
Expected: every test errors with `AttributeError: 'GameQuerySet' object has no
attribute 'tracked_by'`.

- [ ] **Step 3: Add the method**

In `games/models.py`, replace the `GameQuerySet` body:

```python
class GameQuerySet(TombstonableQuerySet):
    def visible_to(self, library):
        return self.filter(Q(library__isnull=True) | Q(library=library)).alive()

    def tracked_by(self, library):
        """Every live game this library tracks, with its two facts read.

        No `library=library`: a shared catalog game this library
        tracks belongs on the list, because a list of tracked games
        is what the page claims to be.

        A FilteredRelation, not a plain path. Django opens a join per
        filter() call on a multi-valued relation, and a list applies
        its scope and its criteria in separate calls; on a plain path
        the second join carries no library condition. The alias
        copies its condition into every join it opens, and
        `unique_library_player_game` allows at most one row per pair,
        so the joins cannot disagree. The pairing is the guarantee,
        not the alias alone.

        The alias by itself selects no column, so the two facts are
        annotated as well. `tracked_status` and `tracked_mastered`
        avoid the catalog columns' names.

        `alive()` comes first, and it is what keeps a removed game
        off the list: since #676 a game delete leaves the catalog row
        tombstoned and the projection row beside it.
        """
        return (
            self.alive()
            .annotate(
                tracked=FilteredRelation(
                    "player_games", condition=Q(player_games__library=library)
                )
            )
            .filter(tracked__isnull=False)
            .annotate(
                tracked_status=F("tracked__status"),
                tracked_mastered=F("tracked__mastered"),
            )
        )
```

Add `F` and `FilteredRelation` to the `django.db.models` import at the top of
the file if they are not already there.

- [ ] **Step 4: Run it and watch it pass**

Run: `make test ARGS="tests/test_playergame_tracked_by.py"`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add games/models.py tests/test_playergame_tracked_by.py
git commit -m "Join the row a library's game reads belong to"
```

---

### Task 3: `FilterField.metadata_lookup`

Child B re-points `GameFilter.status` at `tracked__status`. `_walk_lookup`
resolves real model paths, `tracked` is an annotation alias that resolves to
nothing, and `field_metadata` treats a handler-less field whose lookup names no
column as a misconfigured field and raises. So the query path and the metadata
path must be declared apart. A ships the option; B uses it.

Both game fields will need it, because neither carries a handler:
`field_metadata` skips column resolution only for a handler-mapped field.

**Files:**
- Modify: `common/criteria.py` (`FilterField` at 965, `field_metadata` at 2610)
- Test: `tests/test_filter_field_metadata_lookup.py`

**Interfaces:**
- Produces: `FilterField(lookup, handler, label, search_url, imperative,
  metadata_lookup)`. `metadata_lookup: ORMLookup | None = None`. When set,
  `field_metadata` resolves the column from it instead of from `lookup`;
  `to_q` ignores it entirely.

- [ ] **Step 1: Write the failing test**

Create `tests/test_filter_field_metadata_lookup.py`:

```python
"""metadata_lookup: the query path and the metadata path, declared apart."""

from dataclasses import dataclass, field
from typing import ClassVar

import pytest

from common.criteria import (
    ChoiceCriterion,
    FilterField,
    Modifier,
    OperatorFilter,
    field_metadata,
)
from games.models import PlayerGame


@dataclass
class _AliasedFilter(OperatorFilter):
    AND: list["_AliasedFilter"] = field(default_factory=list)
    OR: list["_AliasedFilter"] = field(default_factory=list)
    NOT: list["_AliasedFilter"] = field(default_factory=list)

    status: ChoiceCriterion | None = None

    fields: ClassVar[dict[str, FilterField]] = {
        "status": FilterField("tracked__status", metadata_lookup="status"),
    }

    @classmethod
    def _comparison_model(cls):
        return PlayerGame


def test_metadata_resolves_the_declared_path():
    entry = next(
        meta for meta in field_metadata(_AliasedFilter) if meta["name"] == "status"
    )

    assert [value for value, _label in entry["choices"]] == [
        "unplayed",
        "played",
        "completed",
        "retired",
        "shelved",
        "abandoned",
    ]


def test_the_query_still_uses_the_alias():
    criterion = ChoiceCriterion(value="played", modifier=Modifier.EQUALS)
    q = _AliasedFilter.fields["status"].to_q("status", criterion)

    assert "tracked__status" in str(q)


def test_a_handler_refuses_a_metadata_lookup():
    with pytest.raises(ValueError, match="metadata_lookup"):
        FilterField(handler=lambda criterion: None, metadata_lookup="status")
```

The choice order in the first test is `PlayerGameStatus`'s declaration order —
read it off `games/models.py:1291` and correct the list if it differs.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_filter_field_metadata_lookup.py"`
Expected: `TypeError: FilterField.__init__() got an unexpected keyword argument
'metadata_lookup'`.

- [ ] **Step 3: Add the field**

In `common/criteria.py`, inside `FilterField`, after `imperative`:

```python
    # The path ``field_metadata`` walks, when it differs from the path ``to_q``
    # emits. A query may read an annotation alias (``tracked__status``), which
    # names no model column, while the widget still needs the real column's
    # choices and nullability (``player_games__status``). Ignored by ``to_q``.
    metadata_lookup: ORMLookup | None = None
```

And in `__post_init__`, after the `search_url` check:

```python
        if self.metadata_lookup is not None and self.handler is not None:
            # Handler-mapped fields skip column resolution, so metadata_lookup
            # has no consumer.
            raise ValueError(
                "FilterField metadata_lookup has no effect on a handler-mapped field"
            )
```

- [ ] **Step 4: Consume it in `field_metadata`**

In `common/criteria.py`, in `field_metadata`, replace the one line that picks
the lookup:

```python
                lookup = field_spec.lookup or name
```

with:

```python
                lookup = field_spec.metadata_lookup or field_spec.lookup or name
```

Extend the comment block just above it with one sentence:

```python
            # ``metadata_lookup`` wins where it is set: the query may read an
            # annotation alias that resolves to no column, and the widget still
            # needs the real one.
```

- [ ] **Step 5: Run it and watch it pass**

Run: `make test ARGS="tests/test_filter_field_metadata_lookup.py"`
Expected: 3 passed.

- [ ] **Step 6: Run the filter suite**

Run: `make test ARGS="tests/test_filter_paths.py tests/test_filters.py"`
Expected: green. The new field is optional and defaults to `None`, so nothing
existing changes.

- [ ] **Step 7: Commit**

```bash
git add common/criteria.py tests/test_filter_field_metadata_lookup.py
git commit -m "Let a filter field name its column apart from its query path"
```

---

### Task 4: The parity guard

This file is the arbiter for the whole cutover. It builds both queries itself,
so it holds whether or not the production surfaces have switched yet, and it
fails the moment they disagree. Child D deletes it, which is why it lives in one
file and depends on nothing that outlives the cutover.

Child C adds the `stats_links` builders to it. It cannot do so here: a
`stats_links` filter carries a status *word* only after child B re-points
`GameFilter.status`, so in A the new form of those links is inexpressible.

**Files:**
- Test: `tests/test_playergame_read_parity.py`

**Interfaces:**
- Consumes: `Game.objects.tracked_by()` from Task 2.
- Produces: nothing importable. It is a test file.

- [ ] **Step 1: Write the file**

Create `tests/test_playergame_read_parity.py`:

```python
"""Old catalog read against new projection read, id set by id set.

Created by #678 A and deleted by #678 D. Its whole purpose is to
guard the switch, so it does not outlive it. Every case builds both
queries here rather than calling a view, so it holds before, during
and after each child re-points its surface.
"""

import pytest

from games.models import Game, PlayerGame, PlayerGameStatus
from games.playergame_status import (
    LEGACY_STATUS_TO_PLAYER_STATUS,
    legacy_status_for,
)
from games.sorting import GAME_SORTS


@pytest.fixture
def a_library_of_every_status(owned_library):
    """One game per status, one mastered, one of each sort key's value."""
    games = []
    for index, player_status in enumerate(PlayerGameStatus):
        game = Game.objects.create(
            library=owned_library,
            name=f"Game {index}",
            sort_name=f"game {index}",
            year_released=2000 + index,
            wikidata=f"Q{index}",
        )
        mastered = index % 2 == 0
        PlayerGame.objects.filter(library=owned_library, game=game).update(
            status=player_status, mastered=mastered
        )
        if player_status is not PlayerGameStatus.SHELVED:
            #: The catalog holds what the mirror would have written.
            Game.objects.filter(pk=game.pk).update(
                status=legacy_status_for(player_status), mastered=mastered
            )
        games.append(game)
    return games


def ids(queryset):
    return set(queryset.values_list("id", flat=True))


def ordered_ids(queryset):
    return list(queryset.values_list("id", flat=True))


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("legacy_status", "player_status"),
    sorted(LEGACY_STATUS_TO_PLAYER_STATUS.items()),
)
def test_a_status_selects_the_same_games(
    owned_library, a_library_of_every_status, legacy_status, player_status
):
    old = Game.objects.for_library(owned_library).filter(status=legacy_status)
    new = Game.objects.tracked_by(owned_library).filter(tracked__status=player_status)

    assert ids(old) == ids(new)


@pytest.mark.django_db
@pytest.mark.parametrize("mastered", [True, False])
def test_mastery_selects_the_same_games(
    owned_library, a_library_of_every_status, mastered
):
    #: The shelved game has no catalog letter, so the old query cannot
    #: see it. Exclude it from both sides rather than from one.
    shelved = PlayerGame.objects.get(
        library=owned_library, status=PlayerGameStatus.SHELVED
    ).game_id
    old = (
        Game.objects.for_library(owned_library)
        .filter(mastered=mastered)
        .exclude(pk=shelved)
    )
    new = (
        Game.objects.tracked_by(owned_library)
        .filter(tracked__mastered=mastered)
        .exclude(pk=shelved)
    )

    assert ids(old) == ids(new)


@pytest.mark.django_db
@pytest.mark.parametrize("sort_key", sorted(GAME_SORTS))
@pytest.mark.parametrize("descending", [False, True])
def test_a_sort_returns_the_same_order(
    owned_library, a_library_of_every_status, sort_key, descending
):
    """Ordering by letter and ordering by word agree.

    a, f, p, r, u against abandoned, completed, played, retired,
    unplayed: the two orders match, so ?sort=status returns the same
    page. shelved takes its place between retired and unplayed and is
    excluded here, because the catalog side cannot hold it.
    """
    shelved = PlayerGame.objects.get(
        library=owned_library, status=PlayerGameStatus.SHELVED
    ).game_id
    spec = GAME_SORTS[sort_key]
    old_expression = spec.expression
    new_expression = "tracked_status" if old_expression == "status" else old_expression
    prefix = "-" if descending else ""

    old = Game.objects.for_library(owned_library).exclude(pk=shelved)
    new = Game.objects.tracked_by(owned_library).exclude(pk=shelved)
    if spec.annotate:
        old = old.annotate(**spec.annotate)
        new = new.annotate(**spec.annotate)
    if old_expression == "filtered_playtime":
        pytest.skip("list_games pre-annotates this alias; no parity to check here")

    assert ordered_ids(old.order_by(f"{prefix}{old_expression}", "id")) == ordered_ids(
        new.order_by(f"{prefix}{new_expression}", "id")
    )
```

- [ ] **Step 2: Run it**

Run: `make test ARGS="tests/test_playergame_read_parity.py"`
Expected: green. If the status-sort case fails, the two orders genuinely
disagree and the spec's claim is wrong — stop and report it rather than
adjusting the assertion.

- [ ] **Step 3: Commit**

```bash
git add tests/test_playergame_read_parity.py
git commit -m "Pin the old read and the new read to the same answer"
```

---

### Task 5: A status travels as a word

Every setter moves at once: the form field, the selector's options, the
endpoint's schema, and the write path they all reach. `_mirror()` keeps
converting the word back to a letter, so every surface A has not moved yet
carries on reading a current catalog column.

`shelved` is withheld from the setters, because `legacy_status_for()` has no
letter for it and `_mirror()` would raise after the event had already committed.
`record_facts()` refuses it before dispatch, in one place, so the form, the
selector and the endpoint all get the same answer.

**Files:**
- Modify: `games/playergame_status.py`
- Modify: `games/writes/playergame.py`
- Modify: `games/views/playergame_writes.py`
- Modify: `games/api.py` (`GameStatusUpdate` at 112, `partial_update_game` at 198)
- Modify: `games/forms.py` (`GameForm`, 802-855)
- Modify: `games/views/game.py` (`add_game`, 229-271)
- Modify: `games/views/session.py` (`_record_played`, 181-191)
- Test: `tests/test_playergame_status_word_setters.py`

**Interfaces:**
- Produces: `SETTABLE_PLAYER_STATUSES: tuple[LabeledStatus, ...]` in
  `games/playergame_status.py`, where `type LabeledStatus = tuple[str, str]`.
  Five pairs, `(value, label)`, in `Game.Status` declaration order.
- Produces: `record_facts(actor, game, *, status: PlayerGameStatus | None = None,
  mastered: bool | None = None, correlation_id: uuid.UUID) -> None`. Raises
  `PlayerGameWriteFailed(409)` for a status no letter holds.
- Produces: `record_facts_for_request(request, game, *, status:
  PlayerGameStatus | None = None, mastered: bool | None = None, correlation_id)
  -> bool`, same change.
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing test**

Create `tests/test_playergame_status_word_setters.py`:

```python
"""A status travels as a word from the widget to the projection."""

import pytest
from django.urls import reverse

from games.models import Game, PlayerGame, PlayerGameStatus
from games.playergame_status import SETTABLE_PLAYER_STATUSES
from games.writes.playergame import (
    PlayerGameWriteFailed,
    new_correlation_id,
    record_facts,
)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def test_only_the_words_a_letter_holds_are_settable():
    assert [value for value, _label in SETTABLE_PLAYER_STATUSES] == [
        PlayerGameStatus.UNPLAYED,
        PlayerGameStatus.PLAYED,
        PlayerGameStatus.COMPLETED,
        PlayerGameStatus.RETIRED,
        PlayerGameStatus.ABANDONED,
    ]


@pytest.mark.django_db(transaction=True)
def test_the_form_posts_a_word(logged_in, owned_library):
    response = logged_in.post(
        reverse("games:add_game"),
        {
            "name": "Outer Wilds",
            "status": "completed",
            "mastered": "on",
            "wikidata": "",
        },
    )

    assert response.status_code == 302
    game = Game.objects.get(name="Outer Wilds")
    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert row.status == PlayerGameStatus.COMPLETED
    assert row.mastered is True
    #: The mirror keeps the catalog current for the surfaces A leaves.
    game.refresh_from_db()
    assert (game.status, game.mastered) == ("f", True)


@pytest.mark.django_db(transaction=True)
def test_the_endpoint_takes_a_word(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    response = logged_in.patch(
        f"/api/games/{game.pk}/status",
        {"status": "played"},
        content_type="application/json",
    )

    assert response.status_code == 204
    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert row.status == PlayerGameStatus.PLAYED


@pytest.mark.django_db(transaction=True)
def test_shelved_is_refused_before_anything_is_recorded(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    with pytest.raises(PlayerGameWriteFailed) as refusal:
        record_facts(
            owned_user,
            game,
            status=PlayerGameStatus.SHELVED,
            correlation_id=new_correlation_id(),
        )

    assert refusal.value.status_code == 409
    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert row.status == PlayerGameStatus.UNPLAYED


@pytest.mark.django_db(transaction=True)
def test_a_session_marks_an_unplayed_game_played(logged_in, owned_library):
    """_record_played reads the row, not the catalog column.

    The catalog says played and the projection says unplayed, so a
    view that still read the column would record nothing.
    """
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    Game.objects.filter(pk=game.pk).update(status="p")
    started = timezone.now().replace(microsecond=0)

    logged_in.post(
        reverse("games:add_session"),
        {
            "game": str(game.pk),
            "timestamp_start": started.strftime("%Y-%m-%d %H:%M"),
            "timestamp_start_timezone": "",
            "timestamp_end": "",
            "timestamp_end_timezone": "",
            "duration_manual": "",
            "note": "",
            "mark_as_played": "on",
        },
    )

    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert row.status == PlayerGameStatus.PLAYED
```

The payload is `_session_payload` from `tests/test_playergame_view_cutover.py:156`,
inlined so this file stands alone. Add `from django.utils import timezone`.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playergame_status_word_setters.py"`
Expected: `ImportError: cannot import name 'SETTABLE_PLAYER_STATUSES'`.

- [ ] **Step 3: Derive the settable list**

In `games/playergame_status.py`, after `PLAYER_STATUS_TO_LEGACY_STATUS`:

```python
#: (value, label) per status, for a widget that sets one. The same
#: shape as common.components.LabeledOption, declared apart: this is
#: a domain module, and importing the component package for a pair
#: of strings would point the dependency the wrong way.
type LabeledStatus = tuple[str, str]

#: Every word a letter holds, in Game.Status declaration order.
#: SHELVED is absent, because _mirror() would have no letter to
#: write and would raise after the event had already committed.
#: #678 D removes the mirror and this list with it.
SETTABLE_PLAYER_STATUSES: tuple[LabeledStatus, ...] = tuple(
    (player_status.value, player_status.label)
    for player_status in PLAYER_STATUS_TO_LEGACY_STATUS
)
```

- [ ] **Step 4: Make the write path take a word**

In `games/writes/playergame.py`, change the import line

```python
from games.playergame_status import (
    LegacyStatus,
    legacy_status_for,
    player_status_for,
)
```

to

```python
from games.playergame_status import (
    PLAYER_STATUS_TO_LEGACY_STATUS,
    legacy_status_for,
)
```

Replace `record_facts`'s signature and its first lines:

```python
def record_facts(
    actor: User,
    game: Game,
    *,
    status: PlayerGameStatus | None = None,
    mastered: bool | None = None,
    correlation_id: uuid.UUID,
) -> None:
    """State one fact or two, then mirror.

    None means this act does not state that fact.
    """
    if status is not None and status not in PLAYER_STATUS_TO_LEGACY_STATUS:
        #: Refused before dispatch, not after: _mirror() raising on
        #: the way out would leave a committed event whose word the
        #: catalog cannot hold.
        raise PlayerGameWriteFailed(
            f"{PlayerGameStatus(status).label} cannot be recorded yet. The "
            "catalog columns still mirror the projection and no catalog "
            "status states this one; #678 D removes the mirror and the "
            "restriction with it.",
            409,
        )
    library = actor.library
    command = RecordPlayerGameFacts(
        game_id=game.pk,
        status=status,
        mastered=mastered,
    )
```

The rest of the function is unchanged.

- [ ] **Step 5: Make the request wrapper take a word**

In `games/views/playergame_writes.py`, replace

```python
from games.playergame_status import LegacyStatus
```

with

```python
from games.models import Game, PlayerGameStatus
```

(merging it into the existing `from games.models import Game` line) and change
both `status: LegacyStatus | None = None` annotations in
`record_facts_for_request` to `status: PlayerGameStatus | None = None`.

- [ ] **Step 6: Make the endpoint take a word**

In `games/api.py`:

```python
class GameStatusUpdate(Schema):
    #: The enum, so Ninja refuses unknown members. SHELVED is a
    #: member and reaches record_facts(), which answers 409 while
    #: the mirror still needs a letter.
    status: PlayerGameStatus
```

Add `PlayerGameStatus` to the `from games.models import ...` list. Drop `Game`
from that list only if nothing else in the file uses it — `partial_update_game`
still does.

- [ ] **Step 7: Make the form take a word**

In `games/forms.py`, in `GameForm`:

```python
    #: Plain fields, so form.save() writes neither column.
    status = forms.ChoiceField(choices=SETTABLE_PLAYER_STATUSES, required=True)
    mastered = forms.BooleanField(required=False)
```

In `__init__`, the initial for an existing game must come from the projection,
because the catalog letter is no longer what the field speaks. Replace the last
three lines of the method — shown here as a whole method so the indentation is
unambiguous; `...` stands for the lines above it, which do not change:

```python
def __init__(self, *args, library: UserLibrary, **kwargs):
    ...
    #: They left Meta.fields, so model_to_dict misses them.
    if self.instance.pk is not None:
        tracked = PlayerGame.objects.filter(library=library, game=self.instance).first()
        if tracked is not None:
            self.initial.setdefault("status", tracked.status)
            self.initial.setdefault("mastered", tracked.mastered)
```

In `save`, convert on the insert. One line of the existing comment is new, and
the two assignments change:

```python
def save(self, commit=True):
    game = super().save(commit=False)
    #: The row starts where the form says. Starting at the default
    #: and letting the mirror move it would append a GameStatusChange
    #: that does not exist today: the audit signal skips a first save.
    #: The form speaks words and the column holds letters until #678 D.
    if game._state.adding:
        game.status = legacy_status_for(PlayerGameStatus(self.cleaned_data["status"]))
        game.mastered = self.cleaned_data["mastered"]
    if commit:
        game.save()
        self.save_m2m()
    return game
```

Add the imports `PlayerGame`, `PlayerGameStatus` from `games.models` and
`SETTABLE_PLAYER_STATUSES`, `legacy_status_for` from `games.playergame_status`.

- [ ] **Step 8: Fix the add-game rollback**

In `games/views/game.py`, `add_game`'s failure branch calls
`Game.objects.filter(pk=game.pk).update(status=Game.Status.UNPLAYED,
mastered=False)`. It stays a letter, because it writes the catalog column
directly rather than stating a fact. Read it, confirm it is unchanged, and edit
nothing. It is listed because the surrounding lines all move and skipping the
check is how it would get "fixed" into a word.

- [ ] **Step 9: Make `_record_played` read the projection**

In `games/views/session.py`:

```python
def _record_played(request: HttpRequest, session: Session) -> None:
    """State Played for a game the projection calls unplayed."""
    tracked = PlayerGame.objects.filter(
        library=cast(User, request.user).library, game=session.game
    ).first()
    if tracked is None or tracked.status != PlayerGameStatus.UNPLAYED:
        return
    record_facts_for_request(
        request,
        session.game,
        status=PlayerGameStatus.PLAYED,
        correlation_id=new_correlation_id(),
    )
```

Change the import line `from games.models import Device, Game, Session,
UserLibrary` to add `PlayerGame` and `PlayerGameStatus`. `Game` is still used by
`add_session`, so keep it.

- [ ] **Step 10: Run the new test**

Run: `make test ARGS="tests/test_playergame_status_word_setters.py"`
Expected: 5 passed.

- [ ] **Step 11: Run the suites this touched**

Run: `make test ARGS="tests/test_playergame_view_cutover.py tests/test_playergame_write_path.py tests/test_api.py tests/test_forms.py"`
Expected: failures where a test posts a letter. Change each payload to the word
— `"f"` to `"completed"`, `"u"` to `"unplayed"`, `"p"` to `"played"`, `"r"` to
`"retired"`, `"a"` to `"abandoned"`. Where a test asserts on `game.status`,
leave it: the mirror still writes the letter.

- [ ] **Step 12: Commit**

```bash
git add games/playergame_status.py games/writes/playergame.py games/views/playergame_writes.py games/api.py games/forms.py games/views/session.py tests/
git commit -m "Say the status in the word the projection keeps"
```

---

### Task 6: The status dot speaks words

`_STATUS_COLORS` is keyed on letters. The projection holds words, so the table
is re-keyed and `shelved` gains a colour. Two call sites still hold letters:
`GameStatusSelector`, which Task 5 already moved to words, and `_game_history`,
which reads `GameStatusChange` and keeps letters until child D. The history site
converts at the call.

**Files:**
- Modify: `common/components/domain.py` (`_STATUS_COLORS` at 43, `GameStatus` at
  52, `GameStatusSelector` at 281)
- Modify: `games/views/game.py` (`_game_history` at 475)
- Modify: `tests/test_custom_elements.py` (96-105)
- Test: `tests/test_game_status_component.py`

**Interfaces:**
- Consumes: `SETTABLE_PLAYER_STATUSES` from Task 5.
- Produces: `GameStatus(children, status: str = PlayerGameStatus.UNPLAYED,
  display: str = "", class_: str = "")` — `status` is a `PlayerGameStatus`
  value.
- Produces: `GameStatusSelector(game, game_statuses: Sequence[LabeledStatus],
  csrf_token: str, class_: str = "", *, current: str)` — `current` is the
  `PlayerGameStatus` value the page shows. The caller supplies it, because it
  comes from the annotated queryset and not from the model instance.

- [ ] **Step 1: Write the failing test**

Create `tests/test_game_status_component.py`:

```python
"""The status dot and the status selector, on words."""

from types import SimpleNamespace
from uuid import uuid7

from common.components import GameStatus, GameStatusSelector, render
from games.models import PlayerGameStatus
from games.playergame_status import SETTABLE_PLAYER_STATUSES


def test_every_status_has_its_own_colour():
    colours = {
        str(render(GameStatus(["x"], status=status))) for status in PlayerGameStatus
    }

    assert len(colours) == len(PlayerGameStatus)


def test_the_selector_marks_the_projection_status_current():
    game = SimpleNamespace(id=uuid7(), status="u", mastered=False)

    html = str(
        render(
            GameStatusSelector(
                game,
                SETTABLE_PLAYER_STATUSES,
                "tok",
                current=PlayerGameStatus.COMPLETED,
            )
        )
    )

    assert "Completed" in html
    #: The catalog letter on the instance is not what is shown.
    assert 'data-value="completed"' in html
```

`render` is whatever `tests/test_custom_elements.py:100` imports; match that
import exactly. If the marker attribute is not `data-value`, read the real one
off `common/components/custom_elements.py`'s `SelectOption` rendering and use
it.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_game_status_component.py"`
Expected: the first test fails (five colours for six statuses, all falling back
to grey); the second fails on the missing `current` keyword.

- [ ] **Step 3: Re-key the colours**

In `common/components/domain.py`:

```python
_STATUS_COLORS = {
    PlayerGameStatus.UNPLAYED: "bg-gray-500",
    PlayerGameStatus.PLAYED: "bg-orange-400",
    PlayerGameStatus.COMPLETED: "bg-green-500",
    PlayerGameStatus.RETIRED: "bg-purple-500",
    PlayerGameStatus.SHELVED: "bg-sky-500",
    PlayerGameStatus.ABANDONED: "bg-red-500",
}
```

Import `PlayerGameStatus` from `games.models` at the top of the file, or inside
the function if the module avoids a model import at import time — check the
file's existing style and follow it.

Change `GameStatus`'s signature default and its lookup:

```python
def GameStatus(
    children: Children = None,
    status: str = PlayerGameStatus.UNPLAYED,
    display: str = "",
    class_: str = "",
) -> Node:
    """Colored status dot with label. Status is a PlayerGameStatus value.
```

```python
    dot_color = _STATUS_COLORS.get(status, _STATUS_COLORS[PlayerGameStatus.UNPLAYED])
```

The rest of the docstring and body are unchanged.

- [ ] **Step 4: Give the selector its current status**

In `common/components/domain.py`:

```python
def GameStatusSelector(
    game,
    game_statuses,
    csrf_token: str,
    class_: str = "",
    *,
    current: str,
) -> Node:
    """Status value-selector: a listbox that PATCHes /api/games/<id>/status.

    ``current`` is the status the page shows, taken from the library's
    projection row. It is a parameter rather than a read off ``game``
    because it arrives as a queryset annotation, which is not an
    attribute of the model instance.
    """
    from common.components.custom_elements import SelectDropdown, SelectOption

    labels = dict(game_statuses)
    options: list[SelectOption] = [
        SelectOption(
            value,
            GameStatus([label], status=value, display="flex"),
            value == current,
        )
        for value, label in game_statuses
    ]
    return SelectDropdown(
        current_label=GameStatus(
            [labels.get(current, current)], status=current, display="flex"
        ),
        options=options,
        id=f"game-{game.id}-status",
        patch_url=f"/api/games/{game.id}/status",
        body_key="status",
        event="status-changed",
        csrf=csrf_token,
        class_=class_,
    )
```

`labels.get(current, current)` is what shows a status the setter list withholds:
if a `shelved` row ever reaches this page before child D, the trigger reads
`shelved` rather than crashing.

- [ ] **Step 5: Convert at the history call site**

In `games/views/game.py`, in `_game_history`:

```python
        old_status = GameStatus(
            status=player_status_for(change.old_status)
            if change.old_status
            else PlayerGameStatus.UNPLAYED,
            children=[change.get_old_status_display() if change.old_status else "-"],
        )
        new_status = GameStatus(
            status=player_status_for(change.new_status),
            children=[change.get_new_status_display()],
        )
```

Add `from games.playergame_status import player_status_for` and
`PlayerGameStatus` to the `games.models` import. Child D deletes this whole
function.

- [ ] **Step 6: Fix the existing render test**

In `tests/test_custom_elements.py`, around line 104:

```python
            GameStatusSelector(
                game,
                [("unplayed", "Unplayed"), ("completed", "Completed")],
                "tok",
                current="unplayed",
            )
```

Adjust any assertion in that test that names a letter.

- [ ] **Step 7: Run both tests**

Run: `make test ARGS="tests/test_game_status_component.py tests/test_custom_elements.py"`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add common/components/domain.py games/views/game.py tests/test_game_status_component.py tests/test_custom_elements.py
git commit -m "Colour the dot by the word the projection holds"
```

---

### Task 7: The list and the detail page read the projection

**Files:**
- Modify: `games/views/game.py` (`list_games` at 104, `view_game` at 807,
  `_game_header`'s status row at 640-644)
- Test: `tests/test_playergame_game_views.py`

**Interfaces:**
- Consumes: `tracked_by()` (Task 2), `SETTABLE_PLAYER_STATUSES` (Task 5),
  `GameStatusSelector(..., current=...)` (Task 6).

- [ ] **Step 1: Write the failing test**

Create `tests/test_playergame_game_views.py`:

```python
"""The games list and the game page show the projection, not the catalog."""

import pytest
from django.urls import reverse
from django.utils import timezone

from games.models import Game, PlayerGame, PlayerGameStatus


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def disagreeing_game(owned_library):
    """The projection says Completed; the catalog still says unplayed."""
    game = Game.objects.create(
        library=owned_library, name="Outer Wilds", status="u", mastered=False
    )
    PlayerGame.objects.filter(library=owned_library, game=game).update(
        status=PlayerGameStatus.COMPLETED, mastered=True
    )
    return game


@pytest.mark.django_db
def test_the_list_shows_the_projection_status(logged_in, disagreeing_game):
    response = logged_in.get(reverse("games:list_games"))

    assert response.status_code == 200
    assert "Completed" in response.content.decode()


@pytest.mark.django_db
def test_the_page_shows_the_projection_status(logged_in, disagreeing_game):
    response = logged_in.get(disagreeing_game.get_absolute_url())

    assert response.status_code == 200
    assert "Completed" in response.content.decode()


@pytest.mark.django_db
def test_the_page_shows_the_projection_mastery(logged_in, disagreeing_game):
    response = logged_in.get(disagreeing_game.get_absolute_url())

    assert "👑" in response.content.decode()


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_an_untracked_game_is_off_the_list(logged_in, owned_library):
    Game.objects.create(library=owned_library, name="Outer Wilds")

    response = logged_in.get(reverse("games:list_games"))

    assert "Outer Wilds" not in response.content.decode()


@pytest.mark.django_db
def test_a_removed_game_is_off_the_list(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    Game.objects.filter(pk=game.pk).update(tombstoned_at=timezone.now())

    response = logged_in.get(reverse("games:list_games"))

    assert "Outer Wilds" not in response.content.decode()


@pytest.mark.django_db
def test_a_shared_game_this_library_tracks_is_on_the_list(logged_in, owned_library):
    import uuid

    shared = Game.objects.create(library=None, name="Shared Title")
    PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        game=shared,
        tracked_at=timezone.now(),
    )

    response = logged_in.get(reverse("games:list_games"))

    assert "Shared Title" in response.content.decode()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playergame_game_views.py"`
Expected: the three "shows the projection" tests fail (the page reads the
catalog), and the untracked / shared cases fail.

- [ ] **Step 3: Switch `list_games`**

In `games/views/game.py`, line 109:

```python
    games = Game.objects.tracked_by(library).select_related("platform")
```

and the row's fourth cell at line 167, today
`GameStatusSelector(game, Game.Status.choices, get_token(request))`, becomes:

```python
GameStatusSelector(
    game,
    SETTABLE_PLAYER_STATUSES,
    get_token(request),
    current=game.tracked_status,
)
```

It sits inside the `make_row(...)` call in the `"rows"` comprehension, so it
keeps its trailing comma and its indentation there.

- [ ] **Step 4: Switch `view_game`**

In `games/views/game.py`, line 809:

```python
    game = owned_or_404(Game.objects.tracked_by(library), library, id=game_id)
```

and `render_page`'s last argument at line 833, `mastered=game.mastered`, becomes
`mastered=game.tracked_mastered`.

- [ ] **Step 5: Switch the detail page's status row**

In `games/views/game.py`, in `_game_header`, the Status row at lines 640-644 is
one element of a list, so it keeps its trailing comma and its 8-space
indentation. Dedented to show the shape:

```python
_meta_row(
    "Status",
    Span()[
        GameStatusSelector(
            game,
            SETTABLE_PLAYER_STATUSES,
            get_token(request),
            current=game.tracked_status,
        )
    ],
    "👑" if game.tracked_mastered else "",
)
```

- [ ] **Step 6: Fix the imports**

Add `from games.playergame_status import SETTABLE_PLAYER_STATUSES` to
`games/views/game.py`. Remove `Game.Status.choices` uses; keep the `Game`
import, which `add_game`'s rollback and several querysets still need.

- [ ] **Step 7: Run it and watch it pass**

Run: `make test ARGS="tests/test_playergame_game_views.py"`
Expected: 6 passed.

- [ ] **Step 8: Run the page suites**

Run: `make test ARGS="tests/test_paths_return_200.py tests/test_rendered_pages.py tests/test_views.py"`
Expected: green. A failure that reads an empty games list means a test built its
own `Game` queryset and passed it somewhere that now needs the annotation — give
that test `tracked_by()`.

- [ ] **Step 9: Commit**

```bash
git add games/views/game.py tests/test_playergame_game_views.py
git commit -m "Show the list a library's own row, not the catalog's"
```

---

### Task 8: Nested game filters resolve from the projection

`relation_to_q` builds every subquery from `context.queryset_for(Game)`, so one
line covers every nested `GameFilter` at once — the one `stats_links` puts
inside a `PurchaseFilter` included. `list_games` is the separate top-level
supplier and Task 7 already moved it. The two had to change together, so this
task lands immediately after.

A `GameFilter` applied to a queryset without the annotation raises `FieldError`
— a 500, not a degraded page. After this task only one production site can make
that mistake, and it has already moved.

**Files:**
- Modify: `games/filters.py` (`filter_query_context_for_library` at 817)
- Test: `tests/test_playergame_nested_filter_scope.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_playergame_nested_filter_scope.py`:

```python
"""A nested game filter resolves from the library's tracked games."""

from datetime import date

import pytest

from common.criteria import Modifier, StringCriterion
from common.filter_execution import execute_filter
from games.filters import (
    GameFilter,
    PurchaseFilter,
    filter_query_context_for_library,
)
from games.models import Game, Purchase


def a_purchase_of(library, game):
    purchase = Purchase.objects.create(
        library=library, name="Order", date_purchased=date(2026, 1, 1)
    )
    purchase.games.add(game)
    return purchase


def named_outer_wilds():
    """A non-empty sub-filter, so the compiler builds the subquery."""
    return PurchaseFilter(
        game_filter=GameFilter(
            name=StringCriterion(value="Outer", modifier=Modifier.INCLUDES)
        )
    )


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_an_untracked_game_matches_no_nested_filter(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    a_purchase_of(owned_library, game)

    matched = execute_filter(
        named_outer_wilds(),
        Purchase.objects.for_library(owned_library),
        filter_query_context_for_library(owned_library),
    )

    assert not matched.exists()


@pytest.mark.django_db
def test_a_tracked_game_matches(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    purchase = a_purchase_of(owned_library, game)

    matched = execute_filter(
        named_outer_wilds(),
        Purchase.objects.for_library(owned_library),
        filter_query_context_for_library(owned_library),
    )

    assert list(matched) == [purchase]


@pytest.mark.django_db
def test_the_context_queryset_carries_the_annotation(owned_library):
    Game.objects.create(library=owned_library, name="Outer Wilds")

    queryset = filter_query_context_for_library(owned_library).queryset_for(Game)

    assert queryset.get().tracked_status is not None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playergame_nested_filter_scope.py"`
Expected: the first and third fail — the context still hands back
`for_library()`.

- [ ] **Step 3: Switch the context**

In `games/filters.py`, in `filter_query_context_for_library`:

```python
    scoped_querysets: dict[builtins.type, QuerySet] = {
        #: tracked_by, not for_library: a nested game filter resolves
        #: from the games this library tracks, and its criteria read
        #: the projection through the `tracked` alias.
        Game: Game.objects.tracked_by(library),
        Session: Session.objects.for_library(library),
```

- [ ] **Step 4: Run it and watch it pass**

Run: `make test ARGS="tests/test_playergame_nested_filter_scope.py"`
Expected: 3 passed.

- [ ] **Step 5: Run every filter suite**

Run: `make test ARGS="tests/test_filters.py tests/test_filter_paths.py tests/test_filter_execution.py tests/test_stats_links.py"`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add games/filters.py tests/test_playergame_nested_filter_scope.py
git commit -m "Resolve a nested game filter from the tracked games"
```

---

### Task 9: The browser check, and the gate

A unit test can assert the query. Only the browser can assert that the widget
the page renders sets what the reloaded page then shows. Note the project's
rule: a UI assertion is not a database assertion — this test waits on a
server-rendered reload rather than the optimistic DOM update.

**Files:**
- Test: `e2e/test_games_list_projection_e2e.py`
- Modify: `e2e/test_custom_elements_e2e.py` (the two status-selector tests)

- [ ] **Step 1: Update the existing selector test**

`e2e/test_custom_elements_e2e.py:16` picks `[data-option][data-value="f"]` and
expects the trigger to read `Finished`. After Task 6 the option's value is the
word and the label is `PlayerGameStatus.COMPLETED`'s. In
`test_game_status_selector_opens_and_patches` and in
`test_status_selector_reverts_on_failed_patch` (line 121), replace every
`data-value="f"` with `data-value="completed"`, every `data-value="u"` with
`data-value="unplayed"`, and every `"Finished"` with `"Completed"`. Leave the
`Game.objects.create(..., status="u")` calls alone — the catalog column still
holds a letter, and the projection row the autouse fixture writes starts at
`unplayed` regardless.

Run: `make test-e2e ARGS="-k selector"`
Expected: green.

- [ ] **Step 2: Write the list test**

Create `e2e/test_games_list_projection_e2e.py`. The sign-in fixture and the
dropdown idiom are copied from `e2e/test_custom_elements_e2e.py` rather than
invented:

```python
"""The games list under the inner join, in a real browser."""

import pytest
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import Page, expect

from games.models import Game, PlayerGame, PlayerGameStatus


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def list_url(live_server) -> str:
    return f"{live_server.url}{reverse('games:list_games')}"


@pytest.mark.django_db(transaction=True)
def test_a_tracked_game_is_listed(authenticated_page: Page, live_server, e2e_library):
    Game.objects.create(library=e2e_library, name="Outer Wilds")

    authenticated_page.goto(list_url(live_server))

    expect(authenticated_page.get_by_text("Outer Wilds")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_a_removed_game_is_not_listed(
    authenticated_page: Page, live_server, e2e_library
):
    game = Game.objects.create(library=e2e_library, name="Outer Wilds")
    Game.objects.filter(pk=game.pk).update(tombstoned_at=timezone.now())

    authenticated_page.goto(list_url(live_server))

    expect(authenticated_page.get_by_text("Outer Wilds")).to_have_count(0)


@pytest.mark.django_db(transaction=True)
def test_the_status_a_selector_sets_survives_a_reload(
    authenticated_page: Page, live_server, e2e_library
):
    game = Game.objects.create(library=e2e_library, name="Outer Wilds")
    page = authenticated_page
    page.goto(list_url(live_server))

    host = page.locator(f"#game-{game.pk}-status")
    expect(host).to_be_attached()
    host.locator("[data-toggle]").click()
    expect(host.locator("[data-menu]")).to_be_visible()
    with page.expect_response(
        lambda response: (
            "/status" in response.url and response.request.method == "PATCH"
        )
    ):
        host.locator('[data-option][data-value="completed"]').click()

    #: The reload is the assertion. The trigger swaps its label
    #: optimistically, so reading it here would pass without a write.
    page.goto(list_url(live_server))
    expect(page.locator(f"#game-{game.pk}-status [data-label]")).to_contain_text(
        "Completed"
    )

    row = PlayerGame.objects.get(library=e2e_library, game=game)
    assert row.status == PlayerGameStatus.COMPLETED
```

- [ ] **Step 3: Run it**

Run: `make test-e2e ARGS="-k projection"`
Expected: 3 passed.

- [ ] **Step 4: Run the gate**

Run: `make check`
Expected: green — lint, format check, mypy, vale, ts-check, vitest, and the
whole pytest suite including `e2e/`. Nothing short of this counts as done.

- [ ] **Step 5: Commit and open the pull request**

```bash
git add e2e/test_games_list_projection_e2e.py e2e/test_custom_elements_e2e.py
git commit -m "Watch the list and the selector in a real browser"
git push -u origin codex/playergame-read-cutover-a
gh pr create --base codex/playergame-read-cutover \
  --title "PGAME-08 A: the join and the display" \
  --body "See docs/superpowers/plans/2026-08-28-playergame-read-cutover-a.md"
```

---

## What child A leaves behind

Named here so the next plan starts from a true picture, not so anyone acts on it
now.

- `GameFilter.status` and `.mastered` still name the catalog columns. The quick
  bar and the builder still filter on letters. Child B re-points them at
  `tracked__status` / `tracked__mastered` with the `metadata_lookup` Task 3
  added, and moves `GAME_SORTS["status"]` to `tracked_status`.
- `stats_data`, the three `PurchaseQuerySet` methods and the five `stats_links`
  builders still read `games__status=` letters, and are correct because
  `_mirror()` keeps the letters current. Child C moves them and adds their cases
  to `tests/test_playergame_read_parity.py`.
- The History section still reads `GameStatusChange`, the audit signal still
  writes it, and `_mirror()` still runs. Child D moves History to the events,
  retires the four `statuschange` routes, deletes `_mirror()`,
  `games/views/playergame_writes.py`, the reverse half of
  `games/playergame_status.py` — `legacy_status_for`, `LegacyStatus`,
  `UnmappedPlayerStatus`, `SETTABLE_PLAYER_STATUSES` and the refusal
  `record_facts()` raises — and the parity suite.
- `shelved` is filterable and unsettable until D removes that refusal.
