# CAT-02 Legacy Game Catalog Writes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the existing Add/Edit Game flow through a transactional catalog writer that creates or updates one explicit default Edition/Release graph while keeping legacy columns synchronized.

**Architecture:** Add explicit default markers with partial uniqueness to the passive #649 hierarchy, then implement one row-locking `save_private_game` service over canonical temporal/catalog values. Keep legacy integer-year and form knowledge in a separate compatibility adapter, and change only the two current Game view save call sites.

**Tech Stack:** Python 3.14, Django 6 ORM/forms/views/migrations, PostgreSQL, pytest-django, pytest-xdist, Make.

**Spec:** `docs/superpowers/specs/2026-08-20-issue-888-legacy-game-catalog-writes-design.md`

## Global Constraints

- Treat issue #888, the overhaul charter, the catalog wave specification, and the delivered #649 hierarchy as authoritative.
- Preserve the current Add/Edit UI, validation sequence, submit actions, origins, and redirect targets.
- Create exactly one explicitly default Edition and Release for a supported legacy Game write; never select a child by count, UUID order, name, year, or Platform.
- Keep default flags internal (`editable=False`) and `False` by default so non-default #649 multiplicity remains valid.
- Keep `save_private_game` free of legacy integer-year field names; it consumes canonical `TemporalValue | None` and exact `Platform | None` values.
- Keep legacy mapping in `save_legacy_game_form`; do not override `Game.save`, use signals, or override `GameForm.save`.
- Preserve NULL Platform as explicitly unspecified and cleared/unknown years as SQL NULL; never infer either value.
- Make the Game compatibility write and all canonical graph writes one transaction, and prove rollback from fresh database state.
- Do not backfill existing Games; #650 owns historical graph creation and reconciliation.
- Do not add multi-edition UI, shared-record mutation, IGDB behavior, matching, merges, external references, tombstones, redirects, Catalogue pages, new reads, filters, APIs, statistics, frontend code, or unrelated refactors.
- Use `make check` with the Makefile's default `PYTEST_WORKERS`; do not set normal verification to serial mode.
- Stop and return to the design gate if actual scope crosses three independent runtime subsystems, 40 files, or 2,000 non-generated changed lines.

## File structure

- Modify `games/models.py`: add internal default markers and partial unique constraints to Edition and Release.
- Create `games/migrations/0019_catalog_write_defaults.py`: add the two flags and two constraints without data backfill.
- Create `games/catalog_writes.py`: own canonical private Game/default-graph persistence and transaction boundaries.
- Create `games/catalog_compat.py`: translate the current GameForm's legacy values to the durable service.
- Modify `games/views/game.py`: use the adapter at the add/edit save call sites only.
- Create `tests/test_catalog_writes.py`: pin default selection, canonical persistence, idempotency, isolation, and rollback.
- Create `tests/test_catalog_write_views.py`: pin real form/view synchronization and cleared values.
- Modify `tests/test_catalog_hierarchy_migration.py`: prove forward/reverse schema behavior and pre-existing child preservation.
- Remove this plan and its paired issue design only after implementation and all verification pass; preserve the planning commit in the pushed branch/PR review record.

## Planning gate checkpoint

Commit this plan and its paired design, then stop for explicit approval. No Task
1 step may start before approval.

```bash
git add docs/superpowers/specs/2026-08-20-issue-888-legacy-game-catalog-writes-design.md docs/superpowers/plans/2026-08-20-issue-888-legacy-game-catalog-writes.md
git commit -m "docs: plan legacy Game catalog writes"
```

---

### Task 1: Define explicit default identities in schema

**Files:**
- Modify: `games/models.py`
- Create: `games/migrations/0019_catalog_write_defaults.py`
- Create: `tests/test_catalog_writes.py`
- Modify: `tests/test_catalog_hierarchy_migration.py`

