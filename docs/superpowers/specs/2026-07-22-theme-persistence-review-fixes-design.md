# Design: account-authoritative theme persistence

> Approved follow-up design for PR #468 after comprehensive review.

## Context

PR #468 moves theme selection from browser-only state into `UserPreferences`,
adds System/Light/Dark controls in the navbar and Settings, and prevents a flash
of the wrong theme before CSS loads. Review found that the implementation makes
the cookie and legacy-browser migration state authoritative in places where the
account should be authoritative, and that `ThemeToggleElement` and
`LiveSettingFieldsElement` independently save the same setting.

The revised design removes legacy-browser migration and theme cookies entirely.
Choosing a theme is inexpensive enough that preserving an old anonymous choice
through the upgrade does not justify a migration state machine.

## Settled behavior

- The three preference values and user-facing names are **System**, **Light**,
  and **Dark**. Their stored/API values are `system`, `light`, and `dark`.
- System follows `prefers-color-scheme` and updates when the operating-system
  preference changes.
- `UserPreferences.theme = NULL` has exactly one meaning: no personal override;
  resolve through the site and built-in defaults.
- The Settings theme select includes `Use site default (<resolved label>)` as a
  nullable fourth option. `ThemeToggleElement` continues to cycle only the three
  resolved preferences: System, Light, and Dark.
- Anonymous pages persist their theme in localStorage. Successful authentication
  ignores anonymous localStorage and uses the resolved account preference.
- Logging out resumes the anonymous localStorage preference that existed before
  login. Authenticated pages never overwrite or clear it.
- Authenticated full-page responses provide the current resolved account theme.
  The server-provided value wins unconditionally over browser state.
- Another authenticated browser receives an account change on its next full-page
  navigation, subject to the settings resolver's existing five-second
  cross-worker convergence window.
- Theme changes apply immediately. A failed authenticated save restores the last
  server-committed theme and shows an error toast.
- Theme cookies and legacy localStorage-to-account migration do not exist.

## State ownership

### Server and first paint

`TimetrackerDocument()` is the one initialization authority for the proposed
`ThemeCoordinator`. For authenticated requests it resolves `THEME`, the nullable
personal override, and the inherited site/default preference. It renders one
complete document-level configuration on `Html(...)`:

- `data-theme-mode="account|browser"`;
- `data-theme-preference="system|light|dark"` for the server-resolved account
  preference (browser mode initially omits it and the bootstrap writes it);
- `data-theme-personal-preference=""` for null or a generated preference value;
- `data-theme-inherited-preference="system|light|dark"`;
- `data-theme-source="..."`;
- `data-theme-update-url="..."` and `data-theme-csrf="..."` in account mode;
- `data-theme-preferences="system light dark"` on every document.

The attributes form one written/read contract. A nullable personal preference is
represented explicitly rather than inferred from the resolved value. Browser
mode omits the account-only attributes. No custom element carries another copy of
this initial state or transport configuration.

`THEME_CHOICES` is the server source of truth for the closed preference set and
labels. `TimetrackerDocument()` also renders its generated values as
`data-theme-preferences="system light dark"` on every document so the classic
bootstrap can validate anonymous localStorage without hard-coding another copy.

A new `ts/theme-bootstrap.ts` is compiled to
`games/static/js/dist/theme-bootstrap.js` and included as a synchronous classic
script as the first executable script in `<head>`, before unrelated vendor scripts
and `base.css`. It is an IIFE with no imports or exports; it must not be loaded
through `ModuleScript()`, `defer`, or `async`.

Production Caddy delivery adds
`Cache-Control: public, max-age=31536000, immutable` only for `/static/` filenames
containing Django's 12-hex content-hash fragment (`.<12 hex>.`). Unhashed static
paths do not receive the immutable policy. This realizes the existing
`HashedStaticStorage` cache-forever contract and makes the parser-blocking
bootstrap a browser-cache hit after its first download.

The bootstrap performs only prepaint state application:

