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

- Remove the "type the credentials" step for dev and staging, and guarantee the
  dev user exists (so a fresh worktree needs no manual superuser creation).
- Keep login a real, visible authentication (no request-path auth bypass, no
  weakening of CSRF or the session cookie's `httpOnly`).
- One mechanism shared by local and staging; gated so it is off by default and
  obviously dev-only.

## What this does and does NOT do (goal honesty)

This reduces each login to **one click on a pre-filled form**, against a user
that is guaranteed to exist. It does **not** make authentication *persist* across
separate automation/tool invocations — the browser session still dies between
them, so an agent still navigates to `/login/` and clicks Login once per session.
That per-session click is accepted as trivial; true cross-session persistence
(session-cookie minting, storage-state, a magic-link endpoint) was considered and
rejected as over-built (see Non-goals). The friction this removes is *typing
credentials*, *creating the user*, and *login failing because the password was
never set* — which is the bulk of the real pain.

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
- Parsed once into a small parsed value (e.g. `DEV_LOGIN_PREFILL_CREDS`, a
  `(username, password)` tuple or `None`) so the view does not re-split per
  request. **Parse rules:** split on the **first** `:` only (so a `:` in the
  password is preserved); if there is no `:`, or the username or password is
  empty, the feature is **off** and the malformed value is logged once at
  startup. A malformed flag therefore fails safe (renders a normal empty form).

### 2. `LoginView` prefill (`games/views/auth.py`)

- When the flag is set, the GET renders the login form with the username and
  password fields **pre-populated** with the configured values:
  - username via the form's `initial` (`get_initial()` on the view — verified to
    flow through the custom `LoginView` since it does not override
    `get_form`/`get_form_kwargs`, so the base `FormView` still builds the form
    with initial before the overridden `render_to_response` runs);
  - password by setting the password widget's `render_value = True` **only in the
    prefill path** and supplying the initial value (Django's `PasswordInput`
    omits the value by default; `render_value` stays off for a normal login so a
    password value is never emitted when the flag is unset).
- Both values are rendered as HTML attribute values through the escaping layer
  (the component core escapes attribute values, and Django's widget autoescapes),
  so a crafted flag cannot break out of the `value="…"` attribute. Covered by a
  test.
- The form still POSTs to the normal auth path and authenticates against the
  real user — **login is not bypassed**, just pre-typed. One click on "Login".
- No auto-submit (keeps the login visible and deliberate; matches the "not
  bypassed" intent).
- A small dev-only affordance is acceptable (e.g. a muted "dev credentials
  prefilled" note under the form) but is optional; the value being visible in the
  field is enough.
- The prefill code path is only reached when the flag is set, so production
  (flag empty) renders an ordinary empty login form.
- **`noindex` on the prefilled page:** because the credentials sit in the page
  HTML, when the flag is active the login response sends `X-Robots-Tag: noindex`
  (and/or a `<meta name="robots" content="noindex">`) so the public staging login
  page with visible creds is not indexed by crawlers. (Django admin is already
  NOT mounted on staging — it is gated behind `if settings.DEBUG`, and staging
  runs `DEBUG=false` — so admin is not an exposure vector.)

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

- The `dev` recipe sets `DEV_LOGIN_PREFILL=admin:admin` **inline on the runserver
  command itself** (e.g. `DEV_LOGIN_PREFILL=admin:admin uv run --frozen python
  … manage.py runserver` inside the `concurrently` invocation), NOT relying on the
  caller's shell. So plain `make dev` has prefill on with zero extra setup, while
  the code default stays off (the flag is set by the dev tooling, not defaulted in
  Python). The env var survives Django's autoreloader re-exec (inherited).

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
- Django admin is not an exposure vector on staging: its mount is gated behind
  `if settings.DEBUG`, and staging runs `DEBUG=false`.
- Because the flag literally shows the credentials in the page HTML, the
  prefilled login response is marked `noindex` (so crawlers do not index the
  staging login page with visible creds), and the flag must only be used on dev
  machines and the throwaway demo staging box (whose credentials are already the
  well-known `admin`/`admin` and whose data is regenerated each deploy).
- No production fly/deploy config in the repo sets the flag; the empty default
  keeps it fully inert everywhere it is not explicitly enabled.

## Testing

- **Prefill on:** GET `/login/` with the flag set → HTML has the username value
  and the password value prefilled, and the `X-Robots-Tag: noindex` header is
  present.
- **Prefill off (prod-safe):** GET with the flag unset (the default) → username
  has no prefilled value, the password input has **no `value=` attribute** at all,
  and no `noindex` header. This is the production path.
- **Malformed flag:** values `"admin"` (no colon), `":pw"` (empty user), `"user:"`
  (empty pass) → treated as off (renders a normal empty form), logged. A value
  `"user:a:b"` → password is `"a:b"` (split on first colon only).
- **Escaping / injection:** a flag whose password contains
  `"><img src=x onerror=alert(1)>` renders escaped inside the `value` attribute
  (no attribute break-out, no script).
- **POST still authenticates:** POSTing the prefilled credentials logs in
  (login not bypassed).
- **`devlogin` command:** creates the superuser; idempotent on a second run; a
  subsequent `Client` login with those credentials succeeds.
- Full `direnv exec . make check` green (incl. e2e).

## Rollout / touch list

- `timetracker/settings.py` — add `DEV_LOGIN_PREFILL` via `config()`, parsed into
  the `(username, password)` value (or `None`) with the fail-safe parse rules.
- `games/views/auth.py` — prefill (`get_initial`) + the `noindex` header when the
  flag is active, in `LoginView`.
- `games/forms.py` — set the password widget's `render_value = True` on
  `LoginForm` only in the prefill path.
- `games/management/commands/devlogin.py` — new command (idempotent superuser +
  printed instructions).
- `Makefile` — `devlogin` target (depends on `migrate`); the `dev` recipe sets
  `DEV_LOGIN_PREFILL=admin:admin` inline on the runserver command.
- `fly.staging.toml` — `DEV_LOGIN_PREFILL = "admin:admin"` in `[env]`.
- `docs/configuration.md` — document the flag (dev/staging-only, never in prod).
- Tests — view prefill on/off, malformed flag, escaping, POST auth, `devlogin`.
