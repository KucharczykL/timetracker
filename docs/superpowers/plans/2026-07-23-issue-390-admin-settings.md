# Admin Site Settings Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a superuser-only `/admin-settings` page for editing every live site default, including the live display timezone introduced by PR #480.

**Architecture:** Keep personal and site forms explicit but colocated in `games/views/settings.py`, render both through the existing settings kit, and use the existing `/api/settings/site/{key}` write boundary. Make the site PATCH response match the personal endpoint's resolved-setting contract so the existing live-setting custom element can reconcile values and source badges.

**Tech Stack:** Django 6 function views/forms, Django Ninja, Python component UI, TypeScript custom elements, pytest, Playwright.

## Global Constraints

- Expose exactly these live site defaults: `DEFAULT_CURRENCY`, `DEFAULT_DEVICE`, `DEFAULT_LANDING_PAGE`, `DEFAULT_PAGE_SIZE`, `THEME`, `DISPLAY_TIME_ZONE`, `DATE_FORMAT_LOCALE`, and `DATETIME_FORMAT`.
- Do not render or edit boot-time `TZ` or any other infrastructure setting in Stage 8.
- Anonymous page requests redirect to login; authenticated non-superusers receive a component-rendered HTTP 403 response.
- Environment, environment-file, `.env`, and `settings.ini` values remain locked and disabled.
- Personal overrides continue to win over site defaults.
- Use `render_page()` and Python components; do not add templates or raw HTML strings.
- Run every `make`, `uv`, `pnpm`, and pytest command through `direnv exec .`.

---

## File Structure

- `timetracker/settings_resolver.py`: validate site device IDs and return the normalized value written by `set_site_setting()`.
- `games/api.py`: return a reconciled `SettingOut` from site PATCH requests.
- `tests/test_settings_api.py`: pin the site PATCH, clear, validation, and inheritance contracts.
- `games/views/settings.py`: define `SiteSettingsForm`, build resolved/locked site field state, and render the gated admin page.
- `games/urls.py`: register `/admin-settings`.
- `tests/test_admin_settings_page.py`: cover access control, rendering, fields, resolved values, locking, and infrastructure exclusion.
- `common/layout.py`: thread `is_superuser` through the navbar and render the admin link.
- `tests/test_settings_page.py`: cover navbar visibility without duplicating page behavior tests.
- `e2e/test_admin_settings_page_e2e.py`: cover live writes, reload semantics, clearing, responsive layout, and locked controls in a browser.
- `docs/configuration.md`: document the admin surface and distinguish `DISPLAY_TIME_ZONE` from infrastructure `TZ`.
- `CHANGELOG.md`: announce the new site-settings UI.

---

### Task 1: Make Site PATCH Return the Resolved Setting

**Files:**
- Modify: `tests/test_settings_api.py`
- Modify: `timetracker/settings_resolver.py:254-297`
- Modify: `games/api.py:624-656`

**Interfaces:**
- Consumes: `set_site_setting(key: SettingKey, value: object)`.
- Produces: `set_site_setting(key: SettingKey, value: object) -> object`; `_resolved_site_write(key, saved_value) -> ResolvedSetting`; `PATCH /api/settings/site/{key}` returns `SettingOut`.

- [ ] **Step 1: Write failing site API contract tests**

Add these tests beneath the existing site round-trip test in `tests/test_settings_api.py`:

```python
def test_site_patch_returns_reconciled_setting(
    superuser_client, no_currency_env, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _patch(
            superuser_client,
            _site_patch_url("DEFAULT_CURRENCY"),
            "eur",
        )

    assert response.status_code == 200
    assert response.json() == {
        "key": "DEFAULT_CURRENCY",
        "value": "EUR",
        "source": "database",
        "locked": False,
    }


def test_site_patch_clear_returns_fallback(
    superuser_client, no_currency_env, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        _patch(superuser_client, _site_patch_url("DEFAULT_CURRENCY"), "EUR")
        response = _patch(
            superuser_client,
            _site_patch_url("DEFAULT_CURRENCY"),
            None,
        )

    assert response.status_code == 200
    assert response.json()["key"] == "DEFAULT_CURRENCY"
    assert response.json()["source"] == "default"
    assert response.json()["locked"] is False


def test_site_patch_rejects_missing_device(superuser_client):
    from games.models import SiteSetting

    response = _patch(
        superuser_client,
        _site_patch_url("DEFAULT_DEVICE"),
        9999,
    )

    assert response.status_code == 400
    assert not SiteSetting.objects.filter(key="DEFAULT_DEVICE").exists()
```

