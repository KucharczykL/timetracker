# Settings Command Layer (#487) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route personal and site setting writes through one explicit command layer that returns an operation-aware `SettingMutation`, fix the clear-vs-lock bug, and add a registry-driven write-time validator — without weakening the read-only resolver.

**Architecture:** `timetracker/settings_commands.py` becomes the sole write boundary with two symmetric commands (`change_site_setting`, `change_user_setting`), each returning a `SettingMutation` envelope. Effective-after-write state is computed by a new uncached, best-effort fall-through helper in the resolver so no just-written layer is read back and no uncommitted row leaks into the global snapshot cache. A new `write_validator` slot on `SettingDefinition` holds the DEFAULT_DEVICE existence check, invoked on SET by both commands.

**Tech Stack:** Django 6, Django Ninja, SQLite (WAL), pytest / pytest-django. Python 3.14 (`except A, B:` PEP 758 syntax; interpreter MUST be 3.14.x).

## Global Constraints

- Run every command inside the Nix dev shell: prefix with `direnv exec .` (e.g. `direnv exec . uv run pytest ...`). A bare `pytest`/`make` outside it has no `pnpm` and silently breaks the build. In a fresh worktree run `direnv allow .` once first.
- **Step 0 (before Task 1):** rebase this branch onto `origin/main` — `git fetch origin && git rebase origin/main` — worktrees are cut from possibly-stale main.
- Never write a `GeneratedField`. N/A here but repo-wide.
- Name compound/primitive roles explicitly (TypedDict/NamedTuple/PEP 695 alias), unabbreviated identifiers (`definition` not `def_`, `value` not `v`).
- Verification gate before "done"/PR: full `direnv exec . make check` (lint + format-check + mypy + ts-check + vitest + entire pytest incl. `e2e/`) green. Never a hand-picked subset.
- Backend-pure: no TypeScript / HTTP-response-shape changes in this issue. `_setting_out` output stays byte-identical.
- Commit style: end messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

**Spec:** design doc verified against shipped code post-merge (matched faithfully) and removed; see `timetracker/settings_commands.py` and `timetracker/settings_resolver.py` for the authoritative contract.

---

### Task 1: `write_validator` slot + DEFAULT_DEVICE referential validator

**Files:**
- Modify: `timetracker/settings_registry.py` (add slot at end of `SettingDefinition`; add validator fn; wire DEFAULT_DEVICE)
- Test: `tests/test_settings_commands.py`

**Interfaces:**
- Produces: `SettingWriteValidator` type alias = `Callable[[object], None]`; `SettingDefinition.write_validator: SettingWriteValidator | None = None` (appended last); `get_definition("DEFAULT_DEVICE").write_validator` is set, every other registered definition's is `None`. The validator raises `django.core.exceptions.ValidationError` for a missing device id, returns `None` otherwise.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_settings_commands.py`:

```python
from timetracker.settings_registry import (
    SETTINGS_REGISTRY,
    get_definition,
)


@pytest.mark.django_db
def test_default_device_write_validator_rejects_missing_device():
    from django.core.exceptions import ValidationError

    validator = get_definition("DEFAULT_DEVICE").write_validator
    assert validator is not None
    with pytest.raises(ValidationError):
        validator(9_999_999)  # no such device


def test_only_default_device_declares_a_write_validator():
    with_validator = [
        key
        for key, definition in SETTINGS_REGISTRY.items()
        if definition.write_validator is not None
    ]
    assert with_validator == ["DEFAULT_DEVICE"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `direnv exec . uv run pytest tests/test_settings_commands.py::test_only_default_device_declares_a_write_validator -v`
Expected: FAIL — `AttributeError: 'SettingDefinition' object has no attribute 'write_validator'`.

- [ ] **Step 3: Add the slot + type alias**

In `timetracker/settings_registry.py`, add the alias near the other `type` aliases (after line 27):

```python
type SettingWriteValidator = Callable[[object], None]  # write-time referential check; raises on failure
```

Append the field as the **last** field of `SettingDefinition` (after `note: str = ""`, line 102):

```python
    write_validator: SettingWriteValidator | None = None
