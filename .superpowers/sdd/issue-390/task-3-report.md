# Task 3 report: settings-page theme toggle and navbar account actions

## Status

Complete. The navbar theme toggle is permanently disabled through an explicit
typed flag on the personal settings page, admin settings page (including its
403 surface), and DEBUG settings-kit preview. Normal pages retain the existing
coordinator behavior. Per the follow-up requirement, Settings, conditional
Admin settings, and the CSRF-protected POST Log out action now live inside the
existing Menu dropdown rather than as top-level navbar entries.

## TDD evidence

### Theme toggle RED

Command:

```bash
direnv exec . uv run --frozen pytest \
  tests/test_settings_page.py \
  tests/test_admin_settings_page.py \
  tests/test_settings_ui_kit_preview.py \
  tests/test_theme_layout.py -q
```

Result: exit 1, `4 failed, 39 passed`. The three settings surfaces lacked the
`disabled="true"` host prop, and direct
`ThemeToggle(instance_key="settings", disabled=True)` raised the expected
missing-API `TypeError`.

The brief's literal direct Vitest command initially hit the repository's known
Node 26 runner issue before test bodies (`localStorage` was undefined). Running
the same files with the package script's required Node flag produced the
behavioral RED:

```bash
direnv exec . node --no-experimental-webstorage \
  ./node_modules/vitest/vitest.mjs run \
  ts/elements/theme-toggle.test.ts \
  ts/elements/live-setting-fields.test.ts
```

Result: exit 1, `2 failed, 22 passed`. Coordinator updates re-enabled the
permanently disabled button, and a dispatched click called
`requestPreferenceChange()`.

### Navbar follow-up RED

Command:

```bash
direnv exec . uv run --frozen pytest tests/test_admin_settings_page.py -q
```

Result: exit 1, `3 failed, 13 passed`. Settings and Admin settings were outside
Menu, and anonymous pages still rendered Log out.

An additional focused accessibility RED required the logout form to be
presentation-only inside the menu:

```bash
direnv exec . uv run --frozen pytest \
  tests/test_admin_settings_page.py::test_navbar_keeps_personal_settings_for_normal_user_without_admin_link -q
```

Result: exit 1, `1 failed`; the form had no `role="presentation"`.

The first whole-repository pass captured the browser acceptance RED for the new
theme contract: `2 failed, 2159 passed` in `e2e/test_theme_e2e.py` because the
tests still expected the disabled settings-page toggle to become interactive.
After the navbar move, focused logout and the next full pass captured the
remaining expected navigation RED: hidden Log out needed Menu to open, and two
keyboard tests still treated Session as the final menuitem.

## GREEN evidence

Code generation:

```bash
direnv exec . make gen-element-types
```

Result: exit 0; `ts/generated/props.ts` regenerated with
`ThemeToggleProps.disabled`. Generated output remains ignored and unstaged.

Required Python focus:

```bash
direnv exec . uv run --frozen pytest \
  tests/test_settings_page.py \
  tests/test_admin_settings_page.py \
  tests/test_settings_ui_kit_preview.py \
  tests/test_theme_layout.py -q
```

Result: exit 0, `43 passed`.

Required TypeScript focus, with the repository's Node 26 Vitest flag:

```bash
direnv exec . pnpm exec vitest run \
  ts/elements/theme-toggle.test.ts \
  ts/elements/live-setting-fields.test.ts \
  --execArgv=--no-experimental-webstorage
```

Result: exit 0, `2 files passed`, `24 tests passed`.

Required TypeScript compile:

```bash
direnv exec . pnpm exec tsc --noEmit -p tsconfig.check.json
```

Result: exit 0, no diagnostics.

Focused browser/navbar checks:

```bash
direnv exec . uv run --frozen pytest \
  e2e/test_theme_e2e.py::test_settings_control_updates_permanently_disabled_navbar_theme_state \
  e2e/test_theme_e2e.py::test_failed_theme_save_restores_system_state_then_allows_retry -q
direnv exec . uv run --frozen pytest \
  e2e/test_theme_e2e.py::test_logout_restores_the_anonymous_browser_preference -q
direnv exec . uv run --frozen pytest \
  e2e/test_widgets_e2e.py::test_navbar_menu_keyboard_navigation \
  e2e/test_widgets_e2e.py::test_navbar_menu_arrow_roving -q
```

Results: exit 0; respectively `2 passed`, `1 passed`, and `2 passed`.

Final repository gate:

```bash
direnv exec . make check
```

Result: exit 0. Ruff check/format, mypy (222 files), element/icon codegen,
TypeScript check/emit, and Tailwind passed; Vitest reported `41 files passed,
648 tests passed`; pytest including browser coverage reported
`2161 passed in 237.20s`.

## Files changed

- `common/components/__init__.py`
- `common/components/custom_elements.py`
- `common/components/primitives.py`
- `common/components/theme.py`
- `common/layout.py`
- `games/views/settings.py`
- `games/views/settings_kit_preview.py`
- `ts/elements/theme-toggle.ts`
- `ts/elements/theme-toggle.test.ts`
- `tests/test_theme_layout.py`
- `tests/test_settings_page.py`
- `tests/test_admin_settings_page.py`
- `tests/test_settings_ui_kit_preview.py`
- `e2e/test_theme_e2e.py`
- `e2e/test_widgets_e2e.py`

