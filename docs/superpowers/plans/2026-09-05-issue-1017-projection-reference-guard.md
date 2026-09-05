# Projection Reference Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a cross-library reference out of a projection table detectable before it is written, and legible when it stops a rebuild.

**Architecture:** One new module, `games/projections.py`, enumerates the projection tables and every foreign key out of them into a library-scoped model, holds the registry of audited pairs, and runs the one violation query. A new system check `games.E009` fails when the walk finds a pair the registry does not list. `swap_in` catches SQLSTATE 23503 at commit and raises a typed error whose sentence names the offending rows.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pytest + pytest-django, psycopg 3.

**Spec:** `docs/superpowers/specs/2026-09-05-issue-1017-projection-reference-guard-design.md`

## Global Constraints

- **Drive everything through `make`.** Never wrap a command in `direnv exec .`. Never run raw `uv run` / `pytest` / `pnpm`. A focused run is `make test ARGS="tests/test_x.py -k name -x"`. Set `PYTEST_WORKERS=0` when a failure is hard to read.
- **The verification gate is the full `make check`**, including `e2e/`. `make check-fast` is for iterating and is not the gate. `ARGS` is never the gate.
- **Python 3.14 only.** A `SyntaxError` in an `except A, B:` line means the wrong interpreter, not broken code.
- **Name variables with complete words.** `template` not `tpl`, `event` not `e`, `field_name` not `fname`.
- **Name compound types explicitly.** A tuple or dict passed between functions gets a `NamedTuple` / `TypedDict` / `type` alias. A bare `str` standing for a domain concept gets a PEP 695 alias, e.g. `type FieldName = str`.
- **Some words are refused** and `make vale` enforces them over docs *and* code comments. A projector *replays*; the row is the *projection*. Never "folds", "tombstone", "archive", "heal". Say "remove" for a user act, "purge" for the whole library, "destroy" for what a script does to a row. Identifiers are out of scope.
- **Comments are `#:` prefixed** in this codebase when they annotate a declaration. Keep them at the density of the surrounding file — roughly one short comment per non-obvious decision, never a line-by-line narration.
- **Nothing destroys a record**: never call `instance.delete()` in application code. Test code may, and existing tests do.
- **No dispatch inside a transaction**: `run_in_transaction` refuses to nest. A test that POSTs through a dispatching view needs `@pytest.mark.django_db(transaction=True)`.
- **Never write to a `GeneratedField`.**

---

## File Structure

| File | Responsibility |
|------|----------------|
| `games/projections.py` (create) | The projection tables, the walk over their outward references, the audited registry, the violation query. Depends on `games.models` only. |
| `games/events/rebuild.py` (modify) | Loses `projection_models`, re-imports it. Gains `SwapRefusedByReference` and the 23503 handler in `swap_in`. |
| `games/events/retry.py` (modify) | Gains `FOREIGN_KEY_VIOLATION`; `_sqlstate` and `_constraint_name` become public. |
| `games/events/benchmark.py` (modify) | Imports `projection_models` from its new home. |
| `games/checks.py` (modify) | Gains `check_projection_references` → `games.E009`. |
| `games/management/commands/audit_library_ownership.py` (modify) | Its projection block becomes one call. |
| `games/management/commands/rebuild_projections.py` (modify) | Answers `SwapRefusedByReference`. |
| `games/models.py` (modify) | The `ProjectionModel` docstring gains the check. |
| `tests/test_projection_references.py` (create) | The walk, the registry, `games.E009`. |
| `tests/test_library_commands.py` (modify) | The derived violation line; the two widened-walk cases. |
| `tests/test_projection_rebuild.py` (modify) | Its `projection_models` import; the two swap-refusal cases. |

**Task order and why:** Task 1 stands alone and everything imports it. Task 2 (the check) and Task 3 (the audit command) both consume Task 1 and are independent of each other. Task 4 (the swap) consumes Task 1 and Task 5 (the command) consumes Task 4. Task 6 is the docs sweep and the gate.

---

### Task 1: The topology module

**Files:**
- Create: `games/projections.py`
- Modify: `games/events/rebuild.py:30-38` (remove `projection_models`), `games/events/rebuild.py:12-21` (imports)
- Modify: `games/events/benchmark.py:15-20` (import site)
- Test: `tests/test_projection_references.py` (create)

**Interfaces:**
- Consumes: `games.models.ProjectionModel`, `games.models.PlayerGame`, `games.models.Playthrough`.
- Produces:
  - `type FieldName = str`
  - `class ProjectionReference(NamedTuple): model: type[ProjectionModel]; field: models.ForeignKey[Any, Any]`
  - `AUDITED_PROJECTION_REFERENCES: tuple[ProjectionReference, ...]`
  - `def projection_models(apps: Apps = global_apps) -> tuple[type[ProjectionModel], ...]`
  - `def projection_references(apps: Apps = global_apps) -> tuple[ProjectionReference, ...]`
  - `def unaudited_projection_references(apps: Apps = global_apps) -> tuple[ProjectionReference, ...]`
  - `def cross_library_violations(references: Iterable[ProjectionReference], library_ids: Sequence[Any]) -> list[str]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_projection_references.py`:

```python
"""Every reference out of a projection table, enumerated."""

import uuid

import pytest
from django.db import models
from django.test.utils import isolate_apps
from django.utils import timezone
from test_projection_targets import declare_projection_models

from games.models import Game, PlayerGame, Playthrough, ProjectionModel
from games.projections import (
    AUDITED_PROJECTION_REFERENCES,
    ProjectionReference,
    cross_library_violations,
    projection_references,
    unaudited_projection_references,
)


def named(references):
    """`(model name, field name)` per reference, for a readable assertion."""
    return [
        (reference.model.__name__, reference.field.name) for reference in references
    ]


def test_the_walk_finds_every_outward_reference():
    """Both keys out of a projection, and neither library column."""
    assert named(projection_references()) == [
        ("PlayerGame", "game"),
        ("Playthrough", "player_game"),
    ]


def test_the_library_column_is_not_a_reference():
    """`UserLibrary` has no library of its own."""
    assert "library" not in {
        reference.field.name for reference in projection_references()
    }


def test_every_reference_is_audited():
    """The registry and the walk agree."""
    assert unaudited_projection_references() == ()
    assert named(AUDITED_PROJECTION_REFERENCES) == named(projection_references())


@isolate_apps("games")
def test_an_unregistered_reference_is_unaudited():
    """`Entry.shelf` is a foreign key nobody registered."""
    shelf, entry = declare_projection_models()

    unaudited = unaudited_projection_references(apps=shelf._meta.apps)

    assert named(unaudited) == [("Entry", "shelf")]


@isolate_apps("games")
def test_a_cascade_reference_is_walked_too():
    """`CASCADE` across libraries is worse than `RESTRICT`, not better."""
    shelf, entry = declare_projection_models()

    found = projection_references(apps=shelf._meta.apps)

    assert entry._meta.get_field("shelf").remote_field.on_delete is models.CASCADE
    assert ("Entry", "shelf") in named(found)


@pytest.fixture
def tracked_pair(owned_library):
    """One library's game and the row that tracks it."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    tracked = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=game,
        tracked_at=timezone.now(),
    )
    return game, tracked


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_a_matching_library_is_no_violation(owned_library, tracked_pair):
    assert (
        cross_library_violations(AUDITED_PROJECTION_REFERENCES, [owned_library.pk])
        == []
    )


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_a_game_with_no_library_is_no_violation(owned_library):
    """A shared catalog row crosses no boundary."""
    shared = Game.objects.create(name="Tunic")
    PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=shared,
        tracked_at=timezone.now(),
    )

    assert shared.library_id is None
    assert (
        cross_library_violations(AUDITED_PROJECTION_REFERENCES, [owned_library.pk])
        == []
    )


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_a_reference_across_libraries_is_reported(
    owned_library, other_library, tracked_pair
):
    """The row and the row it names, both ids."""
    game, tracked = tracked_pair
    run = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=other_library,
        player_game=tracked,
        kind="ordinary",
        created_at=timezone.now(),
    )

    reported = cross_library_violations(
        AUDITED_PROJECTION_REFERENCES, [owned_library.pk]
    )

    assert reported == [
        f"Playthrough.player_game: {run.pk} names PlayerGame {tracked.pk}"
    ]
```

Add the `other_library` fixture to the same file, above `tracked_pair`:

```python
@pytest.fixture
def other_library(django_user_model):
    """A second owner, for the cross-library cases."""
    return django_user_model.objects.create_user(
        username="reference-outsider", password="p"
    ).library
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_projection_references.py -x"`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'games.projections'`.

- [ ] **Step 3: Create `games/projections.py`**

```python
"""The projection tables, and every row outside a library they can name."""

from collections.abc import Iterable, Sequence
from typing import Any, NamedTuple

from django.apps import apps as global_apps
from django.apps.registry import Apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import F, Q

from games.models import PlayerGame, Playthrough, ProjectionModel

type FieldName = str  # e.g. "player_game"

#: The column every library-scoped model carries.
LIBRARY_FIELD: FieldName = "library"


class ProjectionReference(NamedTuple):
    """One foreign key out of a projection table."""

    model: type[ProjectionModel]
    field: models.ForeignKey[Any, Any]

    def __str__(self) -> str:
        return f"{self.model.__name__}.{self.field.name}"


def projection_models(apps: Apps = global_apps) -> tuple[type[ProjectionModel], ...]:
    """Every projection table in `apps`, sorted."""
    found = [
        model
        for model in apps.get_models()
        if issubclass(model, ProjectionModel) and model._meta.managed
    ]
    #: `managed` is what excludes the manufactured twins.
    return tuple(sorted(found, key=lambda model: model._meta.db_table))


def _is_library_scoped(model: type[models.Model]) -> bool:
    """Whether a row of `model` belongs to one library."""
    try:
        model._meta.get_field(LIBRARY_FIELD)
    except FieldDoesNotExist:
        return False
    return True


