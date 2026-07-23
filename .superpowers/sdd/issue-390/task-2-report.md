# Task 2 report: Superuser Admin Settings page and navigation

## Status

Implemented the command-backed site-default settings page at
`/tracker/admin-settings` and a distinct superuser-only navbar entry. The page
uses the existing Python component/settings-kit stack and preserves the
personal Settings page behavior.

## TDD evidence

### RED

After adding `tests/test_admin_settings_page.py` and before changing production
code:

```text
$ direnv exec . uv run --frozen pytest tests/test_admin_settings_page.py -q
FFFFFFFFFFFFFFF [100%]
15 failed in 2.10s
```

The failures were the expected missing-feature failures:

- `/tracker/admin-settings` returned 404 instead of the login redirect;
- `games:admin_settings` could not be reversed;
- `SiteSettingsForm` did not exist;
- the admin navbar URL/link did not exist.

### GREEN

After the minimal view/form/URL/navbar implementation:

```text
$ direnv exec . uv run --frozen pytest tests/test_admin_settings_page.py -q
............... [100%]
15 passed in 2.26s
```

Two intermediate test runs caught and isolated:

- an incorrect `P` import boundary (`common.components.primitives` is the
  established source);
- two overly broad test assertions (doctype capitalization and matching
  `disabled:` utility classes instead of the native `disabled` attribute).

Those were corrected without changing the requested behavior.

## Verification

Exact focused suite from the task brief:

```text
$ direnv exec . uv run --frozen pytest \
    tests/test_admin_settings_page.py \
    tests/test_settings_page.py \
    tests/test_settings_ui_kit.py \
    tests/test_navbar_log_button.py \
    tests/test_navbar_playtime.py \
    tests/test_theme_layout.py -q
.................................................................. [100%]
66 passed in 4.70s
```

Formatting:

```text
$ direnv exec . make format
2 files reformatted, 218 files left unchanged
```

Full repository gate required by `CLAUDE.md`:

```text
$ direnv exec . make check
ruff check: All checks passed
ruff format --check: 220 files already formatted
mypy: Success: no issues found in 222 source files
TypeScript checks/build: passed
Vitest: 41 files passed, 646 tests passed
pytest/e2e: 2156 passed in 234.57s (0:03:54)
```

Final whitespace validation:

```text
$ git diff --check
(no output; exit 0)
```

## Files changed

- `games/views/settings.py`
  - added explicit `SiteSettingsForm` with the eight approved site-default
    controls;
  - resolved every initial value with `resolve_with_origin()`;
  - mapped origin/locked/help metadata into `SettingFieldState`;
  - added the login-protected, superuser-authorized page and component-rendered
    403 response;
  - used the site PATCH URL and generic live-setting path, with reload markers
    on the four document-presentation settings.
- `games/urls.py`
  - added `games:admin_settings` at app path `admin-settings`.
- `common/layout.py`
  - threaded `is_superuser` through `TimetrackerDocument` to `Navbar` to
    `NavbarMenu`;
  - added the adjacent superuser-only Admin settings link while retaining the
    personal Settings link for authenticated users.
- `tests/test_admin_settings_page.py`
  - added focused authorization, rendering, choices, origin/lock, reload,
    generic PATCH, and navbar tests.

## Self-review

- Authorization is enforced in the view after `login_required`; navbar
  visibility is not the security boundary.
- The page renders exactly the eight brief-approved keys in stable order. It
  neither resolves nor renders `TZ` or any infrastructure key.
- The site form is explicit and separate from `UserSettingsForm`; the personal
  form was not parameterized.
- Registry choices, labels, help text, `PrimitiveWidgetsMixin`, device
  name-ordering, and the existing settings-kit components are reused.
- All seven selects contain `Use configured default`; the existing live-setting
  serializer maps a blank native control to JSON `null`, which invokes Task 1's
  clear-row contract.
- Locked origins preserve their effective value and use Django's real
  `Field.disabled`, with the existing origin badge and lock explanation.
- Site `THEME` is not decorated with `ThemeSetting`; it is generic live-save and
  requests the same post-save reload behavior as the other document-level
  presentation controls.
- The explicit boolean path is
  `TimetrackerDocument -> Navbar -> NavbarMenu`. The link is adjacent to
  personal Settings and absent for anonymous/ordinary users.
- No navbar-theme disabling, Django-admin removal, purchase-currency changes,
  browser tests/docs, or external issue mutations were added.

## Read-only code review

An independent reviewer checked the working diff against the authoritative Task
2 brief and returned **Ready**, with no Critical, Important, or Minor issues.
The reviewer independently reran the focused suite (`66 passed in 4.72s`) and
confirmed the authorization boundary, eight-field scope, locked native-control
behavior, generic site-theme path, reload markers, and navbar boolean threading.

## Concerns

No implementation blockers or known defects. No editable site key currently
opts into `NAME__FILE`, so the environment-file page contract is tested at the
resolver boundary (the same approach used by the Task 1 command tests); the
environment, `.env`, and `settings.ini` families use real source discovery.
