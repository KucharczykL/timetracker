# Task 1 report: site-setting command service and backend API contract

## Status

DONE

## Implementation summary

- Added `timetracker.settings_commands.change_site_setting()` as the sole
  site-setting mutation boundary.
- Added `SettingLockedError` with the exact `key` and owning `source`.
- The command rejects unknown and infra keys, checks the current resolved
  source before normalization/mutation, rejects all locked sources, normalizes
  values through the registry, verifies `DEFAULT_DEVICE` existence, owns
  `SiteSetting` set/delete operations, and returns direct `ResolvedSetting`
  results without resolving after the mutation.
- Removed `set_site_setting` and `clear_site_setting` from
  `timetracker.settings_resolver` and migrated backend test/setup callers.
- Changed `PATCH /api/settings/site/{key}` to call the command for both set and
  clear, return flat `SettingOut` with HTTP 200, return HTTP 409 for locked
  settings, and retain HTTP 400 validation errors and the superuser gate.
- Inspected the existing `SiteSetting` save/delete signal. It already schedules
  `clear_settings_cache` with `transaction.on_commit()`, so no signal change was
  needed.
- Added an eight-key parameterized backend contract matrix plus locked-source,
  invalid-request, rollback/cache, on-commit, direct-response, and resolver
  surface tests.

## TDD evidence

### RED

Command:

```bash
direnv exec . uv run --frozen pytest tests/test_settings_commands.py -q
```

Output:

```text
FFFFFFFFFFFFFFFFFFFFFFF                                                  [100%]
...
E       assert 204 == 200
...
E       ModuleNotFoundError: No module named 'timetracker.settings_commands'
...
E       AssertionError: assert not True
...
23 failed in 3.62s
```

The failures were the intended missing behavior: the legacy endpoint returned
204, the command module did not exist, the API had no command import, and the
resolver still exposed both mutation helpers.

### First implementation run and test-fixture correction

Command:

```bash
direnv exec . uv run --frozen pytest tests/test_settings_commands.py -q
```

Output:

```text
........F...F..........                                                  [100%]
2 failed, 21 passed in 3.47s
```

Both failures were for the `env_file` parameter. No current live site key opts
into registry `allow_file=True`, so `DEFAULT_CURRENCY__FILE` cannot naturally
produce that source. The test was corrected to simulate
`resolve_with_origin()` returning `SettingSource.ENV_FILE`, while env, `.env`,
and INI remain real integration paths.

### GREEN

Command:

```bash
direnv exec . uv run --frozen pytest tests/test_settings_commands.py -q
```

Output:

```text
.......................                                                  [100%]
23 passed in 3.45s
```

## Final verification

Required focused command:

```bash
direnv exec . uv run --frozen pytest \
  tests/test_settings_api.py \
  tests/test_settings_commands.py \
  tests/test_settings_resolver.py \
  tests/test_user_preferences_resolver.py -q
```

Final output:

```text
........................................................................ [ 53%]
..............................................................           [100%]
134 passed in 12.49s
```

Migrated live-currency integration command:

```bash
direnv exec . uv run --frozen pytest tests/test_site_settings_currency.py -q
```

Output:

```text
.....                                                                    [100%]
5 passed in 0.43s
```

Static checks:

```bash
direnv exec . uv run --frozen ruff check \
  timetracker/settings_commands.py timetracker/settings_resolver.py \
  games/api.py games/admin.py tests/test_settings_commands.py \
  tests/test_settings_api.py tests/test_settings_resolver.py \
  tests/test_user_preferences_resolver.py tests/test_site_settings_currency.py
```

```text
All checks passed!
```

```bash
direnv exec . uv run --frozen ruff format --check \
  timetracker/settings_commands.py timetracker/settings_resolver.py \
  games/api.py games/admin.py tests/test_settings_commands.py \
  tests/test_settings_api.py tests/test_settings_resolver.py \
  tests/test_user_preferences_resolver.py tests/test_site_settings_currency.py
```

```text
9 files already formatted
```

Full repository gate:

```bash
direnv exec . make check
```

The first full run correctly stopped on a test-helper mypy error:

```text
tests/test_settings_commands.py:127: error: No overload variant of "get" of
"dict" matches argument types "object", "object"  [call-overload]
Found 1 error in 1 file (checked 221 source files)
make: *** [Makefile:166: typecheck] Error 1
```

The helper was corrected without changing production behavior. Final output:

```text
All checks passed!
219 files already formatted
Success: no issues found in 221 source files
common/components/icons_generated.py is up to date.
Test Files  41 passed (41)
Tests  646 passed (646)
======================= 2141 passed in 232.62s (0:03:52) =======================
```

`git diff --check` also completed with no output.

## Files changed

- `timetracker/settings_commands.py` — new command service and lock exception.
- `timetracker/settings_resolver.py` — removed public site mutation helpers;
  retained read resolution and the personal preference helper.
- `games/api.py` — command-routed site PATCH with flat 200/400/409 contract.
- `games/admin.py` — updated stale command-boundary wording only; no admin
  behavior change.
- `tests/test_settings_commands.py` — eight-key matrix and command/API/cache
  contract coverage.
- `tests/test_settings_api.py` — adapted the existing site PATCH status
  assertion to 200.
- `tests/test_settings_resolver.py` — migrated site writes to the command.
- `tests/test_user_preferences_resolver.py` — migrated site-default setup to
  the command.
- `tests/test_site_settings_currency.py` — migrated live-currency setup to the
  command.

## Self-review

- Checked every requirement in `task-1-brief.md` against the final diff.
- Confirmed the command performs its one resolver call before mutation and
  constructs both successful responses directly.
- Confirmed validation and device existence checks precede DB mutation.
- Confirmed locked set and clear preserve existing rows and surface key/source.
- Confirmed API unknown/infra/invalid/missing-device failures preserve rows.
- Confirmed cache state remains pre-write until captured on-commit callbacks
  run, and rollback discards the write/callback without caching uncommitted
  data.
- Confirmed all eight and only the eight required live defaults appear in the
  contract matrix, with valid/canonical, alternate personal, and invalid values.
- Confirmed GET and personal endpoint code was not changed.
- Confirmed no UI, theme control, Django-admin behavior, currency form, docs,
  migration, or external issue work was added.
- An independent read-only code review found no Critical, Important, or Minor
  issues and assessed the implementation as ready to merge after this report
  and focused commit.

## Concerns

None. One coverage note: no current runtime-editable setting enables
`allow_file`, so the command's `ENV_FILE` lock case is tested at the resolver
boundary; the other three locked sources use real configuration files/env.
