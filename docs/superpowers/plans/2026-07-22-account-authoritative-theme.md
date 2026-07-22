# Account-Authoritative Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace theme cookies and browser-to-account migration with server-hydrated account state, an anonymous-only localStorage preference, and one optimistic `ThemeCoordinator` shared by the navbar and Settings controls.

**Architecture:** `TimetrackerDocument()` renders the complete document-level theme configuration and a synchronous external bootstrap applies it before CSS. `ThemeCoordinator` is the sole interactive theme state/persistence owner; `ThemeToggleElement` and `ThemeSettingElement` are presenters. `FormFieldPresentation` decorates the Settings select without replacing canonical form rendering, while `SettingSourceBadgeElement` observes typed committed-setting events.

**Tech Stack:** Django 6, htpy-style Python components, TypeScript 7, native custom elements, Vitest/jsdom, pytest, Playwright, Caddy.

## Global Constraints

- Preference values and labels are exactly `system`/System, `light`/Light, and `dark`/Dark.
- `UserPreferences.theme = NULL` means no personal override and resolves through site/default settings.
- Account documents ignore localStorage unconditionally; browser-mode documents use only localStorage and the OS preference.
- Theme changes apply immediately; failed authenticated saves restore the last server-committed state.
- `theme-bootstrap.js` is a synchronous classic script with no imports or exports and precedes every executable script and stylesheet.
- `ThemeCoordinator` is the only code that PATCHes `THEME`.
- Existing unrelated worktree changes must be preserved.

---

### Task 1: Generalize FormFields presentation and explicit live-save ownership

**Files:**
- Modify: `common/components/primitives.py`
- Modify: `common/components/settings_kit.py`
- Modify: `games/views/session.py`
- Modify: `games/views/settings.py`
- Modify: `tests/test_settings_ui_kit.py`
- Modify: other callers found by `rg "extras=|label_extras=" -g '*.py'`

**Interfaces:**
- Produces: `FormFieldPresentation(label_extra=None, after_control=None, decorate_control=None)`.
- Produces: `FormFields(form, presentations=..., groups=...)` with no `extras` or `label_extras` parameters.
- Produces: `SettingFieldState.live_save: bool = True` and `[data-live-setting-control]` only for fields owned by `LiveSettingFieldsElement`.

- [ ] **Step 1: Add failing renderer and ownership tests**

Add focused tests proving that a decorated control remains inside the canonical label/error/help row, grouped and ungrouped rendering share the same path, unknown presentation keys raise, existing callers can express label/after-control content, and `live_save=False` retains `data-setting-key` without `data-live-setting-control`.

```python
presentation = FormFieldPresentation(
    label_extra=Badge("Personal", size="sm"),
    after_control=P()["Help"],
    decorate_control=lambda control: Element("control-owner")[control],
)
html = str(FormFields(form, presentations={"display_name": presentation}))
assert "<control-owner><input" in html
assert "Personal" in html and "Help" in html

state = SettingFieldState("THEME", "default", live_save=False)
assert 'data-setting-key="THEME"' in rendered
assert "data-live-setting-control" not in rendered
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `direnv exec . pytest tests/test_settings_ui_kit.py -q`

Expected: failures because `FormFieldPresentation`, `presentations`, and `live_save` do not exist.

- [ ] **Step 3: Implement the presentation object and migrate callers**

Add the frozen parameter object, validate presentation keys once, pass one presentation into `_form_field_row()`, apply `decorate_control` only to `Safe(str(field))`, and migrate every `extras`/`label_extras` caller. Add `SettingFieldState.live_save`; stamp the positive marker only when true.

```python
@dataclass(frozen=True, slots=True)
class FormFieldPresentation:
    label_extra: Node | None = None
    after_control: Node | None = None
    decorate_control: Callable[[Node], Node] | None = None
```

- [ ] **Step 4: Run renderer/settings-kit tests**

Run: `direnv exec . pytest tests/test_settings_ui_kit.py tests/test_settings_ui_kit_preview.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add common/components/primitives.py common/components/settings_kit.py games/views tests/test_settings_ui_kit.py tests/test_settings_ui_kit_preview.py
git commit -m "refactor(forms): compose per-field presentations"
```

### Task 2: Generate the closed theme vocabulary from THEME_CHOICES

**Files:**
- Modify: `timetracker/settings_registry.py`
- Modify: `common/components/ts_codegen.py`
- Modify: `games/management/commands/gen_element_types.py`
- Modify: `tests/test_ts_codegen.py`
- Modify: `tests/test_settings_registry.py`
- Generate: `ts/generated/theme-preferences.ts` (gitignored build artifact)

**Interfaces:**
- Produces: `render_choice_vocabulary(type_name, values_name, labels_name, choices) -> str`.
- Produces: `THEME_PREFERENCES`, `ThemePreference`, and `THEME_LABELS` in `ts/generated/theme-preferences.ts`.

- [ ] **Step 1: Add failing choice-vocabulary tests**

Cover deterministic output, escaping, empty values, and duplicate values. Assert the theme result is exactly:

```ts
export const THEME_PREFERENCES = ["system", "light", "dark"] as const;
export type ThemePreference = typeof THEME_PREFERENCES[number];
export const THEME_LABELS = {
  system: "System",
  light: "Light",
  dark: "Dark"
} satisfies Record<ThemePreference, string>;
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `direnv exec . pytest tests/test_ts_codegen.py tests/test_settings_registry.py -q`

