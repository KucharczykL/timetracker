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
  effective preferences: System, Light, and Dark.
- Anonymous pages persist their theme in localStorage. Successful authentication
  ignores anonymous localStorage and uses the resolved account preference.
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

`TimetrackerDocument()` resolves `THEME` with
`resolve_str_for_user(request.user, "THEME")` for authenticated requests. It
renders the result on `Html(...)` as `data-theme-preference`. Anonymous documents
omit that attribute.

`THEME_CHOICES` is the server source of truth for the closed preference set and
labels. `TimetrackerDocument()` also renders its generated values as
`data-theme-preferences="system light dark"` on every document so the classic
bootstrap can validate anonymous localStorage without hard-coding another copy.

A new `ts/theme-bootstrap.ts` is compiled to
`games/static/js/dist/theme-bootstrap.js` and included as a synchronous classic
script before `base.css`. It is an IIFE with no imports or exports; it must not be
loaded through `ModuleScript()`, `defer`, or `async`.

The bootstrap performs only prepaint state application:

1. Read the generated allowed values from `data-theme-preferences`.
2. If `data-theme-preference` is a valid server value, use it.
3. Otherwise, read and validate the anonymous `color-theme` localStorage value.
4. Fall back to `system`.
5. Set `data-theme-preference` and add/remove `<html class="dark">`, resolving
   System through `matchMedia("(prefers-color-scheme: dark)")`.

The bootstrap does not call the API, render controls, or contain Python-generated
JavaScript. The current `theme_bootstrap_script()` function is removed.

### Interactive state and persistence

A new shared TypeScript singleton, `ThemeCoordinator`, owns interactive theme
state after bootstrap. For authenticated pages it distinguishes the effective
preference displayed by `ThemeToggleElement` from the nullable personal selection
displayed by `ThemeSettingElement`. It holds the effective preference, personal
selection (`ThemePreference | null`), inherited site/default preference, last
server-committed state, authenticated/anonymous persistence configuration,
saving state, OS media listener, and subscribers.

`ThemeCoordinator` exposes typed operations to:

- configure anonymous or authenticated persistence idempotently;
- subscribe/unsubscribe a rendered control;
- request a preference change;
- apply the effective `dark` class;
- react to anonymous cross-tab localStorage changes.

Only `ThemeCoordinator` PATCHes `THEME`. An authenticated request follows this
sequence:

1. Set the effective preference and personal selection immediately and notify
   every subscriber. Selecting `null` applies the known inherited preference.
2. Mark saving and disable every subscribed control.
3. Send one PATCH; overlapping requests are impossible while saving.
4. On success, accept the validated server value/source as effective and
   committed; retain a `null` personal selection when the source is inherited.
5. On failure, restore the previous committed effective preference and personal
   selection, then show the error toast.
6. Clear saving and re-enable every subscriber.

Anonymous requests apply immediately and write `color-theme` to localStorage;
they never call the API. Authenticated pages do not read anonymous localStorage
or authenticated storage events. Account changes from another browser or tab
are authoritatively reconciled on the next full-page navigation.

`ThemeToggleElement` becomes a subscriber/presenter. It renders the icon,
tooltip, and accessible label for the current state and asks `ThemeCoordinator`
for the next generated preference when clicked. It no longer owns fetch,
rollback, localStorage, `matchMedia`, or direct Settings DOM synchronization.

A new `ThemeSettingElement` owns the Settings theme `<select>`. Its generated
props include the concrete endpoint/CSRF token, the initial nullable personal
selection, and the resolved inherited preference. The blank choice is labeled
`Use site default (<resolved label>)`. The element configures and subscribes to
`ThemeCoordinator`, stops its theme `change` event before it reaches
`LiveSettingFieldsElement`, and delegates the requested value. It updates the
select value, disabled state, and `aria-busy` from coordinator notifications.
`LiveSettingFieldsElement` therefore continues to own every generic live setting
except `THEME`; it neither saves nor snapshots the theme select.

