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

### `changed` detection (read-before-write)

`set_preference_value` / `SiteSetting` writes are write-only, so each command reads
the **raw** currently-stored value once, before writing, and compares to the
normalized value:

- **Site:** read the `SiteSetting` row (`.value`) for `key`, if any.
- **User:** fetch `UserPreferences.get_for_user(user)` **once**; read the current
  value off that instance — typed column via `getattr(row, field)` for keys in
  `USER_PREFERENCE_FIELD_BY_KEY`, else `row.extra_preferences.get(key)` — then call
  `set_preference_value` on the **same** instance. One fetch, not two.

Comparison is normalized-vs-normalized (the stored raw is run through
`normalize_setting_value` before comparing) so a stored JSON `1` and an incoming
`"1"` compare equal and don't produce a false `changed=True`.

Wrap each command body in `transaction.atomic()` so the read-then-write sees a
consistent snapshot and the commit-time cache invalidation batches cleanly.

### `write_validator` registry hook

Add an optional field to `SettingDefinition` — **appended last**, since all 14
definitions pass leading args positionally:

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
| user    | CLEAR     | `resolve_with_origin(key)` — shared chain (env → site DB → default), excludes the user layer — **with `locked` forced `False`** |
| site    | SET       | `ResolvedSetting(normalized, DATABASE, locked=False)` |
| site    | CLEAR     | env/ini raw via `resolve_raw_with_source` if present (`locked=True`), else `default_factory()` — **must bypass the stale DB snapshot** |

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
- Env-shadowed **site** clear: row deleted, `effective.source == ENV`,
  `effective.locked is True`, `operation == CLEAR`, `changed` reflects the DB row.
- Env-shadowed **user** clear: personal row deleted, `effective` falls through the
  shared chain, `effective.locked is False`.
- Locked **site** SET still raises `SettingLockedError`; CLEAR under the same lock
  succeeds and deletes the row.
- `write_validator` fires on **both** command entry points (bad device id →
  `ValidationError`, nothing written), parametrized over user and site; does **not**
  fire on CLEAR.
- Registry: `DEFAULT_DEVICE.write_validator` is set, the other seven are `None`; a
  `resolve*` of a dangling device id issues no device-existence query and does not
  raise (guards #492's premise).
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
