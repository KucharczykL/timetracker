# Stage 6.5: Per-User Timezone and Formatting Locale

## Goal

Let each account choose the IANA timezone and date-formatting locale used for
wall-clock display and datetime form interpretation, without changing the
boot-time site `TZ` setting or requiring an application restart.

Formatting locale is separate from UI translation. It controls date-related
names and conventions only; it must not translate application copy.

## Scope

This stage sits between Stage 6 (centralized `DateTimePresentation` contract)
and Stage 7 (per-user date/time format profile). Stage 6 provides the
request-scoped presentation object; Stage 6.5 populates its timezone and locale
from per-user preferences.

## Architecture

### Data Flow

```
┌───────────────────────────────────────────────────────┐
│  Request arrives                                      │
│                                                       │
│  TimezoneActivationMiddleware                         │
│  ├── resolve_for_user_with_origin("USER_TIMEZONE")   │
│  │   └── user pref > site default > boot-frozen TZ   │
│  ├── resolve_for_user_with_origin("USER_FORMATTING_  │
│  │   LOCALE")                                         │
│  │   └── user pref > site default > boot-frozen TZ   │
│  ├── timezone.activate(timezone_value)                │
│  └── request._formatting_locale = locale_value        │
│                                                       │
│  View / Template                                      │
│  └── date_time_presentation_for_request(request)     │
│      └── reads get_current_timezone() +               │
│          request._formatting_locale                    │
│                                                       │
│  DateTimePresentation                                 │
│  ├── .format(datetime, style) uses active tz          │
│  └── .to_client_config() emits versioned JSON         │
│      └── locale + time_zone → browser contract        │
└───────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Dedicated middleware** (`common/middleware.py`) — clean separation of
   concerns. The middleware runs after
   `AuthenticationMiddleware` so `request.user` is available.

2. **`formats.override()` is NOT used in the middleware.** Instead, the
   resolved locale is stored on `request._formatting_locale` and
   `date_time_presentation_for_request` reads it. This avoids scoping
   `formats.override()` to the wrong scope and keeps the middleware lightweight.

3. **`zoneinfo.ZoneInfo` for validation** — no external dependencies. Invalid
   zones raise `ZoneInfoNotFoundError` and are rejected at write time.

4. **Hardcoded locale registry** — a finite `FORMATTING_LOCALE_CHOICES` tuple
   in `settings_registry.py`. Predictable, testable, no system dependency.

5. **Searchable select for timezone** — ~400 IANA zones are too many for a
   plain `<select>`. Uses the existing `SearchSelect` custom element with
   lazy loading via an API endpoint.

6. **`DateTimePresentation` signature unchanged** — it reads from Django's
   per-request timezone/locale (set by middleware), not from a new parameter.
   Backward-compatible.

7. **`_day_periods_for_locale` uses `formats.override`, not `translation.override`**
   (fix from Stage 6): the existing code used `from django.utils.translation
   import override`, which affects gettext lookups and could leak into
   application copy rendering. Stage 6.5 fixes this to use
   `from django.utils.formats import override as formats_override`, which only
   affects date/time formatting paths. This is a **pre-existing bug fix**
   included in this stage.

## Data Model

### UserPreferences

Two new nullable columns:

| Field | Type | Nullable | Default | Description |
|-------|------|----------|---------|-------------|
| `timezone` | CharField(max_length=100) | Yes | `None` | IANA timezone name |
| `formatting_locale` | CharField(max_length=20) | Yes | `None` | Locale code (e.g. `cs`, `en-US`) |

Both map to `USER_PREFERENCE_FIELD_BY_KEY`:
```python
USER_PREFERENCE_FIELD_BY_KEY = {
    ...
    "USER_TIMEZONE": "timezone",
    "USER_FORMATTING_LOCALE": "formatting_locale",
}
```

`None` means "use site/default" — the resolver falls through to the site
default (for locale) or the boot-frozen `settings.TIME_ZONE` (for timezone).

### Settings Registry

Three new `SettingDefinition` entries:

```python
SettingDefinition(
    "USER_TIMEZONE",
    scope=SettingScope.USER,
    apply_timing=ApplyTiming.LIVE,
    label="Time zone",
    help_text="Timezone used for wall-clock display and datetime form interpretation.",
    default_factory=lambda: settings.TIME_ZONE,
    validator=_validate_timezone,
    widget="timezone",
)

SettingDefinition(
    "USER_FORMATTING_LOCALE",
    scope=SettingScope.USER,
    apply_timing=ApplyTiming.LIVE,
    label="Formatting locale",
    help_text="Locale used for month/weekday names in date display.",
    default_factory=_default_formatting_locale,
    validator=_validate_formatting_locale,
    widget="select",
)

