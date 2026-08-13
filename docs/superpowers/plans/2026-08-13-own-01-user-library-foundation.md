# OWN-01 UserLibrary Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the unused one-to-one `UserLibrary` identity and provision it for newly created users without changing any existing data access.

**Architecture:** `UserLibrary` is a small identity record with a UUIDv7 primary key, one-to-one User owner, and explicitly preservable creation timestamp. A User `post_save` receiver creates it only for newly created non-raw Users. Existing production data is deliberately untouched until the coordinated #630 cutover.

**Tech Stack:** Python 3.14 stdlib UUIDv7 convention from #639, Django 6 models/signals/migrations, pytest-django, PostgreSQL 17.

## Global Constraints

- #639 must be merged first; consume its approved UUIDv7 callable rather than defining another helper.
- The model is named `UserLibrary`, never `PlayerLibrary` or bare `Library`.
- Do not scope any existing query, add any ownership FK, or add compatibility behavior in this issue.
- Do not backfill the existing production User in this migration.
- `created_at` must default on ordinary creation but accept an explicit restored/migrated value.
- Raw fixtures and bulk User creation are unsupported and must not be disguised as working.
- Keep the normal parallel `PYTEST_WORKERS`; run full verification through the managed hidden Windows process required by `AGENTS.md`.

---

### Task 1: Add the UserLibrary model and schema migration

**Files:**
- Modify: `games/models.py`
- Create: `games/migrations/0002_user_library.py`
- Create: `tests/test_user_library.py`

**Interfaces:**
- Consumes: the UUIDv7 default callable established by #639.
- Produces: `UserLibrary(id: UUID, user: User, created_at: datetime)` and `user.library`.

- [ ] **Step 1: Write model-contract tests**

```python
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from games.models import UserLibrary


@pytest.mark.django_db
def test_user_library_uses_uuid7_and_preserves_explicit_created_at():
    user = User.objects.create_user("owner")
    library = UserLibrary.objects.create(user=user)
    assert isinstance(library.pk, UUID)
    assert library.pk.version == 7

    restored_at = datetime(2022, 12, 31, 14, 18, 27, tzinfo=ZoneInfo("Europe/Prague"))
    other = User.objects.create_user("restored")
    UserLibrary.objects.filter(user=other).delete()
    restored = UserLibrary.objects.create(user=other, created_at=restored_at)
    assert restored.created_at == restored_at


@pytest.mark.django_db
def test_user_library_is_one_to_one_and_cascades_with_user():
    user = User.objects.create_user("owner")
    library_id = UserLibrary.objects.create(user=user).pk
    with pytest.raises(IntegrityError), transaction.atomic():
        UserLibrary.objects.create(user=user)
    user.delete()
    assert not UserLibrary.objects.filter(pk=library_id).exists()
```

- [ ] **Step 2: Run the focused tests and confirm the missing model failure**

Run: `make test-fast ARGS="tests/test_user_library.py -x"`

Expected: collection fails because `UserLibrary` does not exist.

- [ ] **Step 3: Implement the minimal model**

Use the exact UUIDv7 callable exported by #639 in place of `uuid7_default` below:

```python
class UserLibrary(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7_default, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="library",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self) -> str:
        return str(self.id)
```

Generate `0002_user_library.py` with `makemigrations`. Inspect it and ensure it
contains only `CreateModel`; it must not contain `RunPython` or touch existing
Users.

- [ ] **Step 4: Run migration and model tests**

Run: `make test-fast ARGS="tests/test_user_library.py -x"`

Expected: PASS.

- [ ] **Step 5: Commit the model**

```bash
git add games/models.py games/migrations/0002_user_library.py tests/test_user_library.py
git commit -m "feat: add UserLibrary identity (#629)"
```

### Task 2: Provision libraries for newly created Users

**Files:**
- Modify: `games/signals.py`
- Modify: `tests/test_user_library.py`
- Modify: `tests/test_signals.py`

**Interfaces:**
- Consumes: `UserLibrary` from Task 1 and Django's User `post_save` `created: bool` contract.
- Produces: `provision_user_library(sender, instance, created, raw, **kwargs) -> None`.

- [ ] **Step 1: Add failing provisioning tests**

```python
@pytest.mark.django_db
def test_new_user_eagerly_gets_one_library():
    user = User.objects.create_user("new-user")
    assert UserLibrary.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_saving_existing_user_does_not_replace_library():
    user = User.objects.create_user("existing")
    library_id = user.library.pk
    user.email = "new@example.com"
    user.save(update_fields=["email"])
    assert user.library.pk == library_id
    assert UserLibrary.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_bulk_created_user_has_no_implicit_library():
    user = User.objects.bulk_create([User(username="bulk")])[0]
    assert not UserLibrary.objects.filter(user=user).exists()
```

Extend the existing fixture-signal tests to prove `raw=True` does not create a
library as a side effect.

- [ ] **Step 2: Run the focused tests and confirm provisioning fails**

Run: `make test-fast ARGS="tests/test_user_library.py tests/test_signals.py -x"`

Expected: the ordinary-creation assertion fails.

- [ ] **Step 3: Add the idempotent created-only receiver**

```python
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def provision_user_library(sender, instance, created, raw=False, **kwargs):
    if raw or not created:
        return
    UserLibrary.objects.get_or_create(user=instance)
```

Import Django settings and `UserLibrary` in `games/signals.py`. Do not connect a
second receiver in `apps.py`; `GamesConfig.ready()` already imports the signal
module once.

- [ ] **Step 4: Run signal and model tests**

Run: `make test-fast ARGS="tests/test_user_library.py tests/test_signals.py -x"`

Expected: PASS.

- [ ] **Step 5: Commit automatic creation**

```bash
git add games/signals.py tests/test_user_library.py tests/test_signals.py
git commit -m "feat: provision libraries for new users (#629)"
```

### Task 3: Prove the foundation is behaviorally dormant

**Files:**
- Modify: `tests/test_user_library.py`
- Modify: `docs/configuration.md`

**Interfaces:**
- Consumes: the complete #629 model/signal behavior.
- Produces: deployment documentation stating that existing Users are backfilled only by #630.

- [ ] **Step 1: Add a migration-state regression test**

Use `MigrationExecutor` to migrate from `0001_squashed_0036_alter_playevent_days_to_finish`
to `0002_user_library`, create one legacy User in the old app state, and assert
the new migration does not create a UserLibrary for it. Then create a User with
the runtime model and assert the signal does.

- [ ] **Step 2: Run the migration regression**

Run: `make test-fast ARGS="tests/test_user_library.py -k migration -x"`

Expected: PASS after the Task 1 migration remains schema-only.

- [ ] **Step 3: Document the deployment boundary**

Add a short upgrade note to `docs/configuration.md`:

```markdown
`0002_user_library` creates libraries for Users created after deployment. It
does not claim or scope existing data. Do not create or assign a production
library manually; the rehearsed OWN cutover migration owns that operation.
```

- [ ] **Step 4: Run the complete gate**

Run the managed hidden Windows `make check` process and wait for its final exit
status and log.

Expected: exit 0 with the repository's default parallel worker count.

- [ ] **Step 5: Commit verification documentation**

```bash
git add tests/test_user_library.py docs/configuration.md
git commit -m "docs: define UserLibrary foundation boundary (#629)"
```