Change the existing `test_site_patch_sets_fallback_for_overlayless_user` assertion from status `204` to status `200`.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
direnv exec . uv run --frozen pytest \
  tests/test_settings_api.py::test_site_patch_returns_reconciled_setting \
  tests/test_settings_api.py::test_site_patch_clear_returns_fallback \
  tests/test_settings_api.py::test_site_patch_rejects_missing_device \
  tests/test_settings_api.py::test_site_patch_sets_fallback_for_overlayless_user -q
```

Expected: failures because site PATCH returns 204 and site writes do not reject a nonexistent device.

- [ ] **Step 3: Share device-existence validation between user and site writes**

In `timetracker/settings_resolver.py`, extract the existing device check:

```python
def _validate_referenced_device(key: SettingKey, normalized: object) -> None:
    if key != "DEFAULT_DEVICE" or normalized is None:
        return
    from games.models import Device

    device_id = cast(int, normalized)
    if not Device.objects.filter(pk=device_id).exists():
        raise ValidationError(f"No device with id {device_id!r}.")
```

Call it after normalization in both write functions:

```python
normalized = None if value is None else normalize_setting_value(value, definition)
_validate_referenced_device(key, normalized)
```

and:

```python
def set_site_setting(key: SettingKey, value: object) -> object:
    definition = get_definition(key)
    if definition.scope is SettingScope.INFRA:
        raise ValueError(f"{key} is infra-scoped (boot-only); cannot store in DB.")
    normalized = normalize_setting_value(value, definition)
    _validate_referenced_device(key, normalized)

    from games.models import SiteSetting

    SiteSetting.objects.update_or_create(key=key, defaults={"value": normalized})
    return normalized
```

Update the docstring to state that the normalized value is returned and nonexistent device IDs are rejected.

- [ ] **Step 4: Build a cache-safe immediate site-write response**

Add this helper in `games/api.py` beside `_setting_out()`. It deliberately does
not trust the cached database snapshot: `SiteSetting` invalidation runs on
transaction commit, which may not have happened yet when Ninja serializes the
response.

```python
def _resolved_site_write(
    key: SettingKey,
    saved_value: object | None,
) -> ResolvedSetting:
    resolved = resolve_with_origin(key)
    if resolved.locked:
        return resolved
    if saved_value is None:
        definition = get_definition(key)
        return ResolvedSetting(
            definition.default_factory(),
            SettingSource.DEFAULT,
            False,
        )
    return ResolvedSetting(saved_value, SettingSource.DATABASE, False)
```

Then change the endpoint to:

```python
@settings_router.patch("/site/{key}", response=SettingOut)
def update_site_setting(request, key: str, payload: SettingValueIn):
    """Set or clear a site default and return its freshly resolved state."""
    if not request.user.is_superuser:
        raise HttpError(403, "Superuser required.")
    try:
        definition = get_definition(key)
    except UnregisteredSettingError:
        raise HttpError(400, f"Unknown setting {key!r}.")
    if definition.scope is SettingScope.INFRA:
        raise HttpError(400, f"{key} is infra-scoped and cannot be stored.")
    try:
        if payload.value is None:
            clear_site_setting(key)
            saved_value = None
        else:
            saved_value = set_site_setting(key, payload.value)
    except (ValidationError, ValueError, TypeError) as error:
        _raise_400(error)
    messages.success(request, f"{definition.label} saved")
    return _setting_out(key, _resolved_site_write(key, saved_value))
```

- [ ] **Step 5: Run the API and resolver tests**

Run:

```bash
direnv exec . uv run --frozen pytest \
  tests/test_settings_api.py \
  tests/test_settings_resolver.py \
  tests/test_user_preferences_resolver.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add games/api.py timetracker/settings_resolver.py tests/test_settings_api.py
