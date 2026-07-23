# Design: superuser site settings page

> Approved design for issue #390, revised after the per-user presentation work
> merged in PR #480.

## Context

The settings epic already provides an origin-aware registry and resolver,
database-backed site defaults and personal overrides, authenticated settings
APIs, the reusable settings UI kit, and the personal `/settings` page. Issue
#390 adds the superuser-facing `/admin-settings` page.

The issue originally named `DEFAULT_CURRENCY` as the only editable site default
and described infrastructure `TZ` as a display-only field. PR #480 subsequently
introduced `DISPLAY_TIME_ZONE`: a validated, live setting used for wall-clock
display and datetime-form interpretation. It is deliberately distinct from
boot-time `TZ`, which initializes Django's `TIME_ZONE` before database-backed
resolution is available.

Stage 8 will therefore expose `DISPLAY_TIME_ZONE` as the editable site-wide
“Time zone” default. Infrastructure `TZ` remains boot-only and is deferred,
along with every other infrastructure value, to Stage 9's read-only inspector.

## Scope

The page exposes all eight settings that currently support a site default and an
optional personal override:

- `DEFAULT_CURRENCY`
- `DEFAULT_DEVICE`
- `DEFAULT_LANDING_PAGE`
- `DEFAULT_PAGE_SIZE`
- `THEME`
- `DISPLAY_TIME_ZONE`
- `DATE_FORMAT_LOCALE`
- `DATETIME_FORMAT`

Stage 8 does not render infrastructure settings. It does not change resolver
precedence, cache behavior, personal settings semantics, or the Stage 9
inspector.

## Architecture

Add `admin_settings()` beside `user_settings()` in
`games/views/settings.py`, route it as `/admin-settings`, and render it through
`render_page()`. Keep `@login_required` for anonymous requests, then explicitly
check `request.user.is_superuser`. An authenticated non-superuser receives an
HTTP 403 page assembled with existing Python components and `render_page()`;
there is no Django 403 template.

Add an explicit `SiteSettingsForm` rather than generating a form from registry
metadata or parameterizing `UserSettingsForm`. The form uses the same registry
choice constants, typed Django fields, widget conventions, and small formatting
helpers as the personal form, while keeping its different inheritance semantics
clear. A blank site value means “remove the database override and use the
configured or code default,” whereas a blank personal value means “inherit the
site default.”

Render the form with the existing `SettingsScaffold`, `SettingsSection`,
`LiveSettingFields`, source badge, and locked-control behavior. The live PATCH
URL template targets `/api/settings/site/{key}`. The site-theme field uses the
generic live-setting save path, not the personal `ThemeSetting` coordinator,
because it writes a site default rather than the current user's override. Theme
and presentation-related fields request the existing post-save reload where
required so document-level presentation state is rebuilt from the committed
site value.

Thread an `is_superuser` boolean through the existing document/navbar call
chain into `NavbarMenu()`. Render a distinct “Admin settings” link only when the
request is authenticated as a superuser. The existing personal “Settings” link
remains visible to every authenticated user.

## Resolution and form state

Build each field's initial state with `resolve_with_origin()`. The form displays
the effective site value and the existing source metadata.

- A value from the site database or registry default is editable.
- A value pinned by an environment variable, file-backed environment variable,
  `.env`, or `settings.ini` is disabled and displays its source and lock reason.
- Clearing an editable value removes its `SiteSetting` row and immediately
  resolves the lower-priority configured or registry default.
- Infrastructure `TZ` is neither resolved nor rendered by this page.

`DISPLAY_TIME_ZONE` uses the existing IANA timezone choices and validator. A
site change is live: users without a personal override inherit it on their next
request, while a user's `DISPLAY_TIME_ZONE` override continues to win.

## Save flow and errors

The existing CSRF-protected site settings API remains the write boundary and
continues to enforce superuser authorization independently of the page.
`PATCH /api/settings/site/{key}` validates through the registry and resolver,
then returns the freshly resolved `SettingOut` instead of an empty 204 response.
This makes its success contract match the personal settings endpoint and lets
the live settings component immediately reconcile the effective value, source
badge, and lock state.

Invalid values do not modify the database. The UI keeps the last committed value
and uses the existing toast/error path. Validation remains specific to each
setting: currencies normalize to three uppercase ASCII letters, device IDs must
exist, enumerated settings accept only registered choices, and timezones accept
only supported IANA names.

The existing resolver cache and invalidation design does not change. A successful
write invalidates the writing process immediately; other web or worker processes
converge within the existing TTL.

## Apply semantics

All eight controls edit live site defaults. Their existing consumers continue to
resolve per user, so personal overrides remain authoritative:

- Currency changes affect purchase-form defaults, `Purchase.save()`, and the FX
  task for inheriting users.
- Device, landing-page, page-size, theme, locale, and date/time-format changes
  affect their already-routed consumers.
- Display-timezone changes affect request timezone activation, wall-clock
  rendering, and datetime-local form interpretation for inheriting users.

This design does not make Django's boot-time `TIME_ZONE` database-editable and
does not claim that changing `TZ` can take effect without a restart.

## Testing

### View and navigation

- Anonymous users are redirected to login.
- Authenticated non-superusers receive a rendered HTTP 403 page.
- Superusers see all eight site-default controls and the site PATCH contract.
- Infrastructure keys, including `TZ`, do not appear.
- “Admin settings” appears in the navbar only for superusers.
- Personal “Settings” remains visible to every authenticated user.

### Form and API

- Each setting renders the correct typed widget, effective value, source, and
  lock state.
- Environment/file/ini-pinned fields are disabled with the existing source and
  reason treatment; database/default-backed fields are editable.
- Non-superusers cannot list or mutate site settings through the API.
- A successful PATCH returns the reconciled `SettingOut`.
- Clearing deletes the database override and returns the fallback value/source.
- Invalid currency, device, enum, and timezone writes fail without changing the
  database.

### Inheritance and consumers

- Every supported site default is inherited by a user without a personal
  override.
- A personal override continues to win over its site default.
- Currency remains live across the purchase form, `Purchase.save()`, and FX
  task.
- A display-timezone site change drives request timezone activation and
  server/client presentation for inheriting users.

### Browser behavior

- A superuser can update and clear representative text and select controls.
- Effective values and source badges reconcile without a manual reload.
- A locked control cannot submit a write.
- The page remains usable in the existing mobile and desktop settings scaffold.

Final verification is `direnv exec . make check`.

## Out of scope

- Editing or inspecting boot-time infrastructure settings.
- Exporting settings to `settings.ini`.
- Changing resolver precedence or cross-process cache timing.
- Adding new settings or personal-preference consumers.
