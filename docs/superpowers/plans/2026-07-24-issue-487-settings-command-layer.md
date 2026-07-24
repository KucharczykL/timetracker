# Settings Command Layer

**Goal:** Route personal and site setting writes through one explicit command layer that returns an operation-aware `SettingMutation`, fix the clear-vs-lock bug, and add a registry-driven write-time validator — without weakening the read-only resolver.

**Architecture:** `timetracker/settings_commands.py` is the sole write boundary: two symmetric commands, `change_site_setting(key, value)` and `change_user_setting(user, key, value)`, each returning a `SettingMutation` envelope. Effective-after-write state is computed by an uncached, best-effort fall-through helper in the resolver, so no just-written layer is read back and no uncommitted row leaks into the global snapshot cache. A `write_validator` slot on `SettingDefinition` holds the `DEFAULT_DEVICE` existence check, invoked on SET by both commands. `settings_resolver.py` stays read-only.

**Tech stack:** Django 6, Django Ninja, SQLite (WAL), pytest / pytest-django. Python 3.14 (bare `except A, B:` PEP 758 syntax; interpreter must be 3.14.x).

## Constraints

- Every command runs inside the Nix dev shell, via `direnv exec .`.
- Never write a `GeneratedField`.
- Name compound/primitive roles explicitly (TypedDict/NamedTuple/PEP 695 alias); unabbreviated identifiers.
- Backend-pure: no TypeScript / HTTP-response-shape change. `_setting_out` output is byte-identical.

## The mutation envelope

```python
class SettingOperation(StrEnum):
    SET = "set"
    CLEAR = "clear"

class SettingMutation(NamedTuple):
    effective: ResolvedSetting    # resolved state after the write
    operation: SettingOperation   # SET (value given) | CLEAR (value is None)
    changed: bool                 # storage actually mutated
    stored: object | None         # normalized value now stored...
    stored_present: bool          # ...vs cleared/absent (disambiguates a stored None)
```

`(operation, changed, stored_present)` distinguishes all four cases:

| case        | operation | changed | stored_present |
|-------------|-----------|---------|-----------------|
| set         | SET       | True    | True            |
| no-op set   | SET       | False   | True            |
| clear       | CLEAR     | True    | False           |
| no-op clear | CLEAR     | False   | False           |

`SettingMutation` composes `ResolvedSetting`; the read result type is unchanged.

## `changed` detection + no-op short-circuit

Each command reads the currently-stored value before writing, via a non-creating read (never a `get_or_create`-style helper, which would insert a phantom row on a no-op):

- **Site:** `SiteSetting.objects.filter(key=key).values_list("value", flat=True).first()`.
- **User:** `UserPreferences.objects.filter(user=user).first()`; typed column via `getattr` for keys in `USER_PREFERENCE_FIELD_BY_KEY`, else `extra_preferences.get(key)`.

The comparison is normalized-incoming vs raw-stored — the stored value is never re-normalized. Re-normalizing would crash on a first-time SET (column `None`) or a poisoned row, since validators reject `None`. Comparing directly instead degrades gracefully: a poisoned value simply compares unequal, `changed=True`, and the clear/overwrite proceeds.

A no-op SET or no-op CLEAR performs no `save`/`delete`/`update_or_create` — no signal fires, no cache invalidation. Both commands wrap their read-decide-write in `transaction.atomic()`.

## `write_validator` registry hook

`SettingDefinition.write_validator: SettingWriteValidator | None = None`, appended last on the frozen dataclass (every existing definition passes only `key` positionally). `DEFAULT_DEVICE` sets it to a device-existence check, invoked after normalize, only on SET — a CLEAR has no pointer to check. The read path never calls it, so a dangling stored device id degrades gracefully instead of crashing a resolve.

## clear-vs-lock + effective-after-write

The lock guards SET only — a CLEAR always removes the row, even under a locked source (env/file/dotenv/ini):

```python
if operation is SET:
    if current.source in LOCKED_SOURCES:
        raise SettingLockedError(key, current.source)
    # normalize -> write_validator -> store
else:  # CLEAR — never lock-checked
    # delete the DB row if present
```

`effective` never reads back the just-written layer (its snapshot is invalidated only on commit and is stale mid-transaction):

| command | operation | `effective` |
|---------|-----------|--------------|
| user    | SET       | `ResolvedSetting(normalized, USER, locked=False)` |
| user    | CLEAR     | shared-chain fall-through (env → site DB → default), `locked` forced `False` |
| site    | SET       | `ResolvedSetting(normalized, DATABASE, locked=False)` |
| site    | CLEAR     | fall-through excluding the DB layer (env → default), bypassing the stale DB snapshot |

`resolve_fallthrough_uncached(key, *, skip_db)` (in the resolver) computes both CLEAR cells: it normalizes the raw source like a real resolve, never populates the global snapshot cache (so a rolled-back outer transaction can't leak an uncommitted row into it), and degrades best-effort — a malformed locked env value falls back to the default rather than raising (the delete has already happened inside `atomic()`; raising would roll it back and resurrect the row).

User-layer `effective` always reports `locked=False` — a user can always override a personal preference, matching the read endpoint's contract.

## Endpoints

Both PATCH endpoints route through the commands; HTTP response shape is unchanged — `_setting_out` still receives a `ResolvedSetting` (`mutation.effective`). Guards stay as before: the user endpoint keeps its scope check and 400 on an unregistered key; the site endpoint keeps its 409 on a locked SET.

## Testing invariants

- Four-way matrix per scope (set / no-op set / clear / no-op clear) against `operation`, `changed`, `stored_present`, `effective`.
- First-time SET on a fresh user does not crash.
- No-op writes fire no signal and no cache invalidation.
- A poisoned stored row is clearable without raising.
- An env-shadowed clear returns the normalized env value with the correct source/locked; a malformed locked env value degrades to the default without rolling back.
- A locked SET still raises; CLEAR under the same lock succeeds.
- `write_validator` fires on SET only, on both command entry points.
- Only `DEFAULT_DEVICE` declares a `write_validator`.
