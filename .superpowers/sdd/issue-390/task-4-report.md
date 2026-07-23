# Task 4 report: Django admin removal and explicit purchase currency context

## Status

Complete on top of `e9572da`.

## TDD evidence

### RED: purchase currency context

Command:

```bash
direnv exec . uv run --frozen pytest tests/test_site_settings_currency.py tests/test_user_preference_consumers.py -q
```

Result: exit 1; `5 failed, 13 passed in 1.57s`.

Expected failures proved that:

- `PurchaseForm(default_currency=...)` was rejected by Django's base form;
- `PurchaseForm()` did not require explicit context;
- add/add-for-game rendered the site `CZK` placeholder despite the user's `EUR`.

### RED: Django admin in DEBUG

An initial run exposed that the main pytest process uses `DEBUG=false`; that
harness was corrected to inspect a clean `DEBUG=true` subprocess.

Command after the correction:

```bash
direnv exec . uv run --frozen pytest tests/test_admin_removed.py -q
```

Result: exit 1; `2 failed in 0.36s`.

Expected failures proved that `django.contrib.admin` was in DEBUG
`INSTALLED_APPS` and `/admin/` resolved with the `admin` namespace.

### GREEN: focused TDD cycles

Commands and results:

```bash
direnv exec . uv run --frozen pytest tests/test_site_settings_currency.py tests/test_user_preference_consumers.py -q
# 18 passed in 1.51s

direnv exec . uv run --frozen pytest tests/test_admin_removed.py -q
# 2 passed in 0.33s
```

## Verification

Required focused matrix plus the directly adapted consumer and admin-removal
modules:

```bash
direnv exec . uv run --frozen pytest \
  tests/test_purchase_defaults.py \
  tests/test_site_settings_currency.py \
  tests/test_price_update.py \
  tests/test_settings_resolver.py \
  tests/test_user_preferences_resolver.py \
  tests/test_user_preference_consumers.py \
  tests/test_config.py \
  tests/test_admin_removed.py -q
```

Result: exit 0; `119 passed in 5.78s`.

Formatting:

```bash
direnv exec . uv run --frozen ruff format \
  games/forms.py games/views/purchase.py timetracker/settings.py \
  timetracker/urls.py tests/test_site_settings_currency.py \
  tests/test_user_preference_consumers.py tests/test_admin_removed.py \
  tests/test_settings_resolver.py tests/test_user_preferences_resolver.py
```

The sandboxed attempt could not write the external Nix/uv caches. The approved
rerun succeeded: `2 files reformatted, 7 files left unchanged`.

The first full gate then found one newly exposed mypy error:

```text
games/forms.py:302: error: "Field" has no attribute "queryset"  [attr-defined]
```

The required typed `default_currency: str` parameter caused mypy to begin
checking the formerly untyped `__init__` body. The repository's established
`cast(forms.ModelChoiceField, ...)` pattern fixed the root cause.

Targeted type verification:

```bash
direnv exec . uv run --frozen mypy games/forms.py
# Success: no issues found in 1 source file
```

Final repository gate:

```bash
direnv exec . make check
```

Result: exit 0.

- Ruff lint passed.
- Ruff format check: `220 files already formatted`.
- Mypy: `Success: no issues found in 222 source files`.
- TypeScript/Vitest: `41 passed` files, `649 passed` tests.
- Django/Playwright pytest: `2150 passed in 231.60s`.

Final searches:

```bash
rg -n --glob '!*.diff' \
  'from games\.admin|import games\.admin|from django\.contrib import admin|django\.contrib\.admin|admin\.site|path\(["'\"']admin/' \
  games timetracker tests
```

Only the intentional assertion string in `tests/test_admin_removed.py` remains;
there are no admin imports, registrations, or routes.

```bash
rg -n --glob '!*.diff' 'PurchaseForm\(' games tests
```

All four production add/edit constructions pass `default_currency`; all direct
test constructions pass it except the intentional required-argument failure
test.

```bash
git diff --check
```

Result: exit 0, no output.

## Files changed

Modified:

- `games/forms.py`
- `games/views/purchase.py`
- `timetracker/settings.py`
- `timetracker/urls.py`
- `tests/test_settings_resolver.py`
- `tests/test_site_settings_currency.py`
- `tests/test_user_preference_consumers.py`
- `tests/test_user_preferences_resolver.py`

Added:

- `tests/test_admin_removed.py`
- `.superpowers/sdd/issue-390/task-4-report.md`

Deleted:

- `games/admin.py`

## Self-review

- `PurchaseForm` requires keyword-only `default_currency` and no longer imports
  or calls the settings resolver.
- The explicit currency controls unbound initial state, the widget placeholder,
  and bound blank-currency cleanup.
- Bound/unbound add, add-for-game, and edit constructions all receive the
  existing `resolve_str_for_user(request.user, "DEFAULT_CURRENCY")` result.
- Combined and separate-per-game blank submissions use that same user value.
- `Purchase.save()` and `convert_prices()` remain unchanged and site-scoped;
  tests distinguish site `EUR` from a personal `GBP` override.
- Django auth, superuser support, `django_extensions`, debug-toolbar app,
  middleware, and URLs remain intact.
- Only admin-form-specific resolver tests were removed. `SiteSetting` and
  `UserPreferences` models and their non-admin tests remain.
- No Admin Settings page or theme implementation file was touched.

## Concerns

None. Pre-existing untracked SDD briefs/review diffs were not modified or
included in this task.
