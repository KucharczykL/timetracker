# Issue #487 — Unify personal and site mutations behind a command layer

**Status:** design approved, adversarially reviewed
**Issue:** https://github.com/KucharczykL/timetracker/issues/487
**Follows:** #390 (introduced `change_site_setting`)
**Enables / stacks:** #488 (namespaced committed events — consumes this envelope), #492 (clear site `DEFAULT_DEVICE` on device delete — routes through the command)

## Problem

After #390 the settings write path is split and lopsided:

- `change_site_setting()` (in `timetracker/settings_commands.py`) is the validated,
  lock-aware **site** mutation boundary and returns a `ResolvedSetting`.
- `set_user_preference()` still lives in the **read**-oriented resolver
  (`timetracker/settings_resolver.py`) and returns "the normalized value or `None`".
- Both API layers (`update_user_setting`, `update_site_setting` in `games/api.py`)
  return only effective resolved state — a caller cannot tell a real write from a
  no-op, or a clear from a set.
- The `DEFAULT_DEVICE` existence check is duplicated verbatim in both write functions.
- A latent bug: `change_site_setting` checks the lock **before** branching on
  set-vs-clear, so a DB row shadowed by an env var can never be deleted through any
  UI/API and silently resurfaces once the env var is dropped.

## Goal

Move personal and site writes behind one explicit command layer that returns an
operation-aware result, without weakening the resolver's read-only boundary.

## Architecture

### Module boundary

`timetracker/settings_commands.py` becomes the sole write boundary:

- `change_site_setting(key, value) -> SettingMutation`
- `change_user_setting(user, key, value) -> SettingMutation` — moved out of
  `settings_resolver.py` (was `set_user_preference`), renamed for symmetry.

`settings_resolver.py` becomes read-only, matching its module docstring. Remove
`set_user_preference` and drop it from that module's `__all__`; add
`change_user_setting` to `settings_commands.py`'s `__all__`.

Both commands are **sync-only**, matching the current functions (async callers keep
using `sync_to_async`).

### The mutation envelope

New named types (in `settings_commands.py`):

```python
class SettingOperation(StrEnum):
    SET = "set"
    CLEAR = "clear"

class SettingMutation(NamedTuple):
    effective: ResolvedSetting    # resolved state AFTER the write
    operation: SettingOperation   # SET (value given) | CLEAR (value is None)
    changed: bool                 # storage actually mutated
    stored: object | None         # normalized value now stored...
    stored_present: bool          # ...vs cleared/absent (disambiguates a stored None)
```

The issue's four acceptance cases fall out of `(operation, changed, stored_present)`:

| case        | operation | changed | stored_present |
|-------------|-----------|---------|----------------|
| set         | SET       | True    | True           |
| no-op set   | SET       | False   | True           |
| clear       | CLEAR     | True    | False          |
| no-op clear | CLEAR     | False   | False          |

`SettingMutation` **composes** `ResolvedSetting` (does not extend it); the read
result type is untouched.

### `changed` detection + no-op short-circuit (read-before-write)

Each command reads the currently-stored value **before** writing, using a
**non-creating** read (never `get_for_user`, which does `get_or_create` and would
insert a phantom row on a no-op):

- **Site:** `SiteSetting.objects.filter(key=key).values_list("value", flat=True).first()`
  → `(stored, stored_present)`.
- **User:** `UserPreferences.objects.filter(user=user).first()`; if a row exists, read
  the current value — typed column via `getattr(row, field)` for keys in
  `USER_PREFERENCE_FIELD_BY_KEY` (a `None` column means absent), else
  `row.extra_preferences.get(key)`. No row / `None` column ⇒ `stored_present = False`.

**Never re-normalize the stored value.** Stored values were normalized at write time,
so compare the **normalized incoming** value directly against the **raw stored**
value. Re-running `normalize_setting_value` on the stored side would crash: the
validators reject `None` (e.g. `_validate_currency` does `str(value).upper()`), so a
first-time SET (column `None`) or a poisoned-row repair-by-clear would 400. Direct
comparison also degrades gracefully — a poisoned `"garbage"` row compares unequal to
any normalized value, yielding `changed=True` (the clear/overwrite proceeds), never a
crash. This matches the resolver's deliberate poison tolerance
(`settings_resolver.py:179-191`).

`changed` and `stored_present`:

- **CLEAR:** `changed = stored_present`; `stored = None`, `stored_present = False`
  after.
- **SET:** `stored_present_after = True`, `stored = normalized`;
  `changed = (not stored_present) or normalized != stored`.

