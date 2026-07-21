# Configuration

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
| `TZ` | str | `Europe/Prague` (dev) / `UTC` (prod) | no | Time zone. |
| `DEFAULT_CURRENCY` | str | `CZK` | no | Default currency for new purchases when none is entered, and the FX conversion target for background price conversion. |
| `DATA_DIR` | path | project root | no | Directory holding the SQLite database. Also read by `entrypoint.sh`. |
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
  absent `extra_preferences` key) falls through to the `SiteSetting` site default
  and then the code default. Non-user keys proxy straight to `resolve_with_origin`.
- **Scopes.** **user**-scoped settings (`DEFAULT_CURRENCY`, `DEFAULT_DEVICE`,
  `DEFAULT_LANDING_PAGE`) have a personal override layer *and* a `SiteSetting`
  site default; a plain **site**-scoped setting has only the shared `SiteSetting`
  default (none exist today). **infra**-scoped settings (`DEBUG`, `SECRET_KEY`,
  `APP_URL`, `DEV_LOGIN_PREFILL`, `ALLOWED_HOSTS`, `DATA_DIR`, `TZ`,
  `HASHED_STATIC`) are boot-only and never read from the DB.
- **`TZ` is display-only.** `TIME_ZONE` is frozen when `settings.py` imports, so
  a DB value could never take effect; change it via env/`.ini` + restart.
- **Not runtime-editable, not registered.** `ENV_FILE`/`INI_FILE` *locate* the
  config sources (read before the chain exists) and the deprecated `PROD` alias
  is excluded, so none appear in the registry.
- **Consistency.** Web workers and the django-q qcluster each cache the
  `SiteSetting` and `UserPreferences` snapshots for a few seconds; a runtime
  change converges across processes within that window. Writes go through the
  resolver, the Django admin, or the `/api/settings` endpoints (all validated); a
  raw `QuerySet.update()` is invisible until the cache lapses.
- **API.** `/api/settings/user` (`GET`/`PATCH`, scoped to the requesting user)
  reads and writes personal prefs; `/api/settings/site` (`GET`/`PATCH`,
  superuser-only) reads and writes the site defaults. `PATCH` with `value: null`
  clears a setting back to unset.

### Personal settings page

Every authenticated user can open `/tracker/settings` from the main navigation.
Changes save immediately against the account through `/api/settings/user`:

- **Default currency** pre-fills new purchases and supplies the fallback when a
  submitted purchase has no currency, including separate-per-game purchases.
- **Default device** pre-selects the device on every add-session path and fills
  an empty device when editing a session. An existing device is preserved.
- **Default landing page** controls the `/tracker/` redirect. Supported values
  are the Sessions, Games, and Purchases lists and Statistics for the current
  calendar year. The stored value is a validated Django URL name, not an
  arbitrary URL.

Clearing a control removes the personal override and restores the resolved site
or built-in default. Existing non-empty values on edit forms are never replaced
just by opening the form.

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
setting that opts in (currently `SECRET_KEY`), point a `*__FILE` variable at
the mounted path:

```
SECRET_KEY__FILE=/run/secrets/timetracker_secret_key
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

| Variable | Default | Purpose |
|----------|---------|---------|
| `PUID` / `PGID` | `1000` / `100` | uid/gid the container process runs as. |
| `DATA_DIR` | `/home/timetracker/app/data` | Database directory. Shared with Django via the same env var + matching default. |
| `CREATE_DEFAULT_SUPERUSER` | `false` | Create an `admin`/`admin` superuser on first start. |
| `STAGING` | `false` | Scrub copied sessions / django-q schedule on staging. |
| `LOAD_SAMPLE_DATA` | `false` | Seed sample fixtures when the database is empty. |

## Migrating from the old config

- `PROD=1` → `DEBUG=false`. `PROD` still works as a **deprecated alias** for
  one release and emits a `DeprecationWarning`.
- `ALLOWED_HOSTS` is now configurable (it was previously hard-coded to `*`).
  After upgrading, set `APP_URL` (or `ALLOWED_HOSTS` explicitly) or the host
  will be rejected. Reverse-proxy deployments that relied on `*` should set
  `ALLOWED_HOSTS=*`.
