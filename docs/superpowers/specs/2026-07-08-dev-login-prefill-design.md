# Dev login prefill — design

## Context / problem

Every page behind the app is `@login_required`, and there is no fast, canonical
way to get authenticated for development:

- **Local worktrees** start with no database and no user, so each session has to
  create a superuser and then log in through the form. The browser session does
  not survive across separate automation/tool invocations, so the form login is
  repeated constantly.
- **CI/staging** (a public fly.io box) already provisions `admin`/`admin` via the
  `CREATE_DEFAULT_SUPERUSER` entrypoint flag and loads demo data
  (`LOAD_SAMPLE_DATA`), but a human or agent opening the staging URL still types
  the credentials into the login form every time.

We want one canonical, low-friction way to reach an authenticated state that
works both locally and on the fly.io staging deploy, without weakening the real
login path.

## Goals

- Remove the "type the credentials" step for dev and staging.
- Keep login a real, visible authentication (no request-path auth bypass, no
  weakening of CSRF or the session cookie's `httpOnly`).
- One mechanism shared by local and staging; gated so it is off by default and
  obviously dev-only.

## Non-goals

- No auto-login middleware / silent per-request authentication (considered and
  rejected: a public URL would authenticate every visitor).
- No dev-only login endpoint or magic-link token (avoids adding to the request
  path).
- No session-cookie minting / Playwright storage-state artifact (considered and
  rejected as over-built; `httpOnly` sessions make direct cookie injection
  awkward and it duplicates the form).

## Design

One switch — prefill the login form — used in every environment; plus a make
target that provisions the dev superuser and prints instructions.

### 1. Config flag — `DEV_LOGIN_PREFILL`

- New setting read through `config("DEV_LOGIN_PREFILL", default="")` in
  `timetracker/settings.py` (per the project rule: all settings go through
  `timetracker/config.py`'s `config()`, never bare `os.environ`).
- Value is `"<username>:<password>"`; empty string (the default) means the
  feature is **off** everywhere. It is never defaulted on in code.
- Parsed once into `DEV_LOGIN_PREFILL_USERNAME` / `DEV_LOGIN_PREFILL_PASSWORD`
  (or a small parsed tuple) so the view does not re-split per request. A value
  with no `:` is treated as off (and logged), so a malformed flag fails safe.

### 2. `LoginView` prefill (`games/views/auth.py`)

- When the flag is set, the GET renders the login form with the username and
  password fields **pre-populated** with the configured values:
  - username via the form's `initial`;
  - password by setting the password widget's `render_value = True` and
    supplying the initial value (Django's `PasswordInput` omits the value by
    default).
- The form still POSTs to the normal auth path and authenticates against the
  real user — **login is not bypassed**, just pre-typed. One click on "Login".
- No auto-submit (keeps the login visible and deliberate; matches the "not
  bypassed" intent).
- A small dev-only affordance is acceptable (e.g. a muted "dev credentials
  prefilled" note under the form) but is optional; the value being visible in the
  field is enough.
- The prefill code path is only reached when the flag is set, so production
  (flag empty) renders an ordinary empty login form.

### 3. `make devlogin` target

- A management command (`games/management/commands/devlogin.py`) that:
  - `get_or_create`s the dev superuser (`admin`/`admin`, or the credentials from
    `DEV_LOGIN_PREFILL` if set), idempotently;
  - prints short instructions, e.g.:
    > Superuser `admin` ready. Run `make dev`, open `/login/` — the credentials
    > are prefilled when `DEV_LOGIN_PREFILL` is set; click Login.
- `make devlogin` runs it, depending on `migrate` so a fresh worktree database
  exists first.

### 4. Local enablement — `make dev`

- `make dev` passes `DEV_LOGIN_PREFILL=admin:admin` in its environment so local
  development has prefill on with zero extra setup, while the code default stays
  off (the flag is set by the dev tooling, not defaulted in Python).

### 5. Staging enablement — `fly.staging.toml`

- Add `DEV_LOGIN_PREFILL = "admin:admin"` to the `[env]` block, alongside the
  existing `CREATE_DEFAULT_SUPERUSER = "true"` and `LOAD_SAMPLE_DATA = "true"`.
  The CI fly deploy then serves a prefilled login page; one click authenticates.

### 6. Documentation

- Document `DEV_LOGIN_PREFILL` in `docs/configuration.md` as **dev/staging-only**,
  with the format, the default-off behaviour, and an explicit "never set in
  production" warning. Mention `make devlogin` as the local entry point.

## Safety

- Off by default (`DEV_LOGIN_PREFILL=""`); enabled only by an explicit flag.
- No change to the request/auth path when off — the prefill branch is skipped, so
  production renders a normal empty form.
- `devlogin` is a dev management command, never wired into the served app.
- `httpOnly`, CSRF, and the real authentication flow are untouched.
- Because the flag literally shows the credentials in the page, it must only be
  used on dev machines and the throwaway demo staging box (whose credentials are
  already the well-known `admin`/`admin`).

## Testing

- **Prefill (view):** GET `/login/` with the flag set → response HTML contains the
  username and password field values prefilled; with the flag unset → neither is
  prefilled (password never rendered). A POST with the prefilled values still
  authenticates (login not bypassed).
- **`devlogin` command:** running it creates the superuser (idempotent on a second
  run) and a subsequent `Client` login with those credentials succeeds.
- Full `direnv exec . make check` green (incl. e2e).

## Rollout / touch list

- `timetracker/settings.py` — add `DEV_LOGIN_PREFILL` via `config()`.
- `games/views/auth.py` — prefill in `LoginView`.
- `games/management/commands/devlogin.py` — new command.
- `Makefile` — `devlogin` target; `make dev` sets `DEV_LOGIN_PREFILL=admin:admin`.
- `fly.staging.toml` — `DEV_LOGIN_PREFILL = "admin:admin"` in `[env]`.
- `docs/configuration.md` — document the flag.
- Tests — view prefill + `devlogin` command.