**Short-circuit no-ops: skip the write entirely when `changed` is `False`.** A no-op
SET (stored equals normalized) and a no-op CLEAR (nothing stored) perform **no**
`save`/`delete`/`update_or_create`, so no `post_save`/`post_delete` fires and the
settings cache is not needlessly invalidated. `changed=False` then means literally
"storage untouched", satisfying the issue's "storage actually changed" contract.

Wrap each command's read-decide-write in `transaction.atomic()` so the decision sees a
consistent snapshot and the commit-time cache invalidation batches cleanly.

### `write_validator` registry hook

Add an optional field to `SettingDefinition` — **appended last**. (Only `key` is
passed positionally in the 16 definitions — 8 USER + 8 INFRA — so appending is safe
regardless; last-position is belt-and-suspenders.)

```python
write_validator: SettingWriteValidator | None = None  # (value) -> None; raises ValidationError
```

`DEFAULT_DEVICE` sets it to the device-exists check. Both commands invoke it after
normalize, **only on SET** (`normalized is not None`) — a CLEAR has no pointer to
check. The read path never calls it, so a dangling stored device id still never
crashes a resolve (the premise #492 depends on). The two duplicated
`Device.objects.filter(pk=...).exists()` blocks are deleted from the commands.

### clear-vs-lock fix + effective-after-write

The lock guards **SET only**. A CLEAR is "remove my stored row" and is always
permitted, even when a locked source (env/file/dotenv/ini) shadows the key:

```python
if operation is SET:
    if current.source in LOCKED_SOURCES:
        raise SettingLockedError(key, current.source)
    # normalize -> write_validator -> store
else:  # CLEAR
    # delete the DB row if present; never lock-checked
```

`effective` is computed **without a resolver read-back of the just-written layer**
(its snapshot is invalidated only on commit and is stale mid-transaction):

| command | operation | `effective` |
|---------|-----------|-------------|
| user    | SET       | `ResolvedSetting(normalized, USER, locked=False)` |
| user    | CLEAR     | fall-through of the shared chain (env → site DB → default), excluding the user layer, **`locked` forced `False`** |
| site    | SET       | `ResolvedSetting(normalized, DATABASE, locked=False)` |
| site    | CLEAR     | fall-through excluding the DB layer (env → default), **bypassing the stale DB snapshot** |

**Shared fall-through helper, in the resolver.** Both CLEAR cells need "resolve as if
layer X weren't there", and both must (a) normalize like a real resolve, (b) not
populate the global snapshot cache with possibly-uncommitted state, (c) tolerate
poison. Add to `settings_resolver.py` a small internal that mirrors the resolver's env
branch precisely — `resolve_raw_with_source(definition.env_name or key,
allow_file=definition.allow_file)`, then `normalize_setting_value(raw.raw,
definition)` with `source = raw.source` and `locked = raw.source in LOCKED_SOURCES` —
falling through to `default_factory()`/`DEFAULT`/`False`. Requirements this pins down:

- **Normalize the raw** (fixes the type bug — env `DEFAULT_PAGE_SIZE=100` yields int
  `100`, source `ENV`, not the string `"100"`; the source/locked come from `raw`, not
  a hardcoded `ENV`).
- **Uncached read.** The fall-through reads the DB (for user-CLEAR's site layer)
  **without** writing `_snapshot`/`_user_snapshot`, so a command running inside an
  outer transaction that later rolls back cannot leak an uncommitted site row into the
  global cache — honoring the "rollback cannot leak into caches" acceptance criterion.
- **Best-effort normalization.** A malformed **locked** env value must **not** raise
  here: the delete has already happened inside `atomic()`, and raising would roll it
  back and resurrect the row — defeating the whole "clear escapes a bad shadow"
  feature. On a normalization failure, degrade `effective` to
  `default_factory()`/`DEFAULT`, mirroring the read path's poison tolerance
  (`settings_resolver.py:169-191`). The clear still succeeds.

For **user CLEAR**, the fall-through additionally consults the site DB layer (env →
site DB → default) but reports `locked=False` (a user can always re-override).

Two correctness notes surfaced by review:

- **User-layer `effective` always reports `locked=False`.** A user can always
  override a personal preference (env-locking per-user prefs is deferred), exactly as
  `list_user_settings` forces `locked=False` today (`games/api.py:592`). Without this,
  the envelope would report `locked=True` for a cleared user key shadowed by env,
  lying to #488 which consumes the envelope.
- **Site SET reporting `source=DATABASE` is truthful, not a lie.** A site SET only
  succeeds when no locked source shadows the key (the lock guard raises otherwise), so
  after a successful SET the DB layer genuinely wins.
- **Site CLEAR must resolve env/ini directly** rather than returning
  `default_factory()` unconditionally (today's code): once clear is allowed under a
  shadowing env var, the effective value is the env value with `locked=True`.

### Endpoints (backend-pure)

`games/api.py` routes both PATCH endpoints through the commands. HTTP response shape
is **unchanged** — still `SettingOut` built by `_setting_out`:

- `update_user_setting` → `change_user_setting(...)`; returns
  `_setting_out(key, mutation.effective, locked=False)`. Deletes the current manual
  `if saved_value is None: resolve_with_origin(...) else ResolvedSetting(...)`
  reconstruction — the command computes `effective` correctly.
- `update_site_setting` → `change_site_setting(...)`; returns
  `_setting_out(key, mutation.effective)`.

`_setting_out` receives `mutation.effective` (a `ResolvedSetting`), so its
`.value/.source/.locked` access is unchanged and the TypeScript `ResolvedSetting`
shape in `ts/settings-events.ts` is untouched. No TS change in #487; #488 owns the
event/namespace contract.

Endpoint guards stay as today (defense in depth): `update_user_setting` keeps its
early `get_definition` (400 on `UnregisteredSettingError`) and `scope is not USER`
check; the command re-enforces scope (`change_user_setting` raises `ValueError` for a
non-USER key, as `set_user_preference` does now). Error catches unchanged —
`change_user_setting` raises `ValueError`/`ValidationError`; `change_site_setting`
additionally raises `SettingLockedError` (→409) and `UnregisteredSettingError` (→400).

### Cache / rollback invariants (must remain true)

- Snapshot invalidation stays commit-only and signal-driven
  (`games/signals.py`: `post_save`/`post_delete` on `SiteSetting`/`UserPreferences`
  → `transaction.on_commit(clear_settings_cache)`).
- Commands never read the resolver's own just-written layer back (the effective
  table respects this).
- A rolled-back command cannot leak uncommitted state into resolver caches.

## Testing

Extend `tests/test_settings_commands.py` (the existing site contract matrix, rollback
test, and endpoint mock stub already assert `ResolvedSetting` returns — update them to
`SettingMutation`/`.effective`):

- Four-way matrix **per scope** (user + site): set / no-op set / clear / no-op clear —
  assert `operation`, `changed`, `stored_present`, and `effective`.
- **First-time SET** on a fresh user (all columns `None`) does not crash and reports
  `changed=True` (guards the D1 no-normalize-of-stored fix).
- **No-op writes touch nothing:** a no-op SET and a no-op CLEAR fire **no**
  `post_save`/`post_delete` and schedule **no** `clear_settings_cache` on-commit
  (assert via `transaction.on_commit` capture or a signal spy) — `changed=False`.
- **Poisoned-row repair:** a raw `SiteSetting.objects.update(value="garbage")` row is
  clearable via `change_site_setting(key, None)` (returns `changed=True`, row gone) —
  no `ValidationError` on the compare path.
- Env-shadowed **site** clear (shadow via **ENV/DOTENV/INI**, not ENV_FILE — no
  writable key opts into `allow_file`; INFRA `SECRET_KEY` is the sole one and is
  rejected): row deleted, `effective` comes from the real `resolve_raw` fall-through
  with the correct **normalized type** and `source`/`locked` from that raw layer.
- Malformed **locked** env + site clear: the delete succeeds and `effective` degrades
  to the default rather than raising / rolling back (guards the D6 best-effort fix).
- Env-shadowed **user** clear: personal row deleted, `effective` falls through the
  shared chain, `effective.locked is False`.
- Locked **site** SET still raises `SettingLockedError`; CLEAR under the same lock
  succeeds and deletes the row.
- `write_validator` fires on **both** command entry points (bad device id →
  `ValidationError`, nothing written), parametrized over user and site; does **not**
  fire on CLEAR (`normalized is None`).
- Registry: `DEFAULT_DEVICE.write_validator` is set and **every other registered
  definition** (USER and INFRA alike) has `write_validator is None`; a `resolve*` of a
  dangling device id issues no device-existence query and does not raise (guards
  #492's premise).
- Endpoints: existing PATCH tests keep passing (response shape unchanged); add a test
  that an env-shadowed site clear returns 200 with the effective env value (was
  impossible before the lock fix).

Gate on the full `direnv exec . make check` (incl. `e2e/`) green before PR.

## Docs

Update `docs/configuration.md` (§ around line 97): document `change_user_setting`
alongside `change_site_setting`, and note both now return `SettingMutation`.

## Out of scope (own issues)

- Namespaced committed events / TypeScript event contract — **#488** (consumes this
  envelope).
- `Device` `post_delete` receiver clearing a dangling site `DEFAULT_DEVICE` — **#492**
  (routes its cleanup through `change_site_setting`).
- `UserSettingsForm`/`SiteSettingsForm` + state-builder dedup — **#495**.