**Interfaces:**
- Produces: `Edition.is_default: bool`, internal and false by default.
- Produces: `Release.is_default: bool`, internal and false by default.
- Produces: database constraints `unique_default_edition_per_game` and `unique_default_release_per_edition`.
- Preserves: arbitrary non-default Edition/Release multiplicity from #649.

- [ ] **Step 1: Write model tests for one explicit default and unrestricted non-default children**

Create `tests/test_catalog_writes.py` with the imports and first test:

```python
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from games.models import Edition, Game, Platform, Release
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


def test_default_markers_allow_one_default_and_multiple_nondefaults(owned_library):
    game = Game.objects.create(library=owned_library, name="Defaults")
    default_edition = Edition.objects.create(game=game, is_default=True)
    Edition.objects.create(game=game)
    Edition.objects.create(game=game)
    Release.objects.create(edition=default_edition, is_default=True)
    Release.objects.create(edition=default_edition)
    Release.objects.create(edition=default_edition)

    assert game.editions.filter(is_default=True).get() == default_edition
    assert default_edition.releases.filter(is_default=True).count() == 1
    assert Edition._meta.get_field("is_default").editable is False
    assert Release._meta.get_field("is_default").editable is False

    with pytest.raises(IntegrityError), transaction.atomic():
        Edition.objects.create(game=game, is_default=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        Release.objects.create(edition=default_edition, is_default=True)
```

- [ ] **Step 2: Run the model test to verify it fails**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_writes.py::test_default_markers_allow_one_default_and_multiple_nondefaults -q
```

Expected: FAIL because `Edition` and `Release` do not accept `is_default`.

- [ ] **Step 3: Add the model fields and conditional constraints**

In `games/models.py`, insert this `Meta` class immediately inside `Edition`,
then add `is_default` after the existing `game` field:

```python
class Meta:
    constraints = (
        models.UniqueConstraint(
            fields=("game",),
            condition=Q(is_default=True),
            name="unique_default_edition_per_game",
        ),
    )

is_default = models.BooleanField(default=False, editable=False)
```

Insert this `Meta` class immediately inside `Release`, then add `is_default`
after the existing `edition` field:

```python
class Meta:
    constraints = (
        models.UniqueConstraint(
            fields=("edition",),
            condition=Q(is_default=True),
            name="unique_default_release_per_edition",
        ),
    )

is_default = models.BooleanField(default=False, editable=False)
```

Generate the migration through the project environment:

```bash
direnv exec . uv run --frozen python manage.py makemigrations games --name catalog_write_defaults
```

Inspect `games/migrations/0019_catalog_write_defaults.py` and keep only two
`AddField` and two `AddConstraint` operations. There must be no `RunPython` or
child-row update.

- [ ] **Step 4: Run the model test to verify it passes**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_writes.py::test_default_markers_allow_one_default_and_multiple_nondefaults -q
```

Expected: PASS.

- [ ] **Step 5: Add a migration test for pre-existing unmarked children and reversibility**

Append to `tests/test_catalog_hierarchy_migration.py`, following that file's
existing `MigrationExecutor`/leaf-restoration pattern:

```python
BEFORE_CATALOG_WRITES = ("games", "0018_catalog_hierarchy")
WITH_CATALOG_WRITES = ("games", "0019_catalog_write_defaults")


@pytest.fixture
def catalog_write_migration_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_CATALOG_WRITES])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_CATALOG_WRITES]).apps
    yield old_apps, leaf_nodes
    MigrationExecutor(connection).migrate(leaf_nodes)


def test_catalog_write_migration_preserves_children_as_nondefaults(
    catalog_write_migration_harness,
):
    apps, _ = catalog_write_migration_harness
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")
    user = User.objects.create(username="catalog-writer-migration")
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    game = Game.objects.create(library_id=library.pk, name="Existing")
    edition = Edition.objects.create(game_id=game.pk)
    release = Release.objects.create(edition_id=edition.pk)

    executor = MigrationExecutor(connection)
    executor.migrate([WITH_CATALOG_WRITES])
    new_apps = executor.loader.project_state([WITH_CATALOG_WRITES]).apps
    NewEdition = new_apps.get_model("games", "Edition")
    NewRelease = new_apps.get_model("games", "Release")
    assert NewEdition.objects.get(pk=edition.pk).is_default is False
    assert NewRelease.objects.get(pk=release.pk).is_default is False

    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_CATALOG_WRITES])
    restored_apps = executor.loader.project_state([BEFORE_CATALOG_WRITES]).apps
    assert restored_apps.get_model("games", "Edition").objects.filter(pk=edition.pk).exists()
    assert restored_apps.get_model("games", "Release").objects.filter(pk=release.pk).exists()
```

