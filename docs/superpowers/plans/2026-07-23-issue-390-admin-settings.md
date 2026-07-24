# Admin Site Settings Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a superuser-only `/tracker/admin-settings` page for every
live site default while preserving personal overrides, configuration locks, and
boot-only infrastructure semantics.

**Architecture:** The page uses an explicit `SiteSettingsForm` and the existing
settings kit. The site API delegates mutations to
`timetracker/settings_commands.py`; resolver snapshots remain read-only and
invalidate only after transaction commit. Navigation extends the existing Menu
dropdown, and Django admin is removed.

**Tech Stack:** Django 6 forms/views, Django Ninja, Python components,
TypeScript custom elements, pytest, and Playwright.

## Global constraints

- Expose exactly `DEFAULT_CURRENCY`, `DEFAULT_DEVICE`,
  `DEFAULT_LANDING_PAGE`, `DEFAULT_PAGE_SIZE`, `THEME`,
  `DISPLAY_TIME_ZONE`, `DATE_FORMAT_LOCALE`, and `DATETIME_FORMAT`.
- Do not render or edit boot-time `TZ`; Stage 9 owns its future read-only
  inspection.
- Higher environment/configuration sources render disabled and return HTTP 409
  from direct site PATCH attempts.
- Settings, Admin settings, and POST Logout stay inside the existing Menu
  dropdown. Admin settings is superuser-only.
- The navbar theme switcher is unavailable on settings pages.
- Purchase-entry views use the user's resolved currency. Context-free
  `Purchase.save()` and FX conversion/reporting use the site currency.
- Run repository commands through `direnv exec .`.

## Task 1: Establish the site command boundary

**Files:** `timetracker/settings_commands.py`, `games/api.py`,
`games/signals.py`, backend command/API tests.

- [x] Add failing tests for normalized set/clear results, all eight keys,
  invalid values/device references, locked-source 409, and transaction rollback.
- [x] Implement `change_site_setting()` as the sole site mutation command.
- [x] Return the command's canonical `ResolvedSetting` directly from PATCH.
- [x] Keep cache invalidation on transaction commit; remove public
  resolver-owned site mutation helpers.

## Task 2: Render and authorize Admin settings

**Files:** `games/views/settings.py`, `games/urls.py`,
`tests/test_admin_settings_page.py`.

- [x] Add anonymous redirect and component-rendered non-superuser 403 coverage.
- [x] Render typed controls for the exact eight live site defaults.
- [x] Exclude `TZ` and every other infrastructure key.
- [x] Render effective source state; disable higher-source-owned fields with a
  visible explanation.
- [x] Mark theme and date/time presentation controls for the existing
  reload-after-save flow.

## Task 3: Integrate navigation and remove superseded administration

**Files:** `common/layout.py`, `timetracker/settings.py`,
`timetracker/urls.py`, purchase consumers, navigation/admin/currency tests.

- [x] Put personal Settings, superuser Admin settings, and POST Logout inside
  the existing Menu dropdown.
- [x] Disable only the navbar theme switcher on settings pages.
- [x] Remove Django admin while retaining auth/superusers,
  `django_extensions`, and the debug toolbar.
- [x] Pass the request user's resolved currency into purchase-entry forms and
  keep model/FX fallback site-wide.

## Task 4: Browser acceptance and active documentation

**Files:** `e2e/test_admin_settings_page_e2e.py`,
`docs/settings-panel-epic.md`, `docs/configuration.md`, this design/plan,
`CHANGELOG.md`.

- [x] Cover Menu-dropdown access and responsive section navigation at mobile
  and desktop viewports.
- [x] Cover representative normalized text, select, clear/fallback, source
  badge, and display-timezone reload behavior.
- [x] Verify a locked field's disabled state, owner, and explanation without
  interacting with the control.
- [x] Remove stale Stage 8/9, resolver mutation, immediate cache, retained
  admin, and site-only purchase-entry claims from active documentation.

## Verification

```bash
direnv exec . uv run --frozen pytest \
  e2e/test_admin_settings_page_e2e.py \
  e2e/test_settings_page_e2e.py \
  e2e/test_settings_ui_kit_e2e.py -q
direnv exec . uv run --frozen ruff check \
  e2e/test_admin_settings_page_e2e.py
direnv exec . uv run --frozen ruff format --check \
  e2e/test_admin_settings_page_e2e.py
git diff --check
```

The controller runs the final full `direnv exec . make check`.