- [ ] **Step 3: Implement generation and rename the Python choices**

Change `THEME_CHOICES` to System/Light/Dark. Implement the reusable renderer using `json.dumps`, validate unique non-empty string values, and add the generated target to `gen_element_types`.

- [ ] **Step 4: Generate and verify the contract**

Run: `direnv exec . python manage.py gen_element_types && direnv exec . pytest tests/test_ts_codegen.py tests/test_settings_registry.py -q && direnv exec . pnpm exec tsc --noEmit`

Expected: generated module exists and all commands pass.

- [ ] **Step 5: Commit**

```bash
git add timetracker/settings_registry.py common/components/ts_codegen.py games/management/commands/gen_element_types.py tests/test_ts_codegen.py tests/test_settings_registry.py
git commit -m "feat(theme): generate shared preference vocabulary"
```

### Task 3: Replace inline/cookie bootstrap with document hydration

**Files:**
- Create: `ts/theme-bootstrap.ts`
- Modify: `common/layout.py`
- Modify: `common/components/theme.py`
- Modify: `games/views/auth.py`
- Modify: `games/api.py`
- Delete: `timetracker/theme.py`
- Delete: `tests/test_theme_auth.py`
- Modify: `tests/test_theme_layout.py`
- Modify: `tests/test_settings_api.py`
- Modify: `games/migrations/0030_userpreferences_theme.py`
- Modify: `games/models.py`

**Interfaces:**
- Produces the `Html(...)` attributes named in the design: mode, allowed values, resolved/personal/inherited preference, source, update URL, and CSRF.
- Produces a self-contained IIFE bootstrap that writes `data-theme-preference` and the `dark` class.

- [ ] **Step 1: Rewrite Python tests for the final contract**

Assert anonymous documents have browser mode and no account transport; authenticated documents expose complete resolved/personal/inherited state and override stale browser state. Assert the external classic script is the first executable head script and precedes `base.css`. Delete cookie assertions and assert theme PATCH/login responses do not set theme cookies.

- [ ] **Step 2: Run the focused Python tests and confirm failures**

Run: `direnv exec . pytest tests/test_theme_layout.py tests/test_theme_auth.py tests/test_settings_api.py -q`

Expected: failures against the cookie/inline implementation; the deleted test file is removed after confirming its replacement coverage.

- [ ] **Step 3: Implement server hydration and cleanup**

Use `resolve_for_user_with_origin()` and `resolve_with_origin()` in `TimetrackerDocument()`. Render the exact root attributes, replace the inline script with `StaticScript("dist/theme-bootstrap.js")`, remove theme props from `ThemeToggle`, remove login/API cookie writes and imports, delete `timetracker/theme.py`, and amend migration `0030` to `system` with `max_length=6`.

- [ ] **Step 4: Implement and compile the classic bootstrap**

Keep the file script-scope-only—no imports or exports. Read allowed values from the root, prefer server state in account mode, otherwise safely read localStorage, fall back to System, and resolve the dark class through `matchMedia`.

- [ ] **Step 5: Verify Python, migration, and emitted JavaScript**

Run: `direnv exec . make ts && direnv exec . pytest tests/test_theme_layout.py tests/test_settings_api.py -q && direnv exec . python manage.py makemigrations --check --dry-run`

Expected: all pass; emitted `theme-bootstrap.js` contains no top-level import/export.

- [ ] **Step 6: Commit**

```bash
git add ts/theme-bootstrap.ts common/layout.py common/components/theme.py games/views/auth.py games/api.py games/migrations/0030_userpreferences_theme.py games/models.py tests/test_theme_layout.py tests/test_settings_api.py
git rm timetracker/theme.py tests/test_theme_auth.py
git commit -m "refactor(theme): hydrate account state without cookies"
```

### Task 4: Standardize committed-setting events and badge ownership