Keep imports (`call_command`, `connection`, `MigrationExecutor`, `timezone`)
shared with the existing file rather than duplicating them.

- [ ] **Step 6: Run schema-focused tests and migration checks**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_writes.py::test_default_markers_allow_one_default_and_multiple_nondefaults tests/test_catalog_hierarchy_migration.py -q
direnv exec . uv run --frozen python manage.py makemigrations --check
```

Expected: PASS and “No changes detected”.

- [ ] **Step 7: Commit the default-graph contract**

```bash
git add games/models.py games/migrations/0019_catalog_write_defaults.py tests/test_catalog_writes.py tests/test_catalog_hierarchy_migration.py
git commit -m "feat: identify default catalog graphs"
```

---

### Task 2: Implement the durable transactional catalog writer

**Files:**
- Create: `games/catalog_writes.py`
- Modify: `tests/test_catalog_writes.py`

**Interfaces:**
- Consumes: an unsaved or existing private `Game`, canonical `TemporalValue | None` values, and exact `Platform | None`.
- Produces: `PrivateGameGraph(game: Game, edition: Edition, release: Release)`.
- Produces: `save_private_game(*, game, original_release_date, release_date, platform) -> PrivateGameGraph`.
- Guarantees: one transaction, Game-row serialization for existing graphs, explicit default lookup/creation, exact NULL preservation, and stable default UUIDs on repeat saves.

- [ ] **Step 1: Write the failing create/idempotency tests**

Append to `tests/test_catalog_writes.py`:

```python
from games.catalog_writes import save_private_game


def test_save_private_game_creates_one_default_graph(owned_library):
    platform = Platform.objects.create(name="PC")
    graph = save_private_game(
        game=Game(library=owned_library, name="Portal"),
        original_release_date=TemporalValue.from_year(2007),
        release_date=TemporalValue.from_year(2008),
        platform=platform,
    )

    graph.game.refresh_from_db()
    graph.release.refresh_from_db()
    assert graph.edition == graph.game.editions.get(is_default=True)
    assert graph.release == graph.edition.releases.get(is_default=True)
    assert graph.game.original_release_date == TemporalValue.from_year(2007)
    assert graph.release.release_date == TemporalValue.from_year(2008)
    assert graph.release.platform == platform
    assert {graph.game.pk.version, graph.edition.pk.version, graph.release.pk.version} == {7}

    repeated = save_private_game(
        game=graph.game,
        original_release_date=TemporalValue.from_year(2007),
        release_date=TemporalValue.from_year(2008),
        platform=platform,
    )
    assert repeated.edition.pk == graph.edition.pk
    assert repeated.release.pk == graph.release.pk
    assert Edition.objects.filter(game=graph.game).count() == 1
    assert Release.objects.filter(edition=graph.edition).count() == 1
```

- [ ] **Step 2: Run the test to verify the service is missing**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_writes.py::test_save_private_game_creates_one_default_graph -q
```

Expected: collection/import FAIL because `games.catalog_writes` does not exist.

- [ ] **Step 3: Implement the minimal service and return type**

Create `games/catalog_writes.py`:

```python
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from games.models import Edition, Game, Platform, Release
from timetracker.temporal import TemporalValue


@dataclass(frozen=True, slots=True)
class PrivateGameGraph:
    game: Game
    edition: Edition
    release: Release


def _validate_platform(game: Game, platform: Platform | None) -> None:
    if game.library_id is None:
        raise ValidationError("A private Game requires a library owner.")
    if platform is not None and platform.library_id not in (None, game.library_id):
        raise ValidationError("Platform belongs to another library.")


@transaction.atomic
def save_private_game(
    *,
    game: Game,
    original_release_date: TemporalValue | None,
    release_date: TemporalValue | None,
    platform: Platform | None,
) -> PrivateGameGraph:
    _validate_platform(game, platform)
    if not game._state.adding:
        Game.objects.select_for_update().get(pk=game.pk)

    game.original_release_date = original_release_date
    game.save()
    edition, _ = Edition.objects.select_for_update().get_or_create(
        game=game,
        is_default=True,
    )
    release, _ = Release.objects.select_for_update().get_or_create(
        edition=edition,
        is_default=True,
    )
    release.platform = platform
    release.release_date = release_date
    release.save(update_fields=("platform", "release_date"))
    return PrivateGameGraph(game=game, edition=edition, release=release)
```

The service returns the persisted model instances without refreshing generated
columns. Tests that inspect generated projections explicitly refresh their own
instances; the service does not add presentation-only queries.

- [ ] **Step 4: Run the create/idempotency test to verify it passes**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_writes.py::test_save_private_game_creates_one_default_graph -q
```

Expected: PASS.

- [ ] **Step 5: Write update, clearing, and unmarked-child tests**

Append:

```python
def test_save_private_game_updates_and_clears_the_same_default_graph(owned_library):
    first_platform = Platform.objects.create(name="First")
    second_platform = Platform.objects.create(name="Second")
    graph = save_private_game(
        game=Game(
            library=owned_library,
            name="Before",
            original_year_released=1998,
            year_released=1999,
            platform=first_platform,
        ),
        original_release_date=TemporalValue.from_year(1998),
        release_date=TemporalValue.from_year(1999),
        platform=first_platform,
    )
    edition_id, release_id = graph.edition.pk, graph.release.pk

    graph.game.name = "After"
    graph.game.original_year_released = None
    graph.game.year_released = None
    graph.game.platform = None
    updated = save_private_game(
        game=graph.game,
        original_release_date=None,
        release_date=None,
        platform=None,
    )
    updated.game.refresh_from_db()
    updated.release.refresh_from_db()

    assert (updated.edition.pk, updated.release.pk) == (edition_id, release_id)
    assert updated.game.name == "After"
    assert updated.game.original_release_date is None
    assert updated.release.release_date is None
    assert updated.release.platform is None
    assert (
        updated.game.original_year_released,
        updated.game.year_released,
        updated.game.platform,
    ) == (None, None, None)


def test_save_private_game_does_not_adopt_unmarked_children(owned_library):
    game = Game.objects.create(library=owned_library, name="Unmarked")
    unmarked_edition = Edition.objects.create(game=game)
    unmarked_release = Release.objects.create(edition=unmarked_edition)

    graph = save_private_game(
        game=game,
        original_release_date=None,
        release_date=None,
        platform=None,
    )

    assert graph.edition.pk != unmarked_edition.pk
    assert graph.release.pk != unmarked_release.pk
    assert game.editions.filter(is_default=True).count() == 1
    assert Edition.objects.filter(game=game).count() == 2
```

- [ ] **Step 6: Run the focused update tests**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_writes.py -q
```

Expected: PASS.

- [ ] **Step 7: Write isolation and forced-rollback tests**

Append tests using fresh database reads after exceptions:

```python
def test_save_private_game_rejects_a_foreign_private_platform(
    owned_library, django_user_model
):
    other = django_user_model.objects.create_user(username="other-catalog-owner")
    foreign = Platform.objects.create(library=other.library, name="Foreign")
    game = Game(library=owned_library, name="Rejected")

    with pytest.raises(ValidationError, match="another library"):
        save_private_game(
            game=game,
            original_release_date=None,
            release_date=None,
            platform=foreign,
        )
    assert not Game.objects.filter(name="Rejected").exists()


def test_save_private_game_rolls_back_new_game_when_release_write_fails(
    owned_library, monkeypatch
):
    def fail_save(*args, **kwargs):
        raise RuntimeError("forced release failure")

    monkeypatch.setattr(Release, "save", fail_save)
    with pytest.raises(RuntimeError, match="forced release failure"):
        save_private_game(
            game=Game(
                library=owned_library,
                name="Rolled back",
                year_released=2001,
            ),
            original_release_date=None,
            release_date=TemporalValue.from_year(2001),
            platform=None,
        )

    assert not Game.objects.filter(name="Rolled back").exists()
    assert Edition.objects.count() == 0
    assert Release.objects.count() == 0
```

Append the edit rollback variant:

```python
def test_save_private_game_rolls_back_existing_compatibility_and_catalog_fields(
    owned_library, monkeypatch
):
    graph = save_private_game(
        game=Game(
            library=owned_library,
            name="Before failure",
            original_year_released=1998,
            year_released=1999,
        ),
        original_release_date=TemporalValue.from_year(1998),
        release_date=TemporalValue.from_year(1999),
        platform=None,
    )
    game_id, edition_id, release_id = (
        graph.game.pk,
        graph.edition.pk,
        graph.release.pk,
    )
    original_release_save = Release.save

    def fail_existing_release(instance, *args, **kwargs):
        if instance.pk == release_id:
            raise RuntimeError("forced release failure")
        return original_release_save(instance, *args, **kwargs)

    monkeypatch.setattr(Release, "save", fail_existing_release)
    graph.game.name = "After failure"
    graph.game.original_year_released = None
    graph.game.year_released = None
    with pytest.raises(RuntimeError, match="forced release failure"):
        save_private_game(
            game=graph.game,
            original_release_date=None,
            release_date=None,
            platform=None,
        )

    stored_game = Game.objects.get(pk=game_id)
    stored_release = Release.objects.get(pk=release_id)
    assert stored_game.name == "Before failure"
    assert stored_game.original_year_released == 1998
    assert stored_game.year_released == 1999
    assert stored_game.original_release_date == TemporalValue.from_year(1998)
    assert stored_release.release_date == TemporalValue.from_year(1999)
    assert stored_game.editions.get(is_default=True).pk == edition_id
    assert stored_release.pk == release_id
```

- [ ] **Step 8: Run all catalog writer tests**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_writes.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit the durable writer**

```bash
git add games/catalog_writes.py tests/test_catalog_writes.py
git commit -m "feat: add transactional private catalog writer"
```

---

### Task 3: Route the legacy Game form through the compatibility adapter

**Files:**
- Create: `games/catalog_compat.py`
- Modify: `games/views/game.py`
- Create: `tests/test_catalog_write_views.py`
- Test: `tests/test_returns_views.py`
- Test: `tests/test_rendered_pages.py`
- Test: `tests/test_library_form_isolation.py`

**Interfaces:**
- Consumes: one already validated `GameForm`.
- Produces: `save_legacy_game_form(form: GameForm) -> Game`.
- Maps: `original_year_released` and `year_released` to year-precision temporal values; NULL to unknown; current Platform exactly to default Release Platform.
- Preserves: current form errors and all add/edit redirects/actions.

- [ ] **Step 1: Write a failing add-view synchronization test**

Create `tests/test_catalog_write_views.py`:

```python
import pytest
from django.urls import reverse

from games.models import Game, Platform
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


def game_payload(**overrides):
    payload = {
        "name": "Legacy form game",
        "sort_name": "Form game, Legacy",
        "platform": "",
        "year_released": "2002",
        "original_year_released": "2001",
        "status": Game.Status.PLAYED,
        "mastered": "on",
        "wikidata": "Q123",
    }
    payload.update(overrides)
    return payload


def test_add_game_writes_legacy_and_default_catalog_graph(
    client, owned_user, owned_library
):
    platform = Platform.objects.create(name="PC")
    client.force_login(owned_user)
    response = client.post(
        reverse("games:add_game"),
        game_payload(platform=str(platform.pk)),
    )

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("games:list_games")
    game = Game.objects.get(name="Legacy form game")
    edition = game.editions.get(is_default=True)
    release = edition.releases.get(is_default=True)
    assert game.library == owned_library
    assert game.original_release_date == TemporalValue.from_year(2001)
    assert release.release_date == TemporalValue.from_year(2002)
    assert release.platform == platform
    assert (game.original_year_released, game.year_released, game.platform) == (
        2001,
        2002,
        platform,
    )
    assert (game.sort_name, game.status, game.mastered, game.wikidata) == (
        "Form game, Legacy",
        Game.Status.PLAYED,
        True,
        "Q123",
    )
```

- [ ] **Step 2: Run it to verify the old view creates no graph**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_write_views.py::test_add_game_writes_legacy_and_default_catalog_graph -q
```

Expected: FAIL when no default Edition exists.

- [ ] **Step 3: Implement the compatibility adapter**

Create `games/catalog_compat.py`:

```python
from typing import TYPE_CHECKING

from games.catalog_writes import save_private_game
from games.models import Game
from timetracker.temporal import TemporalValue

if TYPE_CHECKING:
    from games.forms import GameForm


def _year_value(year: int | None) -> TemporalValue | None:
    return TemporalValue.from_year(year) if year is not None else None


def save_legacy_game_form(form: "GameForm") -> Game:
    game = form.save(commit=False)
    return save_private_game(
        game=game,
        original_release_date=_year_value(game.original_year_released),
        release_date=_year_value(game.year_released),
        platform=game.platform,
    ).game
```

The type-only import avoids a runtime forms/service cycle.

- [ ] **Step 4: Change only the two Game view save call sites**

In `games/views/game.py`, import `save_legacy_game_form`. Replace:

```python
game = form.save()
```

with:

```python
game = save_legacy_game_form(form)
```

and replace the edit path's bare `form.save()` with:

```python
save_legacy_game_form(form)
```

Do not change surrounding redirect or rendering code.

- [ ] **Step 5: Run the add-view test to verify it passes**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_write_views.py::test_add_game_writes_legacy_and_default_catalog_graph -q
```

Expected: PASS.

- [ ] **Step 6: Write the edit-and-clear test**

Append:

```python
def test_edit_game_updates_then_clears_legacy_and_canonical_values(
    client, owned_user, owned_library
):
    first = Platform.objects.create(name="First")
    second = Platform.objects.create(name="Second")
    client.force_login(owned_user)
    client.post(
        reverse("games:add_game"),
        game_payload(name="Editable", platform=str(first.pk)),
    )
    game = Game.objects.get(name="Editable")
    edition_id = game.editions.get(is_default=True).pk
    release_id = game.editions.get(is_default=True).releases.get(is_default=True).pk

    response = client.post(
        reverse("games:edit_game", args=[game.pk]),
        game_payload(
            name="Edited",
            platform=str(second.pk),
            original_year_released="2010",
            year_released="2011",
        ),
    )
    assert response.status_code == 302
    game.refresh_from_db()
    release = game.editions.get(is_default=True).releases.get(is_default=True)
    assert (game.editions.get(is_default=True).pk, release.pk) == (
        edition_id,
        release_id,
    )
    assert game.original_release_date == TemporalValue.from_year(2010)
    assert release.release_date == TemporalValue.from_year(2011)
    assert release.platform == second

    client.post(
        reverse("games:edit_game", args=[game.pk]),
        game_payload(
            name="Edited",
            platform="",
            original_year_released="",
            year_released="",
        ),
    )
    game.refresh_from_db()
    release.refresh_from_db()
    assert (game.original_year_released, game.year_released, game.platform) == (
        None,
        None,
        None,
    )
    assert game.original_release_date is None
    assert release.release_date is None
    assert release.platform is None
    assert Edition.objects.filter(game=game).count() == 1
    assert Release.objects.filter(edition_id=edition_id).count() == 1
```

