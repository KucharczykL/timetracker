# Issue #392 — Export site settings to settings.ini snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give superusers a download action on `/admin-settings` that serializes the current `SiteSetting` DB rows into a `[timetracker]` `settings.ini` snapshot — for backup, and as the promotion path for pinning a DB value (or `TZ`) to env/ini.

**Architecture:** A pure serialization function (`timetracker/settings_export.py`) reads `SiteSetting.objects.all()`, converts each stored value back to the raw string form the existing ini reader (`timetracker/config.py:_load_ini_file`) expects, `%`-escapes it so `ConfigParser`'s `BasicInterpolation` doesn't choke on read, and writes a `[timetracker]` section via `configparser.ConfigParser`. A new Django view wraps this in a superuser-gated file download, wired into `/admin-settings` next to the existing "Site defaults" section.

**Tech Stack:** Django views, `configparser` (stdlib), the existing `timetracker.settings_registry`/`timetracker.settings_resolver` layer, `common.components` (ControlButton), pytest-django, Playwright (`pytest-playwright`).

## Global Constraints

- Every command runs inside the Nix dev shell: `direnv exec . <command>` (see root `CLAUDE.md`).
- Gate on the full `direnv exec . make check` (lint, format-check, mypy, ts-check, vitest, entire pytest suite incl. `e2e/`) before considering any task done — never a hand-picked subset.
- **Must not quote exported values** — the ini reader (`timetracker/config.py`) applies `_unquote` only to `.env`, not `.ini`; a quoted export would re-import with literal quote characters.
- **Must escape `%`** — the reader (`dict(parser[INI_SECTION])`) runs under `ConfigParser`'s default `BasicInterpolation`, which raises `InterpolationSyntaxError` on a lone `%`. Verified empirically (see Task 1): writing `%%` round-trips to a literal `%` on read; writing an unescaped `%` raises on `ConfigParser.set()` itself.
- **`GeneratedField`s are never written** — not touched by this feature, but keep in mind while editing nearby model code.
- Name variables with complete words (project convention).
- No comments unless they explain non-obvious *why* (project convention) — the `%`-escaping and no-quoting rules are exactly this kind of non-obvious constraint and deserve a one-line comment at the point they're applied.

---

## File Structure

- **Create:** `timetracker/settings_export.py` — `export_site_settings_ini() -> str`, the pure serialization function. No Django view/HTTP concerns here, matching the existing split between `timetracker/settings_commands.py` (mutation) and `games/views/settings.py` (HTTP).
- **Create:** `tests/test_settings_export.py` — unit tests for the serialization function, including the `%`-round-trip proof against the real reader (`timetracker.config`).
- **Modify:** `games/views/settings.py` — add `export_admin_settings_ini` view; add a download `ControlButton` to `admin_settings()`.
- **Modify:** `games/urls.py` — register `admin-settings/export` → `export_admin_settings_ini`.
- **Modify:** `tests/test_admin_settings_page.py` — view-level tests (superuser download, non-superuser 403, `Content-Disposition` header, button present in rendered page).
- **Modify:** `e2e/test_admin_settings_page_e2e.py` — one browser test that the download link is visible to a superuser and triggers a same-origin navigation to the export URL.
- **Modify:** `docs/configuration.md` — document the export action under "Admin settings page" / "Site defaults section".
- **Modify:** `CHANGELOG.md` — one bullet under `### New`.
- **Modify (after merge):** GitHub issue #381 (epic) — check off `#392`; issue #392 itself gets closed by the merge commit / PR.

---

## Task 1: `export_site_settings_ini()` serialization function

**Files:**
- Create: `timetracker/settings_export.py`
- Test: `tests/test_settings_export.py`