def projection_references(apps: Apps = global_apps) -> tuple[ProjectionReference, ...]:
    """Every foreign key out of a projection into a library-scoped row.

    Keyed on the referenced model carrying a library, not on it being a
    projection: that is the condition the cost follows. `UserLibrary` has
    no library of its own, so the `library` column excludes itself and
    needs no case. `on_delete` does not narrow the walk either --
    `RESTRICT` stops the referenced library from ever being purged, and
    `CASCADE` would take rows out of it.
    """
    found = [
        ProjectionReference(model, field)
        for model in projection_models(apps)
        for field in model._meta.concrete_fields
        if isinstance(field, models.ForeignKey)
        and _is_library_scoped(field.related_model)
    ]
    return tuple(
        sorted(
            found,
            key=lambda reference: (
                reference.model._meta.db_table,
                reference.field.column,
            ),
        )
    )


#: Every reference the ownership audit reads. `games.E009` refuses a walk
#: that finds one this list does not.
AUDITED_PROJECTION_REFERENCES: tuple[ProjectionReference, ...] = (
    ProjectionReference(PlayerGame, PlayerGame._meta.get_field("game")),
    ProjectionReference(Playthrough, Playthrough._meta.get_field("player_game")),
)


def unaudited_projection_references(
    apps: Apps = global_apps,
) -> tuple[ProjectionReference, ...]:
    """Every reference the walk finds and the registry omits."""
    audited = {
        (reference.model._meta.label, reference.field.name)
        for reference in AUDITED_PROJECTION_REFERENCES
    }
    return tuple(
        reference
        for reference in projection_references(apps)
        if (reference.model._meta.label, reference.field.name) not in audited
    )


def cross_library_violations(
    references: Iterable[ProjectionReference],
    library_ids: Sequence[Any],
) -> list[str]:
    """Every row that names a row in another library.

    The `isnull` clause is on the referenced row's library, and it is
    load-bearing. Django compiles `exclude()` to mean "not equal, nulls
    included": it puts `IS NOT NULL` inside the negation, so a null on
    either side would be answered as a violation. A null foreign key
    joins no row, and a joined row with no library is shared.
    """
    violations: list[str] = []
    for reference in references:
        name = reference.field.name
        rows = (
            reference.model.objects.filter(
                Q(library_id__in=library_ids)
                | Q(**{f"{name}__library_id__in": library_ids}),
                **{f"{name}__library__isnull": False},
            )
            .exclude(**{f"{name}__library_id": F("library_id")})
            .values_list("pk", reference.field.attname)
        )
        referenced = reference.field.related_model.__name__
        for row_id, referenced_id in rows:
            violations.append(
                f"{reference}: {row_id} names {referenced} {referenced_id}"
            )
    return violations
```

- [ ] **Step 4: Move `projection_models` out of `rebuild.py`**

In `games/events/rebuild.py`, remove the `projection_models` definition at lines 30-38 and the now-unused `global_apps` usage inside it. Replace the definition with an import, so `tests/test_projection_rebuild.py:40` and `games/events/benchmark.py:18` keep working:

Delete from `games/events/rebuild.py`:

```python
def projection_models(apps: Apps = global_apps) -> tuple[type[ProjectionModel], ...]:
    """Every projection table in `apps`, sorted."""
    found = [
        model
        for model in apps.get_models()
        if issubclass(model, ProjectionModel) and model._meta.managed
    ]
    #: `managed` is what excludes the manufactured twins.
    return tuple(sorted(found, key=lambda model: model._meta.db_table))
```

Add to its import block, keeping the existing `from games.models import ...` line:

```python
from games.projections import projection_models
```

Leave `rebuild.py`'s `type TableName = str` alias where it is: `games/events/benchmark.py:17` imports it from `rebuild`, and `games/projections.py` declares no copy.

- [ ] **Step 5: Run the new tests**

Run: `make test ARGS="tests/test_projection_references.py -x"`
Expected: PASS, 8 tests.

- [ ] **Step 6: Run the tests that import the moved name**

Run: `make test ARGS="tests/test_projection_rebuild.py -x"`
Expected: PASS. If `ImportError` on `projection_models`, the re-import in Step 4 is missing.

- [ ] **Step 7: Lint, type-check, and lint the prose**

Run: `make lint && make format && make typecheck && make vale`
Expected: clean. `make vale` reports 7 warnings and no errors — that is the unchanged baseline; a new error means a refused word entered a comment.

- [ ] **Step 8: Commit**

```bash
git add games/projections.py games/events/rebuild.py games/events/benchmark.py tests/test_projection_references.py
git commit -m "Enumerate every reference out of a projection table

The walk keys on the referenced model carrying a library rather than on
it being a projection, which is what matches the cost: PlayerGame.game
is RESTRICT into Game, and a PlayerGame naming another library's Game
blocks that library's purge forever.

projection_models moves here from games/events/rebuild.py. An audit
query has nothing to do with rebuilding, and leaving it there would make
that module the home of the audited registry as well.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The completeness check

