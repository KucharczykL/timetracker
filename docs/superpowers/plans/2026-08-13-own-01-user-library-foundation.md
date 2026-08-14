# OWN-01 UserLibrary Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the unused one-to-one `UserLibrary` identity and provision it for newly created users without changing any existing data access.

**Architecture:** `UserLibrary` is a small identity record backed by the repository's reusable PostgreSQL-aware `UUIDv7Field`, a one-to-one User owner, and an explicitly preservable creation timestamp. A User `post_save` receiver creates the record only for newly created, non-raw Users. Existing Users and global game data remain untouched until the coordinated #630 cutover.

**Tech Stack:** Python 3.14, Django 6 models/signals/migrations, PostgreSQL 18 and the `uuid_v7` domain introduced by #639, pytest-django.

## Global Constraints

- #639 is merged as `games.0002_uuid_v7_domain`; use `timetracker.uuidv7.UUIDv7Field` rather than defining another UUID default, validator, or field.
- The model is named `UserLibrary`, never `PlayerLibrary` or bare `Library`.
- Do not scope any existing query, add an ownership FK to existing private data, provision `UserPreferences`, or add compatibility behavior in this issue.
- Do not backfill any existing User in the schema migration.
- `created_at` must default on ordinary creation but preserve an explicitly supplied restore or migration timestamp.
- Ordinary ORM User creation is supported; raw fixture saves and `bulk_create()` deliberately do not provision libraries.
- Drive setup, code generation, migrations, and tests through Make targets. Do not invoke `uv`, `pnpm`, `pytest`, or `manage.py` directly.
- Keep the normal parallel `PYTEST_WORKERS`; run the full `make check` gate through the managed hidden Windows process required by `AGENTS.md`.

## File Structure

- `games/models.py` defines the new identity record and imports the existing UUIDv7 field.
- `games/migrations/0003_userlibrary.py` contains the additive `CreateModel` operation and depends on `0002_uuid_v7_domain`.
- `games/signals.py` owns ordinary User provisioning and no other creation path.
- `tests/test_user_library.py` covers the model contract, supported and unsupported provisioning paths, and the schema-only migration boundary.
- `tests/test_signals.py` proves a real raw fixture load does not provision a library.

## Planning-Time Handoff

The companion #630 plan now consumes `games.0003_userlibrary` and creates
`games.0004_user_library_ownership_cutover`. This planning-only renumbering is
already applied; #629 implementation does not need to edit the #630 plan.

---

### Task 1: Add the UserLibrary model and additive migration

**Files:**
- Modify: `games/models.py:571`
- Create: `games/migrations/0003_userlibrary.py`
- Create: `tests/test_user_library.py`

**Interfaces:**
- Consumes: `timetracker.uuidv7.UUIDv7Field` and migration state `games.0002_uuid_v7_domain`.
- Produces: `UserLibrary(id: UUID, user: User, created_at: datetime)` and the reverse relation `user.library`.

- [ ] **Step 1: Write model-contract tests that remain valid after provisioning is added**

```python
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from games.models import UserLibrary


def create_user_without_signals(username: str) -> User:
    return User.objects.bulk_create([User(username=username)])[0]


@pytest.mark.django_db
def test_user_library_uses_uuid7_and_preserves_explicit_created_at():
    owner = create_user_without_signals("owner")
    library = UserLibrary.objects.create(user=owner)
    assert isinstance(library.pk, UUID)
    assert library.pk.version == 7

    restored_at = datetime(
        2022,
        12,
        31,
        14,
        18,
        27,
        tzinfo=ZoneInfo("Europe/Prague"),
    )
    restored_owner = create_user_without_signals("restored")
    restored = UserLibrary.objects.create(
        user=restored_owner,
        created_at=restored_at,
    )
    restored.refresh_from_db()
    assert restored.created_at == restored_at


@pytest.mark.django_db
def test_user_library_is_one_to_one_and_cascades_with_user():
    user = create_user_without_signals("one-to-one")
    library_id = UserLibrary.objects.create(user=user).pk

    with pytest.raises(IntegrityError), transaction.atomic():
        UserLibrary.objects.create(user=user)

    user.delete()
    assert not UserLibrary.objects.filter(pk=library_id).exists()
```