git commit -m "feat(settings): reconcile site setting writes"
```

---

### Task 2: Add the Superuser Site Settings View

**Files:**
- Create: `tests/test_admin_settings_page.py`
- Modify: `games/views/settings.py`
- Modify: `games/urls.py:18-22`

**Interfaces:**
- Consumes: `resolve_with_origin(key)`, `LiveSettingFields(...)`, and `SettingFieldState`.
- Produces: `SiteSettingsForm`; `admin_settings(request) -> HttpResponse`; URL name `games:admin_settings`.

- [ ] **Step 1: Write failing access and rendering tests**

Create `tests/test_admin_settings_page.py`:

```python
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from games.models import Device, SiteSetting
from timetracker import config as config_module
from timetracker import settings_resolver


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def superuser(db):
    return get_user_model().objects.create_superuser(
        username="boss",
        password="pw",
    )


@pytest.fixture
def superuser_client(superuser):
    client = Client()
    client.force_login(superuser)
    return client


def test_admin_settings_requires_login(db):
    response = Client().get("/tracker/admin-settings")

    assert response.status_code == 302
    assert response.url == "/login/?next=/tracker/admin-settings"


def test_admin_settings_renders_component_403_for_non_superuser(auth_client):
    response = auth_client.get(reverse("games:admin_settings"))

    assert response.status_code == 403
    html = response.content.decode()
    assert "<html" in html
    assert "Superuser required" in html


def test_admin_settings_renders_all_live_site_defaults(superuser_client):
    response = superuser_client.get(reverse("games:admin_settings"))

    assert response.status_code == 200
    html = response.content.decode()
    assert 'patch-url-template="/api/settings/site/__key__"' in html
    for key in (
        "DEFAULT_CURRENCY",
        "DEFAULT_DEVICE",
        "DEFAULT_LANDING_PAGE",
        "DEFAULT_PAGE_SIZE",
        "THEME",
        "DISPLAY_TIME_ZONE",
        "DATE_FORMAT_LOCALE",
        "DATETIME_FORMAT",
    ):
        assert f'data-setting-key="{key}"' in html
    assert 'data-setting-key="TZ"' not in html
    assert "<theme-setting" not in html


def test_admin_settings_uses_resolved_values_and_lists_devices(superuser_client):
    device = Device.objects.create(name="Steam Deck", type=Device.HANDHELD)
    SiteSetting.objects.create(key="DEFAULT_DEVICE", value=device.pk)
    SiteSetting.objects.create(key="THEME", value="dark")
    SiteSetting.objects.create(
        key="DISPLAY_TIME_ZONE",
        value="Pacific/Kiritimati",
    )
    settings_resolver.clear_cache()

    html = superuser_client.get(reverse("games:admin_settings")).content.decode()

    assert f'<option value="{device.pk}" selected>' in html
    assert '<option value="dark" selected>Dark</option>' in html
    assert (
        '<option value="Pacific/Kiritimati" selected>'
        "Pacific/Kiritimati</option>" in html
    )


def test_admin_settings_disables_environment_locked_field(
    superuser_client, monkeypatch
):
    monkeypatch.setenv("DEFAULT_CURRENCY", "USD")
    config_module.reset_caches()
    settings_resolver.clear_cache()

    html = superuser_client.get(reverse("games:admin_settings")).content.decode()
    currency = html[
        html.index('<input type="text" name="default_currency"') :
        html.index(">", html.index('<input type="text" name="default_currency"')) + 1
    ]

    assert " disabled" in currency
    assert 'data-setting-origin="env"' in html
    assert "Managed by Environment; it cannot be changed here." in html
```

- [ ] **Step 2: Run the page tests and verify they fail**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_admin_settings_page.py -q
```

Expected: failures because the route and view do not exist.

- [ ] **Step 3: Add the explicit site form**

In `games/views/settings.py`, add `SiteSettingsForm` with the same eight field names and typed controls as `UserSettingsForm`. Its select fields must start with a clear option:

```python
_CLEAR_SITE_DEFAULT = (("", "Use configured default"),)


class SiteSettingsForm(PrimitiveWidgetsMixin, forms.Form):
    default_currency = forms.CharField(
        required=False,
        max_length=3,
        widget=forms.TextInput(
            attrs={"x-mask": "aaa", "x-data": "", "class": "uppercase"}
        ),
    )
    default_device = forms.ModelChoiceField(
        queryset=Device.objects.none(),
        required=False,
        empty_label="Use configured default",
    )
    default_landing_page = forms.ChoiceField(
        required=False,
        choices=(*_CLEAR_SITE_DEFAULT, *LANDING_PAGE_CHOICES),
    )
    default_page_size = forms.ChoiceField(
        required=False,
        choices=(
            *_CLEAR_SITE_DEFAULT,
            *((size, str(size)) for size in PAGE_SIZE_CHOICES),
        ),
    )
    theme = forms.ChoiceField(
        required=False,
        choices=(*_CLEAR_SITE_DEFAULT, *THEME_CHOICES),
    )
    display_time_zone = forms.ChoiceField(
        required=False,
        choices=(*_CLEAR_SITE_DEFAULT, *DISPLAY_TIME_ZONE_CHOICES),
    )
    date_format_locale = forms.ChoiceField(
        required=False,
        choices=(*_CLEAR_SITE_DEFAULT, *FORMAT_LOCALE_CHOICES),
    )
    datetime_format = forms.ChoiceField(
        required=False,
        choices=(*_CLEAR_SITE_DEFAULT, *DATETIME_FORMAT_CHOICES),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        device_field = cast(forms.ModelChoiceField, self.fields["default_device"])
        device_field.queryset = Device.objects.order_by("name")
        for field_name, key in _FIELD_KEYS.items():
            self.fields[field_name].label = get_definition(key).label
        for field_name in (
            "theme",
            "display_time_zone",
            "date_format_locale",
            "datetime_format",
        ):
            self.fields[field_name].widget.attrs["data-reload-after-save"] = ""
```

- [ ] **Step 4: Build resolved site form state and render the view**

Add:

```python
def _site_form_and_states() -> tuple[SiteSettingsForm, dict[str, SettingFieldState]]:
    initial: dict[str, object] = {}
    states: dict[str, SettingFieldState] = {}
    for field_name, key in _FIELD_KEYS.items():
        definition = get_definition(key)
        resolved = resolve_with_origin(key)
        initial[field_name] = resolved.value
        states[field_name] = SettingFieldState(
            key,
            str(resolved.source),
            locked=resolved.locked,
            help_text=definition.help_text,
        )
    return SiteSettingsForm(initial=initial), states


@login_required
def admin_settings(request: HttpRequest) -> HttpResponse:
    if not request.user.is_superuser:
        content = ContentContainer()[
            PageHeading(["Superuser required"]),
            Div(class_="mt-4 text-body")[
                "You do not have permission to manage site settings."
            ],
        ]
        return render_page(
            request,
            content,
            title="Superuser required",
            status=403,
        )

    form, states = _site_form_and_states()
    patch_url = reverse(
        "api-1.0.0:update_site_setting",
        kwargs={"key": "__key__"},
    )
    sections = [
        SettingsSection(
            "site-defaults",
            "Site defaults",
            LiveSettingFields(
                form,
                states=states,
                patch_url_template=patch_url,
                csrf=get_token(request),
            ),
            "Defaults inherited by users who have not selected a personal value.",
        )
    ]
    content = Div(class_="flex flex-col")[
        ContentContainer(class_="mb-6")[PageHeading(["Admin settings"])],
        SettingsScaffold(sections),
    ]
    return render_page(request, content, title="Admin settings")
```

Export the new form/view in `__all__`.

- [ ] **Step 5: Register the route**

Add to `games/urls.py` immediately after the personal settings route:

```python
path(
    "admin-settings",
    settings_views.admin_settings,
    name="admin_settings",
),
```

- [ ] **Step 6: Run page and existing settings tests**

Run:

```bash
direnv exec . uv run --frozen pytest \
  tests/test_admin_settings_page.py \
  tests/test_settings_page.py \
  tests/test_settings_ui_kit.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add games/views/settings.py games/urls.py tests/test_admin_settings_page.py
git commit -m "feat(settings): add admin site settings page"
```

---

### Task 3: Add the Superuser Navbar Entry

**Files:**
- Modify: `tests/test_settings_page.py`
- Modify: `common/layout.py:207-375`
- Modify: `common/layout.py:435-490`
- Modify: `common/layout.py:500-535`

**Interfaces:**
- Consumes: `request.user.is_superuser`.
- Produces: `NavbarMenu(..., is_superuser: bool = False)` and `Navbar(..., is_superuser: bool = False)`.

- [ ] **Step 1: Write failing navbar visibility tests**

