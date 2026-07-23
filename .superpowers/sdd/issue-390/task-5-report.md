# Task 5 report: browser acceptance and active documentation

## Status

Complete. Added focused Admin Settings Playwright acceptance coverage, rewrote
the active issue #390/settings documentation to the implemented design, and
added Unreleased changelog entries.

## TDD evidence

### Existing browser baseline

Command:

```bash
direnv exec . uv run --frozen pytest \
  e2e/test_settings_page_e2e.py \
  e2e/test_settings_ui_kit_e2e.py -q
```

Output:

```text
..............                                                           [100%]
14 passed in 14.35s
```

### RED

The new acceptance module was written before documentation/support changes and
run directly:

```bash
direnv exec . uv run --frozen pytest \
  e2e/test_admin_settings_page_e2e.py -q
```

Output:

```text
...F.                                                                    [100%]
FAILED e2e/test_admin_settings_page_e2e.py::test_configuration_locked_field_shows_owner_and_explanation[chromium]
1 failed, 4 passed in 7.32s
```

The failure was the intended locked-explanation assertion resolving two copies:
the hidden source-tooltip `<dd>` and the visible inline metadata `<p>`. This
proved the browser assertion had to identify the presented explanation instead
of merely matching text anywhere in the document.

### GREEN

The locator was narrowed to `[data-setting-metadata]`; the disabled field was
only observed and never interacted with.

Command:

```bash
direnv exec . uv run --frozen pytest \
  e2e/test_admin_settings_page_e2e.py -q
```

Output:

```text
.....                                                                    [100%]
5 passed in 7.26s
```

## Acceptance coverage

`e2e/test_admin_settings_page_e2e.py` now covers:

- superuser login, Admin settings heading, and navigation through the existing
  Menu dropdown;
- mobile and desktop settings-section navigation modes;
- lowercase currency input, site PATCH 200, canonical uppercase reconciliation,
  and Database source badge;
- a representative page-size select PATCH;
- clearing the currency override, canonical `CZK` fallback, and Default source;
- `DISPLAY_TIME_ZONE` PATCH, navigation/reload, and the rebuilt root document
  presentation contract;
- an environment-owned disabled field with source and visible lock explanation.

The module contains no `wait_for_timeout`, does not interact with disabled
controls, and does not duplicate the backend eight-key behavior matrix. Its
fixture removes all eight relevant environment/file variables, redirects
`.env`/INI lookup to missing temporary paths, and resets both configuration and
resolver caches before and after use; `monkeypatch` restores the environment.

## Documentation changed

- `docs/settings-panel-epic.md`
  - revised Stage 8 to the exact eight live defaults and the command/409/clear
    contracts;
  - kept boot-only `TZ` off Stage 8 and in the planned Stage 9 read-only
    inspector;
  - documented Menu-dropdown placement, unavailable settings-page navbar theme
    switcher, removed Django admin, on-commit cache invalidation, and split
    personal/site currency semantics.
- `docs/configuration.md`
  - documented `/tracker/admin-settings`, the exact live site-default list,
    source locking, the `settings_commands.py` boundary, and 409 behavior;
  - distinguished live `DISPLAY_TIME_ZONE` from restart-required `TZ`;
  - distinguished request-aware purchase entry from context-free model/FX
    currency;
  - documented removal of Django admin while retaining auth/superusers,
    `django_extensions`, and the debug toolbar.
- `docs/superpowers/specs/2026-07-23-issue-390-admin-settings-design.md`
  - replaced stale resolver mutation, immediate cache, navbar, admin, and
    currency claims with a concise implemented design.
- `docs/superpowers/plans/2026-07-23-issue-390-admin-settings.md`
  - replaced obsolete code snippets with a concise completed plan matching the
    command, page, navigation, administration, currency, and browser contracts.
- `CHANGELOG.md`
  - added the superuser Admin Settings page and Django admin removal under
    Unreleased and corrected the currency scope wording.

The repository has no dedicated Markdown formatter/check target. Documentation
hygiene was checked with `git diff --check`.

## Final verification

Required focused browser command:

```bash
direnv exec . uv run --frozen pytest \
  e2e/test_admin_settings_page_e2e.py \
  e2e/test_settings_page_e2e.py \
  e2e/test_settings_ui_kit_e2e.py -q
```

Output:

```text
...................                                                      [100%]
19 passed in 20.31s
```

Focused source checks:

```bash
direnv exec . uv run --frozen ruff check \
  e2e/test_admin_settings_page_e2e.py
direnv exec . uv run --frozen ruff format --check \
  e2e/test_admin_settings_page_e2e.py
git diff --check
```

Output:

```text
All checks passed!
1 file already formatted
```

`git diff --check` exited 0 with no output.

## Self-review

- Re-read every Task 5 acceptance and documentation bullet against the changed
  files.
- Confirmed Admin settings is exercised inside Menu at both viewports, not as a
  top-level navbar entry.
- Confirmed each browser mutation waits for the correct site PATCH and checks
  status 200; the timezone test additionally waits for navigation/load.
- Confirmed the locked test performs assertions only.
- Confirmed no fixed sleeps appear in the new module.
- Confirmed stale public `set_site_setting`/`clear_site_setting`, retained admin,
  site-only purchase-entry, and pre-commit cache claims are absent from the
  revised documents.
- Preserved all unrelated untracked `.superpowers/sdd` artifacts.

## Concerns

- No dedicated Markdown checker exists in this repository, so documentation
  verification is limited to review, stale-claim scans, and
  `git diff --check`.
- Per the task split, the controller still owns the final full
  `direnv exec . make check`.
