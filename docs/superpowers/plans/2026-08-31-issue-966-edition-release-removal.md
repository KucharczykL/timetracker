# Remove one Edition or one Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `Edition` and `Release` a `removed_at` of their own, compose it with
the marks of their ancestors, and register `catalog.release` so the retention guard
protects a Release from the first day one can be named.

**Architecture:** Additive only. Two nullable columns and two partial indexes in one
migration; `alive()` on each child queryset reads its own mark plus every ancestor's;
both models join `REMOVABLE_MODELS` and extend `ReferencedRow`; one new `REQUIRED`
reference kind, `catalog.release`. Nothing removes either row yet — #967 owns the
verbs, #969 owns the screens.

**Tech Stack:** Django 6 + PostgreSQL 18, Python 3.14, pytest (pytest-xdist), ruff,
mypy, vale.

**Spec:** `docs/superpowers/specs/2026-08-30-issue-966-edition-release-removal-design.md`
(issue: https://github.com/KucharczykL/timetracker/issues/966)

## Global Constraints

- **Everything through `make`.** Never `uv run pytest` / `pnpm` directly. Iterate with
  `make test ARGS="…"` and `make check-fast`; the gate is the full `make check`.
- **`PYTEST_WORKERS=0`** when debugging a failure — parallel output interleaves.
- **Nothing destroys a record.** `remove()`/`restore()` from `games/removal.py`; never
  `instance.delete()` in application code.
- **One act, one verb.** The act is remove, the column is `removed_at`. `make vale`
  fails on `archive`/`tombstone` next to a record noun, and on `fold` next to the
  domain. This holds for **code comments and docstrings**, not identifiers.
- **Comments are short** — roughly seven words, `#:` for a field or constant note.
- **Complete words in identifiers** — `edition` not `ed`, `release` not `rel`.
- **Name compound types** — a `TypedDict`/`NamedTuple`/alias, not a repeated
  structural annotation.
- **A commit message is a sentence in the imperative**, no `feat:`/`fix:` prefix, and
  ends with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **This child adds no behaviour.** No write service, no screen, no route, no form, no
  rule about which row may be removed. A default Edition or Release is removable here
  as far as this code is concerned; #967 states when a writer may.
- **`make format` reformats Python inside Markdown fences.** Snippets in this document
  that are not a complete top-level `def`/`class` use a `text` fence on purpose. Do
  not change a fence to `python` while implementing.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `games/models.py` | the two columns, the two partial indexes, `alive()` on both child querysets, `ReferencedRow` as their base | 1, 2, 4 |
| `games/migrations/0039_removable_editions_and_releases.py` | the columns and the indexes, forward and back | 1 |
| `games/removal.py` | both models in `REMOVABLE_MODELS` | 3 |
| `games/events/references.py` | `_capture_release` and the `catalog.release` registration | 4 |
| `games/retention.py` | the guard tolerates a model no kind captures | 4 |
| `games/signals.py` | the `pre_delete` backstop covers `Release` | 4 |
| `tests/test_catalog_hierarchy.py` | the columns and the indexes are declared | 1 |
| `tests/test_removed_rows.py` | what a removed child does to the reads | 2 |
| `tests/test_removable_models.py` | the builders the registry demands | 3 |
| `tests/test_event_references.py` | what a Release reference records | 4 |
| `tests/test_retention.py` | destruction refused, resolution after removal, purge | 4 |
| `docs/event-retention.md`, `docs/event-references.md`, `CLAUDE.md` | the two pages that state the old rule | 5 |

---

## Task 1: The two columns and the two indexes

**Files:**
- Modify: `games/models.py` (`Edition` at ~477, `Release` at ~513)
- Create: `games/migrations/0039_removable_editions_and_releases.py`
- Test: `tests/test_catalog_hierarchy.py` (append at the end)

**Interfaces:**
- Consumes: nothing.
- Produces: `Edition.removed_at` and `Release.removed_at`, both
  `DateTimeField(null=True, blank=True, default=None, editable=False)`; the index
  names `live_edition_per_game_idx` and `live_release_per_edition_idx`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catalog_hierarchy.py`:

```python
def test_a_catalog_child_holds_a_mark_of_its_own():
    """#967 removes one of many; the mark is where it lands."""
    for model in (Edition, Release):
        field = model._meta.get_field("removed_at")
        assert (field.null, field.blank, field.default, field.editable) == (
            True,
            True,
            None,
            False,
        )
```

```python
def test_a_catalog_child_indexes_the_live_children_of_one_parent():
    """A list reads one parent's live children, and nothing else."""
    edition_index = Edition._meta.indexes[0]
    release_index = Release._meta.indexes[0]

    assert (edition_index.fields, edition_index.condition) == (
        ["game"],
        models.Q(removed_at__isnull=True),
    )
    assert (release_index.fields, release_index.condition) == (
        ["edition"],
        models.Q(removed_at__isnull=True),
    )
```

`models` is already imported in that file (`from django.db import IntegrityError,
models, transaction`).

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_catalog_hierarchy.py -k catalog_child -x"`
Expected: FAIL — `FieldDoesNotExist: Edition has no field named 'removed_at'`.

- [ ] **Step 3: Add the column and the index to `Edition`**

`Edition` is short enough to replace whole. In `games/models.py`, replace the class
body with this (the `EditionQuerySet` above it is untouched in this task):

```python
class Edition(models.Model):
    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("game",),
                condition=Q(is_default=True),
                name="unique_default_edition_per_game",
            ),
        )
        indexes = (
            #: The live Editions of one Game.
            models.Index(
                fields=("game",),
                condition=Q(removed_at__isnull=True),
                name="live_edition_per_game_idx",
            ),
        )

    id = UUIDv7Field(primary_key=True, editable=False)
    objects = EditionQuerySet.as_manager()
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="editions",
    )
    is_default = models.BooleanField(default=False, editable=False)
    #: Set instead of destroying the row.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )
```

- [ ] **Step 4: Add the same two to `Release`**

`Release` carries fourteen generated columns, so edit it in place rather than
retyping it. Give its `Meta` an `indexes` tuple beside the existing `constraints`:

```text
        indexes = (
            #: The live Releases of one Edition.
            models.Index(
                fields=("edition",),
                condition=Q(removed_at__isnull=True),
                name="live_release_per_edition_idx",
            ),
        )
```

and add the column immediately after `release_date_end_qualifier`, before `def
clean(self)`:

```text
    #: Set instead of destroying the row.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )
```

- [ ] **Step 5: Generate the migration**

Run: `make makemigrations`

The target passes no `ARGS` (and must not gain any — `make migrate` depends on it, so
`ARGS="games 0038…"` would reach `makemigrations` as an app label). Django writes an
auto-named file. Rename it:

```bash
git mv games/migrations/00*_edition_removed_at*.py \
       games/migrations/0039_removable_editions_and_releases.py
```

No other migration depends on it yet, so the file name is the only reference.

- [ ] **Step 6: Read the migration back**

Open it and confirm it says exactly this, with the dependency on
`0038_temporal_qualifiers`:

```text
        migrations.AddField(
            model_name="edition",
            name="removed_at",
            field=models.DateTimeField(
                blank=True, default=None, editable=False, null=True
            ),
        ),
        migrations.AddField(
            model_name="release",
            name="removed_at",
            field=models.DateTimeField(
                blank=True, default=None, editable=False, null=True
            ),
        ),
        migrations.AddIndex(
            model_name="edition",
            index=models.Index(
                condition=models.Q(("removed_at__isnull", True)),
                fields=["game"],
                name="live_edition_per_game_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="release",
            index=models.Index(
                condition=models.Q(("removed_at__isnull", True)),
                fields=["edition"],
                name="live_release_per_edition_idx",
            ),
        ),
```

Four operations, in any order. Anything else in the file means a model edit went
astray — fix the model, delete the migration, and generate it again.

- [ ] **Step 7: Apply it, reverse it, apply it again**

```bash
make migrate
make migrate ARGS="games 0038_temporal_qualifiers"
make migrate
```

Expected: three clean runs. The middle one proves the migration reverses, which the
spec asks for; `AddField` and `AddIndex` both reverse on their own.

- [ ] **Step 8: Run the tests**

Run: `make test ARGS="tests/test_catalog_hierarchy.py -x"`
Expected: PASS, the whole file — nothing else in it reads these two models' columns.

- [ ] **Step 9: Confirm no drift**

Run: `make check-migrations`
Expected: "No changes detected".

- [ ] **Step 10: Commit**

```bash
git add games/models.py games/migrations/0039_removable_editions_and_releases.py \
        tests/test_catalog_hierarchy.py
git commit -m "$(cat <<'EOF'
Give an Edition and a Release a mark of their own

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: A row is visible when no ancestor is removed

**Files:**
- Modify: `games/models.py` (`RemovableMixin` ~57, `EditionQuerySet` ~461,
  `ReleaseQuerySet` ~497)
- Test: `tests/test_removed_rows.py` (the section at line 97)

**Interfaces:**
- Consumes: `Edition.removed_at`, `Release.removed_at` (Task 1).
- Produces: `Edition.objects.alive()` reads two marks (its own, its Game's);
  `Release.objects.alive()` reads three (its own, its Edition's, its Game's).
  `for_library(library)` and `visible_to(library)` on both call `.alive()`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_removed_rows.py`, add a restoring helper beside `remove_row` (the
module sets the column by hand on purpose — `games.removal` does not accept these two
models until Task 3):

```python
def restore_row(instance):
    type(instance).objects.filter(pk=instance.pk).update(removed_at=None)
    instance.refresh_from_db()
    return instance
```

```python
def make_graph(library, name="Baldur's Gate 3"):
    game = make_game(library, name=name)
    edition = Edition.objects.create(game=game, is_default=True)
    release = Release.objects.create(edition=edition, is_default=True)
    return game, edition, release
```

Replace the section banner at line 97 —
`# --- Edition and Release inherit it, having no column of their own -----------`
— with:

```text
# --- a child holds its own mark, under parents that hold theirs --------------
```

Keep `test_the_editions_of_a_removed_game_leave_with_it` exactly as it is: a removed
Game must still hide both children. Add these below it:

```python
def test_a_removed_edition_takes_its_releases_with_it(owned_library):
    game, edition, release = make_graph(owned_library)

    remove_row(edition)

    assert not Edition.objects.for_library(owned_library).exists()
    assert not Release.objects.for_library(owned_library).exists()
    assert not Release.objects.visible_to(owned_library).exists()
    assert Game.objects.for_library(owned_library).get() == game
    assert Release.objects.filter(pk=release.pk).exists()
```

```python
def test_a_removed_release_leaves_its_edition_where_it_was(owned_library):
    game, edition, release = make_graph(owned_library)

    remove_row(release)

    assert not Release.objects.for_library(owned_library).exists()
    assert Edition.objects.for_library(owned_library).get() == edition
    assert Game.objects.for_library(owned_library).get() == game
    assert Release.objects.filter(pk=release.pk).exists()
```

```python
def test_restoring_a_game_leaves_a_separately_removed_child_out(owned_library):
    """Two marks, two answers. The child keeps its own."""
    game, edition, release = make_graph(owned_library)
    second = Edition.objects.create(game=game)
    remove_row(edition)
    remove_row(game)

    restore_row(game)

    assert Edition.objects.for_library(owned_library).get() == second
    assert not Release.objects.for_library(owned_library).exists()
    assert Release.objects.filter(pk=release.pk).exists()
```

```python
def test_a_removed_child_stays_for_the_plain_manager(owned_library):
    game, edition, release = make_graph(owned_library)
    remove_row(edition)
    remove_row(release)

    assert Edition.objects.count() == 1
    assert Release.objects.count() == 1
    assert list(Edition.objects.alive()) == []
    assert list(Release.objects.alive()) == []
```

```python
def test_removing_a_child_in_one_library_leaves_the_other_alone(
    owned_library, other_library
):
    _, mine, _ = make_graph(owned_library, name="Mine")
    _, theirs, their_release = make_graph(other_library, name="Theirs")

    remove_row(mine)

    assert not Edition.objects.for_library(owned_library).exists()
    assert Edition.objects.for_library(other_library).get() == theirs
    assert Release.objects.for_library(other_library).get() == their_release
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_removed_rows.py -x"`
Expected: FAIL on `test_a_removed_edition_takes_its_releases_with_it` — the querysets
read only the Game's mark, so the removed Edition still answers `for_library`.

- [ ] **Step 3: Say what `alive()` means where it is defined**

`RemovableMixin`'s docstring states the rule this task changes. Replace the class in
`games/models.py`:

```python
class RemovableMixin:
    """The row stays; the reads skip it.

    `alive()` asks about this row. A catalog child holds a mark and
    sits under rows that hold one, so its queryset widens the
    question to its ancestors.

    A mixin rather than a queryset: two queryset bases give
    django-stubs two `as_manager` return types to disagree over.
    """

    def alive(self):
        return self.filter(removed_at__isnull=True)
```

- [ ] **Step 4: Compose the marks on the two child querysets**

Replace `EditionQuerySet`:

```python
class EditionQuerySet(RemovableMixin, models.QuerySet):
    """An Edition holds a mark, under a Game that holds one.

    A removed Game hides its Editions. An Edition keeps its own
    mark through that, thus restoring the Game shows back only the
    Editions nobody removed.
    """

    def alive(self):
        return super().alive().filter(game__removed_at__isnull=True)

    def for_library(self, library):
        return self.filter(game__library=library).alive()

    def visible_to(self, library):
        return self.filter(
            Q(game__library__isnull=True) | Q(game__library=library)
        ).alive()
```

Replace `ReleaseQuerySet`:

```python
class ReleaseQuerySet(RemovableMixin, models.QuerySet):
    """A Release holds a mark, under two rows that hold one."""

    def alive(self):
        return (
            super()
            .alive()
            .filter(
                edition__removed_at__isnull=True,
                edition__game__removed_at__isnull=True,
            )
        )

    def for_library(self, library):
        return self.filter(edition__game__library=library).alive()

    def visible_to(self, library):
        return self.filter(
            Q(edition__game__library__isnull=True) | Q(edition__game__library=library)
        ).alive()
```

- [ ] **Step 5: Run the tests again**

Run: `make test ARGS="tests/test_removed_rows.py -x"`
Expected: PASS, every test in the file.

- [ ] **Step 6: Run everything that reads these two models**

Run: `make test ARGS="tests/test_catalog_hierarchy.py tests/test_catalog_writes.py tests/test_catalog_compat.py tests/test_catalog_write_views.py tests/test_retention.py"`
Expected: PASS. `test_catalog_visibility_is_opt_in_and_derives_through_the_hierarchy`
is the one that proves the rewrite kept the shared-catalog branch.

- [ ] **Step 7: Type-check**

Run: `make typecheck`
Expected: clean. A second `QuerySet` base here is what `RemovableMixin` exists to
avoid; if mypy reports two `as_manager` return types, the mixin was subclassed wrong.

- [ ] **Step 8: Commit**

```bash
git add games/models.py tests/test_removed_rows.py
git commit -m "$(cat <<'EOF'
Read a child as visible when no ancestor is removed

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Both models join the removal registry

**Files:**
- Modify: `games/removal.py:24-35`
- Test: `tests/test_removable_models.py`

**Interfaces:**
- Consumes: the columns (Task 1), `for_library` (Task 2).
- Produces: `remove(edition)`, `restore(edition)`, `remove(release)`,
  `restore(release)`; `REMOVABLE_MODELS` grows to nine.

- [ ] **Step 1: Write the failing builders**

In `tests/test_removable_models.py`, import both models — the import list becomes
`Device, Edition, FilterPreset, Game, Platform, PlayEvent, Purchase, Release, Session,
UserLibrary` — and add two builders beside the others:

```python
def _edition(library: UserLibrary) -> Edition:
    return Edition.objects.create(game=_game(library))
```

```python
def _release(library: UserLibrary) -> Release:
    return Release.objects.create(edition=_edition(library))
```

Add both to `BUILDERS`:

```text
    Edition: _edition,
    Release: _release,
```

Neither builder marks the row default. Whether a default may be removed is #967's
rule; nothing here states one.

- [ ] **Step 2: Run the file and watch it fail**

Run: `make test ARGS="tests/test_removable_models.py -x"`
Expected: FAIL on `test_every_removable_model_has_a_builder` — `BUILDERS` holds two
models `REMOVABLE_MODELS` does not.

- [ ] **Step 3: Register both models**

In `games/removal.py`, import them and extend the tuple. The comment above it already
says why `PlayerGame` is absent; leave that and add the order:

```python
#: Every model a user can remove.
#: PlayerGame is absent: it is a projection,
#: and only its projector writes it.
REMOVABLE_MODELS: tuple[type[Model], ...] = (
    Game,
    Edition,
    Release,
    Platform,
    Device,
    Session,
    PlayEvent,
    Purchase,
    FilterPreset,
)
```

Add `Edition` and `Release` to the `from games.models import (...)` block, in
alphabetical order with the rest.

No `_AFTER_STAMP` entry for either: no signal recounts or recalculates anything from
an Edition or a Release.

- [ ] **Step 4: Run the file again**

Run: `make test ARGS="tests/test_removable_models.py -v"`
Expected: PASS — 20 tests, including
`test_for_library_hides_a_removed_row[Edition]`,
`[Release]`, `test_restore_brings_it_back[Edition]` and `[Release]`.

- [ ] **Step 5: Commit**

```bash
git add games/removal.py tests/test_removable_models.py
git commit -m "$(cat <<'EOF'
Let remove and restore accept a catalog child

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: A Release is a row an event may name

**Files:**
- Modify: `games/events/references.py` (imports ~24, captures ~156-178, registry
  ~180-205)
- Modify: `games/retention.py` (imports ~13-19, `refuse_to_delete_a_referenced_row`
  ~100)
- Modify: `games/signals.py` (imports, the `pre_delete` receiver ~89)
- Modify: `games/models.py` (`class Edition`, `class Release` — bases only)
- Test: `tests/test_event_references.py`, `tests/test_retention.py`

**Interfaces:**
- Consumes: `remove()` on a Release (Task 3).
- Produces: the kind name `catalog.release` at `Resolution.REQUIRED`, capturing
  `label=release.edition.game.name` and `detail=release.platform.name` or `""`;
  `refuse_to_delete_a_referenced_row` returns quietly for a model no kind captures.

**Why the guard has to give:** `ReferencedRow.delete()` calls the guard, the guard
calls `must_be_retained`, and that calls `kinds.kind_of(instance)`, which raises
`UnmappedReferenceModel` for a model with no kind. The spec puts `ReferencedRow` under
both children and keeps `catalog.edition` out of the registry, so without this an
`Edition.delete()` raises a `TypeError` subclass instead of deleting —
`test_catalog_hierarchy_delete_behavior_is_explicit` would go red. The tolerance is
sound on its own terms: a row no kind captures is a row `capture_reference` refuses,
so no event can name it and no reference can be stranded.

- [ ] **Step 1: Write the failing capture test**

In `tests/test_event_references.py`, beside the other capture tests (after
`test_a_platform_captures_its_name_and_group`), add:

```python
@pytest.mark.django_db
def test_a_release_captures_the_games_name_and_its_platform(game, platform):
    """A Release has no words of its own; both are joins."""
    release = Release.objects.create(
        edition=Edition.objects.create(game=game), platform=platform
    )

    assert capture_reference(release) == Reference(
        kind="catalog.release",
        id=str(release.pk),
        label="Baldur's Gate 3",
        detail="Steam",
    )
```

```python
@pytest.mark.django_db
def test_a_release_on_no_platform_captures_an_empty_detail(game):
    release = Release.objects.create(edition=Edition.objects.create(game=game))

    assert capture_reference(release)["detail"] == ""
```

Extend the shipped-kinds test in the same file:

```python
def test_every_shipped_kind_must_resolve_at_replay():
    for name in ("device", "catalog.game", "catalog.platform", "catalog.release"):
        assert DEFAULT_REFERENCE_KINDS.kind_for(name).resolution is Resolution.REQUIRED
```

`Edition` is already imported there; add `Release`. Leave
`test_a_model_no_kind_captures_is_refused` alone — it names an Edition, and an Edition
stays out of the registry, which is exactly what it now guards.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_event_references.py -x"`
Expected: FAIL — `UnmappedReferenceModel: Release has no reference kind`.

- [ ] **Step 3: Register the kind**

In `games/events/references.py`, add `Release` to
`from games.models import Device, Game, Platform` and add the capture beside
`_capture_platform`:

```python
def _capture_release(release: Release) -> Reference:
    """A Release has no words of its own.

    The label is the Game's name, thus a reader of a recorded
    reference sees the work. The detail is the Platform, which is
    what tells two Releases of one Game apart. Both are joins: a
    caller capturing many selects them first.
    """
    return Reference(
        kind="catalog.release",
        id=str(release.pk),
        label=release.edition.game.name,
        detail="" if release.platform is None else release.platform.name,
    )
```

and register it after `catalog.platform`:

```text
DEFAULT_REFERENCE_KINDS.register(
    ReferenceKind(
        name="catalog.release",
        model=Release,
        capture=_capture_release,
        resolution=Resolution.REQUIRED,
    )
)
```

`catalog.edition` stays out: no event names an Edition, and a kind with no event
states a convention rather than a rule.

- [ ] **Step 4: Run the capture tests**

Run: `make test ARGS="tests/test_event_references.py -x"`
Expected: PASS.

- [ ] **Step 5: Write the failing retention tests**

`tests/test_retention.py` already imports `Edition`, `Release`, `remove`,
`ReferencedRowDeletion`, `LibraryEventReference`, `call_command` and `StringIO`, so
these tests need no new import. Add a fixture beside `game`/`platform`/`device`:

```python
@pytest.fixture
def release(game, platform):
    return Release.objects.create(
        edition=Edition.objects.create(game=game, is_default=True),
        is_default=True,
        platform=platform,
    )
```

Add these, in the sections their names match — the first two under "the guard holds
outside the views", the third under "except during a whole-library purge", the last
two beside the resolver tests:

```python
def test_a_raw_delete_of_a_referenced_release_is_refused(owned_library, release):
    name_in_an_event(owned_library, release)

    with pytest.raises(ReferencedRowDeletion, match="games.removal.remove"):
        release.delete()

    assert Release.objects.filter(pk=release.pk).exists()
```

```python
def test_a_cascade_that_would_take_a_referenced_release_is_refused(
    owned_library, release
):
    """The parent is unreferenced; the child is not."""
    name_in_an_event(owned_library, release)

    with pytest.raises(ReferencedRowDeletion):
        release.edition.game.delete()

    assert Release.objects.filter(pk=release.pk).exists()
```

```python
def test_an_edition_no_kind_captures_still_deletes(owned_library, release):
    """No kind, thus no event can name it, thus nothing to keep."""
    edition_id = release.edition_id

    release.delete()
    Edition.objects.get(pk=edition_id).delete()

    assert not Edition.objects.filter(pk=edition_id).exists()
```

```python
def test_a_removed_release_still_resolves(owned_library, release):
    reference = name_in_an_event(owned_library, release)

    remove(release)

    assert resolve_reference(reference) == release
    assert not Release.objects.for_library(owned_library).exists()
```

```python
def test_purging_a_library_takes_its_referenced_releases(
    owned_user, owned_library, release
):
    name_in_an_event(owned_library, release)

    call_command(
        "purge_user_library",
        user=owned_user.username,
        confirm=owned_user.username,
        stdout=StringIO(),
    )

    assert not Release.objects.filter(pk=release.pk).exists()
    assert not LibraryEventReference.objects.exists()
```

Every test in this module already runs under
`pytest.mark.django_db(transaction=True)` and `pytest.mark.untracked_games` through
the module-level `pytestmark`, which is what a refused delete inside a transaction
needs.

- [ ] **Step 6: Run them and watch them fail**

Run: `make test ARGS="tests/test_retention.py -k release -x"`
Expected: FAIL on the first — a plain `models.Model` reaches no guard, so the delete
succeeds and nothing raises.

- [ ] **Step 7: Put both children under `ReferencedRow`**

In `games/models.py`, change the two class statements and nothing else:

```text
class Edition(ReferencedRow):
```

```text
class Release(ReferencedRow):
```

The base is abstract and declares no field, and each child keeps its own `Meta`, so
this writes no migration. Step 11 proves that.

- [ ] **Step 8: Let the guard pass over a model no kind captures**

In `games/retention.py`, add `UnmappedReferenceModel` to the
`from games.events.references import (...)` block and rewrite the guard:

```python
def refuse_to_delete_a_referenced_row(instance: Model) -> None:
    """The guard, called from `pre_delete`."""
    if _purging.get():
        return
    try:
        retained = must_be_retained(instance)
    except UnmappedReferenceModel:
        #: No kind, thus no event names it.
        return
    if not retained:
        return
    raise ReferencedRowDeletion(
        f"{instance} cannot be deleted: "
        f"{reference_count(instance)} recorded event(s) reference it, and a "
        "replay must still be able to resolve them. Take it out of the "
        "library with games.removal.remove, which keeps the row."
    )
```

`must_be_retained` and `reference_count` stay strict. They are asked about a kind; the
guard is called with any row.

- [ ] **Step 9: Extend the `pre_delete` backstop**

In `games/signals.py`, add `Release` to the `from games.models import (...)` block and
one decorator to the existing receiver:

```python
@receiver(pre_delete, sender=Game)
@receiver(pre_delete, sender=Platform)
@receiver(pre_delete, sender=Device)
@receiver(pre_delete, sender=Release)
def refuse_to_delete_a_row_an_event_references(sender, instance, **kwargs):
    """Stop a delete that strands a reference.

    Here, not in the views, so every call path is held to it.
    """
    refuse_to_delete_a_referenced_row(instance)
```

`Edition` is not listed: no kind captures one, so the receiver would do nothing.

- [ ] **Step 10: Run the retention suite**

Run: `make test ARGS="tests/test_retention.py"`
Expected: PASS, the whole file.

- [ ] **Step 11: Prove the base change wrote no migration**

Run: `make check-migrations`
Expected: "No changes detected".

- [ ] **Step 12: Run the event and catalog suites together**

Run: `make test ARGS="tests/test_event_references.py tests/test_event_reference_index.py tests/test_reference_reconciliation.py tests/test_catalog_hierarchy.py tests/test_removed_rows.py tests/test_removable_models.py"`
Expected: PASS. `test_catalog_hierarchy_delete_behavior_is_explicit` is the one the
guard tolerance protects.

- [ ] **Step 13: Commit**

```bash
git add games/events/references.py games/retention.py games/signals.py \
        games/models.py tests/test_event_references.py tests/test_retention.py
git commit -m "$(cat <<'EOF'
Keep a Release an event named, and resolve it after removal

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: The pages that state the old rule

**Files:**
- Modify: `docs/event-retention.md:38-40`
- Modify: `docs/event-references.md:61-72`
- Modify: `CLAUDE.md:161-171`
- Remove: `docs/superpowers/plans/2026-08-31-issue-966-edition-release-removal.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no code.

- [ ] **Step 1: Correct the retention page**

In `docs/event-retention.md`, under "Where a removed row is not visible", replace:

> `Edition` and `Release` have no `removed_at` column. They also have no
> visibility of their own. Their querysets read the column of the parent `Game`.

with:

> `Edition` and `Release` each hold a `removed_at` of their own, and each reads its
> ancestors' as well: an Edition is visible while neither it nor its `Game` is
> removed, and a Release while neither it, nor its `Edition`, nor that Game is. A
> child keeps its own mark through a parent's, thus restoring a Game shows back only
> the children nobody removed. A partial index on each parent key, conditional on
> `removed_at IS NULL`, serves the read for one parent's live children.

- [ ] **Step 2: Correct the references page**

In `docs/event-references.md`, replace the line above the table —

> The default registry has three kinds. All three are `REQUIRED`.

with:

> The default registry has four kinds. All four are `REQUIRED`.

Add a row at the bottom of the table:

```text
| `catalog.release` | `Release` | the Game's `name` | `platform.name`, or `""` |
```

Then replace the paragraph below the table —

> `Edition` and `Release` have no kind. Neither model has a display field of its
> own. A snapshot of one of these models needs a join to a parent model.

with:

> `Edition` has no kind. No event names one, and a kind with no event states a
> convention rather than a rule. `Release` has one from #966, before #690 records the
> first, so the retention policy covers a Release from the first day one can be named.
> Neither model has a display field of its own, thus capturing a Release reads its
> Edition's Game and its Platform; a caller capturing many selects them first.

- [ ] **Step 3: Correct `CLAUDE.md`**

Replace the first sentence of the removal paragraph at line 161:

> **Nothing a user removes is destroyed** (#944). The seven removable models —
> Game, Platform, Device, Session, PlayEvent, Purchase, FilterPreset — each carry a
> nullable `removed_at`, listed in `REMOVABLE_MODELS` in `games/removal.py`.

with:

> **Nothing a user removes is destroyed** (#944). The nine removable models —
> Game, Edition, Release, Platform, Device, Session, PlayEvent, Purchase,
> FilterPreset — each carry a nullable `removed_at`, listed in `REMOVABLE_MODELS` in
> `games/removal.py`.

and add one sentence at the end of that paragraph, after "A Purchase is live while any
of its games is, or while it names none.":

> An Edition and a Release read their ancestors' marks as well as their own, so a
> removed Game hides both and restoring it leaves a separately removed child out
> (#966).

- [ ] **Step 4: Lint the prose**

Run: `make vale`
Expected: no error-level alert. `remove`, `removed row` and `purge` are the words
these pages want; `archive`, `tombstone` and `delete`-next-to-a-record are refused.

- [ ] **Step 5: Take this plan out of the tree**

```bash
git rm docs/superpowers/plans/2026-08-31-issue-966-edition-release-removal.md
```

The spec stays. `make format-check` reads Python inside Markdown fences, so the plan
document goes before the gate runs, not after.

- [ ] **Step 6: Run the gate**

Run: `make check`
Expected: green — lint, format-check, mypy, vale, ts-check, icons, migrations, vitest
and the whole pytest suite including `e2e/`. Nothing here touches TypeScript, so a
red vitest or ts-check means an unrelated tree state.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
Say where a catalog child's mark is read

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: Finish the branch**

Announce: "I'm using the finishing-a-development-branch skill to complete this work."
Then follow superpowers:finishing-a-development-branch — push, open the pull request
against `main`, and reference #966.

---

## Acceptance, mapped

| Issue acceptance | Where it is met |
|---|---|
| `remove()`/`restore()` accept an Edition and a Release; nothing destroys either | Task 3, `tests/test_removable_models.py` parametrized over nine models |
| A removed child leaves every list, form, filter and API response; the plain manager sees it | Task 2, `for_library`/`visible_to` call `.alive()`; `test_a_removed_child_stays_for_the_plain_manager` |
| A removed Game hides its children; restoring it leaves a separately removed one out | Task 2, `test_restoring_a_game_leaves_a_separately_removed_child_out` |
| A Release an event named cannot be destroyed, and resolves after removal | Task 4, `test_a_raw_delete_of_a_referenced_release_is_refused`, `test_a_removed_release_still_resolves` |
| A whole-library purge still completes | Task 4, `test_purging_a_library_takes_its_referenced_releases` |
| `tests/test_removable_models.py` passes with both registered; two-library isolation passes | Tasks 2 and 3 |
| The full `make check` gate passes at the default worker count | Task 5, Step 6 |

## Out of scope, on purpose

- **No write verb.** `add_edition`, `remove_release` and the rest are #967's, together
  with the rule that a default may not be removed while a live sibling could take the
  mark. Nothing in this plan refuses a removal.
- **No screen, route, form or confirmation.** #969.
- **No recovery screen.** #795.
- **No `catalog.edition` kind.** No event names an Edition.
- **No behaviour change.** Every Game still holds one default Edition and one default
  Release, both columns are null on every row, and every existing query answers what
  it answered.