**Files:**
- Create: `ts/settings-events.ts`
- Create: `ts/elements/setting-source-badge.ts`
- Create: `ts/elements/setting-source-badge.test.ts`
- Modify: `ts/elements/live-setting-fields.ts`
- Modify: `ts/elements/live-setting-fields.test.ts`
- Modify: `common/components/settings_kit.py`
- Modify: `common/components/custom_elements.py`
- Modify: `tests/test_settings_ui_kit.py`

**Interfaces:**
- Produces: `ResolvedSetting`, `SETTING_COMMITTED_EVENT`, response validation, and `dispatchSettingCommitted(resolved)`.
- Produces: `SettingSourceBadgeElement`, which updates only its matching badge.
- Changes `LiveSettingFieldsElement` discovery to `[data-live-setting-control]` and removes its configurable event prop/private metadata updater.

- [ ] **Step 1: Write failing TypeScript and Python tests**

Assert complete payload dispatch, invalid payload rejection, key-filtered badge updates, positive control discovery, and removal of the configurable `event` attribute.

- [ ] **Step 2: Run and confirm failures**

Run: `direnv exec . pnpm vitest run ts/elements/live-setting-fields.test.ts ts/elements/setting-source-badge.test.ts && direnv exec . pytest tests/test_settings_ui_kit.py -q`

- [ ] **Step 3: Implement the typed event and presenter**

Move source labels/descriptions/tone updates into `SettingSourceBadgeElement`; register its generated key prop and media. Dispatch the validated server response after generic saves. Listen on `document.body`, because committed events do not bubble downward.

- [ ] **Step 4: Verify focused tests and TypeScript**

Run: `direnv exec . make gen-element-types && direnv exec . pnpm vitest run ts/elements/live-setting-fields.test.ts ts/elements/setting-source-badge.test.ts && direnv exec . pnpm exec tsc --noEmit && direnv exec . pytest tests/test_settings_ui_kit.py -q`

- [ ] **Step 5: Commit**

```bash
git add ts/settings-events.ts ts/elements/setting-source-badge.ts ts/elements/setting-source-badge.test.ts ts/elements/live-setting-fields.ts ts/elements/live-setting-fields.test.ts common/components/settings_kit.py common/components/custom_elements.py tests/test_settings_ui_kit.py
git commit -m "refactor(settings): give source badges commit ownership"
```

### Task 5: Implement ThemeCoordinator as an explicit state machine

**Files:**
- Create: `ts/theme-coordinator.ts`
- Create: `ts/theme-coordinator.test.ts`

**Interfaces:**
- Produces: `getThemeCoordinator()`, `ThemeCoordinatorState`, `ThemeSnapshot`, and `requestPreferenceChange(value): Promise<"committed" | "rolled-back" | "busy">`.
- Consumes generated theme preferences and the typed resolved-setting validator/event helper.

- [ ] **Step 1: Write the state-machine tests first**

Cover browser/account/unavailable initialization; System OS changes; immediate optimistic notification; success; nullable inherited success; network and malformed-response rollback; `busy`; both subscription orders; multiple subscribers; disconnect/reconnect during save; anonymous localStorage writes and storage removal/invalid events; authenticated storage-event isolation.

- [ ] **Step 2: Run and confirm failures**

Run: `direnv exec . pnpm vitest run ts/theme-coordinator.test.ts`

- [ ] **Step 3: Implement the minimal coordinator**

Parse root configuration once into a discriminated union. Keep committed and optimistic account snapshots separate. Subscribers receive current state synchronously. Never cancel a save on unsubscribe. Validate responses before commit; log and toast on rollback; dispatch the committed response after success.

- [ ] **Step 4: Run coordinator tests and type-check**

Run: `direnv exec . pnpm vitest run ts/theme-coordinator.test.ts && direnv exec . pnpm exec tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add ts/theme-coordinator.ts ts/theme-coordinator.test.ts
git commit -m "feat(theme): centralize interactive theme state"
```

### Task 6: Convert ThemeToggleElement and add ThemeSettingElement

**Files:**
- Modify: `ts/elements/theme-toggle.ts`
- Modify: `ts/elements/theme-toggle.test.ts`
- Create: `ts/elements/theme-setting.ts`
- Create: `ts/elements/theme-setting.test.ts`
- Modify: `common/components/theme.py`
- Modify: `games/views/settings.py`
- Modify: `tests/test_settings_page.py`

**Interfaces:**
- `ThemeToggleElement` subscribes and cycles only System/Light/Dark.
- `ThemeSettingElement` decorates one select, maps blank to null, stops its change event, and subscribes to coordinator state.
- The Python theme select is `required=False`, includes `Use site default (<resolved label>)`, uses `SettingFieldState.live_save=False`, and renders a `block w-full` wrapper.

- [ ] **Step 1: Rewrite/add failing presenter tests**