Add `Edition` and `Release` to the imports.

- [ ] **Step 7: Run adapter, redirect, and isolation coverage**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_write_views.py tests/test_returns_views.py tests/test_rendered_pages.py tests/test_library_form_isolation.py -q
```

Expected: PASS. This exercises fallback/origin/session redirects, the purchase
submit control, invalid foreign Platforms, rendering, and the new graph sync.

- [ ] **Step 8: Commit the compatibility cutover**

```bash
git add games/catalog_compat.py games/views/game.py tests/test_catalog_write_views.py
git commit -m "feat: synchronize legacy Game form with catalog"
```

---

### Task 4: Complete verification, scope audit, and planning-artifact cleanup

**Files:**
- Delete after all gates pass: `docs/superpowers/specs/2026-08-20-issue-888-legacy-game-catalog-writes-design.md`
- Delete after all gates pass: `docs/superpowers/plans/2026-08-20-issue-888-legacy-game-catalog-writes.md`
- Review: every file changed from `origin/codex/catalog-wave`

**Interfaces:**
- Consumes: all implementation tasks above.
- Produces: one verified issue-only branch ready for a PR to `codex/catalog-wave`.

- [ ] **Step 1: Run focused catalog verification**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_writes.py tests/test_catalog_write_views.py tests/test_catalog_hierarchy.py tests/test_catalog_hierarchy_migration.py tests/test_returns_views.py tests/test_library_form_isolation.py -q
```

Expected: PASS with default pytest-xdist behavior from project configuration.

- [ ] **Step 2: Verify migration state and diff whitespace**

Run:

```bash
direnv exec . uv run --frozen python manage.py makemigrations --check
git diff --check origin/codex/catalog-wave...HEAD
```

Expected: “No changes detected” and no diff-check output.

- [ ] **Step 3: Run the required full gate with default workers**

Run exactly:

```bash
direnv exec . make check
```

Expected: exit 0. Do not set `PYTEST_WORKERS`; retain the Makefile default.

- [ ] **Step 4: Audit issue-only scope and thresholds**

Run:

```bash
git diff --stat origin/codex/catalog-wave...HEAD
git diff --numstat origin/codex/catalog-wave...HEAD
git status --short
```

Confirm no unrelated files changed, fewer than 40 implementation/test files,
fewer than 2,000 non-generated changed lines, and no third runtime subsystem.

- [ ] **Step 5: Remove planning artifacts only after green verification**

Delete the paired design and plan with `apply_patch`, then commit their removal:

```bash
git add docs/superpowers/specs/2026-08-20-issue-888-legacy-game-catalog-writes-design.md docs/superpowers/plans/2026-08-20-issue-888-legacy-game-catalog-writes.md
git commit -m "chore: remove catalog write planning artifacts"
```

The planning commit remains visible in the branch/PR commit range even though
the final target-tree diff contains implementation only.

- [ ] **Step 6: Re-run final lightweight integrity checks**

Run:

```bash
git diff --check origin/codex/catalog-wave...HEAD
git status --short --branch
```

Expected: no whitespace errors and a clean issue branch.

- [ ] **Step 7: Push and open the requested PR**

Push `codex/issue-888-legacy-game-catalog-writes` and open a GitHub PR targeting
`codex/catalog-wave`. The PR body must summarize the default-graph contract,
durable writer, compatibility adapter, focused tests, full `make check` result,
scope totals, and include `Closes #888`.