After a committed theme save, `ThemeCoordinator` dispatches the existing settings
success event with the complete validated server response, including `value`,
`source`, and `locked`. `LiveSettingFieldsElement` listens for external commits
and reuses its existing source-metadata update path, without taking ownership of
the theme select. Its own successful saves adopt the same full-response event
contract instead of dispatching the attempted value. This keeps the Settings
source badge correct after both `ThemeSettingElement` and `ThemeToggleElement`
saves and removes direct DOM access from `ThemeToggleElement`.

Both custom elements receive the concrete theme endpoint and CSRF token through
their generated prop contracts, making coordinator configuration independent of
custom-element connection or module execution order.

The existing general tooltip observer remains. When `ThemeCoordinator`
re-enables the hovered `ThemeToggleElement` button, the tooltip reopens without
requiring pointer movement.

## Generated contract

The existing `gen_element_types` management command additionally generates
`ts/generated/theme-preferences.ts` from `THEME_CHOICES`. The generated module
contains both the tuple and display labels:

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

The legacy-browser migration removed by this design is distinct from Django
schema/data migrations. Migration `0030_userpreferences_theme` has already been
applied on staging and contains the value `auto`, so it remains immutable. A new
reversible migration:

- converts stored `auto` values to `system`;
- alters the field choices to System/Light/Dark;
- reverses `system` to `auto` if rolled back.

No browser localStorage conversion is performed. An anonymous `auto` value is
invalid under the generated contract and naturally falls back to System, which
has identical effective behavior.

## Deletions and documentation

Remove:

- `color-theme` and `color-theme-migrate` cookie handling;
- login and API `Set-Cookie` behavior;
- `THEME_COOKIE_*` and migration-marker constants;
- `data-theme-migration` and automatic migration PATCH logic;
- legacy browser-to-account migration documentation and tests;
- direct DOM synchronization between `ThemeToggleElement` and the Settings
  select.

Update documentation, changelog, Settings labels/help text, tooltips, and tests
to use System consistently. The PR body records `make check` without brittle
numeric test totals.

## Verification

### Browser coverage: `e2e/test_theme_e2e.py`

- Anonymous localStorage applies on the first frame.
- Anonymous System follows light and dark operating-system schemes.
- An authenticated server preference overrides stale localStorage on the first
  frame.
- System, Light, and Dark each render correctly before first paint.
- Browser A saves Dark; an already-authenticated browser B receives Dark on its
  next full-page navigation.
- `ThemeToggleElement` and `ThemeSettingElement` stay synchronized.
- Selecting `Use site default (...)` applies the inherited preference
  immediately, persists `null`, and updates the Settings source badge.
- A rejected save immediately rolls both controls back to the committed value,
  re-enables both controls, reports the error, and reopens a hovered tooltip.

Delete legacy migration and cookie assertions.

### TypeScript coverage

- `ThemeCoordinator` applies requested values immediately.
- All subscribers receive displayed and saving-state changes.
- A successful response establishes the committed value.
- A successful nullable response preserves a `null` personal selection while
  exposing the inherited effective preference.
- A failed response restores the previous committed effective preference and
  personal selection.
- Controls cannot create overlapping PATCH requests.
- Anonymous requests write localStorage without calling the API.
- Anonymous storage events synchronize tabs; authenticated pages ignore them.
- `theme-bootstrap.ts` covers server values, anonymous localStorage, invalid and
  unavailable storage, and System under both OS schemes.
- Generated values, labels, and cycle order are used by both controls.

### Python coverage

- `tests/test_theme_layout.py` verifies authenticated
  `data-theme-preference`, anonymous omission, generated
  `data-theme-preferences`, and the external classic script before `base.css`.
- `tests/test_settings_api.py` verifies System/Light/Dark persistence and durable
  `null` clearing without cookies.
- `tests/test_settings_page.py` verifies the dynamic
  `Use site default (<resolved label>)` choice and nullable initial selection.
- Cookie-only `tests/test_theme_auth.py` coverage is removed.
- Codegen tests verify `THEME_CHOICES` and
  `ts/generated/theme-preferences.ts` remain identical.
- The new Django migration is tested in both directions.

Final verification is the full `direnv exec . make check` plus
`python manage.py makemigrations --check --dry-run` inside the Nix development
shell.