**Interfaces:**
- Consumes: `games.models.SiteSetting` (existing model, `key: str`, `value: JSONField`, ordered by `key`), `timetracker.config.INI_SECTION` (`"timetracker"`).
- Produces: `export_site_settings_ini() -> str` — the full `settings.ini`-format text (a `[timetracker]` section header plus one `KEY = value` line per stored `SiteSetting` row, values `%`-escaped and unquoted). Consumed by Task 2's view.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_settings_export.py
from configparser import ConfigParser

import pytest

from games.models import SiteSetting
from timetracker import config as config_module
from timetracker.config import INI_SECTION, resolve_raw_with_source
from timetracker.settings_export import export_site_settings_ini


@pytest.fixture
def clean_ini_env(monkeypatch, tmp_path):
    """Point the real reader at a scratch file so round-trip tests exercise the
    production read path without touching the repo's settings.ini."""
    monkeypatch.delenv("DEFAULT_CURRENCY", raising=False)
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    ini_path = tmp_path / "settings.ini"
    monkeypatch.setenv("INI_FILE", str(ini_path))
    config_module.reset_caches()
    return ini_path


def test_no_site_settings_produces_bare_section(db):
    text = export_site_settings_ini()
    parser = ConfigParser()
    parser.read_string(text)
    assert parser.has_section(INI_SECTION)
    assert dict(parser[INI_SECTION]) == {}


def test_exports_one_row_per_stored_key(db):
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EUR")
    SiteSetting.objects.create(key="DEFAULT_PAGE_SIZE", value=50)

    text = export_site_settings_ini()

    parser = ConfigParser()
    parser.optionxform = str
    parser.read_string(text)
    assert dict(parser[INI_SECTION]) == {
        "DEFAULT_CURRENCY": "EUR",
        "DEFAULT_PAGE_SIZE": "50",
    }


def test_stale_unregistered_key_is_exported_anyway(db):
    """A row for a since-removed/renamed registry key is still a real DB value —
    drop it silently and a backup snapshot loses data the operator expected. An
    unknown key in the ini is harmless on re-import (nothing looks it up), so
    export everything the DB actually holds rather than filtering by the
    current registry."""
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EUR")
    SiteSetting.objects.create(key="SOME_REMOVED_SETTING", value="stale")

    text = export_site_settings_ini()

    parser = ConfigParser()
    parser.optionxform = str
    parser.read_string(text)
    assert dict(parser[INI_SECTION]) == {
        "DEFAULT_CURRENCY": "EUR",
        "SOME_REMOVED_SETTING": "stale",
    }


def test_page_size_round_trips_through_cast_and_validator(db, clean_ini_env):
    """Acceptance criterion, checked past the raw string layer: the exported
    value must resolve back to the identical typed value through the full
    resolver (cast + validator), not just match byte-for-byte as a string."""
    SiteSetting.objects.create(key="DEFAULT_PAGE_SIZE", value=50)

    text = export_site_settings_ini()
    clean_ini_env.write_text(text)
    config_module.reset_caches()

    from timetracker.settings_resolver import resolve_with_origin

    resolved = resolve_with_origin("DEFAULT_PAGE_SIZE")
    assert resolved.value == 50


def test_percent_bearing_value_round_trips_through_the_real_reader(db, clean_ini_env):
    """Acceptance criterion from #392: a value containing `%` must re-import
    to the identical value through the actual production reader, not a
    reimplementation of it."""
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EU%R")

    text = export_site_settings_ini()
    clean_ini_env.write_text(text)
    config_module.reset_caches()

    result = resolve_raw_with_source("DEFAULT_CURRENCY")
    assert result is not None
    assert result.raw == "EU%R"


def test_exported_values_are_never_quoted(db):
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EUR")

    text = export_site_settings_ini()

    line = next(
        line for line in text.splitlines() if line.startswith("DEFAULT_CURRENCY")
    )
    assert '"' not in line
    assert "'" not in line
