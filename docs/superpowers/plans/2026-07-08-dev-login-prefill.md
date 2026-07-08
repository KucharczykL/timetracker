# Dev Login Prefill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A flag-gated login-form prefill (`DEV_LOGIN_PREFILL`) that fills the username+password on the login page for dev and fly.io staging, plus a `make devlogin` target that provisions the dev superuser — without bypassing authentication.

**Architecture:** A single config flag `DEV_LOGIN_PREFILL="user:pass"` (empty = off). A tiny parser module turns it into credentials or `None`. `LoginView` injects them as form `initial` (and flips the password widget's `render_value` on) so the GET renders a pre-typed form; the form still POSTs and authenticates normally. A `noindex` header is added when prefill is active. `make dev` sets the flag inline; `fly.staging.toml` sets it in `[env]`; `make devlogin` (a management command) ensures the superuser exists.

**Tech Stack:** Django 6, the repo's `config()` settings helper, pytest/pytest-django, Make, Fly.io TOML.

## Global Constraints

- Python 3.14; run every `make`/`uv`/`pytest` command inside the Nix dev shell via `direnv exec . <cmd>` (e.g. `direnv exec . make check`). A fresh worktree needs `direnv allow .` once first.
- All Django settings go through `config()` from `timetracker/config.py` — never bare `os.environ`.
- UI is built with Python components from `common.components`; `SafeText`/component attribute values are auto-escaped by the component core.
- Full verification gate before done: `direnv exec . make check` (lint, format-check, mypy, ts-check, vitest, entire pytest incl. `e2e/`) must be green.
- Name variables with complete words.
- The feature must be **off by default** (`DEV_LOGIN_PREFILL=""`) and never weaken CSRF, `httpOnly`, or the real auth path.

---

## File Structure

- Create `games/dev_login.py` — `prefill_credentials()` parser (reads `settings.DEV_LOGIN_PREFILL`, returns `(username, password)` or `None`, logs malformed values). Single responsibility: parse the flag.
- Create `games/management/commands/devlogin.py` — management command: ensure the dev superuser exists + print instructions.
- Create `tests/test_dev_login.py` — parser, view-prefill, and command tests.
- Modify `timetracker/settings.py` — add the `DEV_LOGIN_PREFILL` config line.
- Modify `games/forms.py` — `LoginForm.__init__` enables password `render_value` when prefill is active.
- Modify `games/views/auth.py` — `LoginView.get_initial()` injects credentials; `render_to_response()` adds the `noindex` header when prefill is active.
- Modify `Makefile` — `dev` recipe sets the flag inline; new `devlogin` target.
- Modify `fly.staging.toml` — `DEV_LOGIN_PREFILL = "admin:admin"` in `[env]`.
- Modify `docs/configuration.md` — document the setting.

---

## Task 1: Credential parser (`games/dev_login.py`)

**Files:**
- Create: `games/dev_login.py`
- Modify: `timetracker/settings.py` (add the config line so `settings.DEV_LOGIN_PREFILL` exists)
- Test: `tests/test_dev_login.py`

**Interfaces:**
- Produces: `prefill_credentials() -> tuple[str, str] | None` — reads `settings.DEV_LOGIN_PREFILL` (raw `"user:pass"`), returns `(username, password)` when well-formed, else `None` (logging a warning for a non-empty malformed value). Splits on the **first** `:` only.

- [ ] **Step 1: Add the setting** in `timetracker/settings.py`. Put this next to the other string `config(...)` calls (e.g. just after the `APP_URL` line, ~line 56):

```python
# Dev/staging-only: when set to "username:password", the login page prefills those
# credentials (see games/dev_login.py). Empty (the default) = off everywhere.
DEV_LOGIN_PREFILL = config("DEV_LOGIN_PREFILL", default="")
```

- [ ] **Step 2: Write the failing test** — create `tests/test_dev_login.py`:

```python
from django.test import SimpleTestCase, override_settings

from games.dev_login import prefill_credentials


class PrefillCredentialsTest(SimpleTestCase):
    @override_settings(DEV_LOGIN_PREFILL="admin:secret")
    def test_valid_pair(self):
        self.assertEqual(prefill_credentials(), ("admin", "secret"))

    @override_settings(DEV_LOGIN_PREFILL="")
    def test_empty_is_off(self):
        self.assertIsNone(prefill_credentials())

    @override_settings(DEV_LOGIN_PREFILL="nocolon")
    def test_missing_colon_is_off(self):
        self.assertIsNone(prefill_credentials())

    @override_settings(DEV_LOGIN_PREFILL=":secret")
    def test_empty_username_is_off(self):
        self.assertIsNone(prefill_credentials())

    @override_settings(DEV_LOGIN_PREFILL="admin:")
    def test_empty_password_is_off(self):
        self.assertIsNone(prefill_credentials())

    @override_settings(DEV_LOGIN_PREFILL="admin:a:b")
    def test_splits_on_first_colon_only(self):
        self.assertEqual(prefill_credentials(), ("admin", "a:b"))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `direnv exec . uv run --frozen pytest tests/test_dev_login.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'games.dev_login'`.

- [ ] **Step 4: Write the implementation** — create `games/dev_login.py`:

```python
"""Dev/staging-only login-form prefill (issue: dev login friction).

Parses the ``DEV_LOGIN_PREFILL`` setting ("username:password") into credentials
the login page pre-fills. Empty or malformed => disabled (fails safe), so the
login form renders normally in production.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def prefill_credentials() -> tuple[str, str] | None:
    """Return the ``(username, password)`` to prefill, or ``None`` when the
    ``DEV_LOGIN_PREFILL`` setting is unset or malformed. Splits on the first
    ``:`` only, so a colon in the password is preserved."""
    raw = settings.DEV_LOGIN_PREFILL
    if not raw:
        return None
    username, separator, password = raw.partition(":")
    if not separator or not username or not password:
        logger.warning(
            "DEV_LOGIN_PREFILL is malformed (%r); expected 'username:password'. "
            "Prefill disabled.",
            raw,
        )
        return None
    return username, password
```

- [ ] **Step 5: Run test to verify it passes**

Run: `direnv exec . uv run --frozen pytest tests/test_dev_login.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add games/dev_login.py timetracker/settings.py tests/test_dev_login.py
git commit -m "feat: DEV_LOGIN_PREFILL config + credential parser"
```

---

## Task 2: Login-form prefill (`LoginForm` + `LoginView`)

**Files:**
- Modify: `games/forms.py` (`LoginForm`, ~line 482)
- Modify: `games/views/auth.py` (`LoginView`, ~line 35)
- Test: `tests/test_dev_login.py`

**Interfaces:**
- Consumes: `prefill_credentials()` from Task 1.
- Produces: a `LoginView` whose GET renders username+password prefilled and sends `X-Robots-Tag: noindex` when prefill is active; renders a normal empty form (no password value, no header) when off.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_dev_login.py`:

```python
from django.test import Client, TestCase
from django.contrib.auth import get_user_model


class LoginPrefillViewTest(TestCase):
    @override_settings(DEV_LOGIN_PREFILL="admin:admin")
    def test_prefills_username_and_password_and_sets_noindex(self):
        response = Client().get("/login/")
        html = response.content.decode()
        # username input + password input both carry value="admin"
        self.assertEqual(html.count('value="admin"'), 2)
        self.assertEqual(response["X-Robots-Tag"], "noindex")

    @override_settings(DEV_LOGIN_PREFILL="")
    def test_off_renders_no_password_value_and_no_header(self):
        response = Client().get("/login/")
        html = response.content.decode()
        # password field present but with no value attribute, and no username value
        self.assertIn('type="password"', html)
        self.assertNotIn('value="admin"', html)
        self.assertNotIn("X-Robots-Tag", response)

    @override_settings(DEV_LOGIN_PREFILL='admin:a"><img src=x onerror=alert(1)>')
    def test_prefill_value_is_html_escaped(self):
        html = Client().get("/login/").content.decode()
        # the raw injection must not appear unescaped
        self.assertNotIn("<img src=x", html)

    @override_settings(DEV_LOGIN_PREFILL="admin:admin")
    def test_post_still_authenticates(self):
        get_user_model().objects.create_superuser("admin", "", "admin")
        client = Client()
        response = client.post("/login/", {"username": "admin", "password": "admin"})
        self.assertEqual(response.status_code, 302)  # redirect on success
        self.assertIn("_auth_user_id", client.session)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `direnv exec . uv run --frozen pytest tests/test_dev_login.py::LoginPrefillViewTest -v`
Expected: FAIL — username/password not prefilled (no `value="admin"`), no `X-Robots-Tag` header.

- [ ] **Step 3: Enable password rendering in `LoginForm`** — in `games/forms.py`, replace the `LoginForm` class body (starting ~line 482) with:

```python
class LoginForm(PrimitiveWidgetsMixin, AuthenticationForm):
    """Django's auth form with our primitive widget styling so login inputs
    self-style like every other form (no styling-at-a-distance)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Dev/staging prefill only: Django's PasswordInput omits the value by
        # default; allow it to render so the login page can be pre-typed. Never
        # enabled when DEV_LOGIN_PREFILL is unset, so production never emits a
        # password value.
        from games.dev_login import prefill_credentials

        if prefill_credentials():
            self.fields["password"].widget.render_value = True
```

(The existing docstring stays; only the `__init__` is added. Import inside the method to avoid any import-order coupling at module load.)

- [ ] **Step 4: Inject credentials + noindex in `LoginView`** — in `games/views/auth.py`, add the import and replace the `LoginView` class:

Add to the imports at the top (after `from games.forms import LoginForm`):

```python
from games.dev_login import prefill_credentials
```

Replace the `LoginView` class:

```python
class LoginView(auth_views.LoginView):
    """Django's LoginView, but the page body is built in Python and the form is
    our `LoginForm` so its inputs self-style like every other form. When
    DEV_LOGIN_PREFILL is set, the form is pre-typed (dev/staging convenience);
    login still POSTs and authenticates normally."""

    authentication_form = LoginForm

    def get_initial(self) -> dict:
        initial = super().get_initial()
        credentials = prefill_credentials()
        if credentials:
            initial["username"], initial["password"] = credentials
        return initial

    def render_to_response(self, context, **response_kwargs) -> HttpResponse:
        response = render_page(
            self.request,
            _login_content(context["form"], self.request),
            title="Login",
        )
        if prefill_credentials():
            # Credentials are visible in the page HTML; keep the prefilled login
            # page out of search indexes on the public staging box.
            response["X-Robots-Tag"] = "noindex"
        return response
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `direnv exec . uv run --frozen pytest tests/test_dev_login.py::LoginPrefillViewTest -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add games/forms.py games/views/auth.py tests/test_dev_login.py
git commit -m "feat: prefill login form + noindex when DEV_LOGIN_PREFILL is set"
```

---

## Task 3: `devlogin` management command

**Files:**
- Create: `games/management/commands/devlogin.py`
- Test: `tests/test_dev_login.py`

**Interfaces:**
- Consumes: `prefill_credentials()` from Task 1.
- Produces: a `devlogin` management command that ensures a superuser exists (credentials from `DEV_LOGIN_PREFILL` if set, else `admin`/`admin`) with a usable password, idempotently, and prints instructions.

- [ ] **Step 1: Write the failing test** — append to `tests/test_dev_login.py`:

```python
from django.core.management import call_command


class DevLoginCommandTest(TestCase):
    def test_creates_usable_superuser_idempotently(self):
        call_command("devlogin")
        call_command("devlogin")  # second run must not error
        User = get_user_model()
        user = User.objects.get(username="admin")
        self.assertTrue(user.is_superuser)
        self.assertTrue(Client().login(username="admin", password="admin"))

    @override_settings(DEV_LOGIN_PREFILL="dev:pw")
    def test_uses_prefill_credentials_when_set(self):
        call_command("devlogin")
        self.assertTrue(Client().login(username="dev", password="pw"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `direnv exec . uv run --frozen pytest tests/test_dev_login.py::DevLoginCommandTest -v`
Expected: FAIL — `Unknown command: 'devlogin'`.

- [ ] **Step 3: Write the command** — create `games/management/commands/devlogin.py`:

```python
"""Create (or repair) the dev superuser and print login instructions.

Idempotent: every run converges the user to a usable superuser, which fixes the
common "user exists but the password was never set" case. Uses the
DEV_LOGIN_PREFILL credentials when set, else admin/admin.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from games.dev_login import prefill_credentials


class Command(BaseCommand):
    help = "Create/repair the dev superuser and print login instructions."

    def handle(self, *args, **options) -> None:
        username, password = prefill_credentials() or ("admin", "admin")
        user_model = get_user_model()
        user, _created = user_model.objects.get_or_create(username=username)
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(
            self.style.SUCCESS(
                f"Superuser '{username}' ready.\n"
                f"Run `make dev`, open /login/ — the credentials are prefilled "
                f"when DEV_LOGIN_PREFILL is set; click Login."
            )
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `direnv exec . uv run --frozen pytest tests/test_dev_login.py::DevLoginCommandTest -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add games/management/commands/devlogin.py tests/test_dev_login.py
git commit -m "feat: devlogin management command (idempotent dev superuser)"
```

---

## Task 4: Environment wiring + docs

**Files:**
- Modify: `Makefile` (`dev` recipe ~line 69-76; add `devlogin` target)
- Modify: `fly.staging.toml` (`[env]` ~line 13-18)
- Modify: `docs/configuration.md` (settings table ~line 30-38)

**Interfaces:**
- Consumes: the `devlogin` command (Task 3) and the `DEV_LOGIN_PREFILL` setting (Task 1). No new code interfaces.

- [ ] **Step 1: Set the flag inline in the `dev` recipe** — in `Makefile`, change the runserver line inside the `dev` target so it reads (only the runserver command string changes):

```makefile
		"DEV_LOGIN_PREFILL=admin:admin uv run --frozen python -Wa manage.py runserver" \
```

- [ ] **Step 2: Add the `devlogin` target** — in `Makefile`, add after the `migrate` target:

```makefile
devlogin: migrate
	uv run --frozen python manage.py devlogin
```

- [ ] **Step 3: Set the staging env var** — in `fly.staging.toml`, add to the `[env]` block:

```toml
  DEV_LOGIN_PREFILL = "admin:admin"
```

- [ ] **Step 4: Document the setting** — in `docs/configuration.md`, add a row to the settings-reference table (after the `DATA_DIR` row):

```markdown
| `DEV_LOGIN_PREFILL` | str (`user:pass`) | `""` (off) | no | **Dev/staging only — never set in production.** When set to `username:password`, the login page prefills those credentials (one click to log in) and sends `X-Robots-Tag: noindex`. Login is not bypassed. `make dev` sets it to `admin:admin`; `make devlogin` provisions that superuser. |
```

- [ ] **Step 5: Verify the wiring** — the command is reachable and the target runs:

Run: `direnv exec . make devlogin`
Expected: prints "Superuser 'admin' ready. …".

- [ ] **Step 6: Commit**

```bash
git add Makefile fly.staging.toml docs/configuration.md
git commit -m "chore: wire DEV_LOGIN_PREFILL into make dev, staging, and docs"
```

---

## Task 5: Full verification

**Files:** none (gate).

- [ ] **Step 1: Run the full check gate**

Run: `direnv exec . make check`
Expected: green — lint, format-check, mypy, ts-check, vitest, and the entire pytest suite (incl. `e2e/` and the new `tests/test_dev_login.py`) pass.

- [ ] **Step 2: Manual smoke (optional but recommended)**

Run: `direnv exec . make devlogin` then `direnv exec . make dev`, open `/login/` — the form shows `admin`/`admin` prefilled; click Login → authenticated. Confirm a normal (unset) run renders an empty form with no password value.

---

## Self-review notes

- **Spec coverage:** config flag (Task 1), LoginView prefill + render_value + noindex (Task 2), devlogin command (Task 3), make dev / fly.staging.toml / docs (Task 4), off-by-default + escaping + POST-auth + malformed + idempotent tests (Tasks 1-3), full `make check` (Task 5). All spec sections mapped.
- **Escaping:** the password value renders through Django's widget, which HTML-escapes attribute values; Task 2's `test_prefill_value_is_html_escaped` guards it.
- **Prod safety:** `DEV_LOGIN_PREFILL` defaults to `""`; the prefill branches (`get_initial`, `render_value`, `noindex`) are all guarded by `prefill_credentials()` being non-`None`; `test_off_renders_no_password_value_and_no_header` guards the production path.
- **Type consistency:** `prefill_credentials() -> tuple[str, str] | None` is used identically in Tasks 2 and 3.