```

- [ ] **Step 4: Add the referential validator and wire DEFAULT_DEVICE**

Add near `_validate_optional_device_id` (after line ~135):

```python
def _require_existing_device(value: object) -> None:
    """Write-time referential check for DEFAULT_DEVICE: the id must name a live
    Device. Read paths never call this (a dangling stored id degrades to the
    default instead of raising — see #492)."""
    if value is None:
        return
    from games.models import Device

    if not Device.objects.filter(pk=value).exists():
        raise ValidationError(f"No device with id {value!r}.")
```

In the DEFAULT_DEVICE `SettingDefinition(...)` (the block with `validator=_validate_optional_device_id`, ~line 210-218) add:

```python
            write_validator=_require_existing_device,
```

- [ ] **Step 5: Run to verify pass**

Run: `direnv exec . uv run pytest tests/test_settings_commands.py -k write_validator_rejects_missing_device -v`
and `direnv exec . uv run pytest tests/test_settings_commands.py::test_only_default_device_declares_a_write_validator -v`
Expected: PASS both.

- [ ] **Step 6: Commit**

```bash
git add timetracker/settings_registry.py tests/test_settings_commands.py
git commit -m "feat(settings): add write_validator slot; DEFAULT_DEVICE existence check

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `SettingMutation` envelope + uncached best-effort fall-through helper

**Files:**
- Modify: `timetracker/settings_resolver.py` (add `resolve_fallthrough_uncached`; export it)
- Modify: `timetracker/settings_commands.py` (add `SettingOperation`, `SettingMutation`)
- Test: `tests/test_settings_commands.py`

**Interfaces:**
- Produces:
  - `SettingOperation(StrEnum)` with `SET = "set"`, `CLEAR = "clear"`.
  - `SettingMutation(NamedTuple)` = `(effective: ResolvedSetting, operation: SettingOperation, changed: bool, stored: object | None, stored_present: bool)`.
  - `resolve_fallthrough_uncached(key: SettingKey, *, skip_db: bool) -> ResolvedSetting` — resolves ignoring the personal layer and (if `skip_db`) the site DB layer, WITHOUT populating the module snapshot cache; best-effort (a malformed consulted value degrades to `default_factory()`/`DEFAULT`/`locked=False` rather than raising).

- [ ] **Step 1: Write the failing test for the helper**

Add to `tests/test_settings_commands.py`:

```python
from timetracker.config import SettingSource


@pytest.mark.django_db
def test_fallthrough_uncached_skip_db_uses_env_normalized(settings, monkeypatch):
    from timetracker.settings_resolver import resolve_fallthrough_uncached

    # env shadows DEFAULT_PAGE_SIZE with a string; must come back as a normalized int.
    monkeypatch.setenv("DEFAULT_PAGE_SIZE", "100")
    config_module._env_file_cache = None  # env is read live; no file cache interference
    resolved = resolve_fallthrough_uncached("DEFAULT_PAGE_SIZE", skip_db=True)
    assert resolved.value == 100
    assert resolved.source == SettingSource.ENV
    assert resolved.locked is True


@pytest.mark.django_db
def test_fallthrough_uncached_degrades_malformed_locked_env_to_default(monkeypatch):
    from timetracker.settings_resolver import resolve_fallthrough_uncached
    from timetracker.settings_registry import get_definition

    monkeypatch.setenv("DEFAULT_PAGE_SIZE", "not-a-number")
    resolved = resolve_fallthrough_uncached("DEFAULT_PAGE_SIZE", skip_db=True)
    assert resolved.value == get_definition("DEFAULT_PAGE_SIZE").default_factory()
    assert resolved.source == SettingSource.DEFAULT
    assert resolved.locked is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `direnv exec . uv run pytest tests/test_settings_commands.py -k fallthrough_uncached -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_fallthrough_uncached'`.

- [ ] **Step 3: Implement the helper**

In `timetracker/settings_resolver.py`, add after `resolve_with_origin` (~line 194):