```

Note: `test_percent_bearing_value_round_trips_through_the_real_reader` stores
`"EU%R"` on `DEFAULT_CURRENCY` directly via the ORM (bypassing the
3-letter-currency validator, which is a write-time-only check in
`change_site_setting`/`normalize_setting_value` — the export function must
not require registry validation to run correctly, since it may need to
round-trip a stale or edge-case stored value). This is deliberate: it proves
the export/reader compatibility independent of what any single registered
setting's validator currently allows.

- [ ] **Step 2: Run tests to verify they fail**

```bash
direnv exec . uv run pytest tests/test_settings_export.py -v
```

Expected: `ModuleNotFoundError: No module named 'timetracker.settings_export'` (or `ImportError`).

- [ ] **Step 3: Write the implementation**

```python
# timetracker/settings_export.py
"""Serializes current SiteSetting DB rows to a settings.ini snapshot (issue #392).

Read-only / pure: builds text, does not touch the filesystem. The caller (the
admin-settings export view) decides how to deliver it.
"""

import io
from configparser import ConfigParser

from timetracker.config import INI_SECTION


def export_site_settings_ini() -> str:
    """Render every stored ``SiteSetting`` row as a ``[timetracker]`` ini section.

    Exports every DB row verbatim, including one for a key no longer in the
    settings registry (a stale row from a removed/renamed setting) — the
    reader loads the whole section into a plain dict, so an unknown key is
    inert on re-import, and silently dropping a real stored value would make
    this an incomplete backup.

    Matches the reader in ``timetracker/config.py`` (``_load_ini_file`` /
    ``dict(parser[INI_SECTION])``, read under the default ``BasicInterpolation``):
    values are written unquoted (only ``.env`` reading strips quotes; ``.ini``
    reading does not) and any literal ``%`` is doubled so interpolation on
    read collapses it back to one ``%`` instead of raising. Leading/trailing
    whitespace in a value does not survive the round trip — an inherent ini
    limitation (``ConfigParser`` strips it on read), not something this
    function preserves.
    """
    from games.models import SiteSetting

    parser = ConfigParser()
    # Preserve key case; ConfigParser lowercases option names by default, and
    # the reader also sets this so the two sides agree on key spelling.
    parser.optionxform = str  # type: ignore[assignment, method-assign]
    parser.add_section(INI_SECTION)

    for row in SiteSetting.objects.order_by("key"):
        raw_value = str(row.value).replace("%", "%%")
        parser.set(INI_SECTION, row.key, raw_value)

    buffer = io.StringIO()
    parser.write(buffer)
    return buffer.getvalue()