**Files:**
- Modify: `games/checks.py` (append a new check after `check_projection_models`)
- Test: `tests/test_projection_references.py` (append)

**Interfaces:**
- Consumes: `games.projections.unaudited_projection_references` from Task 1.
- Produces: `def check_projection_references(*, app_configs=None, databases=None, apps=global_apps, **kwargs) -> list[CheckMessage]`, registered under `@register(Tags.models)`, emitting `games.E009`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_projection_references.py`, and add `from games.checks import check_projection_references` to its imports:

```python
def test_the_real_registry_reports_no_unaudited_reference():
    assert check_projection_references() == []


@isolate_apps("games")
def test_an_unaudited_reference_is_refused():
    """The check reads the isolated registry it is handed.

    `run_checks()` would prove nothing here: `isolate_apps` swaps
    `Options.default_apps` and leaves `django.apps.apps` alone, so the
    synthetic models are invisible to the global registry. That is also
    why no shipped check test regresses.
    """
    shelf, _ = declare_projection_models()

    messages = check_projection_references(apps=shelf._meta.apps)

    assert [str(message.id) for message in messages] == ["games.E009"]
    assert "Entry.shelf" in messages[0].msg
    assert "CASCADE" in messages[0].msg


@isolate_apps("games")
def test_the_check_honours_an_app_label_filter():
    """A check asked about another app answers nothing."""
    shelf, _ = declare_projection_models()

    class OtherConfig:
        label = "not_games"

    messages = check_projection_references(
        app_configs=[OtherConfig()], apps=shelf._meta.apps
    )

    assert messages == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_projection_references.py -k check -x"`
Expected: FAIL with `ImportError: cannot import name 'check_projection_references'`.

- [ ] **Step 3: Add the check**

Append to `games/checks.py`, after `check_projection_models` and its helpers, before `check_atomic_requests`:

```python
@register(Tags.models)
def check_projection_references(
    *,
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    apps: Apps = global_apps,
    **kwargs: Any,
) -> list[CheckMessage]:
    """Refuse a reference the ownership audit does not read."""
    labels = None if app_configs is None else {config.label for config in app_configs}
    errors: list[CheckMessage] = []
    for reference in unaudited_projection_references(apps):
        if labels is not None and reference.model._meta.app_label not in labels:
            continue
        on_delete = reference.field.remote_field.on_delete.__name__
        errors.append(
            Error(
                f"{reference} is an unaudited {on_delete} reference out of a "
                "projection table.",
                hint=(
                    "A value naming another library's row is invisible to "
                    "every query a rebuild runs: a shadow table copies no "
                    "foreign key, and the diff is scoped to one library. It "
                    "is found when the swap refuses at commit, or never. Add "
                    "the pair to AUDITED_PROJECTION_REFERENCES in "
                    "games/projections.py, which is what "
                    "audit_library_ownership reads."
                ),
                obj=reference.model,
                id="games.E009",
            )
        )
    return errors
```

Add to the imports at the top of `games/checks.py`:

```python
from games.projections import unaudited_projection_references
```

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_projection_references.py -x"`
Expected: PASS, 11 tests.

- [ ] **Step 5: Prove the check runs for real**

Run: `make test ARGS="tests/test_projection_rebuild.py tests/test_projection_targets.py tests/test_projection_model.py tests/test_playergame_projection.py tests/test_playthrough_projection.py -x"`
Expected: PASS. These are every file that calls `run_checks()` or a check directly; none should newly report `games.E009`.

- [ ] **Step 6: Commit**

```bash
git add games/checks.py tests/test_projection_references.py
git commit -m "Refuse a projection reference the audit does not read

games.E009 fires from manage.py check, and so from every migrate, every
make dev, and container start -- before the suite does.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The audit command reads the registry

**Files:**
- Modify: `games/management/commands/audit_library_ownership.py:167-257` (the projection block and the docstring), `:8-22` (imports)
- Test: `tests/test_library_commands.py:603-629` and `:581-590`

**Interfaces:**
- Consumes: `games.projections.AUDITED_PROJECTION_REFERENCES` and `cross_library_violations` from Task 1.
- Produces: no new name. The audit's violation line for a registered pair becomes `PlayerGame.game: <id> names Game <id>`.

- [ ] **Step 1: Update the two pinned assertions and add the widened-walk cases**

In `tests/test_library_commands.py`, the relation-name loop around line 581 gains one entry. Replace:

```python
        "UserLibraryPreferences.default_device",
        "Playthrough.player_game",
    ):
```

with:

```python
        "UserLibraryPreferences.default_device",
        "Playthrough.player_game",
        "PlayerGame.game",
    ):
```

Then replace the body of `test_a_playthrough_in_another_library_is_reported` (the assertion at lines 626-629) with the derived line:

```python
    assert (
        f"Playthrough.player_game: {run.pk} names PlayerGame {tracked.pk}"
        in output.getvalue()
    )