## Self-review

- Confirmed page identity is carried only by explicit `is_settings_page` flags;
  there is no URL, route-name, title, heading, or content inspection.
- Confirmed only personal settings, admin settings, and the DEBUG preview set
  the flag; ordinary-page server output remains enabled.
- Confirmed the typed host prop and native real-button `disabled` attribute are
  both present, the restriction label/tooltip remains stable, all three icons
  remain rendered, and shared element-owned disabled utilities provide styling.
- Confirmed coordinator updates still refresh the displayed icon but cannot
  re-enable or relabel a permanent toggle; synthetic and native clicks cannot
  request or fetch a preference change.
- Confirmed normal toggles retain browser cycling, account saving, pending,
  rollback, and unavailable behavior; the existing disabled
  `LiveSettingFields` no-fetch coverage remains unchanged and passing.
- Confirmed the real personal/site theme controls remain enabled unless their
  existing source lock applies.
- Confirmed Settings, conditional Admin settings, and Log out are descendants
  of `#navbarMenu`; anonymous users get none, normal users get Settings and Log
  out, and superusers get all three.
- Confirmed logout remains POST-only with CSRF, uses `role="menuitem"` and
  roving `tabindex="-1"`, and keyboard End/wrap order covers the new final item.
- Confirmed no admin removal, purchase currency, event namespacing, external
  issues, or unrelated behavior was implemented.

## Concerns

No product-code concerns. The brief's literal `pnpm exec vitest` command omits
the Node 26 `--no-experimental-webstorage` flag documented in `CLAUDE.md`; the
flagged focused command and the authoritative `make check` path are green.

## Review follow-up: accessible disabled-theme tooltip

### Status and approach

Complete. The settings-page toggle remains a native disabled button and its
permanent click guard remains intact. When disabled, the shared server-rendered
popover now gives tooltip-trigger ownership to a separate `tabindex="0"` span
around the real button. That surface carries the restriction label and
`aria-describedby`, so pointer hover and keyboard focus can expose the
explanation. Enabled popovers retain the existing real-button trigger behavior.
The shared tooltip controller was not changed.

`ThemeToggleElement` now finds the real button through
`data-pop-over-control`, independently of whichever node owns
`data-pop-over-trigger`. Server-rendering, controller, presenter, and browser
coverage all model this trigger/control distinction.

### TDD evidence

Focused server-rendering RED:

```bash
direnv exec . uv run --frozen pytest tests/test_theme_layout.py -q
```

Result before implementation: exit 1, `1 failed, 8 passed`; the native disabled
button still carried `data-pop-over-trigger` and no focusable tooltip surface
was rendered.

The first repository-wide verification found two stale
`theme-setting.test.ts` fixtures that still modeled a theme toggle with only
`data-pop-over-trigger`. The affected synchronization test failed consistently,
including in isolation (`1 failed, 5 passed`). Updating those fixtures to the
new `data-pop-over-control data-pop-over-trigger` enabled-button contract made
the isolated file green (`6 passed`); no product behavior was changed for that
correction.

### GREEN evidence

Affected Python theme/layout surfaces:

```bash
direnv exec . uv run --frozen pytest \
  tests/test_theme_layout.py \
  tests/test_settings_page.py \
  tests/test_admin_settings_page.py \
  tests/test_settings_ui_kit_preview.py -q
```

Result: exit 0, `43 passed`.

Affected tooltip/theme-toggle Vitest coverage:

```bash
direnv exec . pnpm exec vitest run \
  ts/elements/pop-over.test.ts \
  ts/elements/theme-toggle.test.ts \
  --execArgv=--no-experimental-webstorage
```

Result: exit 0, `2 files passed`, `21 tests passed`.

Changed theme E2Es:

```bash
direnv exec . uv run --frozen pytest \
  e2e/test_theme_e2e.py::test_settings_control_updates_permanently_disabled_navbar_theme_state \
  e2e/test_theme_e2e.py::test_failed_theme_save_restores_system_state_then_allows_retry -q
```

Result: exit 0, `2 passed`. The first scenario verifies real pointer hover,
pointer leave, and keyboard focus on the separate tooltip surface while the
underlying control remains disabled.

TypeScript and diff checks:

```bash
direnv exec . pnpm exec tsc --noEmit -p tsconfig.check.json
git diff --check
```

Results: both exit 0, with no diagnostics.

Corrected final repository gate:

```bash
direnv exec . make check
```

Result: exit 0. Ruff check/format, mypy (222 files), element/icon codegen,
TypeScript check/emit, and Tailwind passed; Vitest reported `41 files passed,
649 tests passed`; pytest including browser coverage reported
`2161 passed in 234.23s`.

### Review follow-up concerns

None. Native disabled semantics and click suppression are retained; the
additional focusable surface exists only for permanently disabled popover
controls. Ordinary theme toggles and ordinary popovers keep their previous
button-trigger interaction.