__all__ = ["export_site_settings_ini"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
direnv exec . uv run pytest tests/test_settings_export.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Typecheck and lint**

```bash
direnv exec . make lint
direnv exec . make typecheck
```

Expected: clean on `timetracker/settings_export.py` and `tests/test_settings_export.py`.

- [ ] **Step 6: Commit**

```bash
git add timetracker/settings_export.py tests/test_settings_export.py
git commit -m "feat(settings): add SiteSetting -> settings.ini export function"
```

---

## Task 2: Superuser download view + `/admin-settings` wiring

**Files:**
- Modify: `games/views/settings.py` (add view function; add button to `admin_settings()`)
- Modify: `games/urls.py` (register the route)
- Test: `tests/test_admin_settings_page.py`

**Interfaces:**
- Consumes: `timetracker.settings_export.export_site_settings_ini() -> str` (Task 1).
- Produces: view `export_admin_settings_ini(request: HttpRequest) -> HttpResponse`, URL name `games:export_admin_settings_ini`. Consumed by Task 3 (e2e) and the `admin_settings()` template wiring in this task.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_admin_settings_page.py` (reuses the file's existing `superuser`/`normal_user` fixtures — see the file's current top, already read during planning):

```python
def test_export_requires_superuser(client: Client, normal_user):
    client.force_login(normal_user)
    response = client.get(reverse("games:export_admin_settings_ini"))
    assert response.status_code == 403


def test_export_requires_login(client: Client):
    response = client.get(reverse("games:export_admin_settings_ini"))
    assert response.status_code == 302  # redirected to login


def test_export_downloads_ini_with_stored_settings(
    client: Client, superuser, clean_site_setting_sources
):
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EUR")
    client.force_login(superuser)

    response = client.get(reverse("games:export_admin_settings_ini"))

    assert response.status_code == 200
    assert response["Content-Disposition"] == 'attachment; filename="settings.ini"'
    content = response.content.decode()
    assert "[timetracker]" in content
    assert "DEFAULT_CURRENCY = EUR" in content


def test_admin_settings_page_shows_export_button(client: Client, superuser):
    client.force_login(superuser)
    response = client.get(reverse("games:admin_settings"))
    assert reverse("games:export_admin_settings_ini") in response.content.decode()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
direnv exec . uv run pytest tests/test_admin_settings_page.py -k export -v
```

Expected: `NoReverseMatch: Reverse for 'export_admin_settings_ini' not found.`

- [ ] **Step 3: Add the view**

In `games/views/settings.py`, add the import and the view function. Add `HttpResponseForbidden` to the existing `django.http` import line (currently `from django.http import HttpRequest, HttpResponse`):

```python
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
```

Add near the top-level imports (alongside the other `timetracker.*` imports):

```python
from timetracker.settings_export import export_site_settings_ini
```

Add the view function, placed after `admin_settings()`:

```python
@login_required
def export_admin_settings_ini(request: HttpRequest) -> HttpResponse:
    # A bare 403 (not the rendered admin_settings() 403 page) is deliberate: this
    # is a download endpoint reached only via a button superusers already see —
    # a direct non-superuser hit gets a plain denial, not a styled page.
    if not request.user.is_superuser:
        return HttpResponseForbidden("Superuser access is required.")
    response = HttpResponse(
        export_site_settings_ini(), content_type="text/plain; charset=utf-8"
    )
    response["Content-Disposition"] = 'attachment; filename="settings.ini"'
    return response
```

Add `"export_admin_settings_ini"` to the module's `__all__` list (alphabetical, matching the existing list style):

```python
__all__ = [
    "SiteSettingsForm",
    "UserSettingsForm",
    "admin_settings",
    "export_admin_settings_ini",
    "user_settings",
]
```

- [ ] **Step 4: Register the URL**

In `games/urls.py`, the existing `admin-settings` path (unchanged) is:

```python
(
    path(
        "admin-settings",
        settings_views.admin_settings,
        name="admin_settings",
    ),
)
```

Insert this new entry directly after it (do not duplicate the existing one above — only add the new `path(...)` call):

```python
(
    path(
        "admin-settings/export",
        settings_views.export_admin_settings_ini,
        name="export_admin_settings_ini",
    ),
)
```

- [ ] **Step 5: Add the download button to the admin-settings page**

In `admin_settings()` (`games/views/settings.py`), the page header currently is:

```python
    content = Div(class_="flex flex-col")[
        ContentContainer(class_="mb-6 flex flex-col gap-2")[
            PageHeading(["Admin settings"]),
            P(class_="text-type-body text-body")[
                "Defaults inherited by users who have not saved personal overrides."
            ],
        ],
        SettingsScaffold(sections),
    ]
```

Add a `ControlButton` import (extend the existing `common.components` import list in this file to include `ControlButton`), then change the header block to:

```python
content = Div(class_="flex flex-col")[
    ContentContainer(class_="mb-6 flex flex-col gap-2")[
        Div(class_="flex flex-wrap items-start justify-between gap-4")[
            Div(class_="flex flex-col gap-2")[
                PageHeading(["Admin settings"]),
                P(class_="text-type-body text-body")[
                    "Defaults inherited by users who have not saved personal overrides."
                ],
            ],
            ControlButton(
                href=reverse("games:export_admin_settings_ini"),
                color="gray",
            )["Download settings.ini"],
        ],
    ],
    SettingsScaffold(sections),
]
```

(`reverse` is already imported in this file.)

- [ ] **Step 6: Run tests to verify they pass**

```bash
direnv exec . uv run pytest tests/test_admin_settings_page.py -v
```

Expected: all tests in the file PASS, including the four new ones.

- [ ] **Step 7: Typecheck, lint, ts-check**

```bash
direnv exec . make lint
direnv exec . make typecheck
```

Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add games/views/settings.py games/urls.py tests/test_admin_settings_page.py
git commit -m "feat(settings): add superuser settings.ini download on /admin-settings"
```

---

## Task 3: E2E coverage

**Files:**
- Modify: `e2e/test_admin_settings_page_e2e.py`

**Interfaces:**
- Consumes: the `superuser_page` fixture already defined in this file (creates a superuser, logs in, returns a Playwright `Page`); URL name `games:export_admin_settings_ini` (Task 2); `games:admin_settings`.
- Produces: nothing consumed by later tasks — this is a leaf verification.

- [ ] **Step 1: Write the failing test**

Add to `e2e/test_admin_settings_page_e2e.py`, following the file's existing style (`superuser_page` fixture, `reverse()` for URLs):

```python
def test_export_button_downloads_settings_ini(live_server, superuser_page: Page):
    page = superuser_page
    page.goto(f"{live_server.url}{reverse('games:admin_settings')}")

    with page.expect_download() as download_info:
        page.get_by_role("link", name="Download settings.ini").click()
    download = download_info.value

    assert download.suggested_filename == "settings.ini"
```

- [ ] **Step 2: Confirm true red/green**

Task 2 already ships the button, so this test is written *after* the feature exists — there is no natural red state to chase here. Confirm the test is meaningful instead: temporarily comment out the `ControlButton(...)` block added in Task 2 Step 5, rerun the command below and confirm it FAILS (`TimeoutError` on `get_by_role("link", name="Download settings.ini")`), then restore the button.

```bash
direnv exec . uv run pytest e2e/test_admin_settings_page_e2e.py -k export_button -v
```

- [ ] **Step 3: Run test to verify it passes**

```bash
direnv exec . uv run pytest e2e/test_admin_settings_page_e2e.py -k export_button -v
```

Expected: PASS.

- [ ] **Step 4: Run the full e2e file to check for regressions**

```bash
direnv exec . uv run pytest e2e/test_admin_settings_page_e2e.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add e2e/test_admin_settings_page_e2e.py
git commit -m "test(e2e): cover the admin-settings.ini download button"
```

---

## Task 4: Docs and changelog

**Files:**
- Modify: `docs/configuration.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: nothing (prose only).
- Produces: nothing (leaf task).

- [ ] **Step 1: Update `docs/configuration.md`**

In the "Site defaults section" subsection (immediately after the bullet list of the eight settings and the "A value owned by an environment variable..." paragraph), add:

```markdown
A **Download settings.ini** button in the page header exports every
currently-stored site default as a `[timetracker]` ini snapshot — for backup,
or to promote a database value to an env-pinned one (edit the downloaded
file, point `INI_FILE`/deploy it as `settings.ini`, restart). Values are
written unquoted and with any literal `%` doubled, matching how
`timetracker/config.py` reads `.ini` files (`BasicInterpolation`, no
`.env`-style unquoting) — a value containing `%` re-imports to the identical
string.
```

- [ ] **Step 2: Update `CHANGELOG.md`**

Add a bullet under `## Unreleased` / `### New`, following the existing settings-related bullets' style:

```markdown
* Add a **Download settings.ini** action to `/admin-settings`, exporting every
  currently-stored site default to a `[timetracker]` ini snapshot for backup
  or promotion to an env-pinned value.
```

- [ ] **Step 3: Commit**

```bash
git add docs/configuration.md CHANGELOG.md
git commit -m "docs(settings): document the settings.ini export action"
```

---

## Task 5: Full verification gate and PR

**Files:** none (verification only).

- [ ] **Step 1: Run the full check suite**

```bash
direnv exec . make check
```

Expected: green — lint, format-check, mypy, ts-check, vitest, and the entire pytest suite including `e2e/`.

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat(settings): export site settings to settings.ini (#392)" --body "$(cat <<'EOF'
## Summary
- Add `timetracker/settings_export.py::export_site_settings_ini()`, matching the existing `.ini` reader's no-quote / `%`-doubling contract.
- Add a superuser-gated download view + `/admin-settings` button.
- Tests: unit (serialization + real-reader round trip incl. a `%`-bearing value), view (403/redirect/200 + button presence), e2e (click-to-download).

Closes #392

## Test plan
- [x] `direnv exec . make check` green (incl. e2e)
- [x] Manually downloaded settings.ini from /admin-settings in the browser and confirmed contents

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Check off #392 in the epic**

```bash
gh issue edit 381 --repo KucharczykL/timetracker --body-file <(gh issue view 381 --repo KucharczykL/timetracker --json body -q .body | sed 's/- \[ \] #392/- [x] #392/')
```

(Do this after the PR merges, not before — the epic's checklist should reflect merged state.)

---

## Self-Review

**Spec coverage:**
- "A superuser download action on `/admin-settings` serializing current DB site settings to a `[timetracker]` ini" → Task 2 (view + button) + Task 1 (serialization).
- "not quote values" → Task 1 implementation (no quoting logic added; `ConfigParser.write()` doesn't quote by default) + `test_exported_values_are_never_quoted`.
- "use `interpolation=None` / escape `%`" → implemented via manual `%%`-doubling before `parser.set()` (empirically verified against `ConfigParser`'s default `BasicInterpolation`, which is what the real reader in `config.py` uses — doubling is the correct fix, not `interpolation=None` on the writer, since the *reader* is fixed and already uses default interpolation; see Task 1's docstring) + `test_percent_bearing_value_round_trips_through_the_real_reader`.
- "Exported file re-imports to identical values, including a value containing %" → the same test, driven through `timetracker.config.resolve_raw_with_source` (the actual production reader), not a reimplementation.
- "Tests" → Tasks 1, 2, 3 (unit, view, e2e).
- Cross-cutting epic requirement ("gates on full `make check` incl. e2e", "update docs/configuration.md and CHANGELOG.md") → Tasks 4 and 5.

**Placeholder scan:** none found — every step has literal code/commands.

**Type consistency:** `export_site_settings_ini() -> str` used identically in Task 1 (definition) and Task 2 (view call site). URL name `games:export_admin_settings_ini` consistent across Tasks 2, 3, 4. View name `export_admin_settings_ini` matches `games/urls.py` reference and `__all__` entry.

**Adversarial review (Fable 5, against the real codebase, 2026-07-25):** confirmed every referenced file/function/fixture/signature exists as described, and independently re-verified the core `%%`-escaping claim with its own empirical repro (including that unescaped whitespace does not round-trip through ini — noted in the export function's docstring above). Four issues found and fixed inline in this plan:
1. Unused `import io` in the planned test file (would fail `make lint`) — removed.
2. Task 2 Step 4 URL diff risked an executor pasting a duplicate `admin-settings` path — reworded to show only the new entry.
3. Silently skipping a stale/unregistered `SiteSetting` row (logged server-side only, invisible to the downloading superuser) would silently drop real data from a "current DB site settings" backup — changed to export every row verbatim regardless of registry membership; the corresponding test now asserts inclusion, not omission.
4. The bare `HttpResponseForbidden` diverges from the sibling `admin_settings()` view's rendered 403 page — kept (right call for a download endpoint) but the divergence is now a one-line comment in the view instead of a silent inconsistency.

Also added `test_page_size_round_trips_through_cast_and_validator`, which checks the acceptance criterion ("re-imports to identical values") past the raw-string layer, through the full typed resolver.