The helper intentionally uses the unsupported bulk path to isolate the model contract. It also prevents these tests from trying to create a second library after Task 2 connects automatic provisioning.

- [ ] **Step 2: Run the focused tests and confirm the missing-model failure**

Run: `make test-fast ARGS="tests/test_user_library.py -x"`

Expected: test collection fails because `games.models.UserLibrary` does not exist.

- [ ] **Step 3: Implement the minimal model**

Add the import near the other project imports in `games/models.py`:

```python
from timetracker.uuidv7 import UUIDv7Field
```

Add the model immediately before `UserPreferences`:

```python
class UserLibrary(models.Model):
    id = UUIDv7Field(primary_key=True, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="library",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self) -> str:
        return str(self.id)
```

`UUIDv7Field` supplies both the Python `uuid.uuid7` default and PostgreSQL `uuidv7()` database default, validates version 7 at the application boundary, and stores the column as the `uuid_v7` domain created by migration `0002_uuid_v7_domain`.

- [ ] **Step 4: Generate the migration through Make**

Run: `make makemigrations`

Expected: Django creates `games/migrations/0003_userlibrary.py`.

- [ ] **Step 5: Inspect the generated migration contract**

The migration must:

```python
dependencies = [
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ("games", "0002_uuid_v7_domain"),
]
```

Its only operation must be `migrations.CreateModel(name="UserLibrary", ...)`, with `id` represented by `timetracker.uuidv7.UUIDv7Field`, the one-to-one User field using `on_delete=CASCADE` and `related_name="library"`, and `created_at` using `django.utils.timezone.now`. It must contain no `RunPython`, `RunSQL`, or other operation that could create a library for an existing User.

- [ ] **Step 6: Run the model tests**

Run: `make test-fast ARGS="tests/test_user_library.py -x"`

Expected: all model-contract tests pass.

- [ ] **Step 7: Verify model/migration drift**

Run: `make check-migrations`

Expected: `No changes detected`.

- [ ] **Step 8: Commit the identity model**

```bash
git add games/models.py games/migrations/0003_userlibrary.py tests/test_user_library.py
git commit -m "feat: add UserLibrary identity (#629)"
```

### Task 2: Provision one library for supported User creation

**Files:**
- Modify: `games/signals.py:1`
- Modify: `tests/test_user_library.py`
- Modify: `tests/test_signals.py:1`

**Interfaces:**
- Consumes: `UserLibrary`, Django's User `post_save` `created`/`raw` contract, and the existing `GamesConfig.ready()` signal import.
- Produces: `provision_user_library(sender, instance, created, raw=False, **kwargs) -> None`.

- [ ] **Step 1: Add failing ordinary, repeated-save, and bulk-creation tests**

Append to `tests/test_user_library.py`:

```python
@pytest.mark.django_db
def test_new_user_eagerly_gets_exactly_one_library():
    user = User.objects.create_user("new-user")
    assert UserLibrary.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_saving_existing_user_does_not_replace_library():
    user = User.objects.create_user("existing")
    library_id = UserLibrary.objects.get(user=user).pk

    user.email = "new@example.com"
    user.save(update_fields=["email"])

    assert UserLibrary.objects.get(user=user).pk == library_id
    assert UserLibrary.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_bulk_created_user_has_no_implicit_library():
    user = User.objects.bulk_create([User(username="bulk")])[0]
    assert not UserLibrary.objects.filter(user=user).exists()
```

- [ ] **Step 2: Extend the real fixture-load test for `raw=True`**

Add these imports to `tests/test_signals.py`:

```python
from django.contrib.auth import get_user_model

from games.models import Game, GameStatusChange, Session, UserLibrary
```

Append this method to `RawFixtureLoadTest`:

```python
def test_user_fixture_does_not_provision_a_library(self):
    user = get_user_model().objects.create_user(username="fixture-user")
    user_id = user.pk
    fixture = self._write_fixture([user])

    user.delete()
    call_command("loaddata", fixture, verbosity=0)

    restored_user = get_user_model().objects.get(pk=user_id)
    self.assertFalse(UserLibrary.objects.filter(user=restored_user).exists())
```