SettingDefinition(
    "DEFAULT_FORMATTING_LOCALE",
    scope=SettingScope.SITE,
    apply_timing=ApplyTiming.LIVE,
    label="Default formatting locale",
    help_text="Formatting locale used when no per-user preference is set.",
    default_factory=lambda: settings.LANGUAGE_CODE,
    validator=_validate_formatting_locale,
    widget="select",
    superuser_only=True,
)
```

#### `_default_formatting_locale` factory

The `USER_FORMATTING_LOCALE` default factory resolves through the site-level
`DEFAULT_FORMATTING_LOCALE` setting, not directly to `settings.LANGUAGE_CODE`.
This ensures that if an admin sets `DEFAULT_FORMATTING_LOCALE=cs`, all users
without a personal override inherit `cs`:

```python
def _default_formatting_locale() -> str:
    """Resolve the effective site default for formatting locale.

    Reads the ``DEFAULT_FORMATTING_LOCALE`` site setting from the DB layer
    (or the cached snapshot); if no site override exists, falls back to
    ``settings.LANGUAGE_CODE`` (the boot-frozen default).
    """
    from timetracker.settings_resolver import resolve_with_origin

    result = resolve_with_origin("DEFAULT_FORMATTING_LOCALE")
    if isinstance(result.value, str):
        return result.value
    return settings.LANGUAGE_CODE
```

### Formatting Locale Registry

A finite tuple of supported locales:

```python
FORMATTING_LOCALE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("cs", "Čeština"),
    ("en-US", "English (US)"),
    ("en-GB", "English (UK)"),
    ("de-AT", "Deutsch (Österreich)"),
    ("de-DE", "Deutsch (Deutschland)"),
    ("pl-PL", "Polski"),
    ("sk-SK", "Slovenčina"),
)
```

## Middleware

### `common/middleware.py` — `TimezoneActivationMiddleware`

```python
class TimezoneActivationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        if user is not None and user.is_authenticated:
            tz_result = resolve_for_user_with_origin(user, "USER_TIMEZONE")
            locale_result = resolve_for_user_with_origin(user, "USER_FORMATTING_LOCALE")

            if isinstance(tz_result.value, str):
                activate(tz_result.value)

            if isinstance(locale_result.value, str):
                request._formatting_locale = locale_result.value
        else:
            locale_result = resolve_with_origin("USER_FORMATTING_LOCALE")
            if isinstance(locale_result.value, str):
                request._formatting_locale = locale_result.value

        return self.get_response(request)
```

### Middleware placement

```python
MIDDLEWARE = [
    ...
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "common.middleware.TimezoneActivationMiddleware",  # ← after auth
    ...
]
```

### Middleware ordering notes

- Placed **after** `AuthenticationMiddleware` so `request.user` is available.
- Placed **before** any view or template-rendering middleware that reads
  `get_current_timezone()` or `get_language()`, so the activated timezone and
  locale are visible to downstream processing.
- `timezone.activate()` is a no-op if the timezone is already active (e.g.
  `"UTC"` when the boot-time `TIME_ZONE` is `"UTC"`), so calling it unconditionally
  when a resolved value is a `str` is safe.
- The middleware runs in every request, including `django_q` worker tasks that
  have no `request.user` and no `request` object. `django_q` tasks are not
  affected because they don't go through the WSGI middleware chain. For
  completeness, any task that needs a specific timezone should call
  `timezone.activate()` explicitly before running.

### Anonymous user resolution

Anonymous users get the **site default** formatting locale (not the code default).
The resolver chain for `USER_FORMATTING_LOCALE` with an anonymous user is:
`resolve_with_origin("USER_FORMATTING_LOCALE")` → no user layer → site DB
(`DEFAULT_FORMATTING_LOCALE`) → code default (`settings.LANGUAGE_CODE`).

## DateTimePresentation Wiring

### Python (`common/date_time_presentation.py`)

`date_time_presentation_for_request` already reads `get_current_timezone()`
which is set by the middleware. No changes needed for timezone.

For locale, add a check for `request._formatting_locale`:

```python
def date_time_presentation_for_request(request: HttpRequest) -> DateTimePresentation:
    cached = getattr(request, _REQUEST_CACHE_ATTRIBUTE, None)
    if isinstance(cached, DateTimePresentation):
        return cached

    active_timezone = django_timezone.get_current_timezone()
    zone = (
        active_timezone
        if isinstance(active_timezone, ZoneInfo)
        else ZoneInfo(django_timezone.get_current_timezone_name())
    )

    # Use middleware-provided locale if present, else fall back to Django's
    # active language or LANGUAGE_CODE.
    locale = getattr(request, "_formatting_locale", None)
    if not locale:
        locale = get_language() or settings.LANGUAGE_CODE

    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale=locale,
        timezone=zone,
    )
    setattr(request, _REQUEST_CACHE_ATTRIBUTE, presentation)
    return presentation
