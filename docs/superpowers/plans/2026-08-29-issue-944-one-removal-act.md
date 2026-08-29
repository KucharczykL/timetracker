# One Removal Act Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make removal one act — nothing a user can reach destroys a row, every
removable record carries `removed_at`, and `purge` names the whole-library
destroy alone.

**Architecture:** A removed row is stamped, not destroyed. Reads exclude it at
`for_library()`, the one choke point every list, form, filter and API response
already goes through. A child row takes no stamp of its own: it reads its
parent's. `PlayerGame` is a projection, so its stamp is written by the projector
from an event, which is why #675's archive machinery is renamed rather than
deleted.

**Tech Stack:** Django 6, PostgreSQL 18, pytest + pytest-xdist, Playwright,
Vale.

**Spec:** `docs/superpowers/specs/2026-08-29-issue-944-one-removal-act-design.md`

## Global Constraints

- **Drive everything through `make`.** Never `direnv exec .`, never a raw `uv
  run` / `pytest` / `pnpm`. Iterate with `make check-fast`; the gate is the full
  `make check`, including `e2e/`.
- **Python 3.14 only.** A `SyntaxError` in an `except A, B:` line means the
  wrong interpreter, not broken code.
- **Never write to a `GeneratedField`**: `duration_calculated`,
  `duration_total`, `price_per_game`, `days_to_finish`.
- **No dispatch inside a transaction.** `run_in_transaction` opens and retries
  its own transaction and refuses to nest. A view that dispatches carries no
  `@transaction.atomic`. A test that POSTs through such a view needs
  `@pytest.mark.django_db(transaction=True)`.
- **A PlayerGame fact is stated as a command.** Never assign to a `PlayerGame`
  column outside a projector.
- **Complete words in identifiers** — `element` not `el`, `event` not `e`.
- **UI is Python components** from `common.components`, htpy form:
  `Div(class_="x")[child]`. Never HTML strings.
- **Mutating links carry `?origin=`** via `action_url(...)`; every mutating view
  ends with `redirect(return_url(request, fallback=...))`; every route is
  classified in `games/views/returns.py` or the completeness guard fails.
- **Comments are seven words or fewer** and say why, not what. Specs and docs
  are ASD-STE100: short sentences, active voice, one idea each.
- **Refused words** (`docs/vocabulary.md`): after Task 8, `tombstone`, `archive`
  and domain `delete` fail `make vale` in prose and in comments. Do not
  reintroduce them.
- **`alive()` keeps its name.** The spec weighed `not_removed()`, `kept()` and
  `in_library()` and deferred the rename on purpose. Do not derive the question
  again.
- **Two things still destroy a row, and both stay.** A library purge, and
  `add_game`'s rollback of its own insert in `games/views/game.py`. Neither is
  a removal; leave both alone.
- **`make makemigrations` passes `--noinput`**, so its questioner answers no to
  every rename and emits `RemoveField` + `AddField`. Every migration in this
  plan is written by hand.
- **`make check-migrations` is the drift check.** `make makemigrations` and
  `make test-fast` ignore `ARGS`, so `make makemigrations ARGS="--check
  --dry-run"` writes a migration file instead of checking for one.
- **The event-era migrations may be edited in place.** No deployment has run
  them — `git ls-tree v1.8.1 games/migrations/` shows a different `0031`–`0033`
  — and the Makefile's `reset-db` comment states the policy. `0033` replays the
  backfill through *live* model code, so a column it reaches must already carry
  its final name by then. Both renames in this plan therefore edit the
  migration that added the column, and `make reset-db` repairs a development
  database that applied the old file.

---

### Task 1: Rename the catalog column to `removed_at`

Mechanical. No behaviour changes: the husk still exists, it is just spelled
differently.

**Files:** the exact set is
`grep -rl tombston --include=*.py --include=*.ts --include=*.md .` minus
`node_modules`, `docs/superpowers/` and the four historical migrations.
- Modify: `games/models.py` (`TombstonableQuerySet`, three `tombstoned_at`
  fields, four constraint conditions, `Edition`/`Release` querysets,
  `GameQuerySet.tracked_by`)
- Modify: `games/retention.py`, `games/signals.py`, `games/forms.py`,
  `games/views/retirement.py`, `games/backfill/playergame.py`,
  `games/commands/playergame.py`, `common/import_data.py`
- Rename: `games/migrations/0027_tombstone_catalog_rows.py` →
  `0027_removable_catalog_rows.py`, edited in place
- Modify: `games/migrations/0028_playergame.py` (its dependency) and
  `games/migrations/0033_playergame_baseline_backfill.py` (`skipped_removed`)
- Rename: `tests/test_tombstoned_rows.py` → `tests/test_removed_rows.py`
- Modify: `tests/test_retention.py`, `tests/test_reference_reconciliation.py`,
  `tests/test_playergame_backfill.py`, `tests/test_playergame_command.py`,
  `tests/test_playergame_game_views.py`, `tests/test_playergame_tracked_by.py`,
  `e2e/test_retention_confirmation_e2e.py`,
  `e2e/test_games_list_projection_e2e.py`, `e2e/test_return_to_origin_e2e.py`
- Leave alone: `0032`, and `tests/test_playergame_backfill_migration.py`'s
  `BEFORE_BASELINE`, which names a migration by its historical title