Before the receiver exists, the fixture assertion is already green; the ordinary-creation assertion from Step 1 is the intentional red test. After the receiver exists, this fixture test prevents accidentally dropping the raw guard.

- [ ] **Step 3: Run the focused tests and confirm ordinary provisioning fails**

Run: `make test-fast ARGS="tests/test_user_library.py tests/test_signals.py -x"`

Expected: `test_new_user_eagerly_gets_exactly_one_library` fails with a count of `0`.

- [ ] **Step 4: Add the created-only, raw-safe receiver**

Add `settings` and `UserLibrary` to `games/signals.py` imports, then add:

```python
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def provision_user_library(sender, instance, created, raw=False, **kwargs) -> None:
    if raw or not created:
        return
    UserLibrary.objects.get_or_create(user=instance)
```

Do not connect a second receiver in `games/apps.py`; `GamesConfig.ready()` already imports `games.signals`. Do not create `UserPreferences` here—#630 owns the final three-record provisioning invariant.

- [ ] **Step 5: Run signal and model tests**

Run: `make test-fast ARGS="tests/test_user_library.py tests/test_signals.py -x"`

Expected: ordinary creation provisions one row, later saves preserve it, and raw/bulk paths remain unprovisioned.

- [ ] **Step 6: Commit automatic creation**

```bash
git add games/signals.py tests/test_user_library.py tests/test_signals.py
git commit -m "feat: provision libraries for new users (#629)"
```

### Task 3: Prove the migration is behaviorally dormant

**Files:**
- Modify: `tests/test_user_library.py`

**Interfaces:**
- Consumes: migration states `games.0002_uuid_v7_domain` and `games.0003_userlibrary` plus the complete Task 2 runtime receiver.
- Produces: regression coverage that distinguishes a pre-existing User from a post-deployment User.

- [ ] **Step 1: Add a migration-state regression test**

Add these imports and constants to `tests/test_user_library.py`:

```python
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE_LIBRARY = ("games", "0002_uuid_v7_domain")
WITH_LIBRARY = ("games", "0003_userlibrary")
```

Append the test:

```python
@pytest.mark.django_db(transaction=True)
def test_user_library_migration_does_not_backfill_existing_users():
    try:
        executor = MigrationExecutor(connection)
        executor.migrate([BEFORE_LIBRARY])
        old_apps = executor.loader.project_state([BEFORE_LIBRARY]).apps
        LegacyUser = old_apps.get_model("auth", "User")
        legacy_user = LegacyUser.objects.create(username="legacy")
        legacy_user_id = legacy_user.pk

        executor = MigrationExecutor(connection)
        executor.migrate([WITH_LIBRARY])
        new_apps = executor.loader.project_state([WITH_LIBRARY]).apps
        HistoricalUserLibrary = new_apps.get_model("games", "UserLibrary")
        assert not HistoricalUserLibrary.objects.filter(user_id=legacy_user_id).exists()

        runtime_user = get_user_model().objects.create_user("post-deployment")
        assert UserLibrary.objects.filter(user=runtime_user).count() == 1
    finally:
        MigrationExecutor(connection).migrate([WITH_LIBRARY])
```

The historical User class avoids firing the current runtime receiver while the `UserLibrary` table is absent. The runtime User created after the target migration exercises the real receiver.

- [ ] **Step 2: Run the migration regression**

Run: `make test-fast ARGS="tests/test_user_library.py -k migration -x"`

Expected: the legacy User has no library and the post-deployment User has exactly one.

- [ ] **Step 3: Run the complete verification gate**

Run `make check` through a managed hidden Windows process and wait for its final log and exit status.

Expected: exit `0`, with the repository's default parallel pytest worker count and the complete unit, TypeScript, migration, and browser suites passing.

- [ ] **Step 4: Commit dormancy coverage**

```bash
git add tests/test_user_library.py
git commit -m "test: lock UserLibrary deployment boundary (#629)"
```
