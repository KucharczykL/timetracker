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
│  │   └── user pref > site default > LANGUAGE_CODE    │
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

2. **`timezone.activate()` + `formats.override()` — no, `formats.override()`**
   is NOT used in the middleware. Instead, the resolved locale is stored on
   `request._formatting_locale` and `date_time_presentation_for_request` reads
   it. This avoids scoping `formats.override()` to the wrong scope and keeps
   the middleware lightweight.

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
    default_factory=lambda: settings.LANGUAGE_CODE,
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

Placed after `AuthenticationMiddleware` in `MIDDLEWARE`.

### Middleware placement

```python
MIDDLEWARE = [
    ...
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "common.middleware.TimezoneActivationMiddleware",  # ← after auth
    ...
]
```

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

### TypeScript (`ts/date-time-presentation.ts`)

No changes needed. The `to_client_config()` method already serializes `locale`
and `time_zone` from the `DateTimePresentation` into the versioned JSON contract.
The browser receives the correct values from the server-rendered HTML.

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

### Timezone dropdown

The timezone field uses a searchable select with lazy-loaded options from an
API endpoint (`/api/1.0.0/timezones/`) that returns the full IANA zone list.
This avoids a 400+ option `<select>` and provides client-side filtering.

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
def _validate_formatting_locale(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text not in _FORMATTING_LOCALE_VALUES:
        choices = ", ".join(c[0] for c in FORMATTING_LOCALE_CHOICES)
        raise ValidationError(f"Must be one of: {choices}.")
    return text
```

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
| `set_user_preference` timezone/locale valid/invalid | `tests/test_settings_resolver.py` |
| `resolve_for_user_with_origin` fallback chain | `tests/test_settings_resolver.py` |
| `date_time_presentation_for_request` with middleware locale | `tests/test_date_time_presentation.py` |
| `DateTimePresentation.format` with alternate locale | `tests/test_date_time_presentation.py` |
| `DateTimePresentation.to_client_config` locale+tz | `tests/test_date_time_presentation.py` |

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

## Migration Path

1. Add `timezone` and `formatting_locale` columns to `UserPreferences` (nullable, default `None`)
2. Add `DEFAULT_FORMATTING_LOCALE` to `SiteSetting` (nullable, default `None` — falls back to `settings.LANGUAGE_CODE`)
3. Add `TimezoneActivationMiddleware` to `MIDDLEWARE` list
4. Update `date_time_presentation_for_request` to read `request._formatting_locale`
5. Update settings form to include new controls
6. Add `FORMATTING_LOCALE_CHOICES` to registry
7. Add validators and registry entries
8. Add tests (unit + e2e)

## Out of Scope

- Browser geolocation or automatic timezone detection
- UI translation (formatting locale ≠ `LANGUAGE_CODE` for gettext)
- Changing the infrastructure `TZ` value at runtime
- Per-user date/time format profile (Stage 7)
- Per-user hour cycle (12h vs 24h) — follows from formatting locale choice

## Dependencies

- **Depends on**: Stages 1, 2, 3, 4, Stage 6 (#388)
- **Blocks**: Stage 7 (#389)