**Interfaces:**
- Consumes: nothing.
- Produces: `RemovableMixin.alive()`, `RemovableLibraryQuerySet.for_library()`,
  and the column name `removed_at` on `Game`, `Platform`, `Device`.

- [ ] **Step 1: Split the queryset base**

In `games/models.py`, replace `TombstonableQuerySet` with two classes:

```python
class RemovableMixin:
    """A removed row stays; the reads leave it out.

    `alive()` asks about this row only. A parent's own removal is a
    condition of `for_library()`, because a child keeps no stamp.

    A mixin rather than a queryset: two queryset bases give
    django-stubs two `as_manager` return types to disagree over.
    """

    def alive(self):
        return self.filter(removed_at__isnull=True)


class RemovableLibraryQuerySet(RemovableMixin, LibraryOwnedQuerySet):
    """A library-owned row a user can remove."""

    def for_library(self, library):
        return super().for_library(library).alive()
```

`RemovableMixin` is deliberately not a `QuerySet`. With two `QuerySet` bases,
django-stubs generates a `ManagerFromRemovableLibraryQuerySet` that mypy reads
as incompatible with `LibraryOwnedQuerySet.as_manager`'s return type.

`GameQuerySet` and `PlatformQuerySet` now extend `RemovableLibraryQuerySet`;
`Device.objects = TombstonableQuerySet.as_manager()` becomes
`RemovableLibraryQuerySet.as_manager()`.

- [ ] **Step 2: Rename the column and every condition**

Three `tombstoned_at = models.DateTimeField(...)` fields become `removed_at`.
Four constraint conditions (`Game` twice, `Platform` twice) take the new name,
as do `Platform.clean()`, `EditionQuerySet`, `ReleaseQuerySet` and
`GameQuerySet.tracked_by`'s `alive()` comment. Then sweep the callers:

Run: `grep -rn "tombston" --include=*.py --include=*.md --include=*.ts .`

Every hit changes, the migration that introduced the column included — see the
next step for why.

- [ ] **Step 3: Edit migration 0027 in place**