```

### `_day_periods_for_locale` fix (Stage 6 bug)

The existing code uses `from django.utils.translation import override`, which
affects gettext lookups. Fix to use `formats.override`:

```python
from django.utils.formats import override as formats_override

@cache
def _day_periods_for_locale(locale: str) -> DayPeriodsConfig:
    with formats_override(locale):  # ← was translation.override
        return {
            "am": date_format(datetime(2000, 1, 1, 0), "A"),
            "pm": date_format(datetime(2000, 1, 1, 12), "A"),
        }
```

The `@cache` decorator is acceptable here: it caches AM/PM labels per locale
across requests. If the server restarts the cache clears. A user changing their
formatting locale would produce the correct AM/PM labels on first call after the
change. This is not a correctness issue — the cache is keyed by locale, not by
request.

### TypeScript (`ts/date-time-presentation.ts`)

No changes needed. The `to_client_config()` method already serializes `locale`
and `time_zone` from the `DateTimePresentation` into the versioned JSON contract.
The browser receives the correct values from the server-rendered HTML.

## `datetime-local` Form Interpretation

Django's `DateTimeInput` widget uses `django.utils.timezone.get_current_timezone()`
to parse and display `datetime-local` input values. Since `timezone.activate()`
sets `django.utils.timezone._active` (a thread-local), the activated per-user
timezone is automatically picked up by the widget.

**This is the correct behavior** — `datetime-local` form submissions are
interpreted in the user's active timezone, as required by the issue.

No additional code is needed. The test suite must verify:
- A `datetime-local` input submitted at a DST boundary is interpreted in the
  user's selected timezone, not the boot-frozen `TIME_ZONE`.
- A user with `America/New_York` submitting `2026-03-08T02:30` (a nonexistent
  time during spring-forward) surfaces a Django validation error rather than
  being silently coerced.

## Settings Form Controls

### `games/views/settings.py` — `UserSettingsForm`

Two new fields:

```python
timezone = forms.ChoiceField(
    required=False,
    choices=IANATimezoneChoices,
    widget=SearchSelectWidget,  # custom element, lazy-loaded
)
formatting_locale = forms.ChoiceField(
    required=False,
    choices=FORMATTING_LOCALE_CHOICES,
    widget=forms.Select(attrs={"class": "..."}),
)
```

Both follow the existing live-save + "Use site default" pattern:
- Empty selection = use site default (shows default label in parentheses)
- On submit: `set_user_preference(user, key, value)` with validation
- Optimistic PATCH + rollback on error
- Cross-device convergence via the user snapshot cache

### Timezone dropdown — `IANATimezoneChoices`

The timezone field uses a searchable select with lazy-loaded options.
`IANATimezoneChoices` is a callable class that builds choices on first call:

```python
class IANATimezoneChoices:
    """Iterable of (value, label) pairs from the system's IANA tzdata."""

    _cache: list[tuple[str, str]] | None = None

    @classmethod
    def get(cls) -> list[tuple[str, str]]:
        if cls._cache is None:
            cls._cache = sorted(
                (tz, tz)
                for tz in zoneinfo.available_timezones()
                if zoneinfo.ZoneInfo(tz) is not None
            )
        return cls._cache
```

This lazily populates from `zoneinfo.available_timezones()` on first access,
providing ~400+ options. The `SearchSelect` custom element filters them
client-side.

### Timezone API endpoint

For the searchable select, the `SearchSelect` custom element needs an API
endpoint to load timezone choices. An existing endpoint may already serve this
purpose; if not, add:

**`/api/1.0.0/timezones/`** (GET, no auth required)

Response:
```json
{
  "choices": [
    {"value": "America/New_York", "label": "America/New_York"},
    {"value": "America/Chicago", "label": "America/Chicago"},
    ...
  ]
}
```

The endpoint returns the full IANA zone list as a JSON array. It is
**unauthenticated** because timezone names are public data (not user-specific).
The response is small (~10 KB) and can be cached by the browser.

### Formatting locale dropdown

A regular `<select>` with `FORMATTING_LOCALE_CHOICES`. Small enough for a
plain dropdown.

## Validation

### Timezone

```python
def _validate_timezone(value: object) -> str:
    text = str(value).strip()
    if not text:
        raise ValidationError("Timezone must be a valid IANA zone name.")
    try:
        ZoneInfo(text)
    except ZoneInfoNotFoundError:
        raise ValidationError(f"'{text}' is not a valid IANA timezone.")
    return text
```

### Formatting Locale

```python
def _validate_formatting_locale(value: object) -> str | None:
    if value is None:
        return None  # ← was returning "" (empty string), which is a valid stored value
    text = str(value).strip()
    if text not in _FORMATTING_LOCALE_VALUES:
        choices = ", ".join(c[0] for c in FORMATTING_LOCALE_CHOICES)
        raise ValidationError(f"Must be one of: {choices}.")
    return text