```

Append two cases after it:

```python
@pytest.mark.django_db
def test_a_tracked_game_from_another_library_is_reported(owner, outsider):
    """`PlayerGame.game` is RESTRICT: it blocks the other library's purge."""
    game = Game.objects.create(library=outsider.library, name="Tunic")
    tracked = PlayerGame.objects.get(game=game)
    PlayerGame.objects.filter(pk=tracked.pk).update(library=owner.library)
    output = StringIO()

    with pytest.raises(CommandError, match="violation"):
        call_command(
            "audit_library_ownership",
            "--user",
            owner.username,
            stdout=output,
        )

    assert f"PlayerGame.game: {tracked.pk} names Game {game.pk}" in output.getvalue()


@pytest.mark.django_db
def test_a_tracked_game_with_no_library_is_no_violation(owner):
    """A shared catalog row crosses no boundary."""
    shared = Game.objects.create(name="Outer Wilds")
    PlayerGame.objects.create(
        id=uuid7(),
        library=owner.library,
        game=shared,
        tracked_at=timezone.now(),
    )
    output = StringIO()

    call_command(
        "audit_library_ownership",
        "--user",
        owner.username,
        stdout=output,
    )

    assert shared.library_id is None
    assert "Cross-library links: 0" in output.getvalue()
```

Note on the first case: `tests/test_library_commands.py` carries **no** `untracked_games` mark, so `Game.objects.create(library=…)` already produces the matching `PlayerGame` through the conftest signal at `tests/conftest.py:227-245`. The `update()` is what makes it cross-library, and it bypasses `save()` so no signal re-runs.

Note on the second case: `Game.objects.create(name=…)` with no library produces **no** `PlayerGame`, because the signal returns early on `instance.library_id is None`. The row is created explicitly.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_library_commands.py -k 'cross_library or another_library or no_library or tracked_game' -x"`
Expected: FAIL — the two existing tests on the old prose and the missing `PlayerGame.game` line, plus the new cases.

- [ ] **Step 3: Replace the projection block**

In `games/management/commands/audit_library_ownership.py`, delete the block from the comment `#: The first foreign key between two projection tables.` through the closing of that `for` loop (lines 244-256), and delete `Playthrough` from the model imports at the top. Append in its place, immediately before `return violations`:

```python
violations.extend(cross_library_violations(AUDITED_PROJECTION_REFERENCES, library_ids))
```

Add to the imports:

```python
from games.projections import (
    AUDITED_PROJECTION_REFERENCES,
    cross_library_violations,
)
```

Replace the `_cross_library_violations` docstring with:

```python
        """Every relation audited, one loop each.

        The six loops below are hand-written because each names its own
        join path, and one of them reads an M2M through table. Every
        reference out of a projection is derived instead, from the
        registry `games.E009` holds complete.
        """
```

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_library_commands.py -x"`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git add games/management/commands/audit_library_ownership.py tests/test_library_commands.py
git commit -m "Audit every registered projection reference in one loop

The command now reports PlayerGame.game, which nothing audited before.
Its violation line is derived from the pair: a guard that forces a new
relation to be registered cannot also demand prose for it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The swap answers 23503

**Files:**
- Modify: `games/events/retry.py:25` (constants), `:67-77` (the two readers), `:88-92` and `:132` (their call sites)
- Modify: `games/events/rebuild.py:295-319` (`swap_in`)
- Test: `tests/test_projection_rebuild.py` (append)

**Interfaces:**
- Consumes: `games.projections.AUDITED_PROJECTION_REFERENCES`, `cross_library_violations` from Task 1.
- Produces:
  - `games.events.retry.FOREIGN_KEY_VIOLATION: str = "23503"`
  - `games.events.retry.sqlstate_of(error: Exception) -> str | None`
  - `games.events.retry.constraint_name_of(error: Exception) -> str | None`
  - `class SwapRefusedByReference(RuntimeError)` in `games/events/rebuild.py`, with attributes `library_id: uuid.UUID`, `constraint_name: str | None`, `violations: tuple[str, ...]`, `tables: tuple[TableDiff, ...]`
  - `swap_in` gains a keyword-only parameter `tables: tuple[TableDiff, ...] = ()`, carried into the error.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_projection_rebuild.py`:

```python
@pytest.fixture
def other_owner(django_user_model):
    """A second library, for a reference across the boundary."""
    return django_user_model.objects.create_user(
        username="rebuild-outsider", password="p"
    )


def plant_tracked_game(library):
    """A PlayerGame with no event behind it.

    The module marks `untracked_games`, so `Game.objects.create` writes
    no tracking row. A replay of this library therefore reproduces
    nothing, which is what makes the swap's DELETE take the row.
    """
    game = Game.objects.create(library=library, name="Outer Wilds")
    return PlayerGame.objects.create(
        id=uuid7(),
        library=library,
        game=game,
        tracked_at=timezone.now(),
    )