Do **not** add a rename migration on top. `0033_playergame_baseline_backfill.py`
imports live model and backfill code by design ("pinned to the application as it
stands when it runs"), so at its point in the graph the column must already
answer to its current name. A 0036 that renames afterwards makes a fresh
`migrate` fail with `column games_game.removed_at does not exist`.

The event-era migrations are unreleased, and the Makefile's `reset-db` comment
states the policy: "A migration that no deployment has run may still be edited
in place, and the event-era ones qualify." `git ls-tree v1.8.1
games/migrations/` confirms it — the released tag has an entirely different
`0031`–`0033`.

```bash
git mv games/migrations/0027_tombstone_catalog_rows.py \
       games/migrations/0027_removable_catalog_rows.py
sed -i s/tombstoned_at/removed_at/g games/migrations/0027_removable_catalog_rows.py
```

Then point `games/migrations/0028_playergame.py`'s dependency at
`("games", "0027_removable_catalog_rows")`, and rename
`0033_playergame_baseline_backfill.py`'s `skipped_tombstoned` summary key to
`skipped_removed`, because it reads a live `BackfillCounts`.

Because the four partial-unique conditions live in `0027` too, the `sed`
rewrites them with the column. No `RemoveConstraint`/`AddConstraint` pair is
needed.

- [ ] **Step 4: Rebuild the development database and prove it agrees**

Run: `make reset-db`, then `make check-migrations`
Expected: a clean replay, then "No changes detected". `make check-migrations` is
the drift check — `make makemigrations ARGS="--check --dry-run"` ignores `ARGS`
and writes a migration file.

- [ ] **Step 5: Run the suite**

Run: `make check-fast`
Expected: PASS. Then `make test-e2e ARGS="-k retention or projection"`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Rename retention's column to removed_at"
```

---

### Task 2: Rename archive to remove on PlayerGame

Also mechanical, and the last task before behaviour changes.

**Files:**
- Modify: `games/models.py:1396` (`PlayerGame.archived_at`),
  `games/models.py:134` (`tracked_by`'s join)
- Modify: `games/events/playergame.py`, `games/events/dispatch.py`
  (`CommandName`), `games/commands/playergame.py`,
  `games/projectors/playergame.py`, `games/backfill/playergame.py`
- Rename: `games/migrations/0032_playergame_archived_at.py` →
  `0032_playergame_removed_at.py`, edited in place
- Modify: `games/migrations/0033_playergame_baseline_backfill.py` (its
  dependency), `tests/test_playergame_backfill_migration.py`
  (`BEFORE_BASELINE`)
- Modify: `tests/test_playergame_command.py`,
  `tests/test_playergame_projection.py`, `tests/test_playergame_events.py`,
  `tests/test_playergame_tracked_by.py`, `tests/test_playergame_backfill.py`,
  `tests/test_playergame_game_views.py`, `tests/test_projection_model.py`,
  `tests/test_returns_classification.py`
- Leave alone: `0033`'s body, which names the act nowhere

**Interfaces:**
- Consumes: Task 1's `removed_at` naming.
- Produces: `RemovePlayerGame`, `CommandName.PLAYERGAME_REMOVE`,
  `PLAYERGAME_REMOVED` (`"library.playergame.removed"`),
  `PlayerGame.removed_at`.

- [ ] **Step 1: Write the failing test**

In `tests/test_playergame_command.py`:

```python
def test_removing_a_tracked_game_stamps_the_projection(owned_user, owned_library):
    game = make_tracked_game(owned_user, owned_library)

    dispatch(RemovePlayerGame(game_id=game.pk), actor=owned_user)

    tracked = PlayerGame.objects.get(library=owned_library, game=game)
    assert tracked.removed_at is not None


def test_removing_a_removed_game_records_nothing(owned_user, owned_library):
    game = make_tracked_game(owned_user, owned_library)
    dispatch(RemovePlayerGame(game_id=game.pk), actor=owned_user)

    before = LibraryEvent.objects.for_library(owned_library).count()
    dispatch(RemovePlayerGame(game_id=game.pk), actor=owned_user)

    assert LibraryEvent.objects.for_library(owned_library).count() == before
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playergame_command.py -k removing -x"`
Expected: FAIL, `ImportError: cannot import name 'RemovePlayerGame'`.

- [ ] **Step 3: Rename the five names**

| Now | After |
| --- | --- |
| `PlayerGame.archived_at` | `PlayerGame.removed_at` |
| `ArchivePlayerGame` | `RemovePlayerGame` |
| `CommandName.PLAYERGAME_ARCHIVE = "library.playergame.archive"` | `PLAYERGAME_REMOVE = "library.playergame.remove"` |
| `PLAYERGAME_ARCHIVED` / `"library.playergame.archived"` | `PLAYERGAME_REMOVED` / `"library.playergame.removed"` |
| `PlayerGames._archived` | `PlayerGames._removed` |

`RestorePlayerGame`, `PLAYERGAME_RESTORED` and `"library.playergame.restored"`
keep their names. `GameQuerySet.tracked_by` filters
`tracked__removed_at__isnull=True`, and its docstring's last paragraph takes the
new word.

Three sentences in `games/commands/playergame.py` are rewritten, not
search-replaced:

- `TrackGame.build`: *"This library removed {game.name}. A removed game is
  restored, not tracked again."*
- `TrackGame._visible_game`: *"…and neither offers a removed row."*
- `RestorePlayerGame`'s docstring: *"Removing a tracked game stamps the catalog
  row and keeps this one, so a removed game may outlive the row it names."*

- [ ] **Step 4: Edit migration 0032 in place**

For Task 1's reason: `0033` replays the backfill through live model code, so a
rename layered after it breaks a fresh `migrate`. The column is added by an
unreleased migration, so the `AddField` states the new name from the start.

```bash
git mv games/migrations/0032_playergame_archived_at.py \
       games/migrations/0032_playergame_removed_at.py
sed -i s/archived_at/removed_at/g games/migrations/0032_playergame_removed_at.py
```

Then point `0033`'s dependency and the migration test's `BEFORE_BASELINE` at
`("games", "0032_playergame_removed_at")`.

No data moves either way. No library has recorded an event of the archive type,
because nothing dispatched the command.

- [ ] **Step 5: Run the tests**

Run: `make reset-db`, then `make test ARGS="tests/test_playergame_command.py
-x"`, then `make check-fast` and `make check-migrations`.
Expected: PASS, and "No changes detected".

- [ ] **Step 6: Prove the word is gone**

Run: `grep -rli "archiv" --include=*.py --include=*.ts --include=*.md . | grep -v node_modules`
Expected: only four files that mean a tar archive or Postgres archive mode —
`scripts/db_dump.py`, `scripts/ensure_postgres.py`, `tests/test_db_dump.py`,
`tests/test_ensure_postgres.py`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Rename PlayerGame's archive act to remove"
```

---

### Task 3: Removal stops destroying

The husk machinery goes. A removed parent hides its children through the
queryset instead of destroying them.

**Files:**
- Create: `games/removal.py`
- Modify: `games/retention.py` (drop `Retirement`, `tombstone_or_delete`,
  `_delete_everything_but`, `_UNCASCADED_COLLATERAL`)
- Modify: `games/models.py` (`SessionQuerySet`, `PlayEventQuerySet`,
  `GameStatusChangeQuerySet`)
- Modify: `games/signals.py` (extract the playtime sum), `games/views/game.py`,
  `games/views/playevent.py`
- Modify: `tests/test_retention.py`
- Create: `tests/test_removal.py`

**Interfaces:**
- Consumes: Task 1's `alive()`.
- Produces: `games.removal.remove(instance) -> None`,
  `games.removal.restore(instance) -> None`,
  `games.removal.REMOVABLE_MODELS: tuple[type[Model], ...]`.

- [ ] **Step 1: Write the failing test**

`tests/test_removal.py`:

```python
pytestmark = pytest.mark.django_db


def test_removing_a_game_keeps_its_sessions(owned_library):
    game = make_game(owned_library)
    session = Session.objects.create(
        game=game,
        timestamp_start=timezone.now(),
        timestamp_end=timezone.now() + timedelta(hours=1),
    )

    remove(game)

    assert Session.objects.filter(pk=session.pk).exists()
    assert not Session.objects.for_library(owned_library).exists()


def test_restoring_a_game_brings_its_sessions_back(owned_library):
    game = make_game(owned_library)
    Session.objects.create(game=game, timestamp_start=timezone.now())
    remove(game)

    restore(game)

    assert Session.objects.for_library(owned_library).count() == 1


def test_a_session_removed_by_itself_stays_removed(owned_library):
    game = make_game(owned_library)
    session = Session.objects.create(game=game, timestamp_start=timezone.now())
    remove(session)
    remove(game)

    restore(game)

    assert not Session.objects.for_library(owned_library).exists()
```

The third test needs Task 5's column and is expected to fail until then. Mark it
`@pytest.mark.xfail(reason="Session.removed_at arrives in Task 5", strict=True)`
and drop the marker in Task 5.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_removal.py -x"`
Expected: FAIL, `ModuleNotFoundError: No module named 'games.removal'`.

- [ ] **Step 3: Write `games/removal.py`**

```python
"""Take a record out of the library, and put it back.

Nothing here destroys a row. `games.retention` keeps the guard that
refuses a destroying delete of a referenced row.
"""

from collections.abc import Callable
from typing import Any

from django.db.models import Model
from django.utils.timezone import now

from games.models import Game, Session

#: Every model a user can remove. PlayerGame is absent: it is a
#: projection, and only its projector writes it.
REMOVABLE_MODELS: tuple[type[Model], ...] = (Game,)


def _recount_purchases(game: Game) -> None:
    """A count of the live games only."""
    for purchase in game.purchases.all():
        purchase.num_purchases = purchase.games.alive().count()
        purchase.updated_at = now()
        purchase.save(update_fields=["num_purchases", "updated_at"])


#: What a stamp does not do by itself.
_AFTER_STAMP: dict[type[Model], Callable[[Any], None]] = {Game: _recount_purchases}


def _stamp(instance: Model, value: Any) -> None:
    model = type(instance)
    if model not in REMOVABLE_MODELS:
        raise TypeError(f"{model.__name__} is not a removable model.")
    #: An update, not a save: Game, Platform, Session and Purchase
    #: each override save() to call clean(), and a stamp must not
    #: revalidate a row a user is taking out. _AFTER_STAMP therefore
    #: does by hand what a post_save receiver would have done.
    model._default_manager.filter(pk=instance.pk).update(removed_at=value)
    instance.removed_at = value  # type: ignore[attr-defined]
    after = _AFTER_STAMP.get(model)
    if after is not None:
        after(instance)


def remove(instance: Model) -> None:
    """Take the row out of the library."""
    _stamp(instance, now())


def restore(instance: Model) -> None:
    """Put the row back."""
    _stamp(instance, None)
```

- [ ] **Step 4: Make the children read their parent**

```python
class SessionQuerySet(RemovableQuerySet):
    def for_library(self, library):
        return self.filter(game__library=library, game__removed_at__isnull=True)
```

`PlayEventQuerySet` and `GameStatusChangeQuerySet` take the same condition.
`SessionQuerySet` keeps `total_duration_unformatted()` and
`calculated_duration_unformatted()` untouched; it swaps `models.QuerySet` for
`RemovableQuerySet` now and gets its own column in Task 5, so until then
`alive()` on it is unused. `GameStatusChangeQuerySet` stays on
`models.QuerySet`: no screen removes one, and #771 takes the table.

- [ ] **Step 5: Delete the husk machinery**

From `games/retention.py` remove `Retirement`, `tombstone_or_delete()`,
`_delete_everything_but()`, `_UNCASCADED_COLLATERAL` and
`detach_game_from_purchases()`. Delete the `pre_delete` receiver
`update_purchase_counts_on_game_delete` in `games/signals.py` with it — a
destroying delete of a Game now happens only in a purge, which takes the
purchases too, and in `add_game`'s rollback, where the game has none.

Keep `refuse_to_delete_a_referenced_row()` and point its message at the new act:

```python
raise ReferencedRowDeletion(
    f"{instance} cannot be deleted: "
    f"{reference_count(instance)} recorded event(s) reference it, and a "
    "replay must still be able to resolve them. Take it out of the "
    "library with games.removal.remove, which keeps the row."
)
```

- [ ] **Step 6: Recompute playtime over live sessions only**

In `games/signals.py`, extract the sum so removal can call it:

```python
def recalculate_playtime(game: Game) -> None:
    """The sum over the sessions still in the library."""
    total = game.sessions.alive().aggregate(
        total=Sum(F("duration_calculated") + F("duration_manual"))
    )["total"]
    game.playtime = total if total else timedelta(0)
    game.save(update_fields=["playtime"])
```

`update_game_playtime` calls it. Task 5 adds `Session: recalculate_playtime` to
`_AFTER_STAMP`.

- [ ] **Step 7: Turn the equivalence test around**

`tests/test_retention.py::test_tombstoning_leaves_exactly_what_deleting_would`
policed the branch that is now gone. Replace it with
`test_removing_leaves_every_child_row`: two libraries, one referenced game and
one unreferenced, remove both, and assert the two libraries hold equal state and
that every session, play event and purchase row still exists.
`test_an_unreferenced_game_is_deleted`, `..._platform_...` and `..._device_...`
go: nothing is destroyed now. The guard tests
(`test_a_raw_delete_of_a_referenced_row_is_refused`,
`test_purging_a_library_takes_its_referenced_rows`) stay unchanged.

- [ ] **Step 8: Run the tests**

Run: `make test ARGS="tests/test_removal.py tests/test_retention.py -x"`, then
`make check-fast`.
Expected: PASS, with the one `xfail` from Step 1.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Stop destroying a row that a user removes"
```

---

### Task 4: A purchase lives while any of its games does

**Files:**
- Modify: `games/models.py` (`PurchaseQueryset.for_library`)
- Modify: `games/signals.py` (`update_num_purchases`)
- Create: `tests/test_removal_purchases.py`

**Interfaces:**
- Consumes: Task 3's `remove()`.
- Produces: nothing new; `Purchase.objects.for_library()` narrows.

- [ ] **Step 1: Write the failing test**

```python
def test_a_bundle_stays_while_one_game_stays(owned_library):
    kept, gone = make_game(owned_library), make_game(owned_library, name="Other")
    purchase = make_purchase(owned_library, games=[kept, gone])

    remove(gone)

    assert Purchase.objects.for_library(owned_library).count() == 1
    purchase.refresh_from_db()
    assert purchase.num_purchases == 1


def test_a_purchase_leaves_with_its_last_game(owned_library):
    game = make_game(owned_library)
    purchase = make_purchase(owned_library, games=[game])

    remove(game)

    assert not Purchase.objects.for_library(owned_library).exists()
    assert Purchase.objects.filter(pk=purchase.pk).exists()


def test_restoring_the_game_brings_the_purchase_back(owned_library):
    game = make_game(owned_library)
    make_purchase(owned_library, games=[game])
    remove(game)

    restore(game)

    assert Purchase.objects.for_library(owned_library).count() == 1
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_removal_purchases.py -x"`
Expected: FAIL on the second test — the purchase is still listed.

- [ ] **Step 3: Filter on a live game**

```python
class PurchaseQueryset(RemovableLibraryQuerySet):
    def for_library(self, library):
        #: A bundle stays while one of its games stays.
        return (
            super()
            .for_library(library)
            .filter(Exists(Game.objects.alive().filter(purchases=OuterRef("pk"))))
        )
```

`RemovableLibraryQuerySet.for_library` needs `Purchase.removed_at`, which Task 5
adds; until then extend `LibraryOwnedQuerySet` and add the `Exists` only.

- [ ] **Step 4: Count the live games**

```python
@receiver(m2m_changed, sender=Purchase.games.through)
def update_num_purchases(sender, instance, action, reverse, **kwargs):
    if not reverse and action.startswith("post_"):
        instance.num_purchases = instance.games.alive().count()
        instance.updated_at = now()
        instance.save(update_fields=["num_purchases", "updated_at"])
```

- [ ] **Step 5: Run the tests**

Run: `make test ARGS="tests/test_removal_purchases.py -x"`, then
`make check-fast`.
Expected: PASS. `price_per_game` follows `num_purchases`, which is the same
arithmetic the destroying delete produced.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Keep a purchase while one of its games stays"
```

---

### Task 5: `removed_at` on the four remaining models

**Files:**
- Modify: `games/models.py` (`Session`, `PlayEvent`, `Purchase`, `FilterPreset`)
- Create: `games/migrations/0036_removable_records.py`
- Modify: `games/removal.py` (`REMOVABLE_MODELS`, `_AFTER_STAMP`)
- Modify: `games/views/game.py:331-333`, `games/views/game.py:388`,
  `games/views/playevent.py:156,250,256,272` (reverse accessors)
- Modify: `tests/test_removal.py` (drop the `xfail`)
- Create: `tests/test_removable_models.py`

**Interfaces:**
- Consumes: `REMOVABLE_MODELS`, `remove()`, `restore()`.
- Produces: `REMOVABLE_MODELS == (Game, Session, PlayEvent, Purchase, FilterPreset)`.

- [ ] **Step 1: Write the failing test**

`tests/test_removable_models.py` — one test over the registry, so a model added
later cannot skip the rule:

```python
@pytest.mark.parametrize("model", REMOVABLE_MODELS, ids=lambda m: m.__name__)
def test_for_library_hides_a_removed_row(owned_library, model):
    instance = make_instance(model, owned_library)

    remove(instance)

    assert not model.objects.for_library(owned_library).filter(pk=instance.pk).exists()
    assert model.objects.filter(pk=instance.pk).exists()


@pytest.mark.parametrize("model", REMOVABLE_MODELS, ids=lambda m: m.__name__)
def test_restore_brings_it_back(owned_library, model):
    instance = make_instance(model, owned_library)
    remove(instance)

    restore(instance)

    assert model.objects.for_library(owned_library).filter(pk=instance.pk).exists()


def test_every_removable_model_has_the_column():
    for model in REMOVABLE_MODELS:
        assert model._meta.get_field("removed_at").null
```

`make_instance` is a `dict[type[Model], Callable[[UserLibrary], Model]]` in the
test module. Write one builder per model; do not reach for a factory library.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_removable_models.py -x"`
Expected: FAIL — `Session` is not in `REMOVABLE_MODELS`.

- [ ] **Step 3: Add the column to four models**

Each gets the same field, beside the other bookkeeping columns:

```python
#: Set instead of destroying the row.
removed_at = models.DateTimeField(null=True, blank=True, default=None, editable=False)
```

`Purchase` and `FilterPreset` switch to `RemovableLibraryQuerySet`.
`PlayEventQuerySet` gains `.alive()` in its `for_library`, beside the parent
condition Task 3 added:

```python
class PlayEventQuerySet(RemovableQuerySet):
    def for_library(self, library):
        return self.filter(game__library=library, game__removed_at__isnull=True).alive()
```

`SessionQuerySet` the same.

- [ ] **Step 4: Write the migration**

`0036_removable_records.py` — four `AddField`s, plus the preset constraint:

```python
(migrations.RemoveConstraint("filterpreset", "unique_library_mode_name_preset"),)
(
    migrations.AddConstraint(
        "filterpreset",
        models.UniqueConstraint(
            fields=("library", "mode", "name"),
            condition=models.Q(removed_at__isnull=True),
            name="unique_library_mode_name_preset",
        ),
    ),
)
```

Without the condition a removed preset holds its own name against the next one.

- [ ] **Step 5: Grow the registry**

```python
REMOVABLE_MODELS: tuple[type[Model], ...] = (
    Game,
    Session,
    PlayEvent,
    Purchase,
    FilterPreset,
)

_AFTER_STAMP: dict[type[Model], Callable[[Any], None]] = {
    Game: _recount_purchases,
    Session: lambda session: recalculate_playtime(session.game),
}
```

Import `recalculate_playtime` from `games.signals`. Then drop the `xfail` marker
from `tests/test_removal.py::test_a_session_removed_by_itself_stays_removed`.

- [ ] **Step 6: Audit the reverse accessors**

Nine reads reach a child without `for_library()`. Each takes `.alive()`:

```python
    counts = [
        (game.sessions.alive().count(), "session"),
        (game.purchases.alive().count(), "purchase"),
        (game.playevents.alive().count(), "play event"),
    ]
```

Run: `grep -rn "\.sessions\.\|\.playevents\.\|\.purchases\." --include=*.py games common | grep -v migrations`
Expected: every hit either chains `.alive()` or is inside `games/removal.py`,
where the count must see every row.

- [ ] **Step 7: Prove a removed session leaves the playtime**

```python
def test_removing_a_session_drops_the_playtime(owned_library):
    game = make_game(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=timezone.now(),
        timestamp_end=timezone.now() + timedelta(hours=2),
    )
    game.refresh_from_db()
    assert game.playtime == timedelta(hours=2)

    remove(Session.objects.get(game=game))

    game.refresh_from_db()
    assert game.playtime == timedelta(0)
```

- [ ] **Step 8: Run the tests**

Run: `make test ARGS="tests/test_removable_models.py tests/test_removal.py -x"`,
then `make check-fast`.
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Give every removable record a removed_at"
```

---

### Task 6: One confirmation helper, one verb in the copy

**Files:**
- Create: `games/views/removal.py`
- Delete: `games/views/deletion.py`, `games/views/retirement.py`
- Modify: `games/views/game.py`, `platform.py`, `device.py`, `session.py`,
  `playevent.py`, `purchase.py`
- Modify: `games/urls.py`, `games/views/returns.py`
- Modify: `games/writes/playergame.py`, `games/views/playergame_writes.py`
- Rename: `tests/test_deletion_helper.py` → `tests/test_removal_helper.py`

**Interfaces:**
- Consumes: `remove()`, `RemovePlayerGame`.
- Produces: `confirm_and_apply(...)` (unchanged signature, new home),
  `confirm_and_remove(request, instance, *, title, message, fallback,
  fallback_args=(), details=None, detail_url=None, action=None)`,
  `games.writes.playergame.untrack_game(user, game, *, correlation_id) -> None`,
  `games.views.playergame_writes.remove_game_for_request(request, game) -> bool`.

- [ ] **Step 1: Write the failing test**

In `tests/test_removal_helper.py`, keep the four `confirm_and_apply` tests and
replace the two `confirm_and_delete` ones:

```python
def test_confirm_and_remove_stamps_rather_than_destroys(client, owned_library):
    game = make_game(owned_library)

    client.post(reverse("games:remove_game", args=[game.pk]))

    game.refresh_from_db()
    assert game.removed_at is not None


def test_the_page_labels_its_button_remove(client, owned_library):
    game = make_game(owned_library)

    page = client.get(reverse("games:remove_game", args=[game.pk])).content.decode()

    assert "Remove" in page
    assert "kept out of sight" not in page
    assert "permanently" not in page.lower()
```

The game view dispatches, so mark these
`@pytest.mark.django_db(transaction=True)`.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_removal_helper.py -x"`
Expected: FAIL, `NoReverseMatch: 'remove_game' is not a valid view function`.

- [ ] **Step 3: Move the helper and write `confirm_and_remove`**

`games/views/removal.py` holds `confirm_and_apply()` verbatim from
`games/views/deletion.py`, plus:

```python
def confirm_and_remove(
    request: HttpRequest,
    instance: Model,
    *,
    title: str,
    message: str,
    fallback: UrlName,
    fallback_args: Sequence[Any] = (),
    details: Children = None,
    detail_url: str | None = None,
    action: Callable[[], object] | None = None,
) -> HttpResponse:
    """Confirm on GET, remove on POST, then return to the origin.

    `action` is for a record whose removal is more than a stamp: a
    game states a fact to its projection first.
    """
    return confirm_and_apply(
        request,
        action=action or partial(remove, instance),
        title=title,
        message=message,
        confirm_label="Remove",
        fallback=fallback,
        fallback_args=fallback_args,
        details=details,
        reject=detail_url,
    )
```

Delete `games/views/deletion.py` and `games/views/retirement.py`, including
`retention_message()` and its "kept out of sight rather than deleted" sentence.

- [ ] **Step 4: Write the two-write act for a game**

In `games/writes/playergame.py`:

```python
def untrack_game(user: User, game: Game, *, correlation_id: uuid.UUID) -> None:
    """State that the library no longer tracks the game."""
    _dispatch(user, RemovePlayerGame(game_id=game.pk), correlation_id=correlation_id)
```

Follow `track_game`'s existing body for how it dispatches and translates. In
`games/views/playergame_writes.py`:

```python
def remove_game_for_request(request: HttpRequest, game: Game) -> bool:
    """Untrack it, then take the catalog row out.

    This order, and no transaction around it: dispatch opens its own
    and refuses to nest. A failure between the two leaves a game no
    list shows, and running the act again completes it.
    """
    try:
        untrack_game(
            cast("User", request.user), game, correlation_id=new_correlation_id()
        )
    except PlayerGameWriteFailed as failure:
        messages.error(request, failure.message)
        return False
    remove(game)
    return True
```

- [ ] **Step 5: Rewrite the six views**

Every `confirm_and_retire`/`confirm_and_delete` call becomes
`confirm_and_remove`. The copy states the act and promises nothing:

```python
@login_required
def remove_game(request: HttpRequest, game_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
    return confirm_and_remove(
        request,
        game,
        title="Remove game",
        message=f"Remove {game.name} from your library?",
        details=_removed_with_game(game),
        fallback="games:list_games",
        detail_url=game.get_absolute_url(),
        action=partial(remove_game_for_request, request, game),
    )
```

The other five drop `noun=`/`label=` and lose the word "permanently":
*"Remove this session of {game}?"*, *"Remove this playthrough of {game}?"*,
*"Remove this purchase of {first_game}?"*, *"Remove {platform.name}?"*,
*"Remove {device.name}?"*. `_deleted_with_game` becomes `_removed_with_game`;
the platform and device detail lines keep their counts and say "become
platformless" and "lose their device" as before.

- [ ] **Step 6: Rename the six routes**

`game/<uuidv7:game_id>/delete` becomes `game/<uuidv7:game_id>/remove`, and so on
for the other five; `games:delete_game` becomes `games:remove_game`. Move all
six entries within the `ORIGIN_AWARE` and `CONFIRMATION` sets in
`games/views/returns.py`, whose completeness guard fails on a route it does not
name. An old bookmark breaks; #648 set that precedent.

Run: `grep -rn "delete_game\|delete_session\|delete_purchase\|delete_playevent\|delete_platform\|delete_device" --include=*.py --include=*.ts .`
Expected: no hits. Every `action_url("games:delete_…")` call site is in that
output before the sweep; Task 7 covers the tests and e2e that name them.

- [ ] **Step 7: Run the tests**

Run: `make test ARGS="tests/test_removal_helper.py -x"`, then `make check-fast`.
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Confirm and remove, in one helper and one word"
```

---

### Task 7: The API, `split_purchase` and the callers

**Files:**
- Modify: `games/api.py:255` (play event), `games/api.py:779` (preset)
- Modify: `games/views/purchase.py:674` (`split_purchase`)
- Rename: `e2e/test_retention_confirmation_e2e.py` →
  `e2e/test_removal_confirmation_e2e.py`
- Modify: `e2e/test_return_to_origin_e2e.py`,
  `tests/test_returns_classification.py`, `tests/test_paths_return_200.py`,
  `tests/test_api.py`

**Interfaces:**
- Consumes: Task 6's routes and `remove()`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

```python
def test_no_route_is_named_delete():
    from games.urls import urlpatterns

    assert not [
        pattern.name
        for pattern in urlpatterns
        if pattern.name and "delete" in pattern.name
    ]


def test_deleting_a_play_event_through_the_api_stamps_it(client, owned_library):
    play_event = make_play_event(owned_library)

    response = client.delete(f"/api/playevent/{play_event.pk}")

    assert response.status_code == 204
    play_event.refresh_from_db()
    assert play_event.removed_at is not None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_api.py -k stamps -x"`
Expected: FAIL, `PlayEvent matching query does not exist` — the row is gone.

- [ ] **Step 3: Stamp in the two API routes**

`DELETE /api/playevent/{id}` and `DELETE /api/presets/{id}` keep the HTTP verb —
it is the transport's word, not the domain's — and call `remove(instance)`
instead of `instance.delete()`. Both keep answering 204.

- [ ] **Step 4: Stamp the split bundle**

In `split_purchase`, `purchase.delete()` becomes `remove(purchase)`. The parts
carry the facts now; the bundle leaves the library rather than being destroyed.

- [ ] **Step 5: Sweep the callers of the renamed routes**

`tests/test_returns_classification.py`, `tests/test_paths_return_200.py` and
`e2e/test_return_to_origin_e2e.py` each name the six routes. Rename every
occurrence and every test function that carries the old verb.

- [ ] **Step 6: Walk a removal in a browser**

Rename `e2e/test_retention_confirmation_e2e.py` to
`e2e/test_removal_confirmation_e2e.py` and add the end-to-end claim the spec
asks for:

```python
def test_removing_a_game_empties_it_from_the_session_list(page, live_server, ...):
    """A removed game takes its sessions out of sight."""
    page.goto(f"{live_server.url}{reverse('games:remove_game', args=[game.pk])}")
    page.get_by_role("button", name="Remove").click()

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    expect(page.get_by_text(game.name)).to_have_count(0)
    assert Session.objects.filter(game=game).exists()
```

Follow the file's existing fixtures for the logged-in page and the seeded game.
Wait on the server-rendered list, never on an optimistic DOM update.

- [ ] **Step 7: Run the whole gate**

Run: `make check`
Expected: PASS, `e2e/` included. This is the first task whose e2e coverage can
break — `test_return_to_origin_e2e.py` names the renamed routes.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Stamp in the API and the split, and sweep the callers"
```

---

### Task 8: Refuse the old words, and say why

**Files:**
- Modify: `.vale/styles/Timetracker/Terminology.yml`,
  `.vale/styles/Timetracker/DiscouragedTerms.yml`
- Modify: `docs/vocabulary.md`, `docs/event-retention.md`, `CLAUDE.md`
- Modify: the #944 issue body (`gh issue edit`)

**Interfaces:**
- Consumes: every rename above.
- Produces: a build that fails on the refused words.

- [ ] **Step 1: Add the error patterns**

In `Terminology.yml`, beside the `fold` tokens:

```yaml
  # tombstone / tombstoned row — one act, one word, and it is remove
  - '(tomb)?stoned?\s+(a\s+|the\s+)?(row|record|game|platform|device)'
  - '(a|the)\s+tombstone\b'
  # archive the game / an archived record
  - 'archiv(e|es|ed|ing)\s+(a\s+|the\s+)?(row|record|game|session|purchase)'
  # delete the record — the domain sense only
  - 'delet(e|es|ed|ing)\s+(a\s+|the\s+)?(row|record|game|session|purchase|preset|play event|device|platform)'
  - 'permanently\s+delete'
```

`tombstone` and `archive` also go in `DiscouragedTerms.yml` at warning level.
**`delete` does not.** It is the right word for `.delete()`, a deleted branch and
a deleted file, and a bare-word rule would print hundreds of warnings that are
all correct usage. The narrow error patterns are the whole rule.

- [ ] **Step 2: Run the linter and purge what it finds**

Run: `make vale`
Expected: findings across `docs/`, `CLAUDE.md` and a few docstrings. Fix every
one in this commit — `make vale` fails on the first error, which is the point.

Two of the findings are this plan and its spec, which name the refused words on
purpose to say why they are refused. Both live under `docs/superpowers/`. Add
that directory to `.vale.ini`'s exclusions if it is not there already: a design
record describes the words a codebase gave up, and a linter that forbids naming
them makes the record unwritable.

- [ ] **Step 3: Write the vocabulary sections**

`docs/vocabulary.md` gets one section per word, in the existing shape: the
replacement, why the word is refused, an error table and a warning table. Say
that `tombstone` described a husk that no longer exists, that `archive` and
`remove` were two names for one act, and that `delete` now means Django's
`.delete()` alone.

- [ ] **Step 4: Rewrite the retention doc**

`docs/event-retention.md` keeps the reference index, the guard, the resolver,
the replay check and the purge exemption. Delete "The two outcomes", "What a
tombstone does" and "The confirmation page". The naming section takes
`removed_at` as its example. Add a short section saying a referenced row is
never destroyed by any screen, so the guard's job is now the shell and the
script alone.

`CLAUDE.md` follows: the `GameStatusChange` and `PlayerGame` bullets, the
deletion convention ("No route mutates on GET" now names
`confirm_and_remove()`), and the models table.

- [ ] **Step 5: Edit the issue**

```bash
gh issue edit 944 --repo KucharczykL/timetracker --body-file /tmp/944.md
```

Two changes: strike "Removing anything offers an undo" from Acceptance and
record that #695 owns it, widened past Session; and note that the PlayerGame
archive machinery was renamed rather than deleted, with the reason — a
projection column exists only if an event states it.

- [ ] **Step 6: Run the gate**

Run: `make check`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Refuse tombstone, archive and the domain delete"
```

---

## Final verification

- [ ] `make check` is green, `e2e/` included, from a clean tree.
- [ ] `grep -rli "tombston\|archiv" --include=*.py --include=*.ts --include=*.md .`
      returns only: the four historical migrations (`0027`, `0028`, `0032`,
      `0033`), `tests/test_playergame_backfill_migration.py`, and the four
      files that mean a tar archive or Postgres archive mode
      (`scripts/db_dump.py`, `scripts/ensure_postgres.py`,
      `tests/test_db_dump.py`, `tests/test_ensure_postgres.py`).
- [ ] `make audit-uuid-identity` passes.
- [ ] `make reset-db` replays the whole graph, the two edited event-era
      migrations included, and `make migrate` then applies 0036 on top.
- [ ] Every acceptance line in #944 is answered, except the undo line the issue
      edit moves to #695.