Assert generated icons/labels/cycle order, tooltip and accessible-label updates, subscriber-driven disabled/ARIA state, no fetch/storage/direct Settings lookup in `ThemeToggleElement`, blank/null mapping, stopped propagation, and reconnect behavior.

- [ ] **Step 2: Run and confirm failures**

Run: `direnv exec . pnpm vitest run ts/elements/theme-toggle.test.ts ts/elements/theme-setting.test.ts && direnv exec . pytest tests/test_settings_page.py -q`

- [ ] **Step 3: Implement both presenters and Python composition**

Build the three SVGs through Node/Element builders using `data-theme-icon="system|light|dark"`; retain the approved half-circle System icon. Subscribe/unsubscribe without configuring state. Decorate the select through `FormFieldPresentation.decorate_control` and attach both custom-element media modules.

- [ ] **Step 4: Verify presenters, settings page, and tooltip behavior**

Run: `direnv exec . make gen-element-types && direnv exec . pnpm vitest run ts/elements/theme-toggle.test.ts ts/elements/theme-setting.test.ts ts/elements/pop-over.test.ts && direnv exec . pytest tests/test_settings_page.py tests/test_theme_layout.py -q`

- [ ] **Step 5: Commit**

```bash
git add ts/elements/theme-toggle.ts ts/elements/theme-toggle.test.ts ts/elements/theme-setting.ts ts/elements/theme-setting.test.ts common/components/theme.py games/views/settings.py tests/test_settings_page.py
git commit -m "feat(theme): synchronize navbar and settings presenters"
```

### Task 7: Add immutable hashed-static delivery and production checks

**Files:**
- Modify: `Caddyfile`
- Modify: `tests/test_hashed_static.py`
- Modify: `Dockerfile` if needed to validate Caddy configuration during the image build

**Interfaces:**
- Hashed `/static/` filenames containing `.[0-9a-f]{12}.` receive `Cache-Control: public, max-age=31536000, immutable`.
- Unhashed `/static/` paths do not receive that header.

- [ ] **Step 1: Add failing production-static tests**

Extend collection coverage to `theme-bootstrap.js`, verify its hashed URL and ordering under `DEBUG=False`, and add a Caddy configuration/integration assertion for hashed versus unhashed cache headers.

- [ ] **Step 2: Run and confirm failures**

Run: `direnv exec . make ts && direnv exec . pytest tests/test_hashed_static.py -q`

- [ ] **Step 3: Add the narrow Caddy matcher and validation**

Configure a named `path_regexp` matcher inside `/static/*`, set the immutable header only for the 12-hex hashed fragment, and keep `file_server` behavior unchanged for all paths. Validate the checked-in Caddyfile with the same Caddy version used by the image.

- [ ] **Step 4: Verify production static behavior**

Run: `direnv exec . pytest tests/test_hashed_static.py -q`

Expected: hashed bootstrap and stylesheet URLs resolve and only hashed paths match the immutable policy.

- [ ] **Step 5: Commit**

```bash
git add Caddyfile Dockerfile tests/test_hashed_static.py
git commit -m "perf(static): cache content-hashed assets immutably"
```

### Task 8: End-to-end behavior, cleanup, and full verification

**Files:**
- Modify: `e2e/test_theme_e2e.py`
- Modify: documentation/changelog files found by `rg -n "Auto|auto|theme migration|color-theme" README.md docs CHANGELOG.md settings.ini.example`
- Modify: PR description outside git after local verification

**Interfaces:**
- Produces complete browser proof for anonymous first paint, account authority, inheritance, rollback, tooltip reopening, and full-navigation convergence.

- [ ] **Step 1: Replace legacy e2e assertions with approved scenarios**

Cover anonymous localStorage first frame/System OS response; login ignores stale storage; logout resumes anonymous state; all three account preferences prepaint; two-browser next-navigation convergence; toggle/select synchronization; null inheritance; rejected save rollback from inherited Dark and inherited System; tooltip reopening and retry.

- [ ] **Step 2: Run focused e2e tests**

Run: `direnv exec . pytest e2e/test_theme_e2e.py -q`

Expected: all pass against the completed implementation.

- [ ] **Step 3: Remove stale terminology and documentation**

Use `rg` to remove user-facing Auto, cookie migration, and brittle numeric test totals. Keep `auto` only where unrelated to theming.

- [ ] **Step 4: Run final verification from a clean generated state**

Run: `direnv exec . make check`

Run: `direnv exec . python manage.py makemigrations --check --dry-run`

Run: `git diff --check && git status --short`

Expected: checks pass, no unexpected migration, no whitespace errors, and only intentional tracked changes remain.

- [ ] **Step 5: Commit final tests/documentation**

```bash
git add e2e docs README.md CHANGELOG.md settings.ini.example
git commit -m "test(theme): verify account-authoritative behavior"
```
