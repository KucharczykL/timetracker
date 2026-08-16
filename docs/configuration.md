# Configuration

## Regex filters

Regex filters use PostgreSQL's regular-expression syntax. Patterns are limited
to 200 characters and validated by PostgreSQL before a filter or preset is
accepted. Regex queries have a one-second transaction-local statement timeout;
when it expires, list pages remove the filter and show a warning, while APIs
return a 400 response.

All configurable Django settings are read through a single helper,
`config()` in [`timetracker/config.py`](../timetracker/config.py). It resolves
each value from a fixed chain of sources so the same setting can come from an
environment variable, a `.env` file, an `.ini` file, or a built-in default —
without any per-setting special-casing in `settings.py`.

## Resolution priority

For a setting named `NAME`, the first source that provides a value wins:

| Priority | Source | Notes |
|---------:|--------|-------|
| 1 | `NAME__FILE` env var | Path to a file; its *stripped* contents are the value. Opt-in per setting (`allow_file=True`). For Docker/Kubernetes secrets. |
| 2 | `NAME` env var | A real process environment variable. |
| 3 | `.env` file | `KEY=value` lines (see [.env syntax](#env-syntax)). |
| 4 | `settings.ini` file | The `[timetracker]` section, parsed with `configparser`. |
| 5 | `SiteSetting` (database) | Site default for **site**- and **user**-scoped settings. Runtime-editable; see [Runtime settings layer](#runtime-settings-layer). |
| 6 | `default` | The in-code fallback in `settings.py`. |

For **user**-scoped settings a personal `UserPreferences` override sits *above*
this whole chain (it wins even over env, since env-locking per-user prefs is
deferred); see [Runtime settings layer](#runtime-settings-layer).

If no source supplies a value and no `default` is defined, startup fails with
`ImproperlyConfigured` rather than silently using an empty value.

**Worked example.** With `VALUE` set in the environment *and* in `.env` *and*
in `settings.ini`, the environment variable wins. Remove it and `.env` wins;
remove that and `settings.ini` wins; remove that and the code default applies.

## Settings reference

| Setting | Cast | Default | `__FILE`? | Description |
|---------|------|---------|:---------:|-------------|
| `SECRET_KEY` | str | insecure dev key | yes | Django secret key. **Required in production** (DEBUG off) — a missing value is a hard error, not a silent insecure fallback. |
| `DEBUG` | bool | `true` (dev) | no | Debug mode. Turn **off** in production. Defaults on for local development. |
| `APP_URL` | str (or comma-separated URLs) | `http://localhost:8000` | no | Public URL(s) of the site. One full URL or a comma-separated list. Derives `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` from all listed URLs. |
| `ALLOWED_HOSTS` | list | derived from `APP_URL` | no | Comma-separated hostnames. Overrides the `APP_URL` derivation (useful for `ALLOWED_HOSTS=*` behind a reverse proxy). |
| `TZ` | str | `Europe/Prague` (dev) / `UTC` (prod) | no | Boot-time Django/server time zone. Requires a restart and is not editable on Admin settings. |
| `DEFAULT_PURCHASE_CURRENCY` | str | `CZK` | no | Live user/site default used to pre-fill the required original currency on new purchases. |
| `DEFAULT_DISPLAY_CURRENCY` | str | `CZK` | no | Live user/site target for that library's converted purchase cache, totals, and statistics. |
| `DEFAULT_PAGE_SIZE` | int | `25` | no | Default rows shown on list pages. Valid preference/site values: `10`, `25`, `50`, `100`, `500`, `1000`. |
| `DATABASE_URL` | PostgreSQL URL | required | yes | Required PostgreSQL connection URL. The database must satisfy the [database contract](database.md): PostgreSQL 18.x, UTF8, `builtin`, and `C.UTF-8`. |
| `DEV_LOGIN_PREFILL` | str (`user:pass`) | `""` (off) | no | **Dev/staging only — never set in production.** When set to `username:password`, the login page prefills those credentials (one click to log in) and sends `X-Robots-Tag: noindex`. Login is not bypassed. `make dev` sets it to `admin:admin`; `make devlogin` provisions that superuser. |

`cast` understands `bool` (`true/1/yes/on` → `True`), `list` (comma-separated,
whitespace-trimmed, empty items dropped), `int`, `Path`, or any callable.

## Runtime settings layer

The `config()` chain above is read once at boot. A **database layer** sits
*below* env/`.env`/`.ini` and *above* the code default, so a subset of settings
can be changed at runtime without a redeploy. It is served by the layered
resolver in
[`timetracker/settings_resolver.py`](../timetracker/settings_resolver.py), backed
by a declarative registry
([`timetracker/settings_registry.py`](../timetracker/settings_registry.py)) and
the global `SiteSetting` model.

- **`resolve_with_origin(key)` → `(value, source, locked)`.** Precedence is
  env/`.env`/`.ini` (all **locked** — they pin the value and win over the DB) >
  `SiteSetting` (database, unlocked) > registry default. Every layer runs through
  the same cast + validator, so a DB-stored `"eur"` resolves identically to an
  env `EUR`.
- **`resolve_for_user_with_origin(user, key)` → `(value, source, locked)`.** For
  a **user**-scoped key, a personal `UserPreferences` value (source `user`) wins
  over the shared chain above — even over env, because env-locking per-user prefs
  is deferred, so such a value reports `locked=False`. Unset (a NULL column / an
  absent `extra_preferences` key) falls through to the complete shared chain:
  enabled environment/config-file sources > `SiteSetting` > registry default.
  Which sources are enabled depends on the setting's registry definition; for
  example, only settings with `allow_file=True` accept a `NAME__FILE` source.
  Non-user keys proxy straight to `resolve_with_origin`.
- **Scopes.** **user**-scoped settings (`DEFAULT_PURCHASE_CURRENCY`,
  `DEFAULT_DISPLAY_CURRENCY`, `DEFAULT_DEVICE`, `DEFAULT_LANDING_PAGE`,
  `DEFAULT_PAGE_SIZE`, `THEME`, `DISPLAY_TIME_ZONE`,
  `SESSION_TIME_ZONE_DISPLAY`, `DATE_FORMAT_LOCALE`, `DATETIME_FORMAT`) have a
  personal override layer *and*
  a `SiteSetting` site default; a plain **site**-scoped setting has only the
  shared `SiteSetting` default (none exist today). **infra**-scoped settings
  (`DEBUG`, `SECRET_KEY`, `APP_URL`, `DEV_LOGIN_PREFILL`, `ALLOWED_HOSTS`,
  `TZ`, `HASHED_STATIC`) are boot-only and never read from the DB. `DATABASE_URL`
  is intentionally not shown in the settings UI because it can contain credentials.
- **`TZ` is infrastructure configuration.** `TIME_ZONE` is frozen when
  `settings.py` imports, so a DB value could never take effect. Change it via
  the environment, `.env`, or `settings.ini` and restart. It is shown
  read-only in the Infrastructure section of the Admin settings page.
- **Not runtime-editable, not registered.** `ENV_FILE`/`INI_FILE` *locate* the
  config sources (read before the chain exists) and the deprecated `PROD` alias
  is excluded, so none appear in the registry.
- **Consistency.** Web workers and the django-q qcluster each cache the
  `SiteSetting` and `UserPreferences` snapshots for a few seconds; a runtime
  change converges across processes within that window. Model signals clear the
  current process's snapshots only after transaction commit; a raw
  `QuerySet.update()` skips those signals and remains invisible until the TTL
  lapses.
- **Mutation boundaries.** Site-default changes go through
  `change_site_setting()` and personal-preference changes go through
  `change_user_setting()`, both in
  [`timetracker/settings_commands.py`](../timetracker/settings_commands.py).
  Each command validates and normalizes values, rejects a higher configuration
  source before touching the database, and returns a `SettingMutation` —
  carrying the resolved effective value, the operation (`set`/`clear`), whether
  storage actually changed, and the stored value or its absence. The resolver
  has no public mutation helpers.
- **API.** `/api/settings/user` (`GET`/`PATCH`, scoped to the requesting user)
  reads and writes personal prefs; `/api/settings/site` (`GET`/`PATCH`,
  superuser-only) reads and writes the site defaults. `PATCH` with `value: null`
  clears a setting back to unset. A site PATCH against an environment,
  environment-file, `.env`, or `settings.ini` owned key returns HTTP 409.

### Admin settings page

Superusers can open `/tracker/admin-settings` through **Admin settings** inside
the existing navbar **Menu** dropdown. The page has two sections.

#### Site defaults section

Edits these ten live site defaults, in the order the page renders them:

- `DEFAULT_PURCHASE_CURRENCY`
- `DEFAULT_DISPLAY_CURRENCY`
- `DEFAULT_DEVICE`
- `DEFAULT_LANDING_PAGE`
- `DEFAULT_PAGE_SIZE`
- `THEME`
- `DISPLAY_TIME_ZONE`
- `SESSION_TIME_ZONE_DISPLAY`
- `DATE_FORMAT_LOCALE`
- `DATETIME_FORMAT`

These values are inherited by users who have not saved a personal override.
Clearing a control deletes its database override and reveals its configured or
built-in fallback. A value owned by an environment variable, file-backed
environment variable, `.env`, or `settings.ini` is disabled and displays both
its source and the reason it cannot be changed.

A **Download settings.ini** button in the page header exports every
currently-stored site default as a `[timetracker]` ini snapshot — for backup,
or to promote a database value to an env-pinned one (edit the downloaded
file, point `INI_FILE`/deploy it as `settings.ini`, restart). Values are
written unquoted and with any literal `%` doubled, matching how
`timetracker/config.py` reads `.ini` files (`BasicInterpolation`, no
`.env`-style unquoting) — a value containing `%` re-imports to the identical
string.

`DISPLAY_TIME_ZONE` is the live site default for wall-clock display and
datetime-form interpretation. It is distinct from boot-only `TZ`: changing
`DISPLAY_TIME_ZONE` rebuilds the document presentation contract after the
save, while changing `TZ` still requires a process restart.

#### Infrastructure section

A read-only inspector of the eight `INFRA`-scoped settings. Each row shows the
resolved value and the source that provided it (environment variable, `.env`,
`settings.ini`, or built-in default). Values are shown as raw repr. The real
`SECRET_KEY` is never rendered — only its presence (masked as `••••••••`) or
absence is shown. To change any of these settings, update the environment or
config file and restart the process.

Settings shown:

- `TZ` — server time zone (IANA name)
- `DEBUG` — debug mode
- `SECRET_KEY` — secret key (presence-only)
- `APP_URL` — application URL
- `DEV_LOGIN_PREFILL` — dev login prefill
- `ALLOWED_HOSTS` — allowed hosts
- `HASHED_STATIC` — hashed static assets

The navbar theme switcher is unavailable on both personal and Admin settings
pages so it cannot compete with the settings form's authoritative control.

### Personal settings page

Every authenticated user can open `/tracker/settings` from the main navigation.
Changes save immediately against the account through `/api/settings/user`:

- **Default purchase currency** pre-fills the required original currency on new
  purchases, including separate-per-game purchases. A blank submitted currency
  is rejected rather than inferred below the form boundary.
- **Display currency** selects the converted purchase totals and statistics for
  this library. Changing it requests a new atomic conversion publication.
- **Default device** pre-selects the device on every add-session path and fills
  an empty device when editing a session. An existing device is preserved.
- **Default landing page** controls the `/tracker/` redirect. Supported values
  are the Sessions, Games, and Purchases lists and Statistics for the current
  calendar year. The stored value is a validated Django URL name, not an
  arbitrary URL.
- **Default rows per page** controls every list using `FindFilter` when its URL
  has no valid `per_page` override. Presets saved without an explicit size keep
  inheriting this preference; choosing a size from a list pins that exact value
  in the URL and any subsequently saved preset.
- **Theme** supports System, Light, and Dark; System follows the operating-system
  color scheme. The navbar button cycles through those three states and the
  settings page exposes the same account preference, including a blank “Use site
  default” choice. Changes apply immediately and a failed account save restores
  the last server-committed theme. A synchronous external bootstrap applies the
  resolved value before CSS loads, avoiding a flash of the wrong theme.
  Authenticated pages always use the account/site value and ignore browser
  storage. Anonymous pages use `color-theme` in `localStorage`; it is neither
  migrated into the account nor overwritten at login, so it resumes after
  logout. Theme cookies are not used.
- **Time zone** (`DISPLAY_TIME_ZONE`) is the IANA zone used for wall-clock
  display and for interpreting datetimes submitted by forms. It is distinct from
  boot-only `TZ`; saving it reloads the page so the document presentation
  contract is rebuilt.
- **Session time zone display** (`SESSION_TIME_ZONE_DISPLAY`) chooses whether a
  session reads in your current time zone or in the zone it was logged in. The
  zone is labelled whenever it differs from the account zone. The built-in
  default is `own` (the session's own zone).
- **Formatting locale** (`DATE_FORMAT_LOCALE`) selects the locale used for month
  names, weekday names, and localized AM/PM labels. It is never activated as a
  translation, so application copy is unaffected.
- **Duration format** controls how elapsed playtime is displayed. Supported
  profiles are:

  | Value | 45 minutes | 1 h 12 m | 83 h 12 m |
  |-------|-----------|----------|-----------|
  | `decimal_hours` | `0.8 h` | `1.2 h` | `83.2 h` |
  | `hours_minutes` | `45 m` | `1 h 12 m` | `83 h 12 m` |
  | `whole_hours` | `1 hour` | `1 hour` | `83 hours` |
  | `adaptive` | `45 m` | `1 h 12 m` | `3 d 11 h` |

  `decimal_hours` is the built-in default. Every profile rounds to its own
  resolution rather than truncating, so a 45-minute session reads as `1 hour`
  under `whole_hours`, never `0 hours`. Only `adaptive` rolls hours into days,
  weeks, and years; the others keep counting hours, because hours are this
  application's unit of account (the filter facets are `playtime_hours` and
  `duration_total_hours`). Grouping and the decimal separator come from the
  formatting locale, so 1234 hours reads `1,234` under `en-us` and `1 234`
  under `cs`. The preference is display only: stored values, the API, filtering,
  and sorting are unaffected.
- **Date/time format** controls numeric date order, visible date separators, and
  the 12- or 24-hour clock used throughout the rendered application. Supported
  profiles are:

  | Value | Date and time example |
  |-------|-----------------------|
  | `iso_8601` | `2026-07-02 19:05` |
  | `dmy_24h` | `02/07/2026 19:05` |
  | `mdy_12h` | `07/02/2026 07:05 PM` |

  `iso_8601` is the built-in default. It is an ISO-local display: the value is
  converted to the active display time zone and shown without a `T` or UTC
  offset. The preference does not change the display time zone. Locale remains
  responsible for month names and localized AM/PM labels; the selected profile
  controls only numeric order, separators, and hour cycle.

Clearing a control removes the personal override and restores the resolved site
default through the setting's enabled environment/config-file sources and
database chain, finally falling back to the built-in default. For Date/time
format, this is `DATETIME_FORMAT` in the environment, `.env`, or `settings.ini`,
then the site value, then `iso_8601`; `DATETIME_FORMAT__FILE` is not supported.
Existing non-empty values on edit forms are never replaced just by opening the
form.

### Currency scope

Purchase-entry requests resolve `DEFAULT_PURCHASE_CURRENCY` for the
authenticated user. The personal-or-inherited value pre-fills new purchase
forms and separate-per-game purchases; `Purchase.save()` requires an explicit
original currency and never guesses from process-global context.

`DEFAULT_DISPLAY_CURRENCY` is resolved independently for each User's library.
It is the target of that library's versioned conversion state and the currency
label used with its published converted totals. Updating one library never
changes another library's cached values or reporting currency.

### One-user production cutover for #630

This is an offline, one-time migration. It accepts exactly one legacy User, or
a genuinely pristine database. Keep the pre-cutover dump, its manifest, and
the migration reconciliation output together in protected storage outside Git.

1. While the **old release is still running**, record its deployment version or
   short commit and query the old resolver for both the site and personal
   `DEFAULT_CURRENCY` triples: effective value, exact source, and lock state.
   Also record the effective default Device id, name, and source. These are
   runtime facts; do not infer them from new-code defaults or from the dump.
2. If the effective default Device is inherited rather than already stored as
   the User's personal preference, select that same Device explicitly on the
   old Personal settings page and verify the resolver now reports source
   `user`. This makes the choice part of the final database snapshot.
3. Verify the old converted purchase cache is complete in the recorded site
   currency: every Purchase has a converted price and currency, every converted
   currency is the recorded Display currency, and no Purchase has
   `needs_price_update` set. Resolve any dirty, blank, null, or mixed rows
   before continuing.
4. Stop the web service and every qcluster/worker so no write can occur after
   the observations. Create a **fresh** custom-format PostgreSQL archive using
   a client compatible with the server. Require the production URL and record
   the identity reported by that connection before dumping:

   ```shell
   : "${PRODUCTION_DATABASE_URL:?set the production database URL explicitly}"
   PRODUCTION_DB_ID="$(psql --dbname="$PRODUCTION_DATABASE_URL" --no-align \
     --tuples-only --command="SELECT current_database() || '@' || \
     COALESCE(inet_server_addr()::text, 'local') || ':' || \
     COALESCE(inet_server_port()::text, 'local')")"
   test -n "$PRODUCTION_DB_ID"
   pg_dump --dbname="$PRODUCTION_DATABASE_URL" --format=custom --no-owner --no-privileges \
     --file=/protected/timetracker-pre-630.dump
   pg_restore --list /protected/timetracker-pre-630.dump
   ```

5. Hash that exact archive (`sha256sum` on Unix, `Get-FileHash -Algorithm
   SHA256` on PowerShell). Create a named empty rehearsal database, set a URL
   that points specifically to it, and pass it explicitly to `pg_restore`:

   ```shell
   createdb --maintenance-db="$POSTGRES_ADMIN_URL" timetracker_630_rehearsal
   DISPOSABLE_DATABASE_URL='postgresql://app@db/timetracker_630_rehearsal'
   DISPOSABLE_DB_ID="$(psql --dbname="$DISPOSABLE_DATABASE_URL" --no-align \
     --tuples-only --command="SELECT current_database() || '@' || \
     COALESCE(inet_server_addr()::text, 'local') || ':' || \
     COALESCE(inet_server_port()::text, 'local')")"
   test -n "$DISPOSABLE_DB_ID"
   test "$DISPOSABLE_DB_ID" != "$PRODUCTION_DB_ID"
   pg_restore --dbname="$DISPOSABLE_DATABASE_URL" --exit-on-error \
     --no-owner --no-privileges /protected/timetracker-pre-630.dump
   ```

   The final comparison proves the two URLs resolve to different connected
   server/database identities. Inspect only this disposable restore when
   collecting database facts.
6. Build the exact version-1 manifest documented in the [cutover manifest
   schema](superpowers/specs/2026-08-13-user-library-ownership-cutover-design.md#cutover-manifest-and-fresh-installs).
   Fill its database observations from the restored archive and its
   `operator_confirmed_settings` from steps 1-3. Confirm its
   `source.dump_sha256` is the lowercase SHA-256 of the archive byte-for-byte,
   and that its filename, database/PostgreSQL version, deployment version,
   User identity, row/link counts, nullable observations, raw settings rows,
   original-currency counts, and converted-cache counts all describe that same
   restore. The manifest contains no credentials.
7. Rehearse the complete migration against that disposable restore first.
   Configure `DEFAULT_PURCHASE_CURRENCY` and `DEFAULT_DISPLAY_CURRENCY` to the
   recorded old **site** currency. If the old site value was provided by a
   locked `DEFAULT_CURRENCY` environment, `.env`, or INI source, keep that old
   source available to this one migration command too; the migration verifies
   its exact old value/source/lock triple. Mount the manifest read-only at an
   absolute path and expose it only to the migration process:

   ```shell
   DATABASE_URL="$DISPOSABLE_DATABASE_URL" \
     TIMETRACKER_OWN_CUTOVER_MANIFEST=/run/secrets/timetracker-own-630.json \
     python manage.py migrate
   DATABASE_URL="$DISPOSABLE_DATABASE_URL" \
     python manage.py audit_library_ownership --user '<exact username>'
   ```

   Retain stdout, including the printed source deployment, dump SHA-256, and
   new library UUID. Verify the audit, manifest row/link/original-currency
   counts, converted-cache state and totals, both effective currency settings,
   the library default Device, and representative pages/APIs before touching
   production.
8. Keep the unchanged production snapshot offline and deliberately switch from
   `DISPOSABLE_DATABASE_URL` to the separately recorded production URL. Run the
   migration and audit with the production target written explicitly:

   ```shell
   DATABASE_URL="$PRODUCTION_DATABASE_URL" \
     TIMETRACKER_OWN_CUTOVER_MANIFEST=/run/secrets/timetracker-own-630.json \
     python manage.py migrate
   DATABASE_URL="$PRODUCTION_DATABASE_URL" \
     python manage.py audit_library_ownership --user '<exact username>'
   ```

   Keep web and workers offline until reconciliation, ownership audit, totals,
   settings, and page/API smoke checks all pass. If a production attempt ever
   wrote outside the atomic migration, restore the exact final dump before a
   new attempt. Remove the old `DEFAULT_CURRENCY` configuration only after
   migration; it has no post-cutover runtime alias. Start services only after
   verification succeeds.

A pristine install (zero Users and zero rows in every legacy private, link,
preference, and old-setting table) is the only path that runs the migration
without `TIMETRACKER_OWN_CUTOVER_MANIFEST`; normal User provisioning creates
the first library afterward. Zero Users with legacy data, or two or more Users,
is rejected.

You must never reuse a manifest from an earlier dump, even when the database
appears unchanged. Any new dump requires a new hash, a new disposable restore,
freshly observed counts/settings, a new manifest, and a complete rehearsal.

### Administration and development tools

The Django admin application and `/admin/` route have been removed. Runtime
site defaults are managed through the superuser Admin settings page and its
validated command/API boundary instead. Django authentication and superuser
accounts remain, including `createsuperuser` and the development `devlogin`
command. In debug mode, `django_extensions` and the Django debug toolbar also
remain available.

## APP_URL, ALLOWED_HOSTS and CSRF

`APP_URL` accepts one full URL or a comma-separated list of full URLs. Both
`ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are derived from all listed URLs —
no need to repeat the same information in separate variables.

Single domain (common case):

```
APP_URL=https://tracker.example.com
# -> ALLOWED_HOSTS     = ["tracker.example.com"]
# -> CSRF_TRUSTED_ORIGINS = ["https://tracker.example.com"]
```

Multiple domains:

```
APP_URL=https://tracker.example.com,https://www.tracker.example.com
# -> ALLOWED_HOSTS     = ["tracker.example.com", "www.tracker.example.com"]
# -> CSRF_TRUSTED_ORIGINS = ["https://tracker.example.com", "https://www.tracker.example.com"]
```

`ALLOWED_HOSTS` can still be overridden directly for edge cases. A typical
reverse-proxy setup where the proxy validates the host:

```
ALLOWED_HOSTS=*
```

## Secrets and `__FILE`

Secret managers (Docker secrets, Kubernetes) mount secrets as files. For any
setting that opts in (currently `SECRET_KEY` and `DATABASE_URL`), point a
`*__FILE` variable at
the mounted path:

```
SECRET_KEY__FILE=/run/secrets/timetracker_secret_key
DATABASE_URL__FILE=/run/secrets/timetracker_database_url
```

The file contents are read and `.strip()`-ed. The strip matters: editors and
`echo` often append a trailing newline, and a stray `\n` inside `SECRET_KEY`
would silently invalidate every signed cookie/token when the file is recreated
without it.

## .env syntax

```dotenv
# full-line comment
KEY=value
export KEY=value            # optional leading "export"
QUOTED="value with spaces"  # surrounding quotes are stripped
SINGLE='also fine'
WITH_HASH="a # b"           # '#' inside quotes is literal
INLINE=value  # trailing comment after an unquoted value is dropped
```

Deliberately **not** supported (documented limits, not bugs):

- variable interpolation (`${OTHER}`)
- multiline values

File locations default to `.env` and `settings.ini` at the project root and
can be moved with the `ENV_FILE` / `INI_FILE` environment variables. Missing
files are ignored, so env-only deployments need neither. A `.env` file used by
`docker-compose` for `${VAR}` substitution is the same file Django reads in
local development; inside the container, real environment variables apply.

See [`.env.example`](../.env.example) and
[`settings.ini.example`](../settings.ini.example) for starting points.

## Container / entrypoint-only variables

These are consumed by [`entrypoint.sh`](../entrypoint.sh) during container
bootstrap, **not** by Django. They are intentionally not part of the Python
config — moving them there would buy nothing and force a bash↔Python bridge.
The entrypoint reads them, translates them into flags for a single
`manage.py bootstrap_container` call, and starts supervisor; static files are
collected into the image at build time rather than on each boot.

| Variable | Default | Purpose |
|----------|---------|---------|
| `CREATE_DEFAULT_SUPERUSER` | `false` | Create an `admin`/`admin` superuser on first start. |
| `STAGING` | `false` | Scrub copied sessions / django-q schedule on staging. |
| `LOAD_SAMPLE_DATA` | `false` | Seed sample fixtures when the database is empty. |
| `RUN_QCLUSTER` | `true` | Run the django-q cluster. `false` saves its ~260 MB where nothing schedules work; the image sets the default because supervisord cannot parse its config with this unset. |

The container runs as uid 1000 — mounted data directories must be writable
by that uid. A database URL secret must also be readable by uid 1000. Docker
Compose's `mode: 0400` does not change a file-backed secret's host ownership,
so set the host file owner/read permission accordingly; the CI smoke test
checks that the image user can read the mounted `DATABASE_URL__FILE`.

## Migrating from the old config

- `PROD=1` → `DEBUG=false`. `PROD` still works as a **deprecated alias** for
  one release and emits a `DeprecationWarning`.
- `ALLOWED_HOSTS` is now configurable (it was previously hard-coded to `*`).
  After upgrading, set `APP_URL` (or `ALLOWED_HOSTS` explicitly) or the host
  will be rejected. Reverse-proxy deployments that relied on `*` should set
  `ALLOWED_HOSTS=*`.