Append to `tests/test_settings_page.py`:

```python
def test_superuser_navbar_links_to_admin_settings(db):
    superuser = get_user_model().objects.create_superuser(
        username="boss",
        password="pw",
    )
    client = Client()
    client.force_login(superuser)

    html = client.get(reverse("games:list_sessions")).content.decode()

    assert f'href="{reverse("games:admin_settings")}"' in html
    assert ">Admin settings</a>" in html


def test_normal_user_navbar_hides_admin_settings(auth_client):
    html = auth_client.get(reverse("games:list_sessions")).content.decode()

    assert f'href="{reverse("games:admin_settings")}"' not in html
    assert ">Admin settings</a>" not in html


def test_anonymous_navbar_hides_admin_settings(db):
    html = Client().get(reverse("login")).content.decode()

    assert 'href="/tracker/admin-settings"' not in html
```

- [ ] **Step 2: Run the navbar tests and verify they fail**

Run:

```bash
direnv exec . uv run --frozen pytest \
  tests/test_settings_page.py::test_superuser_navbar_links_to_admin_settings \
  tests/test_settings_page.py::test_normal_user_navbar_hides_admin_settings \
  tests/test_settings_page.py::test_anonymous_navbar_hides_admin_settings -q
```

Expected: the superuser test fails because no link is rendered.

- [ ] **Step 3: Thread and render the superuser flag**

Add `is_superuser: bool = False` to `NavbarMenu()` and create:

```python
admin_settings_link = (
    Li()[
        A(
            href=reverse("games:admin_settings"),
            class_=_NAV_LINK_CLASS,
        )["Admin settings"]
    ]
    if is_superuser
    else ""
)
```

Place it immediately after `settings_link` in the menu children.

Add the same keyword to `Navbar()` and pass it to `NavbarMenu()`:

```python
is_superuser=is_superuser,
```

Finally, pass the request value from `TimetrackerDocument()`:

```python
is_superuser=bool(
    request.user.is_authenticated and request.user.is_superuser
),
```

- [ ] **Step 4: Run navbar and layout tests**

Run:

```bash
direnv exec . uv run --frozen pytest \
  tests/test_settings_page.py \
  tests/test_navbar_log_button.py \
  tests/test_navbar_playtime.py \
  tests/test_theme_layout.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add common/layout.py tests/test_settings_page.py
git commit -m "feat(settings): link admin settings for superusers"
```

---

### Task 4: Cover Browser Behavior and Document the Feature

**Files:**
- Create: `e2e/test_admin_settings_page_e2e.py`
- Modify: `docs/configuration.md:70-85`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `games:admin_settings`, site PATCH JSON response, and existing settings custom elements.
- Produces: browser-level acceptance coverage and user-facing documentation.

- [ ] **Step 1: Write the browser acceptance test**

Create `e2e/test_admin_settings_page_e2e.py`:

```python
import re

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from timetracker import config as config_module
from timetracker import settings_resolver


@pytest.fixture
def superuser_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_superuser(
        username="boss",
        password="secret123",
    )
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "boss")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.mark.parametrize(
    ("viewport", "mobile"),
    [
        ({"width": 390, "height": 844}, True),
        ({"width": 1280, "height": 900}, False),
    ],
)
def test_superuser_updates_and_clears_site_defaults(
    live_server, superuser_page, viewport, mobile
):
    page = superuser_page
    page.set_viewport_size(viewport)
    page.goto(f"{live_server.url}{reverse('games:admin_settings')}")
    page.wait_for_function("customElements.get('live-setting-fields') !== undefined")

    expect(page.get_by_role("heading", name="Admin settings")).to_be_visible()
    trigger = page.locator("[data-section-nav-trigger]")
    rail = page.locator("[data-section-nav-rail]")
    expect(trigger).to_be_visible() if mobile else expect(trigger).to_be_hidden()
    expect(rail).to_be_hidden() if mobile else expect(rail).to_be_visible()

    currency = page.locator('input[name="default_currency"]')
    currency.fill("eur")
    with page.expect_response(
        lambda response: (
            "/api/settings/site/DEFAULT_CURRENCY" in response.url
            and response.request.method == "PATCH"
        )
    ) as currency_saved:
        currency.blur()
    assert currency_saved.value.status == 200
    expect(currency).to_have_value("EUR")
    currency_badge = page.locator(
        'setting-source-badge[key="DEFAULT_CURRENCY"] [data-setting-origin]'
    )
    expect(currency_badge).to_have_attribute("data-setting-origin", "database")
    expect(currency_badge).to_have_class(re.compile(r"\bbg-brand-soft\b"))

    with page.expect_navigation(wait_until="load"):
        with page.expect_response(
            lambda response: (
                "/api/settings/site/DISPLAY_TIME_ZONE" in response.url
                and response.request.method == "PATCH"
            )
        ) as timezone_saved:
            page.locator('select[name="display_time_zone"]').select_option(
                "Pacific/Kiritimati"
            )
    assert timezone_saved.value.status == 200
    contract = page.locator("html").get_attribute("data-date-time-presentation") or ""
    assert "Pacific/Kiritimati" in contract

    currency = page.locator('input[name="default_currency"]')
    currency.fill("")
    with page.expect_response(
        lambda response: (
            "/api/settings/site/DEFAULT_CURRENCY" in response.url
            and response.request.method == "PATCH"
        )
    ) as currency_cleared:
        currency.blur()
    assert currency_cleared.value.status == 200
    expect(currency_badge).to_have_attribute("data-setting-origin", "default")


def test_environment_locked_site_default_cannot_submit(
    live_server, superuser_page, monkeypatch
):
    monkeypatch.setenv("DEFAULT_CURRENCY", "USD")
    config_module.reset_caches()
    settings_resolver.clear_cache()
    page = superuser_page
    requests = []
    page.on(
        "request",
        lambda request: requests.append(request)
        if "/api/settings/site/DEFAULT_CURRENCY" in request.url
        else None,
    )

    page.goto(f"{live_server.url}{reverse('games:admin_settings')}")
    currency = page.locator('input[name="default_currency"]')

    expect(currency).to_be_disabled()
    badge = page.locator(
        'setting-source-badge[key="DEFAULT_CURRENCY"] [data-setting-origin]'
    )
    expect(badge).to_have_attribute("data-setting-origin", "env")
    currency.press("Enter")
    page.wait_for_timeout(100)
    assert requests == []
```

- [ ] **Step 2: Run the browser test**

Run:

```bash
direnv exec . uv run --frozen pytest e2e/test_admin_settings_page_e2e.py -q
```

Expected: both viewport cases and the locked-field case pass.

- [ ] **Step 3: Update configuration documentation**

In `docs/configuration.md`, add an “Admin settings” paragraph to the runtime settings section:

```markdown
Superusers can edit every live site default at `/tracker/admin-settings`.
The page covers currency, device, landing page, page size, theme, display time
zone, formatting locale, and date/time format. Values pinned by environment,
environment-file, `.env`, or `settings.ini` are shown read-only with their
source.

`DISPLAY_TIME_ZONE` is the live site default inherited by users without a
personal timezone override. It is separate from infrastructure `TZ`, which sets
Django's boot-time `TIME_ZONE`, requires a restart, and is not editable on the
admin settings page.
```

- [ ] **Step 4: Update the changelog**

Under `## Unreleased` → `### New` in `CHANGELOG.md`, add:

```markdown
* Add a superuser-only Admin settings page for live site defaults. Admins can
  configure currency, device, landing page, page size, theme, display timezone,
  formatting locale, and date/time format; users without personal overrides
  inherit the changes. Environment- and config-file-pinned values remain locked
  with their source shown (#390).
```

- [ ] **Step 5: Run documentation-adjacent and full verification**

Run:

```bash
direnv exec . make check
```

Expected: lint, formatting, mypy, TypeScript checks, Vitest, pytest, and e2e all pass.

- [ ] **Step 6: Commit**

```bash
git add \
  e2e/test_admin_settings_page_e2e.py \
  docs/configuration.md \
  CHANGELOG.md
git commit -m "test(settings): cover admin site settings flow"
```

---

## Final Review

- Confirm the page contains all eight live defaults and no infrastructure keys.
- Confirm normal users are blocked independently at page, API, and navbar layers.
- Confirm site PATCH returns normalized/resolved JSON for both set and clear.
- Confirm a site display-timezone change updates inheriting users without changing boot-time `TZ`.
- Confirm `git diff --check` and `direnv exec . make check` are green.