@pytest.mark.django_db(transaction=True)
def test_a_cross_library_reference_refuses_the_swap(owned_library, other_owner):
    """The rows, not a constraint name.

    The violation fires on the swap's DELETE -- the planted row is still
    referenced -- so the sentence is matched on the two ids.
    """
    planted = plant_tracked_game(owned_library)
    run = Playthrough.objects.create(
        id=uuid7(),
        library=other_owner.library,
        player_game=planted,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )

    with pytest.raises(SwapRefusedByReference) as refused:
        rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    sentence = str(refused.value)
    assert str(owned_library.pk) in sentence
    assert (
        f"Playthrough.player_game: {run.pk} names PlayerGame {planted.pk}" in sentence
    )
    assert "audit_library_ownership" in sentence
    assert "Nothing was swapped" in sentence
    #: The live row survives the refused swap.
    assert PlayerGame.objects.filter(pk=planted.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_a_same_library_reference_says_it_found_no_cross_library_pair(owned_library):
    """23503 has three producers, and only one is this error's subject."""
    planted = plant_tracked_game(owned_library)
    Playthrough.objects.create(
        id=uuid7(),
        library=owned_library,
        player_game=planted,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )

    with pytest.raises(SwapRefusedByReference) as refused:
        rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    sentence = str(refused.value)
    assert refused.value.violations == ()
    assert "no cross-library pair" in sentence
    assert refused.value.constraint_name is not None
    assert refused.value.constraint_name in sentence


@pytest.mark.django_db(transaction=True)
def test_the_refusal_carries_the_staged_diff(owned_library, other_owner):
    """The command has no report to print otherwise."""
    planted = plant_tracked_game(owned_library)
    Playthrough.objects.create(
        id=uuid7(),
        library=other_owner.library,
        player_game=planted,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )

    with pytest.raises(SwapRefusedByReference) as refused:
        rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    reported = {table.table: table.only_live for table in refused.value.tables}
    assert reported["games_playergame"] == 1


@pytest.mark.django_db(transaction=True)
def test_an_integrity_error_of_another_state_is_not_answered(owned_library):
    """Only 23503 becomes this error."""
    from django.db import IntegrityError

    from games.events.retry import sqlstate_of

    error = IntegrityError("no cause, no sqlstate")

    assert sqlstate_of(error) is None
```

Add to the file's imports:

```python
from games.events.rebuild import SwapRefusedByReference
from games.models import Game, PlaythroughKind
from django.utils import timezone
```

merging each into the existing import block it belongs to — `SwapRefusedByReference` into the `from games.events.rebuild import (...)` list, `Game` and `PlaythroughKind` into the `from games.models import (...)` list, and `timezone` beside the other Django imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_projection_rebuild.py -k 'refus or cross_library or another_state' -x" PYTEST_WORKERS=0`
Expected: FAIL with `ImportError: cannot import name 'SwapRefusedByReference'`.

- [ ] **Step 3: Make the diagnostics readers public**

In `games/events/retry.py`, add beside `UNIQUE_VIOLATION`:

```python
FOREIGN_KEY_VIOLATION = "23503"
```

Rename `_sqlstate` to `sqlstate_of` and `_constraint_name` to `constraint_name_of`, keeping their bodies and comments exactly as they are, and update the three call sites inside the module: `is_retryable` (two) and `run_in_transaction`'s log line.

- [ ] **Step 4: Answer 23503 in `swap_in`**

In `games/events/rebuild.py`, add the exception above `swap_in`:

```python
class SwapRefusedByReference(RuntimeError):
    """A foreign key stopped the swap at commit."""

    def __init__(
        self,
        *,
        library_id: uuid.UUID,
        constraint_name: str | None,
        violations: tuple[str, ...],
        tables: tuple[TableDiff, ...],
    ) -> None:
        super().__init__(_refusal_sentence(library_id, constraint_name, violations))
        self.library_id = library_id
        self.constraint_name = constraint_name
        self.violations = violations
        self.tables = tables


def _refusal_sentence(
    library_id: uuid.UUID,
    constraint_name: str | None,
    violations: tuple[str, ...],
) -> str:
    """Two shapes: the pairs, or the reason there are none.

    Three failures raise 23503 here, and only one is a reference across
    libraries. The other two are two projectors in one library
    disagreeing, and a RESTRICT reference to a row outside the
    projections. Naming either of those as cross-library would send an
    operator to an audit that answers zero.
    """
    if not violations:
        named = "an unnamed constraint" if constraint_name is None else constraint_name
        return (
            f"The rebuild of library {library_id} was refused at the swap by "
            f"{named}, and the audit finds no cross-library pair, so the "
            "referenced row is missing for another reason. Nothing was "
            "swapped; the live rows are unchanged."
        )
    listed = "\n".join(f"  {violation}" for violation in violations)
    return (
        f"The rebuild of library {library_id} was refused at the swap. A "
        "projection row in another library names a row this rebuild did not "
        f"reproduce:\n{listed}\nNothing was swapped; the live rows are "
        "unchanged. Run: manage.py audit_library_ownership --all-libraries"
    )
```

Then wrap the body of `swap_in`. Its current signature and body:

```python
def swap_in(
    library: UserLibrary,
    models: Iterable[type[ProjectionModel]],
    replayed_through: int,
) -> None:
    """Put the rebuilt rows in place."""
    with transaction.atomic():
        ...
```

becomes:

```python
def swap_in(
    library: UserLibrary,
    models: Iterable[type[ProjectionModel]],
    replayed_through: int,
    *,
    tables: tuple[TableDiff, ...] = (),
) -> None:
    """Put the rebuilt rows in place.

    The whole block, not the cursor: the foreign keys between projection
    tables are DEFERRABLE INITIALLY DEFERRED, so a violation raises when
    the block commits. Django's _commit() runs inside
    wrap_database_errors, so the chain a state read needs is there.
    StreamSequenceMismatch is a CommandConflict, so the wider block does
    not swallow it.
    """
    try:
        with transaction.atomic():
            stream = lock_stream(library)
            stream.require_sequence(replayed_through)
            with connection.cursor() as cursor:
                for model in models:
                    table = connection.ops.quote_name(model._meta.db_table)
                    columns = ", ".join(
                        connection.ops.quote_name(column)
                        for column in insertable_columns(model)
                    )
                    cursor.execute(_DELETE_LIVE_ROWS.format(table=table), [library.pk])
                    cursor.execute(
                        _INSERT_REBUILT_ROWS.format(
                            table=table,
                            columns=columns,
                            shadow=connection.ops.quote_name(shadow_table_name(model)),
                        ),
                        [library.pk],
                    )
    except IntegrityError as error:
        if sqlstate_of(error) != FOREIGN_KEY_VIOLATION:
            raise
        raise SwapRefusedByReference(
            library_id=library.pk,
            constraint_name=constraint_name_of(error),
            violations=tuple(
                cross_library_violations(AUDITED_PROJECTION_REFERENCES, [library.pk])
            ),
            tables=tables,
        ) from error
```

Add to `games/events/rebuild.py`'s imports:

```python
from django.db import IntegrityError, connection, transaction

from games.events.retry import (
    FOREIGN_KEY_VIOLATION,
    constraint_name_of,
    sqlstate_of,
)
from games.projections import (
    AUDITED_PROJECTION_REFERENCES,
    cross_library_violations,
    projection_models,
)
```

merging `IntegrityError` into the existing `from django.db import connection, transaction` line and `projection_models` into the import Task 1 added.

Finally, pass the staged diffs at the one call site, `rebuild_projections` around line 464:

```python
                swap_in(
                    library,
                    models,
                    staged.replayed.replayed_through,
                    tables=staged.tables,
                )
```

- [ ] **Step 5: Run the tests**

Run: `make test ARGS="tests/test_projection_rebuild.py -x" PYTEST_WORKERS=0`
Expected: PASS, whole file.

- [ ] **Step 6: Run the retry tests, whose helpers were renamed**

Run: `make test ARGS="tests/test_event_retry.py -x"`
Expected: PASS. If a test imports `_sqlstate` or `_constraint_name` by name, update the import — do not re-add the private alias.

- [ ] **Step 7: Commit**

```bash
git add games/events/retry.py games/events/rebuild.py tests/test_projection_rebuild.py
git commit -m "Answer a foreign key that stops the swap

The swap restores exactly the keys its DELETE removed, so it only breaks
a reference when the replay reproduces one key fewer. What the diff
cannot report is the cause: a shadow table copies no foreign key, and
the diff is scoped to one library, so the row on the other side of the
boundary is outside every query it runs.

Three failures raise 23503 here and only one is this subject, so the
sentence has two shapes and the empty one says so.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The rebuild command answers the refusal

**Files:**
- Modify: `games/management/commands/rebuild_projections.py:36-48` (`handle`), `:5-16` (imports)
- Test: `tests/test_projection_rebuild.py` (append)

**Interfaces:**
- Consumes: `games.events.rebuild.SwapRefusedByReference` from Task 4.
- Produces: no new name.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_projection_rebuild.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_the_command_prints_the_diff_and_names_the_pair(owned_library, other_owner):
    """Without the carried tables it would print no diff at all."""
    planted = plant_tracked_game(owned_library)
    run = Playthrough.objects.create(
        id=uuid7(),
        library=other_owner.library,
        player_game=planted,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )
    output = StringIO()
    errors = StringIO()

    with pytest.raises(CommandError, match="refused at the swap"):
        call_command(
            "rebuild_projections",
            str(owned_library.pk),
            stdout=output,
            stderr=errors,
        )

    report = output.getvalue() + errors.getvalue()
    assert "games_playergame: 1 live, 0 rebuilt, 1 only live" in report
    assert f"Playthrough.player_game: {run.pk} names PlayerGame {planted.pk}" in report
    assert "audit_library_ownership" in report
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_projection_rebuild.py -k command_prints_the_diff -x" PYTEST_WORKERS=0`
Expected: FAIL — `SwapRefusedByReference` escapes as itself, not as a `CommandError`.

- [ ] **Step 3: Answer it in the command**

In `games/management/commands/rebuild_projections.py`, extend the `try` in `handle`:

```python
        try:
            report = rebuild_projections(library, mode=mode)
        except UnresolvedReferences as error:
            self._write_reconciliation(error.reconciliation)
            #: Both modes fail. No rebuild repairs this.
            raise CommandError(
                f"The events name {error.reconciliation.unresolved} row(s) that "
                "no longer exist, so nothing was replayed."
            ) from error
        except SwapRefusedByReference as error:
            #: The diff the refusal carries: handle() has no report.
            for table in error.tables:
                self._write_table(table)
            raise CommandError(str(error)) from error
```

Add the import:

```python
from games.events.rebuild import (
    RebuildMode,
    RebuildReport,
    SwapRefusedByReference,
    TableDiff,
    rebuild_projections,
)
```

- [ ] **Step 4: Run the test**

Run: `make test ARGS="tests/test_projection_rebuild.py -x" PYTEST_WORKERS=0`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git add games/management/commands/rebuild_projections.py tests/test_projection_rebuild.py
git commit -m "Print the staged diff beside the refusal

handle() calls _write_report only on return, so a refusal printed the
sentence and no table lines -- the very only_live count the sentence
argues the operator has already seen.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: The docs sweep and the gate

**Files:**
- Modify: `games/models.py:1508-1526` (the `ProjectionModel` docstring)
- Modify: `CLAUDE.md` (the conventions list)
- Test: the whole `make check`

**Interfaces:** none.

- [ ] **Step 1: Correct the `ProjectionModel` docstring**

Its last paragraph currently ends "Nothing in the schema refuses it: `audit_library_ownership` reports it." Replace that sentence with:

```
    Nothing in the schema refuses it. `audit_library_ownership` reports
    it, over the references `games/projections.py` registers, and
    `games.E009` refuses a reference that registry omits.
```

- [ ] **Step 2: Add the convention to CLAUDE.md**

In the "Conventions for AI assistants" list, after the bullet beginning "**Nothing opens a server-side cursor**", append:

```markdown
- **A reference out of a projection is registered** — a foreign key from a
  projection table into a library-scoped model goes in
  `AUDITED_PROJECTION_REFERENCES` in `games/projections.py`, or `games.E009`
  refuses it at `manage.py check`. The registry is what
  `audit_library_ownership` reads, and what the swap's refusal sentence
  reads when a rebuild is stopped by SQLSTATE 23503. Nothing else audits
  such a key: a shadow table copies no foreign key, and the rebuild's diff
  is scoped to one library.
```

- [ ] **Step 3: Update the Playthrough bullet in CLAUDE.md**

In the Models list, the `PlayerGame` bullet says `game` is `RESTRICT`, "so a projection row is never collateral". Append to that clause:

```markdown
; #1017 registers it, so `audit_library_ownership` reports a
  `PlayerGame` naming another library's Game
```

- [ ] **Step 4: Lint the prose**

Run: `make vale`
Expected: 7 warnings, no errors — the unchanged baseline.

- [ ] **Step 5: Run the whole gate**

Run: `make check`
Expected: green, e2e included. This is the gate; a subset does not substitute for it.

- [ ] **Step 6: Commit**

```bash
git add games/models.py CLAUDE.md
git commit -m "Sweep the docs for #1017

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Open the pull request**

```bash
git push -u origin claude/issue-1017-projection-reference-guard
gh pr create --fill --base main
```

The body states: the walk keys on the referenced model carrying a library, not on it being a projection; `PlayerGame.game` is audited for the first time; three failures raise 23503 at the swap and the sentence has two shapes; the issue's "reports green" premise is one step off and the spec records the correction.

---

## Self-Review

**Spec coverage.** Every section maps to a task: the topology module and the walk → Task 1; the completeness check → Task 2; the audit command → Task 3; the swap's answer, the three producers of 23503, and the `retry.py` promotions → Task 4; the command's carried diff → Task 5; the docstring and the conventions → Task 6. The spec's "What the diff can and cannot say" section is argument, not deliverable, and is quoted into Task 4's commit message. The spec's "Reversibility" section needs no task: there is no migration.

**Placeholders.** None. Every code step carries the code.

**Type consistency.** `ProjectionReference` carries `field: models.ForeignKey`, not a `field_name: str` — Task 1 defines it that way and Tasks 2, 3 and 4 all read `reference.field.name`, `.attname`, `.column`, and `.remote_field.on_delete`. `cross_library_violations` returns `list[str]` in Task 1 and is wrapped in `tuple(...)` at the one place that stores it, Task 4's exception. `swap_in`'s new `tables` parameter is keyword-only in Task 4 and passed by keyword in the same task's call-site edit and read in Task 5.

**One risk the executor must confirm, not assume.** Task 3's `test_a_tracked_game_from_another_library_is_reported` moves a `PlayerGame` across libraries with `update()`. `PlayerGame` carries `UniqueConstraint(fields=("library", "game"))`, and the owner's library holds no row for that Game, so the move does not collide. If it does, plant the row with `PlayerGame.objects.create()` under a fresh Game instead.