1. Read the generated allowed values from `data-theme-preferences`.
2. In account mode, use the valid server-resolved preference unconditionally.
3. Otherwise, read and validate the anonymous `color-theme` localStorage value.
4. In browser mode, treat missing or invalid storage as `system`.
5. Set `data-theme-preference` and add/remove `<html class="dark">`, resolving
   System through `matchMedia("(prefers-color-scheme: dark)")`.

The bootstrap does not call the API, render controls, or contain Python-generated
JavaScript. The current `theme_bootstrap_script()` function is removed.

### Interactive state and persistence

A new shared TypeScript singleton, `ThemeCoordinator`, owns interactive theme
state after bootstrap. It parses the `TimetrackerDocument()` configuration exactly
once and uses a discriminated state model: browser, account/idle,
account/saving, or unavailable. The state uses distinct names for distinct facts:

- `resolvedPreference`: `system | light | dark`, displayed by
  `ThemeToggleElement`;
- `effectiveColorScheme`: `light | dark`, after resolving System against the OS;
- `personalPreference`: `ThemePreference | null`, displayed by
  `ThemeSettingElement`;
- `inheritedPreference`: the site/default preference applied when the personal
  preference is null.

Account state keeps separate `committed` and `optimistic` snapshots, the resolved
source, transport configuration, the OS media listener, and subscribers.

`ThemeCoordinator` exposes typed operations to:

- subscribe/unsubscribe a rendered control;
- request a preference change;
- apply the effective `dark` class;
- react to anonymous cross-tab localStorage changes.

Only `ThemeCoordinator` PATCHes `THEME`. An authenticated request follows this
sequence:

1. Set the resolved preference and personal selection immediately and notify
   every subscriber. Selecting `null` applies the known inherited preference.
2. Mark saving and disable every subscribed control.
3. Send one PATCH. A second programmatic request returns an explicit `busy`
   result; requests are neither silently discarded nor queued.
4. On success, accept the validated server value/source as resolved and
   committed; retain a `null` personal selection when the source is inherited.
5. On failure, restore the previous committed resolved preference and personal
   selection, then show the error toast.
6. Clear saving and re-enable every subscriber.

Each subscription immediately receives current state. Disconnecting a custom
element only unsubscribes it and never cancels or mutates an in-flight save.
Reconnection therefore receives the current coordinator state rather than stale
server-rendered control values. Multiple instances of either control are valid.

Before accepting a successful PATCH, `ThemeCoordinator` validates that the
response has key `THEME`, a generated preference value, a recognized source, and
`locked: false`. A concrete request must return the same value from the user
source; a null request must return an inherited source. Invalid JSON and
contract violations follow the failure/rollback path and are logged. The next
full-page navigation reconciles the rare case where the server committed but sent
an invalid response; no recovery GET is added.

Invalid document configuration puts `ThemeCoordinator` into unavailable state,
disables its subscribers, and logs an actionable error instead of guessing.

Anonymous requests apply immediately and write `color-theme` to localStorage;
they never call the API. Anonymous storage events apply a valid new preference;
removal or an invalid value applies System, with invalid values also logged.
Receiving tabs do not write in response, avoiding feedback loops. Authenticated
pages do not read anonymous localStorage or storage events. Account changes from
another browser or tab are authoritatively reconciled on the next full-page
navigation.

`ThemeToggleElement` becomes a subscriber/presenter. It renders the icon,
tooltip, and accessible label for the current state and asks `ThemeCoordinator`
for the next generated preference when clicked. It no longer owns fetch,
rollback, localStorage, `matchMedia`, or direct Settings DOM synchronization.

A new `ThemeSettingElement` owns the Settings theme `<select>`. The select is
decorated with the custom element through `FormFields`; both controls read state
and transport from the already-initialized `ThemeCoordinator`. The blank choice
is labeled `Use site default (<resolved label>)`, and the Django `ChoiceField`
uses `required=False` so the null choice is valid and does not emit a misleading
`required` attribute. The element subscribes to
`ThemeCoordinator`, stops its theme `change` event before it reaches
`LiveSettingFieldsElement`, and delegates the requested value. It updates the
select value, disabled state, and `aria-busy` from coordinator notifications.
`LiveSettingFieldsElement` therefore continues to own every generic live setting
except `THEME`; it neither saves nor snapshots the theme select.

