# Design: superuser site settings page

> Approved issue #390 design, revised to match the implemented command,
> navigation, timezone, administration, and currency contracts.

## Goal and scope

`/tracker/admin-settings` gives superusers one component-rendered surface for
editing all live site defaults. Authenticated non-superusers receive a rendered
HTTP 403 response; anonymous users follow the ordinary login redirect.

Stage 8 exposes exactly:

- `DEFAULT_CURRENCY`
- `DEFAULT_DEVICE`
- `DEFAULT_LANDING_PAGE`
- `DEFAULT_PAGE_SIZE`
- `THEME`
- `DISPLAY_TIME_ZONE`
- `DATE_FORMAT_LOCALE`
- `DATETIME_FORMAT`

The page does not render infrastructure configuration. In particular,
boot-time `TZ` remains deferred to Stage 9's read-only inspector.

## Page and navigation

`SiteSettingsForm` remains explicit beside `UserSettingsForm` in
`games/views/settings.py`. It uses the existing registry choices, native Django
fields, `SettingsScaffold`, `LiveSettingFields`, source badges, and disabled
control treatment. A blank site control removes the database override and
reveals the configured or built-in fallback.

The request's superuser state is threaded through `render_page()` and
`NavbarMenu()`. Settings, Admin settings, and the POST Logout action live
inside the existing **Menu** dropdown; Admin settings is omitted for
non-superusers. It is not a new top-level navbar item.

The navbar theme switcher is disabled on personal and Admin settings pages. The
form remains the authoritative theme control there.

## Mutation and source contract

`PATCH /api/settings/site/{key}` is independently superuser-gated and delegates
all writes to `change_site_setting()` in
`timetracker/settings_commands.py`. The command:

1. resolves the current source and rejects environment, environment-file,
   `.env`, or `settings.ini` ownership before mutation;
2. validates and normalizes through the registry;
3. sets or deletes the `SiteSetting` row; and
4. returns the canonical `ResolvedSetting` directly.

The API maps a locked command to HTTP 409 and returns the command result on
success. Site mutation helpers do not belong to `settings_resolver.py`.

Resolver snapshots are not cleared inline during the command. Model signals
schedule local invalidation on transaction commit, preventing rolled-back
values from entering the cache. Other web/worker processes converge within the
existing TTL.

The page displays the effective value and source for every field. Higher
configuration sources render a genuinely disabled native control, their owning
source, and a visible lock explanation. Browser tests observe them but never
interact with disabled controls.

## Timezone contract

`DISPLAY_TIME_ZONE` is a live user-scoped setting with a site default. It
controls wall-clock presentation and datetime-form interpretation. Saving it
uses the existing reload-after-save flow so the server rebuilds the root
document's date/time presentation contract.

Infrastructure `TZ` initializes Django's `TIME_ZONE` at boot. It is not stored
in `SiteSetting`, is not present on Stage 8, and still requires configuration
plus restart. Stage 9 may show it read-only with its source and restart
semantics.

## Currency contract

Currency is intentionally context-sensitive:

- add/edit purchase requests resolve `DEFAULT_CURRENCY` for the authenticated
  user; this drives initial values, blank submissions, and separate-per-game
  purchases;
- `Purchase.save()` has no user context, so an absent currency uses the shared
  site resolution chain;
- the FX conversion task also uses the site value as the single reporting
  target for its run.

A personal preference therefore changes that user's purchase-entry default,
not context-free model behavior or reporting currency.

## Administration

Django admin is removed: `django.contrib.admin`, `games/admin.py`, and the
`/admin/` route are absent. The replacement for runtime site-default changes is
this page plus the validated command/API boundary. Django authentication and
superuser accounts remain. Debug builds continue to include
`django_extensions` and the Django debug toolbar.

## Acceptance coverage

Backend coverage owns the exact eight-key matrix, validation, lock/409,
transaction/cache, authorization, inheritance, and consumer semantics.
Playwright remains representative:

- open Admin settings through the superuser Menu dropdown at mobile and desktop
  viewports and verify the responsive settings navigation;
- normalize a lowercase currency PATCH and update its source badge;
- update one native select through the site PATCH path;
- clear an override and verify its fallback value/default source;
- save `DISPLAY_TIME_ZONE`, observe reload, and inspect the rebuilt document
  contract; and
- verify a locked field is disabled with its owner and explanation.

Browser waits use locators, response/navigation waiters, and state predicates;
they do not use fixed sleeps or interact with disabled controls.