```python
def resolve_fallthrough_uncached(key: SettingKey, *, skip_db: bool) -> ResolvedSetting:
    """Resolve ``key`` ignoring the personal layer and (when ``skip_db``) the site DB
    layer, WITHOUT populating the module snapshot cache. Best-effort: a malformed value
    in a consulted layer degrades to the default rather than raising.

    The command layer uses this to compute post-CLEAR effective state — it must not
    read back the just-deleted layer, and must not leak an outer transaction's
    uncommitted site row into the shared cache (issue #487)."""
    definition = get_definition(key)
    raw = resolve_raw_with_source(
        definition.env_name or definition.key, allow_file=definition.allow_file
    )
    if raw is not None:
        try:
            value = normalize_setting_value(raw.raw, definition)
        except (ValidationError, ValueError, TypeError):
            return ResolvedSetting(
                definition.default_factory(), SettingSource.DEFAULT, False
            )
        return ResolvedSetting(value, raw.source, raw.source in LOCKED_SOURCES)

    if not skip_db and definition.scope in (SettingScope.SITE, SettingScope.USER):
        from games.models import SiteSetting

        stored = (
            SiteSetting.objects.filter(key=key)
            .values_list("value", flat=True)
            .first()
        )
        if stored is not None:
            try:
                value = normalize_setting_value(stored, definition)
            except (ValidationError, ValueError, TypeError):
                pass
            else:
                return ResolvedSetting(value, SettingSource.DATABASE, False)

    return ResolvedSetting(definition.default_factory(), SettingSource.DEFAULT, False)
```

Add `"resolve_fallthrough_uncached",` to that module's `__all__` (line ~280-293).

- [ ] **Step 4: Run to verify pass**

Run: `direnv exec . uv run pytest tests/test_settings_commands.py -k fallthrough_uncached -v`
Expected: PASS both.

- [ ] **Step 5: Add the envelope types**

In `timetracker/settings_commands.py`, add imports and types near the top (after the existing imports, before `SettingLockedError`):

```python
from enum import StrEnum
from typing import NamedTuple


class SettingOperation(StrEnum):
    SET = "set"
    CLEAR = "clear"


class SettingMutation(NamedTuple):
    effective: ResolvedSetting
    operation: SettingOperation
    changed: bool
    stored: object | None
    stored_present: bool
```

(`ResolvedSetting` is already imported from `timetracker.config` in this module.)

- [ ] **Step 6: Commit**

```bash
git add timetracker/settings_resolver.py timetracker/settings_commands.py tests/test_settings_commands.py
git commit -m "feat(settings): SettingMutation envelope + uncached fall-through helper

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `change_site_setting` returns `SettingMutation` (clear-vs-lock fix, no-op short-circuit, write_validator)

**Files:**
- Modify: `timetracker/settings_commands.py` (rewrite `change_site_setting` body + `__all__`)
- Test: `tests/test_settings_commands.py` (update existing `ResolvedSetting`-return assertions to `SettingMutation`; add new coverage)

**Interfaces:**
- Consumes: Task 1 `write_validator`; Task 2 `SettingOperation`, `SettingMutation`, `resolve_fallthrough_uncached`.
- Produces: `change_site_setting(key, value) -> SettingMutation`. Raises `SettingLockedError` only on SET under a locked source; `ValidationError`/`ValueError`/`TypeError` for bad value/scope; `UnregisteredSettingError` for an unknown key (from `get_definition`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings_commands.py`:

```python
import timetracker.settings_commands as commands_module
from timetracker.settings_commands import (
    SettingMutation,
    SettingOperation,
    change_site_setting,
)


@pytest.mark.django_db
def test_site_set_then_noop_set_distinguishable():
    first = change_site_setting("DEFAULT_CURRENCY", "eur")
    assert first.operation is SettingOperation.SET
    assert first.changed is True
    assert first.effective == ResolvedSetting("EUR", SettingSource.DATABASE, False)

    second = change_site_setting("DEFAULT_CURRENCY", "EUR")
    assert second.operation is SettingOperation.SET
    assert second.changed is False  # already stored
    assert second.stored_present is True


@pytest.mark.django_db
def test_site_clear_then_noop_clear_distinguishable():
    change_site_setting("DEFAULT_CURRENCY", "eur")
    cleared = change_site_setting("DEFAULT_CURRENCY", None)
    assert cleared.operation is SettingOperation.CLEAR
    assert cleared.changed is True
    assert cleared.stored_present is False

    noop = change_site_setting("DEFAULT_CURRENCY", None)
    assert noop.changed is False


@pytest.mark.django_db
def test_site_clear_allowed_under_env_lock_and_reports_env_effective(monkeypatch):
    from games.models import SiteSetting

    SiteSetting.objects.create(key="DEFAULT_PAGE_SIZE", value=50)
    monkeypatch.setenv("DEFAULT_PAGE_SIZE", "100")  # ENV is a locked source
    settings_resolver.clear_cache()

    result = change_site_setting("DEFAULT_PAGE_SIZE", None)  # must NOT raise
    assert result.changed is True
    assert not SiteSetting.objects.filter(key="DEFAULT_PAGE_SIZE").exists()
    assert result.effective.value == 100  # normalized int, from env
    assert result.effective.source == SettingSource.ENV
    assert result.effective.locked is True


@pytest.mark.django_db
def test_site_set_under_env_lock_still_raises(monkeypatch):
    from timetracker.settings_commands import SettingLockedError

    monkeypatch.setenv("DEFAULT_PAGE_SIZE", "100")
    settings_resolver.clear_cache()
    with pytest.raises(SettingLockedError):
        change_site_setting("DEFAULT_PAGE_SIZE", 50)


@pytest.mark.django_db
def test_site_clear_repairs_poisoned_row(monkeypatch):
    from games.models import SiteSetting

    SiteSetting.objects.create(key="DEFAULT_PAGE_SIZE", value="garbage")
    result = change_site_setting("DEFAULT_PAGE_SIZE", None)  # must NOT raise
    assert result.changed is True
    assert not SiteSetting.objects.filter(key="DEFAULT_PAGE_SIZE").exists()


@pytest.mark.django_db
def test_site_noop_fires_no_cache_invalidation(monkeypatch):
    from django.db import transaction

    change_site_setting("DEFAULT_CURRENCY", "eur")
    calls: list[int] = []
    monkeypatch.setattr(settings_resolver, "clear_cache", lambda: calls.append(1))
    with transaction.atomic():
        change_site_setting("DEFAULT_CURRENCY", "EUR")  # no-op
    assert calls == []  # no post_save -> no on_commit clear
```

**Also update** the existing assertions that expect a raw `ResolvedSetting` return
from `change_site_setting`:
- `test_rolled_back_command_returns_canonical_without_caching_uncommitted_data`
  (~line 338): `result = change_site_setting("DEFAULT_CURRENCY", "eur")` then change
  `assert result == ResolvedSetting("EUR", SettingSource.DATABASE, False)` to
  `assert result.effective == ResolvedSetting("EUR", SettingSource.DATABASE, False)`.
- The endpoint mock `fake_change_site_setting` (~line 394): make it return a
  `SettingMutation(ResolvedSetting("EUR", SettingSource.DATABASE, False),
  SettingOperation.SET, True, "EUR", True)` instead of a bare `ResolvedSetting`.
- Any assertion in the site contract matrix comparing `change_site_setting(...)`
  directly to a `ResolvedSetting` → compare `.effective`.

- [ ] **Step 2: Run to verify failures**

Run: `direnv exec . uv run pytest tests/test_settings_commands.py -k "site_set_then_noop or site_clear_then_noop or clear_allowed_under_env or clear_repairs_poisoned" -v`
Expected: FAIL — current `change_site_setting` returns `ResolvedSetting`, raises on locked clear, has no `changed`.

- [ ] **Step 3: Rewrite `change_site_setting`**

Replace the body (`timetracker/settings_commands.py` lines ~35-69) with:

```python
def change_site_setting(key: SettingKey, value: object | None) -> SettingMutation:
    """Set or clear a validated site default; return an operation-aware envelope.

    Lock guards SET only — a CLEAR removes the DB row even when a locked source
    (env/file/dotenv/ini) shadows the key, so an operator can drop a stale row
    before dropping the env var. No-op writes touch nothing (no signal, no cache
    invalidation). Effective-after-write is computed without a resolver read-back of
    the just-written layer."""
    definition = get_definition(key)
    if definition.scope is SettingScope.INFRA:
        raise ValueError(f"{key} is infra-scoped (boot-only); cannot store in DB.")

    operation = (
        SettingOperation.CLEAR if value is None else SettingOperation.SET
    )

    from django.db import transaction

    from games.models import SiteSetting

    with transaction.atomic():
        row = SiteSetting.objects.filter(key=key).first()
        stored_present = row is not None
        stored_raw = row.value if row is not None else None

        if operation is SettingOperation.SET:
            raw = resolve_raw_with_source(
                definition.env_name or definition.key,
                allow_file=definition.allow_file,
            )
            if raw is not None and raw.source in LOCKED_SOURCES:
                raise SettingLockedError(key, raw.source)

            normalized = normalize_setting_value(value, definition)
            if definition.write_validator is not None:
                definition.write_validator(normalized)

            changed = (not stored_present) or normalized != stored_raw
            if changed:
                SiteSetting.objects.update_or_create(
                    key=key, defaults={"value": normalized}
                )
            return SettingMutation(
                ResolvedSetting(normalized, SettingSource.DATABASE, False),
                operation,
                changed,
                normalized,
                True,
            )

        # CLEAR — never lock-checked.
        changed = stored_present
        if changed:
            SiteSetting.objects.filter(key=key).delete()
        effective = resolve_fallthrough_uncached(key, skip_db=True)
        return SettingMutation(effective, operation, changed, None, False)
```

Add the needed imports at the top of the module: `resolve_raw_with_source` and
`LOCKED_SOURCES` from `timetracker.config` (extend the existing import), and
`resolve_fallthrough_uncached` from `timetracker.settings_resolver` (extend the
existing import). Remove the now-unused `cast` import and the inline
`Device.objects.filter(...)` block.

Update `__all__` to add `"SettingMutation"`, `"SettingOperation"`.

- [ ] **Step 4: Run to verify pass**

Run: `direnv exec . uv run pytest tests/test_settings_commands.py -v`
Expected: PASS (new + updated existing).

- [ ] **Step 5: Commit**

```bash
git add timetracker/settings_commands.py tests/test_settings_commands.py
git commit -m "feat(settings): change_site_setting returns SettingMutation; clear bypasses lock

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `change_user_setting` — move + rename from resolver, return `SettingMutation`

**Files:**
- Modify: `timetracker/settings_commands.py` (add `change_user_setting`)
- Modify: `timetracker/settings_resolver.py` (delete `set_user_preference`; drop from `__all__`)
- Test: `tests/test_settings_commands.py`

**Interfaces:**
- Consumes: Task 1-3 machinery.
- Produces: `change_user_setting(user, key, value) -> SettingMutation`. Raises `ValueError` for a non-USER key, `ValidationError`/`TypeError` for bad value/device. User effective always `locked=False`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings_commands.py`:

```python
from timetracker.settings_commands import change_user_setting


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user("member", password="x")


@pytest.mark.django_db
def test_user_first_time_set_does_not_crash_and_reports_changed(user):
    result = change_user_setting(user, "THEME", "dark")  # column was NULL
    assert result.operation is SettingOperation.SET
    assert result.changed is True
    assert result.effective == ResolvedSetting("dark", SettingSource.USER, False)


@pytest.mark.django_db
def test_user_noop_set_reports_unchanged(user):
    change_user_setting(user, "THEME", "dark")
    again = change_user_setting(user, "THEME", "dark")
    assert again.changed is False
    assert again.stored_present is True


@pytest.mark.django_db
def test_user_clear_falls_through_and_is_never_locked(user, monkeypatch):
    change_user_setting(user, "DEFAULT_CURRENCY", "eur")
    monkeypatch.setenv("DEFAULT_CURRENCY", "GBP")  # locked source
    settings_resolver.clear_cache()

    cleared = change_user_setting(user, "DEFAULT_CURRENCY", None)
    assert cleared.operation is SettingOperation.CLEAR
    assert cleared.changed is True
    assert cleared.effective.value == "GBP"
    assert cleared.effective.locked is False  # a user can always re-override


@pytest.mark.django_db
def test_user_noop_clear_on_absent_row_touches_nothing(user):
    from games.models import UserPreferences

    result = change_user_setting(user, "THEME", None)
    assert result.changed is False
    assert not UserPreferences.objects.filter(user=user).exists()  # no phantom row


@pytest.mark.django_db
def test_user_write_validator_rejects_missing_device(user):
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        change_user_setting(user, "DEFAULT_DEVICE", 9_999_999)


@pytest.mark.django_db
def test_user_non_user_scope_key_raises(user):
    with pytest.raises(ValueError):
        change_user_setting(user, "DEFAULT_CURRENCY_XYZ_NOT_A_KEY", "x")
```