After any committed setting save, the owner dispatches one typed
`setting-committed` event on `document.body` with the complete validated server
response: `key`, `value`, `source`, and `locked`. A proposed
`SettingSourceBadgeElement` wraps the existing `SettingSourceBadge` markup,
listens for that event, filters on its generated setting-key prop, and updates its
own label, tooltip description, source styling, and locked state.
`LiveSettingFieldsElement` and `ThemeCoordinator` share a typed
`dispatchSettingCommitted()` helper. The configurable event prop and
`LiveSettingFieldsElement.updateSourceMetadata()` are removed. Events report
committed facts; they are not another theme state store.

The existing general tooltip observer remains. When `ThemeCoordinator`
re-enables the hovered `ThemeToggleElement` button, the tooltip reopens without
requiring pointer movement.

## Form rendering and save ownership

`FormFields` adopts a Parameter Object plus Strategy/Decorator design instead of
adding another parallel mapping argument. A frozen `FormFieldPresentation`
contains a field's optional label metadata, content after the control, and an
optional `decorate_control` callable. `FormFields` accepts one `presentations`
mapping keyed by field name. Existing `extras` and `label_extras` call sites are
migrated immediately and those arguments are removed.

`_form_field_row()` still renders the Django control through the canonical
`Safe(str(field))` path, applies `decorate_control` when present, and then renders
the established label, errors, checkbox layout, and metadata. Grouped and
ungrouped fields use the same path; unknown presentation keys fail loudly. Full
row replacement is deliberately not supported.

Setting identity and save ownership are separate capabilities. Every setting
control retains `data-setting-key`, while only controls owned by
`LiveSettingFieldsElement` receive the positive `data-live-setting-control`
marker. `SettingFieldState.live_save` records whether generic live saving applies;
`prepare_setting_fields()` stamps the marker and produces/merges
`FormFieldPresentation` values. The theme state opts out and supplies a
`decorate_control` that wraps its select with `ThemeSettingElement`. The Python
component renders `class_="block w-full"`; custom elements otherwise default to
inline layout and would not preserve the select's full-width field geometry.
`LiveSettingFieldsElement` discovers and snapshots only
`[data-live-setting-control]` descendants.

## Generated contract

The existing `gen_element_types` management command additionally generates
`ts/generated/theme-preferences.ts` from `THEME_CHOICES`. A reusable
choice-vocabulary renderer accepts Django-style value/label pairs, validates
them, and emits a const tuple, its derived union, and the display-label record:

```ts
export const THEME_PREFERENCES = ["system", "light", "dark"] as const;
export type ThemePreference = typeof THEME_PREFERENCES[number];
export const THEME_LABELS = {
  system: "System",
  light: "Light",
  dark: "Dark",
} satisfies Record<ThemePreference, string>;
```

`ThemeCoordinator`, `ThemeToggleElement`, and `ThemeSettingElement` import this
contract. The classic bootstrap obtains the same values from the server-rendered
`data-theme-preferences` attribute because importing an ES module would make the
script deferred. `gen-element-types` regenerates the module before TypeScript
checking and tests, as it already does for the other generated contracts.

System help text explains that it follows the operating-system theme. Tooltips
use generated labels, for example `Theme: System — switch to Light`.

## Database transition

There are no consumers of the unreleased `auto` value and the staging database is
disposable. Amend `0030_userpreferences_theme` directly to use `system`,
`max_length=6`, and the final choices, then reset staging. Do not add `0031`, data
conversion, or an external-configuration alias. `auto` is invalid everywhere.

No browser localStorage conversion is performed. An anonymous `auto` value is
invalid under the generated contract and naturally falls back to System.

## Deletions and documentation

Remove:

- `color-theme` and `color-theme-migrate` cookie handling;
- login and API `Set-Cookie` behavior;
- `THEME_COOKIE_*` and migration-marker constants;
- `data-theme-migration` and automatic migration PATCH logic;
- legacy browser-to-account migration documentation and tests;
- direct DOM synchronization between `ThemeToggleElement` and the Settings
  select.

Development/staging cookies are ignored and allowed to expire naturally. No
one-release cookie-deletion response remains in production code.

Update documentation, changelog, Settings labels/help text, tooltips, and tests
to use System consistently. The PR body records `make check` without brittle
numeric test totals.

## Verification

### Browser coverage: `e2e/test_theme_e2e.py`

- Anonymous localStorage applies on the first frame.
- Anonymous System follows light and dark operating-system schemes.
- Logging out resumes the anonymous preference that existed before login.
- An authenticated server preference overrides stale localStorage on the first
  frame.
- System, Light, and Dark each render correctly before first paint.
- Browser A saves Dark; an already-authenticated browser B receives Dark on its
  next full-page navigation.
- `ThemeToggleElement` and `ThemeSettingElement` stay synchronized.
- Selecting `Use site default (...)` applies the inherited preference
  immediately, persists `null`, and updates the Settings source badge.
- Starting from a null personal preference with inherited Dark, a rejected save
  restores the blank select, Dark preference/icon/class, inherited source badge,
  both controls, retry capability, and a hovered tooltip.
- Starting from null with inherited System, rollback restores the blank select
  and System preference/icon, including subsequent OS-scheme changes.

Delete legacy migration and cookie assertions.

### TypeScript coverage

- `ThemeCoordinator` applies requested values immediately.
- All subscribers receive displayed and saving-state changes.
- A successful response establishes the committed value.
- A successful nullable response preserves a `null` personal selection while
  exposing the inherited resolved preference.
- A failed response restores the previous committed resolved preference and
  personal selection.
- Controls cannot create overlapping PATCH requests.
- A second programmatic request while saving returns `busy`.
- Both custom-element connection orders, multiple instances, and
  disconnect/reconnect during a save preserve coordinator state.
- Invalid document configuration enters unavailable state; malformed successful
  responses roll back, report the error, and do not prevent a later valid retry.
- Anonymous requests write localStorage without calling the API.
- Anonymous storage events synchronize tabs, with removal/invalid values applying
  System; authenticated pages ignore them.
- `theme-bootstrap.ts` covers server values, anonymous localStorage, invalid and
  unavailable storage, and System under both OS schemes.
- Generated values, labels, and cycle order are used by both controls.
- `SettingSourceBadgeElement` accepts only complete committed-event payloads and
  updates only the badge whose key matches.

### Python coverage

- `tests/test_theme_layout.py` verifies the complete account/browser document
  configuration, generated `data-theme-preferences`, and the external classic
  script before every other executable script and `base.css`.
- `tests/test_settings_api.py` verifies System/Light/Dark persistence and durable
  `null` clearing without cookies.
- `tests/test_settings_page.py` verifies the dynamic
  `Use site default (<resolved label>)` choice, `required=False`, nullable initial
  selection, and the block/full-width `ThemeSettingElement` wrapper.
- `tests/test_settings_ui_kit.py` verifies `FormFieldPresentation` for grouped and
  ungrouped fields, control decoration without bypassing labels/errors/metadata,
  rejection of unknown keys, and positive `data-live-setting-control` ownership.
- Cookie-only `tests/test_theme_auth.py` coverage is removed.
- Codegen tests verify the reusable choice-vocabulary renderer and that
  `THEME_CHOICES` and `ts/generated/theme-preferences.ts` remain identical.
- Migration tests verify amended migration `0030` has the final System contract.
- `tests/test_hashed_static.py` compiles/collects the bootstrap under production
  manifest storage, verifies its hashed URL and ordering before the hashed
  stylesheet, and asserts the emitted script remains import/export-free.
- Caddy configuration validation covers the hashed-filename matcher and verifies
  that only hashed `/static/` responses receive the one-year immutable cache
  header.

Final verification is the full `direnv exec . make check` plus
`python manage.py makemigrations --check --dry-run` inside the Nix development
shell.