```

The validator returns `None` for `None` input (clearing the field back to unset)
instead of `""` (empty string), which would be stored as a valid formatting
locale.

## Error Handling

- **Invalid timezone/locale at write time**: `set_user_preference` raises
  `ValidationError` → PATCH returns 400 → frontend shows toast with error
  → value remains unchanged (rollback).
- **Poisoned DB row at read time**: `resolve_for_user_with_origin` catches
  `ValidationError`/`ValueError`/`TypeError` in the normalize path → logs
  error → falls through to site/default → request continues with defaults.
- **`ZoneInfoNotFoundError` at middleware time**: The middleware only calls
  `activate()` if the resolved value is a `str`. If validation caught a bad
  value at write time, it would never be stored. If a DB row was manually
  corrupted, the `resolve_for_user_with_origin` normalize path catches it.
- **`datetime-local` DST edge cases**: Django's `DateTimeInput` raises
  `ValidationError` for nonexistent wall times (e.g. `02:30` during spring-forward
  in `America/New_York`). The form renders the error message inline; no additional
  handling is needed.

## Testing

### Unit tests

| Test | Location |
|------|----------|
| Middleware: authenticated user with timezone set | `tests/test_middleware_timezone.py` |
| Middleware: anonymous user | `tests/test_middleware_timezone.py` |
| Middleware: invalid/poisoned timezone in DB | `tests/test_middleware_timezone.py` |
| Middleware: formatting locale override | `tests/test_middleware_timezone.py` |
| Registry: `_validate_timezone` valid/invalid | `tests/test_settings_registry.py` |
| Registry: `_validate_formatting_locale` valid/invalid | `tests/test_settings_registry.py` |
| Registry: `USER_TIMEZONE` default factory | `tests/test_settings_registry.py` |
| Registry: `DEFAULT_FORMATTING_LOCALE` scope=SITE | `tests/test_settings_registry.py` |
| Registry: `_default_formatting_locale` respects site setting | `tests/test_settings_registry.py` |
| `set_user_preference` timezone/locale valid/invalid | `tests/test_settings_resolver.py` |
| `resolve_for_user_with_origin` fallback chain | `tests/test_settings_resolver.py` |
| `date_time_presentation_for_request` with middleware locale | `tests/test_date_time_presentation.py` |
| `DateTimePresentation.format` with alternate locale | `tests/test_date_time_presentation.py` |
| `DateTimePresentation.to_client_config` locale+tz | `tests/test_date_time_presentation.py` |
| `_day_periods_for_locale` uses formats.override, not translation.override | `tests/test_date_time_presentation.py` |
| `datetime-local` form interpretation in user timezone | `tests/test_datetime_local_form.py` |
| `datetime-local` DST spring-forward raises validation error | `tests/test_datetime_local_form.py` |

### E2E tests

| Test | Viewport |
|------|----------|
| Set timezone via settings, see wall-clock update | Desktop |
| Clear timezone → falls back to site default | Desktop |
| Set formatting locale → month/weekday names update | Desktop |
| Clear formatting locale → falls back to site default | Desktop |
| Invalid timezone → error toast, value unchanged | Desktop |
| Set timezone on mobile → responsive settings form | Mobile |
| Set formatting locale on mobile | Mobile |
| Fresh browser → anonymous uses site defaults | Desktop + Mobile |
| Two accounts with different settings → isolated | Desktop |
| `datetime-local` form interprets input in user timezone | Desktop |
| `datetime-local` DST spring-forward shows validation error | Desktop |

## Migration Path

1. Add `timezone` and `formatting_locale` columns to `UserPreferences` (nullable, default `None`)
2. Add `DEFAULT_FORMATTING_LOCALE` **registry entry** (the `SiteSetting` DB table already exists; no migration needed for the table)
3. Add `TimezoneActivationMiddleware` to `MIDDLEWARE` list
4. Update `date_time_presentation_for_request` to read `request._formatting_locale`
5. Fix `_day_periods_for_locale` to use `formats.override` instead of `translation.override`
6. Update settings form to include new controls
7. Add `FORMATTING_LOCALE_CHOICES` to registry
8. Add validators and registry entries
9. Add timezone API endpoint
10. Add tests (unit + e2e)

## Out of Scope

- Browser geolocation or automatic timezone detection
- UI translation (formatting locale ≠ `LANGUAGE_CODE` for gettext)
- Changing the infrastructure `TZ` value at runtime
- Per-user date/time format profile (Stage 7)
- Per-user hour cycle (12h vs 24h) — follows from formatting locale choice

## Dependencies

- **Depends on**: Stages 1, 2, 3, 4, Stage 6 (#388)
- **Blocks**: Stage 7 (#389)