- [ ] **Step 2: Run to verify it fails**

Run: `direnv exec . uv run pytest tests/test_settings_commands.py -k user_first_time_set -v`
Expected: FAIL — `ImportError: cannot import name 'change_user_setting'`.

- [ ] **Step 3: Implement `change_user_setting`**

Add to `timetracker/settings_commands.py`:

```python
def change_user_setting(
    user: object, key: SettingKey, value: object | None
) -> SettingMutation:
    """Set or clear a user-scoped preference; return an operation-aware envelope.

    Personal overrides are never locked (a user may always override, even over env),
    so there is no lock branch. No-op writes touch nothing. User effective is always
    reported ``locked=False``, matching the read endpoint's contract."""
    definition = get_definition(key)
    if definition.scope is not SettingScope.USER:
        raise ValueError(f"{key} is not a user-scoped setting; cannot store per user.")

    operation = SettingOperation.CLEAR if value is None else SettingOperation.SET

    from django.db import transaction

    from games.models import USER_PREFERENCE_FIELD_BY_KEY, UserPreferences

    with transaction.atomic():
        row = UserPreferences.objects.filter(user=user).first()  # non-creating read
        field = USER_PREFERENCE_FIELD_BY_KEY.get(key)
        if row is None:
            stored_present, stored_raw = False, None
        elif field is not None:
            stored_raw = getattr(row, field)
            stored_present = stored_raw is not None
        else:
            bag = row.extra_preferences or {}
            stored_present = key in bag
            stored_raw = bag.get(key)

        if operation is SettingOperation.SET:
            normalized = normalize_setting_value(value, definition)
            if definition.write_validator is not None:
                definition.write_validator(normalized)
            changed = (not stored_present) or normalized != stored_raw
            if changed:
                UserPreferences.get_for_user(user).set_preference_value(key, normalized)
            return SettingMutation(
                ResolvedSetting(normalized, SettingSource.USER, False),
                operation,
                changed,
                normalized,
                True,
            )

        # CLEAR
        changed = stored_present
        if changed and row is not None:
            row.set_preference_value(key, None)
        effective = resolve_fallthrough_uncached(key, skip_db=False)._replace(
            locked=False
        )
        return SettingMutation(effective, operation, changed, None, False)
```

Add `"change_user_setting",` to `__all__`.

- [ ] **Step 4: Delete `set_user_preference` from the resolver**

In `timetracker/settings_resolver.py` remove the `set_user_preference` function
(lines ~255-277) and its `"set_user_preference",` entry in `__all__`. Leave
`ValidationError` in `__all__` only if still referenced elsewhere; otherwise remove it
too (grep first).

- [ ] **Step 5: Run to verify pass**

Run: `direnv exec . uv run pytest tests/test_settings_commands.py -v`
Expected: PASS. (Callers of the removed `set_user_preference` still import it — fixed in Task 5; if collection errors surface from other test modules, they are addressed there.)

- [ ] **Step 6: Commit**

```bash
git add timetracker/settings_commands.py timetracker/settings_resolver.py tests/test_settings_commands.py
git commit -m "feat(settings): change_user_setting command; drop set_user_preference from resolver

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Route both PATCH endpoints through the commands; fix all callers

**Files:**
- Modify: `games/api.py` (imports; `update_user_setting`; `update_site_setting`)
- Modify: any non-command caller of `set_user_preference` (found via grep) — tests and helpers
- Test: existing endpoint tests in `tests/test_settings_commands.py` + repo-wide grep

**Interfaces:**
- Consumes: `change_user_setting`, `change_site_setting`, `SettingMutation`.
- Produces: endpoints return `_setting_out(key, mutation.effective, ...)`; HTTP response shape unchanged.

- [ ] **Step 1: Find every stale reference**

Run: `direnv exec . rg -n "set_user_preference" --type py`
Expected: hits in `games/api.py` and a few test modules (e.g. `tests/test_user_preferences_resolver.py`, `tests/test_date_time_rendering_paths.py`, `tests/test_date_time_presentation.py`). Note each — they must switch to `change_user_setting` (return value is now a `SettingMutation`; callers that only wrote a pref and ignored the return still work by ignoring it; callers that read the returned normalized value must use `.stored`).

- [ ] **Step 2: Update `games/api.py` imports**

Change the import block (lines ~33-39) so `change_user_setting` replaces
`set_user_preference` and comes from `timetracker.settings_commands` (alongside
`change_site_setting`, `SettingLockedError`).

- [ ] **Step 3: Rewrite `update_user_setting`**

Replace the body (lines ~604-623) with:

```python
    try:
        definition = get_definition(key)
    except UnregisteredSettingError:
        raise HttpError(400, f"Unknown setting {key!r}.")
    if definition.scope is not SettingScope.USER:
        raise HttpError(400, f"{key} is not a user-scoped setting.")
    try:
        mutation = change_user_setting(request.user, key, payload.value)
    except (ValidationError, ValueError, TypeError) as error:
        _raise_400(error)
    messages.success(request, f"{definition.label} saved")
    return _setting_out(key, mutation.effective, locked=False)
```

- [ ] **Step 4: Rewrite `update_site_setting` return**

In the body (lines ~644-657) change `resolved = change_site_setting(...)` to
`mutation = change_site_setting(...)` and the final line to
`return _setting_out(key, mutation.effective)`. Keep the `SettingLockedError`→409,
`UnregisteredSettingError`→400, and `(ValidationError, ValueError, TypeError)`→400
handlers exactly as-is.

- [ ] **Step 5: Update non-api callers**

For each grep hit outside `games/api.py`: replace `set_user_preference(user, key, value)`
with `change_user_setting(user, key, value)` and, if the call inspected the return,
read `.stored`. Update the import line in each such module
(`from timetracker.settings_commands import change_user_setting`).

- [ ] **Step 6: Run the focused + resolver suites**

Run: `direnv exec . uv run pytest tests/test_settings_commands.py tests/test_user_preferences_resolver.py tests/test_date_time_rendering_paths.py tests/test_date_time_presentation.py -v`
Expected: PASS. Confirm no `set_user_preference` import remains: `direnv exec . rg -n "set_user_preference" --type py` returns nothing.

- [ ] **Step 7: Commit**

```bash
git add games/api.py tests/
git commit -m "refactor(settings): route PATCH endpoints through the command layer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Docs + full verification gate

**Files:**
- Modify: `docs/configuration.md`

- [ ] **Step 1: Update the configuration doc**

In `docs/configuration.md` (around line 97, the `change_site_setting()` mention), add
a sentence documenting `change_user_setting()` as the personal write boundary and note
both commands now return a `SettingMutation` (effective state + operation + changed +
stored/stored_present). Keep it to 2-3 lines, matching the doc's style.

- [ ] **Step 2: Run the full gate**

Run: `direnv exec . make check`
Expected: green — lint, format-check, mypy, ts-check, vitest, and the entire pytest
suite **including `e2e/`**. If mypy flags the `write_validator` alias or the
`SettingMutation` field types, fix inline (they are plain `Callable`/`NamedTuple`, no
`Any`).

- [ ] **Step 3: Commit**

```bash
git add docs/configuration.md
git commit -m "docs: document change_user_setting + SettingMutation command layer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Follow-up issues to file

None new — the design already fans out to existing issues: **#488** (namespaced
committed events, consumes this envelope), **#492** (Device `post_delete` clears a
dangling site `DEFAULT_DEVICE`, routes through `change_site_setting`), **#495** (form /
state-builder dedup). When #487 merges, comment on #492 that the command layer is now
available so its cleanup should delete via `change_site_setting`, not raw ORM.

## Self-review notes

- **Spec coverage:** command layer (T3/T4), envelope (T2), write_validator (T1), clear-vs-lock (T3), effective table incl. uncached/best-effort/normalized (T2 helper + T3/T4 use), endpoints backend-pure (T5), cache/rollback invariants (T2 uncached read + no-op short-circuit), docs (T6), tests incl. first-time SET / poisoned repair / no-op-no-invalidation / ENV-not-ENV_FILE shadow / registry-count (T1/T3/T4). All mapped.
- **Types:** `SettingMutation`, `SettingOperation`, `SettingWriteValidator`, `resolve_fallthrough_uncached(key, *, skip_db)` used consistently across tasks.
