# Per-Timestamp Timezone Implementation Plan (issue #540)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store a nullable IANA zone id per `Session` timestamp so a session logged abroad renders in the zone it was played in (with a visible zone label), while `NULL` keeps today's "assume the display zone" behaviour.

**Architecture:** Two nullable `CharField`s on `Session` (`timestamp_start_timezone`, `timestamp_end_timezone`); capture defaults from the browser's zone (`Intl.DateTimeFormat().resolvedOptions().timeZone`) — client-side in the session form's new `time-zone-row` element and in `session-actions.ts`'s finish/reset PATCH; a new `SESSION_TIME_ZONE_DISPLAY` account preference ("account" vs "own") flows through `DateTimePresentation` to both the server renderer (`session_time_range`) and the client row-rebuild (`formatSessionTimeRange`). The zone *label* ("JST") is computed server-side only — once in `games/formatting.py`, shipped to the client as data on `SessionOut` — so a server-rendered row and a client-rebuilt row can never word it differently. A tiny `/api/timezones/search` endpoint feeds the picker.

**Tech Stack:** Django 6 / django-ninja, pure-Python component system (`common/components`), TypeScript custom elements compiled by `tsc`, pytest + vitest + Playwright e2e.

## Global Constraints

- **Verification gate is `make check`** (lint + format-check + mypy + ts-check + vitest + full pytest **including `e2e/`**). Iterate with `make check-fast`; the gate is never a subset.
- Drive everything through `make` (`make test ARGS="..."`, `make ts`, `make gen-element-types`); never raw `uv run` / `pnpm` outside the Makefile.
- **Never write to `GeneratedField`s** (`duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish`).
- Full-page responses use `render_page()`; UI is built from `common.components` node builders in htpy form (`Div(class_="x")[child]`), never raw HTML strings or Django templates.
- New interactive behavior is a **custom element**: semantic tag + `ts/elements/<tag>.ts`, one `TypedDict` registered via `register_element(...)` in `common/components/custom_elements.py`, then `make gen-element-types`. No new inline Alpine or f-string JS.
- JS-bearing components declare `Media` (`.with_media(Media(js=(...,)))`); `Page()` collects and emits it. Import-bearing dist files must load as module scripts (Media `js` entries render as `ModuleScript`).
- New settings go through the settings-registry pattern in `timetracker/settings_registry.py` (per-user preference resolved via `timetracker/settings_resolver.py`), never bare `os.environ`.
- Name compound types (`TypedDict`/`NamedTuple`) and primitive roles (PEP 695 `type` aliases) explicitly.
- Complete, unabbreviated variable names (`element` not `el`, `option` not `o`).
- Comments explain present intent only — no issue/PR references except forward TODOs.
- Run `make ts` after editing any `.ts` file so e2e sees fresh `dist/` output. Never run e2e while `make dev` is up.
- Step 0 of execution: rebase the working branch onto `origin/main` before any edits.

## Design decisions locked in (do not re-litigate)

1. **Row UX — one always-visible control, no hidden/reveal mechanic:** each per-timestamp "Time zone" row is exactly **one** control: the ghost `ComboboxDropdown` trigger ("Start time zone: Europe/Prague (display zone)"), rendered **always visible**. There is no separate toggle button and no `hidden` wrapper — the only `hidden` thing in the row is the `<input type="hidden">` that carries the submitted value. Rationale: two adjacent controls both named after the same field is a double screen-reader announcement (a defect this widget family already produced and fixed once), and a toggle whose visible text ("Zone") differs from its accessible name ("Start time zone options") violates WCAG 2.5.3. One always-visible trigger is reachable in every case by construction — including the one a mismatch check can never detect (editing a session retroactively from the zone it was played in, where the stored and browser zones agree but the user still wants to check or correct it).
   **Mismatch signal:** when post-load JS finds the browser's detected zone disagreeing with the record's effective zone (stored zone, or the account display zone for `NULL`), it adds a visual-emphasis class (`font-semibold`) to the trigger. It does **not** auto-open the dropdown panel: opening a dialog with no user interaction on page load would steal focus and interrupt a screen-reader user on every page whose zones happen to differ. Emphasis is the whole signal; the value the user needs is already in the trigger's own label.
2. **Preference storage:** a new account-level `SESSION_TIME_ZONE_DISPLAY` setting in `timetracker/settings_registry.py`, persisted per user via the existing `UserPreferences.extra_preferences` JSON bag (the `DEFAULT_PAGE_SIZE` precedent — no new column, no migration for the preference).
3. **Scope:** one plan, one phase — model fields + capture + API endpoint + editing UI + display + preference.
4. **Model fields carry no `choices`:** the valid set is the running interpreter's tzdata (validated at the form and API edges), so tzdata updates never churn migrations. `NULL` means "assume the display zone"; no backfill.
5. **`GameStatusChange` gets no zone fields:** it is an audit record written server-side on status transitions, not an attended event with a meaningful browser zone. Its `timestamp` keeps rendering in the display zone.
6. **`games/fixtures/sample.yaml.gz` / `anonymize_sample`:** no change. Zone ids are not PII. The anonymizer offsets session timestamps by whole days (`timedelta(days=...)`), which keeps a timestamp/zone pairing sensible (wall-clock drifts at most one DST hour), and Django's serializer picks the new nullable fields up automatically (`NULL` on all existing prod rows). This is a deliberate no-op, not an omission.

## File Structure

| File | Responsibility |
|---|---|
| `games/models.py` | `Session.timestamp_start_timezone` / `timestamp_end_timezone` fields |
| `games/migrations/0033_*.py` | generated migration for the two fields |
| `timetracker/settings_registry.py` | `SESSION_TIME_ZONE_DISPLAY` choices, validator, `SettingDefinition` |
| `games/api.py` | `/api/timezones/search`; `SessionOut`/`SessionUpdate` zone fields + server-computed zone labels + validation |
| `common/date_time_presentation.py` | `session_time_zone_display` on `DateTimePresentation` + client contract |
| `games/formatting.py` | own-zone rendering + the one `zone_label()` both renderers use, in `session_time_range` |
| `ts/date-time-presentation.ts` | contract parse + zone-aware `formatSessionTimeRange` (projects wall clocks, appends server-supplied labels) |
| `ts/session-row.ts` | pass zone names + server labels through on client row rebuild |
| `ts/elements/session-actions.ts` | send browser zone with finish/reset PATCH |
| `common/components/custom_elements.py` | `TimeZoneRowProps` + `register_element("time-zone-row", ...)` |
| `common/components/time_zone_row.py` | `TimeZoneRow` component (hidden input + one always-visible ghost ComboboxDropdown hosting a panel SearchSelect) |
| `ts/elements/time-zone-row.ts` | capture default, emphasis class on mismatch, mirror picker → hidden input (incl. clear-to-NULL) |
| `common/components/search_select.py` | `SearchSelect(panel=True)` panel-hosted personality |
| `common/components/primitives.py` | `FormFields(..., embedded=...)` host-row embedding |
| `games/forms.py` | `TimeZoneRowWidget`, SessionForm zone fields, `SESSION_TIMEZONE_EMBEDS` |
| `games/views/session.py` | pass `embedded=` field markup; clear zones on clone |
| `tests/`, `ts/**/*.test.ts`, `e2e/test_time_zone_row_e2e.py` | coverage per task |

---

### Task 1: Session model fields + migration + calculation regression

**Files:**
- Modify: `games/models.py` (Session, after `timestamp_end` around line 310)
- Create: `games/migrations/0033_*.py` (generated)
- Test: `tests/test_session_timezones.py`

**Interfaces:**
- Produces: `Session.timestamp_start_timezone: str | None`, `Session.timestamp_end_timezone: str | None` — `CharField(max_length=64, null=True, blank=True, default=None)`, no `choices`. Every later task reads these exact names.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session_timezones.py`:

```python
"""Per-timestamp zone fields on Session: NULL semantics and the guarantee
that a stored zone never feeds back into duration or date-bucket math."""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone as django_timezone

from games.models import Game, GameStatusChange, Session

pytestmark = pytest.mark.django_db


def _make_session(game: Game, **overrides) -> Session:
    defaults = {
        "game": game,
        "timestamp_start": datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        "timestamp_end": datetime(2026, 7, 1, 14, 30, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Session.objects.create(**defaults)


def test_zone_fields_default_to_null(db):
    session = _make_session(Game.objects.create(name="Hades"))
    session.refresh_from_db()
    assert session.timestamp_start_timezone is None
    assert session.timestamp_end_timezone is None


def test_zone_fields_store_iana_names(db):
    session = _make_session(
        Game.objects.create(name="Hades"),
        timestamp_start_timezone="Asia/Tokyo",
        timestamp_end_timezone="Europe/Prague",
    )
    session.refresh_from_db()
    assert session.timestamp_start_timezone == "Asia/Tokyo"
    assert session.timestamp_end_timezone == "Europe/Prague"


def test_duration_calculated_ignores_stored_zones(db):
    """duration_calculated is instant arithmetic over UTC values; a stored
    zone must not change it (spec: 'Calculation — no change, verified')."""
    game = Game.objects.create(name="Hades")
    plain = _make_session(game)
    zoned = _make_session(
        game,
        timestamp_start_timezone="Asia/Tokyo",
        timestamp_end_timezone="Asia/Tokyo",
    )
    plain.refresh_from_db()
    zoned.refresh_from_db()
    assert plain.duration_calculated == timedelta(hours=2, minutes=30)
    assert zoned.duration_calculated == plain.duration_calculated


def test_date_bucketing_ignores_stored_zones(db):
    """__date bucketing resolves in the *active* timezone, never the
    session's own zone — a zoned row lands in the same bucket as its twin."""
    game = Game.objects.create(name="Hades")
    _make_session(game)
    _make_session(game, timestamp_start_timezone="Pacific/Kiritimati")
    with django_timezone.override("UTC"):
        bucketed = Session.objects.filter(
            timestamp_start__date=datetime(2026, 7, 1, tzinfo=UTC).date()
        )
        assert bucketed.count() == 2


def test_game_status_change_has_no_zone_fields(db):
    """Audit records are server-stamped, not attended events; the zone
    columns are deliberately Session-only."""
    field_names = {field.name for field in GameStatusChange._meta.get_fields()}
    assert "timestamp_start_timezone" not in field_names
    assert "timestamp_timezone" not in field_names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test ARGS="tests/test_session_timezones.py -x"`
Expected: FAIL — `TypeError: Session() got unexpected keyword arguments: 'timestamp_start_timezone'` (and the default test fails with `AttributeError`).

- [ ] **Step 3: Add the model fields**

In `games/models.py`, inside `class Session`, directly after the `timestamp_end` field declaration (before `duration_manual`):

```python
    # IANA zone id the timestamp was committed in. NULL means "assume the
    # account's display zone" — exactly the pre-existing behaviour, so old
    # rows need no backfill. No `choices`: the valid set is the running
    # interpreter's tzdata, validated at the form/API edge, so tzdata
    # updates never churn migrations.
    timestamp_start_timezone = models.CharField(
        max_length=64, null=True, blank=True, default=None
    )
    timestamp_end_timezone = models.CharField(
        max_length=64, null=True, blank=True, default=None
    )
```

- [ ] **Step 4: Generate and apply the migration**

Run: `make makemigrations`
Expected: creates `games/migrations/0033_session_timestamp_end_timezone_and_more.py` (name may vary; it must depend on `0032_userpreferences_datetime_format`).
Run: `make migrate`
Expected: `Applying games.0033_... OK`

- [ ] **Step 5: Run tests to verify they pass**

Run: `make test ARGS="tests/test_session_timezones.py -x"`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add games/models.py games/migrations tests/test_session_timezones.py
git commit -m "feat: nullable per-timestamp IANA zone fields on Session"
```

---

### Task 2: SESSION_TIME_ZONE_DISPLAY account preference

**Files:**
- Modify: `timetracker/settings_registry.py`
- Test: `tests/test_session_timezone_preference.py`

**Interfaces:**
- Produces: setting key `"SESSION_TIME_ZONE_DISPLAY"` with values `"account"` (default) / `"own"`; module constant `SESSION_TIME_ZONE_DISPLAY_CHOICES`. Resolved via the existing `resolve_str_for_user(user, "SESSION_TIME_ZONE_DISPLAY")`. Stored in the `UserPreferences.extra_preferences` bag (no column — the `DEFAULT_PAGE_SIZE` precedent), so **no migration**.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session_timezone_preference.py`:

```python
"""The SESSION_TIME_ZONE_DISPLAY per-user preference: registry entry,
default, persistence through the bag, and validation."""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from games.models import UserPreferences
from timetracker import settings_resolver
from timetracker.settings_commands import change_user_setting
from timetracker.settings_registry import (
    SETTINGS_REGISTRY,
    SettingScope,
    SettingWidget,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture(autouse=True)
def _clear_resolver_cache():
    settings_resolver.clear_cache()
    yield
    settings_resolver.clear_cache()


def test_setting_is_registered_as_a_user_select():
    definition = SETTINGS_REGISTRY["SESSION_TIME_ZONE_DISPLAY"]
    assert definition.scope is SettingScope.USER
    assert definition.widget is SettingWidget.SELECT
    assert definition.choices == (
        ("account", "My current time zone"),
        ("own", "The session's own time zone"),
    )


def test_default_resolves_to_account(user):
    assert (
        settings_resolver.resolve_str_for_user(user, "SESSION_TIME_ZONE_DISPLAY")
        == "account"
    )


def test_change_persists_own_through_the_bag(user):
    change_user_setting(user, "SESSION_TIME_ZONE_DISPLAY", "own")
    settings_resolver.clear_cache()
    assert (
        settings_resolver.resolve_str_for_user(user, "SESSION_TIME_ZONE_DISPLAY")
        == "own"
    )
    preferences = UserPreferences.objects.get(user=user)
    assert preferences.extra_preferences["SESSION_TIME_ZONE_DISPLAY"] == "own"


def test_invalid_value_is_rejected(user):
    with pytest.raises(ValidationError):
        change_user_setting(user, "SESSION_TIME_ZONE_DISPLAY", "browser")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test ARGS="tests/test_session_timezone_preference.py -x"`
Expected: FAIL — `KeyError: 'SESSION_TIME_ZONE_DISPLAY'`.

- [ ] **Step 3: Register the setting**

In `timetracker/settings_registry.py`, after `DISPLAY_TIME_ZONE_CHOICES` (line ~76):

```python
SESSION_TIME_ZONE_DISPLAY_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("account", "My current time zone"),
    ("own", "The session's own time zone"),
)
_SESSION_TIME_ZONE_DISPLAY_VALUES: Final[frozenset[str]] = frozenset(
    value for value, _label in SESSION_TIME_ZONE_DISPLAY_CHOICES
)
```

After `_validate_datetime_format` (line ~257):

```python
def _validate_session_time_zone_display(value: object) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else value
    if (
        not isinstance(normalized, str)
        or normalized not in _SESSION_TIME_ZONE_DISPLAY_VALUES
    ):
        raise ValidationError(
            f"Session time zone display must be one of account, own (got {value!r})."
        )
    return normalized
```

In `_build_registry`, directly after the `DISPLAY_TIME_ZONE` definition:

```python
(
    SettingDefinition(
        "SESSION_TIME_ZONE_DISPLAY",
        scope=SettingScope.USER,
        apply_timing=ApplyTiming.LIVE,
        label="Session time zone display",
        help_text=(
            "Show each session in your current time zone, or in the zone "
            "it was logged in (the zone is labelled when it differs)."
        ),
        default_factory=lambda: "account",
        validator=_validate_session_time_zone_display,
        widget=SettingWidget.SELECT,
        choices=SESSION_TIME_ZONE_DISPLAY_CHOICES,
        reload_after_save=True,
    ),
)
```

No column mapping is added to `USER_PREFERENCE_FIELD_BY_KEY` in `games/models.py` — the key deliberately resolves through `extra_preferences`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test ARGS="tests/test_session_timezone_preference.py -x"`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add timetracker/settings_registry.py tests/test_session_timezone_preference.py
git commit -m "feat: SESSION_TIME_ZONE_DISPLAY account preference (account vs own zone)"
```

---

### Task 3: /api/timezones/search endpoint

**Files:**
- Modify: `games/api.py`
- Test: `tests/test_timezone_search_api.py`

**Interfaces:**
- Produces: `GET /api/timezones/search?q=&limit=` returning `list[StringOption]` (`{"value": "Asia/Tokyo", "label": "Asia/Tokyo", "data": {}}`), same shape/auth as **`/api/platforms/groups`** (`games/api.py:183-189`) — the existing `list[StringOption]` feed with a *string* `value`. (`/api/games/search` is **not** the precedent: it returns `list[GameOption]`, whose `value` is an `int` pk.) Task 7's `SearchSelect` consumes it via `search_url`.
- The **browse-all** response (empty `q`) pins one extra first row, `{"value": "", "label": "Use account display zone", "data": {}}` — the only way back to `NULL` once a zone has been captured (every add-form session captures one, so without this row the form's `("", "Account display zone")` choice is validated-but-unreachable). A filtered `q` omits it: a search for "asia" is asking for zones, not for the clear action.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_timezone_search_api.py`:

```python
"""/api/timezones/search: the SearchSelect option feed for the per-timestamp
zone picker — the /api/platforms/groups list[StringOption] pattern over tzdata,
plus the pinned clear-to-NULL row on the browse-all response."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def auth_client(db):
    user = get_user_model().objects.create_user(username="tester", password="pw")
    client = Client()
    client.force_login(user)
    return client


def test_requires_auth():
    response = Client().get("/api/timezones/search")
    assert response.status_code == 401


def test_returns_zone_options_capped_at_limit(auth_client):
    response = auth_client.get("/api/timezones/search")
    assert response.status_code == 200
    options = response.json()
    assert len(options) == 10  # the default limit, clear row included
    assert options[0] == {"value": "", "label": "Use account display zone", "data": {}}
    zone_option = options[1]
    assert set(zone_option) == {"value", "label", "data"}
    assert zone_option["value"] == zone_option["label"]
    assert zone_option["data"] == {}


def test_query_filters_case_insensitively_and_omits_the_clear_row(auth_client):
    response = auth_client.get("/api/timezones/search", {"q": "tokyo", "limit": 50})
    values = [option["value"] for option in response.json()]
    assert values == ["Asia/Tokyo"]  # no "" row while filtering


def test_the_clear_row_is_the_way_back_to_null(auth_client):
    """Every add-form session captures a zone, so a ""-valued option is the
    only reachable route back to NULL ("assume the account display zone")."""
    response = auth_client.get("/api/timezones/search", {"limit": 3})
    options = response.json()
    assert options[0]["value"] == ""
    assert len(options) == 3
    assert all(option["value"] != "" for option in options[1:])


def test_results_are_sorted(auth_client):
    response = auth_client.get("/api/timezones/search", {"q": "Europe/P", "limit": 50})
    values = [option["value"] for option in response.json()]
    assert values == sorted(values)
    assert "Europe/Prague" in values
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test ARGS="tests/test_timezone_search_api.py -x"`
Expected: FAIL — 404s (`assert 404 == 401` on the first test).

- [ ] **Step 3: Add the endpoint**

In `games/api.py`, extend the existing `timetracker.settings_registry` import block with `DISPLAY_TIME_ZONE_CHOICES`, then after the `platform_router` endpoints (before `api.add_router("/playevent", ...)` or alongside the other small routers):

```python
timezone_router = Router()

# The pinned clear-to-NULL row: "" posts as the form's empty choice, which
# cleans to None ("assume the account display zone"). Browse-all only — a
# filtered query is asking for zones, not for the clear action.
_ACCOUNT_ZONE_OPTION: Final[dict[str, object]] = {
    "value": "",
    "label": "Use account display zone",
    "data": {},
}


@timezone_router.get("/search", response=list[StringOption])
def search_timezones(request, q: str = "", limit: int = 10):
    """IANA zone options for the session time-zone picker, shaped like
    /api/platforms/groups (the existing list[StringOption] feed) so the
    SearchSelect client needs nothing new. DISPLAY_TIME_ZONE_CHOICES is already
    the sorted tzdata list."""
    zone_names = [zone_name for zone_name, _label in DISPLAY_TIME_ZONE_CHOICES]
    if q:
        query = q.lower()
        matches = [name for name in zone_names if query in name.lower()]
        return [{"value": name, "label": name, "data": {}} for name in matches[:limit]]
    return [
        _ACCOUNT_ZONE_OPTION,
        *(
            {"value": name, "label": name, "data": {}}
            for name in zone_names[: max(limit - 1, 0)]
        ),
    ]
```

(`Final` comes from `typing`; extend the module's existing import if it is not there yet.)

And with the other `api.add_router` calls:

```python
api.add_router("/timezones", timezone_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test ARGS="tests/test_timezone_search_api.py -x"`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add games/api.py tests/test_timezone_search_api.py
git commit -m "feat: /api/timezones/search combobox feed over tzdata"
```

---

### Task 4: Presentation carries the preference; server display renders the session's own zone with a label

**Files:**
- Modify: `common/date_time_presentation.py`
- Modify: `games/formatting.py`
- Test: `tests/test_session_time_range_timezones.py`

**Interfaces:**
- Consumes: Task 1's `Session.timestamp_start_timezone`/`timestamp_end_timezone`; Task 2's `SESSION_TIME_ZONE_DISPLAY` key.
- Produces:
  - `type SessionTimeZoneDisplayMode = Literal["account", "own"]` in `common/date_time_presentation.py`.
  - `DateTimePresentation.session_time_zone_display: SessionTimeZoneDisplayMode = "account"` (defaulted, so every existing 3-positional-arg construction keeps working).
  - `DateTimePresentationConfig` gains key `"session_time_zone_display": SessionTimeZoneDisplayMode` (contract stays `version: 2`; the key is additive — Task 5 reads it optionally).
  - `session_time_range(session, presentation)` — unchanged signature; renders own-zone wall clocks plus a zone label (`tzname()`, e.g. "JST") whenever the effective zone differs from the account display zone. A labelled endpoint renders in the **full `"datetime"` style** (date + time), not `"time"`-only: an end that lands on the next calendar day in its own zone ("06:00 JST" after "20:00") is unreadable without its date.
  - `zone_label(value: datetime, zone: ZoneInfo) -> str` — **public** (not `_zone_label`): Task 6 imports it so the API ships the very same label string to the client. Computing the label once, server-side, is what stops the two renderers from disagreeing (Python's `tzname()` says "JST" where the browser's `Intl` `timeZoneName: "short"` says "GMT+9" for the same instant).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session_time_range_timezones.py`:

```python
"""session_time_range under SESSION_TIME_ZONE_DISPLAY: own-zone rendering,
zone labels, NULL fallback, and graceful handling of an unusable stored zone."""

from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.formatting import session_time_range
from games.models import Game, Session

pytestmark = pytest.mark.django_db

_ACCOUNT_PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("Europe/Prague")
)
_OWN_PRESENTATION = replace(_ACCOUNT_PRESENTATION, session_time_zone_display="own")

# 2026-07-01 12:00 UTC = 14:00 CEST = 21:00 JST.
_START = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
_END = datetime(2026, 7, 1, 13, 0, tzinfo=UTC)


def _session(**overrides) -> Session:
    defaults = {
        "game": Game.objects.create(name="Hades"),
        "timestamp_start": _START,
        "timestamp_end": _END,
    }
    defaults.update(overrides)
    return Session.objects.create(**defaults)


def test_null_zones_render_exactly_as_before():
    session = _session()
    assert session_time_range(session, _OWN_PRESENTATION) == session_time_range(
        session, _ACCOUNT_PRESENTATION
    )
    assert "14:00" in session_time_range(session, _ACCOUNT_PRESENTATION)


def test_account_preference_ignores_stored_zones():
    session = _session(
        timestamp_start_timezone="Asia/Tokyo",
        timestamp_end_timezone="Asia/Tokyo",
    )
    rendered = session_time_range(session, _ACCOUNT_PRESENTATION)
    assert "21:00" not in rendered
    assert "JST" not in rendered


def test_own_preference_renders_zone_and_label():
    session = _session(
        timestamp_start_timezone="Asia/Tokyo",
        timestamp_end_timezone="Asia/Tokyo",
    )
    rendered = session_time_range(session, _OWN_PRESENTATION)
    assert "21:00 JST" in rendered
    assert "22:00 JST" in rendered


def test_a_labelled_end_carries_its_own_date_across_the_date_line():
    """A labelled endpoint renders date + time, not time alone: 21:00 UTC is
    2026-07-02 06:00 in Tokyo, and "06:00 JST" after a 14:00 start reads as
    the same evening unless the date is there."""
    session = _session(
        timestamp_end=datetime(2026, 7, 1, 21, 0, tzinfo=UTC),
        timestamp_end_timezone="Asia/Tokyo",
    )
    rendered = session_time_range(session, _OWN_PRESENTATION)
    assert rendered == "2026-07-01 14:00 — 2026-07-02 06:00 JST"


def test_own_preference_matching_zone_gets_no_label():
    """A label only where the sorted list would otherwise lie — a session in
    the account's own zone reads exactly as before."""
    session = _session(
        timestamp_start_timezone="Europe/Prague",
        timestamp_end_timezone="Europe/Prague",
    )
    rendered = session_time_range(session, _OWN_PRESENTATION)
    assert rendered == session_time_range(_session(), _ACCOUNT_PRESENTATION)


def test_flight_renders_each_endpoint_in_its_own_zone():
    session = _session(
        timestamp_start_timezone="Europe/Prague",
        timestamp_end_timezone="Asia/Tokyo",
    )
    rendered = session_time_range(session, _OWN_PRESENTATION)
    assert "14:00" in rendered  # start: CEST wall clock, no label (matches account)
    assert "22:00 JST" in rendered  # end: Tokyo wall clock, labelled


def test_unusable_stored_zone_falls_back_to_the_display_zone():
    session = _session(timestamp_start_timezone="Not/AZone")
    assert session_time_range(session, _OWN_PRESENTATION) == session_time_range(
        _session(), _ACCOUNT_PRESENTATION
    )


def test_open_session_labels_its_start():
    session = _session(timestamp_end=None, timestamp_start_timezone="Asia/Tokyo")
    rendered = session_time_range(session, _OWN_PRESENTATION)
    assert rendered.endswith("21:00 JST")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test ARGS="tests/test_session_time_range_timezones.py -x"`
Expected: FAIL — `TypeError: replace() got an unexpected keyword argument 'session_time_zone_display'`.

- [ ] **Step 3: Extend DateTimePresentation**

In `common/date_time_presentation.py`:

1. Add to the imports: `from typing import Literal` (extend the existing `typing` import if present).
2. Near the other module-level aliases:

```python
type SessionTimeZoneDisplayMode = Literal["account", "own"]  # e.g. "own"
```

3. Add to the `DateTimePresentationConfig` TypedDict (line ~114):

```python
    session_time_zone_display: SessionTimeZoneDisplayMode
```

4. Add a defaulted field to the frozen dataclass, after `timezone: ZoneInfo`:

```python
    session_time_zone_display: SessionTimeZoneDisplayMode = "account"
```

5. In `to_client_config()`, add to the returned dict (after `"time_zone"`):

```python
            "session_time_zone_display": self.session_time_zone_display,
```

6. In `date_time_presentation_for_request()`, resolve the preference and pass it (any non-"own" resolve degrades to the default rather than crashing a page on a poisoned bag value):

```python
    display_mode_raw = resolve_str_for_user(
        getattr(request, "user", None), "SESSION_TIME_ZONE_DISPLAY"
    )
    presentation = DateTimePresentation(
        profile=date_time_format_profile(profile_id),
        locale=locale
        if isinstance(locale, str)
        else get_language() or settings.LANGUAGE_CODE,
        timezone=zone,
        session_time_zone_display="own" if display_mode_raw == "own" else "account",
    )
```

- [ ] **Step 4: Rewrite session_time_range**

Replace the whole of `games/formatting.py`:

```python
"""Display formatting for game-domain models, neutral of the view layer so any
view can import it without a view→view dependency."""

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common.date_time_presentation import DateTimePresentation, DateTimeStyle
from games.models import Session


def _presentation_in_zone(
    presentation: DateTimePresentation, zone_name: str | None
) -> DateTimePresentation | None:
    """``presentation`` re-aimed at a session's own zone, or ``None`` when the
    stored name is missing or unusable (e.g. removed from tzdata) — the caller
    falls back to the account zone rather than crashing a list page."""
    if not zone_name:
        return None
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError, ValueError:
        return None
    return replace(presentation, timezone=zone)


def zone_label(value: datetime, zone: ZoneInfo) -> str:
    """Short zone label for display, e.g. "JST" or "+09".

    Public because the session API ships this exact string to the client
    (``games/api.py``) instead of letting the browser recompute it — Intl's
    ``timeZoneName: "short"`` says "GMT+9" where this says "JST", and a row
    must read the same whether the server rendered it or the client rebuilt it.
    """
    return value.astimezone(zone).tzname() or zone.key


def _endpoint_text(
    value: datetime,
    style: DateTimeStyle,
    endpoint_presentation: DateTimePresentation,
    account_presentation: DateTimePresentation,
) -> str:
    labelled = endpoint_presentation.timezone.key != account_presentation.timezone.key
    # A labelled endpoint always carries its date: projecting into another zone
    # can move the wall clock across midnight, and "06:00 JST" after a 20:00
    # start reads as the same evening unless the date is spelled out.
    text = endpoint_presentation.format(value, "datetime" if labelled else style)
    if labelled:
        # Without the label a sorted list lies: a 21:00 session can be
        # genuinely earlier than the 14:00 one after it.
        text = f"{text} {zone_label(value, endpoint_presentation.timezone)}"
    return text


def session_time_range(session: Session, presentation: DateTimePresentation) -> str:
    """The session's start (— end) timestamp string. Shared by every table that
    renders a session, so the formatting cannot drift between them. Under the
    "own" display preference each endpoint renders in its stored zone, labelled
    whenever that differs from the account's display zone."""
    start_presentation = presentation
    end_presentation = presentation
    if presentation.session_time_zone_display == "own":
        start_presentation = (
            _presentation_in_zone(presentation, session.timestamp_start_timezone)
            or presentation
        )
        end_presentation = (
            _presentation_in_zone(presentation, session.timestamp_end_timezone)
            or presentation
        )
    start = _endpoint_text(
        session.timestamp_start, "datetime", start_presentation, presentation
    )
    if session.timestamp_end is None:
        return start
    end = _endpoint_text(session.timestamp_end, "time", end_presentation, presentation)
    return f"{start} — {end}"
```

(`DateTimeStyle` is a real exported alias in `common/date_time_presentation.py` — `type DateTimeStyle = Literal["date", "time", "datetime", "month", "month_year"]` — so `style` is typed, not `# type: ignore`d.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `make test ARGS="tests/test_session_time_range_timezones.py tests/test_game_detail_links.py tests/test_date_time_presentation.py -x"`
Expected: PASS (new file plus the two neighbouring suites still green — they construct `DateTimePresentation` with three positional args, which the defaulted field keeps valid).

- [ ] **Step 6: Commit**

```bash
git add common/date_time_presentation.py games/formatting.py tests/test_session_time_range_timezones.py
git commit -m "feat: render sessions in their own zone with a label under the own-zone preference"
```

---

### Task 5: Client contract + zone-aware formatSessionTimeRange

**Files:**
- Modify: `ts/date-time-presentation.ts`
- Modify: `ts/session-row.ts`
- Test: `ts/date-time-presentation.test.ts` (append), `ts/session-row.test.ts` (append)

**Interfaces:**
- Consumes: Task 4's `session_time_zone_display` config key (absent means `"account"`; the contract stays `version: 2`). Task 4 added it to the Python `DateTimePresentationConfig` TypedDict, so **`make gen-element-types` must run before the vitest edits** — it regenerates `ts/generated/date-time-presentation.ts`, where the key becomes required on the `DateTimePresentationConfig` interface the test file's `configWith()` builds.
- Produces:
  - `type SessionTimeZoneDisplay = "account" | "own"` and `CompiledPresentation.sessionTimeZoneDisplay`.
  - `interface SessionEndpointZone { zone: string | null; label: string | null }` — one endpoint's projection zone (raw IANA name, used to place the wall clock) plus its **already-formatted** label ("JST"), computed server-side in Task 6. Named rather than passed as four loose positional arguments.
  - `formatSessionTimeRange(startISO: string, endISO: string | null, startEndpoint?: SessionEndpointZone, endEndpoint?: SessionEndpointZone): string | null` — `zone` is used only under `"own"`; `label` is appended verbatim when present (never recomputed client-side, and never invented from a zone name). A labelled endpoint renders date + time, matching Task 4's server rule.
  - The old `zoneAbbreviation()` and `usableTimeZone()` helpers are **not** written: the server decides both the wording and whether a label is warranted. Consequence, accepted deliberately: a zone name the browser's own tzdata does not know makes `Temporal` throw, the existing `try`/`catch` reports it and returns `null`, and `session-row.ts` then leaves the **server-rendered** cell text in place (`if (… formattedTimeRange !== null)`) — degrading to the correct server value rather than to a mislabelled client guess.
  - `ts/session-row.ts`'s local `SessionOut` interface gains `timestamp_start_timezone`, `timestamp_end_timezone`, `timestamp_start_timezone_label`, `timestamp_end_timezone_label` (all `string | null`) and passes them through as the two endpoint objects (the server side of that payload lands in Task 6; until then the fields read `undefined ?? null` — the interface change is committed here with the pass-through so Task 6's API change completes the loop).

- [ ] **Step 1: Write the failing vitest cases**

First run `make gen-element-types` (Task 4 changed the Python contract TypedDict), then extend the test file's own contract builder so it keeps type-checking: in `configWith()`, add `session_time_zone_display: "account",` to the returned object literal — it is a required key on the regenerated `DateTimePresentationConfig`.

Append to `ts/date-time-presentation.test.ts`, inside the existing `formatSessionTimeRange` describe block. The helpers below are the file's real ones, already defined and used by its existing cases: `validConfig()` (a version-2 contract with `time_zone: "Europe/Prague"`, ISO date order, `h23`), `alteredConfig(change)` (a `validConfig()` copy the callback mutates), `installConfig(config)` (stamps the contract attribute on `<html>`), and `importFormatter()` (`vi.resetModules()` + dynamic import). Do not invent a second harness.

```typescript
  it("ignores endpoint zones under the account preference", async () => {
    installConfig(
      alteredConfig((config) => {
        config.session_time_zone_display = "account";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(
      formatSessionTimeRange(
        "2026-07-01T12:00:00Z",
        "2026-07-01T13:00:00Z",
        { zone: "Asia/Tokyo", label: "JST" },
        { zone: "Asia/Tokyo", label: "JST" },
      ),
    ).toBe("2026-07-01 14:00 — 15:00");
  });

  it("renders the session's own zone with the server's label under the own preference", async () => {
    installConfig(
      alteredConfig((config) => {
        config.session_time_zone_display = "own";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    // The label is the server's string, verbatim — Intl's own "short" name for
    // Asia/Tokyo is "GMT+9", which would silently disagree with the
    // server-rendered rows in the same table.
    expect(
      formatSessionTimeRange(
        "2026-07-01T12:00:00Z",
        "2026-07-01T13:00:00Z",
        { zone: "Asia/Tokyo", label: "JST" },
        { zone: "Asia/Tokyo", label: "JST" },
      ),
    ).toBe("2026-07-01 21:00 JST — 2026-07-01 22:00 JST");
  });

  it("labels only the endpoint the server labelled", async () => {
    installConfig(
      alteredConfig((config) => {
        config.session_time_zone_display = "own";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(
      formatSessionTimeRange(
        "2026-07-01T12:00:00Z",
        "2026-07-01T13:00:00Z",
        { zone: "Europe/Prague", label: null },
        { zone: "Asia/Tokyo", label: "JST" },
      ),
    ).toBe("2026-07-01 14:00 — 2026-07-01 22:00 JST");
  });

  it("gives a labelled end its own date across the date line", async () => {
    installConfig(
      alteredConfig((config) => {
        config.session_time_zone_display = "own";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    // 21:00 UTC is 06:00 the next day in Tokyo; a bare "06:00 JST" after a
    // 14:00 start reads as the same evening.
    expect(
      formatSessionTimeRange(
        "2026-07-01T12:00:00Z",
        "2026-07-01T21:00:00Z",
        { zone: null, label: null },
        { zone: "Asia/Tokyo", label: "JST" },
      ),
    ).toBe("2026-07-01 14:00 — 2026-07-02 06:00 JST");
  });

  it("renders the account zone when the server sent no label", async () => {
    installConfig(
      alteredConfig((config) => {
        config.session_time_zone_display = "own";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(
      formatSessionTimeRange("2026-07-01T12:00:00Z", null, { zone: null, label: null }),
    ).toBe("2026-07-01 14:00");
  });

  it("treats a contract without the display key as account", async () => {
    installConfig(
      alteredConfig((config) => {
        delete (config as Partial<DateTimePresentationConfig>).session_time_zone_display;
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(
      formatSessionTimeRange("2026-07-01T12:00:00Z", null, {
        zone: "Asia/Tokyo",
        label: "JST",
      }),
    ).toBe("2026-07-01 14:00");
  });

  it("returns null when the runtime does not know the stored zone", async () => {
    installConfig(
      alteredConfig((config) => {
        config.session_time_zone_display = "own";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    // Null leaves session-row.ts's server-rendered cell untouched, which is
    // the correct value — better than a client guess with a wrong wall clock.
    expect(
      formatSessionTimeRange("2026-07-01T12:00:00Z", null, {
        zone: "Not/AZone",
        label: "XXX",
      }),
    ).toBeNull();
    expect(reportClientError).toHaveBeenCalled();
  });
```

(`DateTimePresentationConfig` and `reportClientError` are already imported at the top of the file; the `Partial<…>` cast is what lets the absent-key case delete a now-required contract key without a second harness.)

Append a pass-through case to `ts/session-row.test.ts` (again reusing its existing row/session fixture helpers): a rebuilt row for a session whose payload carries `timestamp_start_timezone: "Asia/Tokyo"`, `timestamp_end_timezone: "Asia/Tokyo"`, `timestamp_start_timezone_label: "JST"`, `timestamp_end_timezone_label: "JST"` under an `"own"` contract must render "JST" in the time-range cell.

- [ ] **Step 2: Run vitest to verify they fail**

Run: `make test-ts`
Expected: FAIL — the new cases report the unlabelled account-zone strings (the extra endpoint arguments are ignored by the current 2-parameter signature) and the session-row case misses "JST".

- [ ] **Step 3: Implement the TS changes**

In `ts/date-time-presentation.ts`:

1. Add near the top-level types:

```typescript
export type SessionTimeZoneDisplay = "account" | "own";

/**
 * One session endpoint's zone: the raw IANA name the wall clock is projected
 * into, plus the display label the *server* computed for it (`null` = nothing
 * to label). The label is never derived here — Intl's short name for
 * Asia/Tokyo is "GMT+9" where the server's `tzname()` says "JST", and the two
 * renderings share one table.
 */
export interface SessionEndpointZone {
  zone: string | null;
  label: string | null;
}

const NO_ENDPOINT_ZONE: SessionEndpointZone = { zone: null, label: null };
```

2. Add `sessionTimeZoneDisplay: SessionTimeZoneDisplay;` to `CompiledPresentation`.

3. In `compilePresentation`, before the return (additive optional key — absent or unknown means "account"):

```typescript
  const sessionTimeZoneDisplay: SessionTimeZoneDisplay =
    config.session_time_zone_display === "own" ? "own" : "account";
```

and include `sessionTimeZoneDisplay,` in the returned object.

4. Give `formatDateTime` a zone override (the projection zone; the `Intl` formatters consume an already-projected `PlainDateTime`, so only this line changes):

```typescript
function formatDateTime(
  iso: string,
  presentation: CompiledPresentation,
  runs: readonly SegmentRun[],
  timeZoneOverride: string | null = null,
): string {
  const value = Temporal.Instant.from(iso)
    .toZonedDateTimeISO(timeZoneOverride ?? presentation.timeZone)
    .toPlainDateTime();
  // …rest unchanged…
```

5. Add the endpoint formatter and rewrite `formatSessionTimeRange` (no `usableTimeZone`, no `zoneAbbreviation` — the server owns validity and wording):

```typescript
function formatEndpoint(
  iso: string,
  presentation: CompiledPresentation,
  runs: readonly SegmentRun[],
  endpoint: SessionEndpointZone,
): string {
  if (presentation.sessionTimeZoneDisplay !== "own" || endpoint.zone === null) {
    return formatDateTime(iso, presentation, runs);
  }
  // The label's presence IS the server's "this endpoint is elsewhere" verdict;
  // the zone comparison only guards a payload that predates a zone change.
  const labelled = endpoint.label !== null && endpoint.zone !== presentation.timeZone;
  const text = formatDateTime(
    iso,
    presentation,
    // A labelled endpoint carries its date: projection can move the wall clock
    // across midnight, and "06:00 JST" after 20:00 reads as the same evening.
    labelled ? ["date", "time"] : runs,
    endpoint.zone,
  );
  // Without the label a sorted list lies: a 21:00 session can be genuinely
  // earlier than the 14:00 one after it.
  return labelled ? `${text} ${endpoint.label}` : text;
}

/** Format a session range with the server-provided browser presentation contract. */
export function formatSessionTimeRange(
  startISO: string,
  endISO: string | null,
  startEndpoint: SessionEndpointZone = NO_ENDPOINT_ZONE,
  endEndpoint: SessionEndpointZone = NO_ENDPOINT_ZONE,
): string | null {
  const presentation = getPresentation();
  if (!presentation) return null;

  try {
    const start = formatEndpoint(startISO, presentation, ["date", "time"], startEndpoint);
    return endISO === null
      ? start
      : `${start} — ${formatEndpoint(endISO, presentation, ["time"], endEndpoint)}`;
  } catch (error) {
    // Includes a zone name this runtime's tzdata does not know: reporting and
    // returning null leaves the server-rendered cell in place, which is right.
    reportClientError("date-time-presentation", errorDetail(error), { toast: false });
    return null;
  }
}
```

In `ts/session-row.ts`: import the type alongside the formatter —
`import { formatSessionTimeRange, type SessionEndpointZone } from "./date-time-presentation.js";`
— and add to the local `SessionOut` interface:

```typescript
  timestamp_start_timezone: string | null;
  timestamp_end_timezone: string | null;
  // Server-computed display labels ("JST"); null when there is nothing to label.
  timestamp_start_timezone_label: string | null;
  timestamp_end_timezone_label: string | null;
```

and change the call:

```typescript
  const startEndpoint: SessionEndpointZone = {
    zone: session.timestamp_start_timezone ?? null,
    label: session.timestamp_start_timezone_label ?? null,
  };
  const endEndpoint: SessionEndpointZone = {
    zone: session.timestamp_end_timezone ?? null,
    label: session.timestamp_end_timezone_label ?? null,
  };
  const formattedTimeRange = formatSessionTimeRange(
    session.timestamp_start,
    session.timestamp_end,
    startEndpoint,
    endEndpoint,
  );
```

- [ ] **Step 4: Run vitest and the TS gate to verify they pass**

Run: `make test-ts`
Expected: PASS (new cases green, existing 2-argument call sites untouched by the defaulted parameters).
Run: `make ts-check && make ts`
Expected: clean type check; fresh `dist/` output.

- [ ] **Step 5: Commit**

```bash
git add ts/date-time-presentation.ts ts/date-time-presentation.test.ts ts/session-row.ts ts/session-row.test.ts
git commit -m "feat: zone-aware client session time range under the own-zone preference"
```

---

### Task 6: Capture on the API path — SessionOut/SessionUpdate zones + session-actions browser zone

**Files:**
- Modify: `games/api.py` (`SessionOut`, `SessionUpdate`, `partial_update_session`)
- Modify: `ts/elements/session-actions.ts`
- Modify: `games/views/session.py` (`clone_session_by_id`)
- Test: `tests/test_api.py` (append)

**Interfaces:**
- Consumes: Task 1's model fields; Task 4's public `zone_label()` and `date_time_presentation_for_request()`.
- Produces:
  - `SessionOut.timestamp_start_timezone: str | None` / `timestamp_end_timezone: str | None` (fulfils Task 5's client payload).
  - `SessionOut.timestamp_start_timezone_label: str | None` / `timestamp_end_timezone_label: str | None` — the display label the client appends verbatim, resolved per request through django-ninja's **response-serialization context**. A resolver that declares a `context` parameter receives `{"request": …, "response_status": …}` (verified in `ninja/schema.py`'s `Resolver._takes_context` and the `context=` calls in `ninja/operation.py`), so the schema can compare each stored zone against *this* request's account display zone. `None` when the endpoint has no stored zone, when the stored zone is unusable, or when it equals the account display zone (nothing to label). The label is sent regardless of the `SESSION_TIME_ZONE_DISPLAY` preference — the client gates on the preference it already parses, which keeps this endpoint free of a second preference read.
  - `SessionUpdate` accepts the same two optional fields; a present non-null value must be a valid IANA name (422 otherwise) and is normalised to `ZoneInfo(...).key`; present-null clears to `NULL`.
  - `session-actions.ts` finish sends `{timestamp_end, timestamp_end_timezone: browserTimeZone()}`; reset sends `{timestamp_start, timestamp_start_timezone: browserTimeZone()}` — the "two readings captured at different moments" from the spec.
  - `clone_session_by_id` clears both zone fields (the clone's start is server-stamped `now`, which has no browser zone; `NULL` = display zone).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py` (reusing its `auth_client` fixture and `_make_session` helper):

```python
def test_session_out_includes_zone_fields(auth_client):
    session = _make_session(timestamp_end=None)
    session.timestamp_start_timezone = "Asia/Tokyo"
    session.save()
    response = auth_client.get(f"/api/session/{session.pk}")
    payload = response.json()
    assert payload["timestamp_start_timezone"] == "Asia/Tokyo"
    assert payload["timestamp_end_timezone"] is None


def test_session_out_ships_the_server_computed_zone_label(auth_client):
    """The label travels as data so a client-rebuilt row cannot word it
    differently from a server-rendered one (tzname "JST" vs Intl "GMT+9")."""
    session = _make_session(timestamp_end=None)
    session.timestamp_start_timezone = "Asia/Tokyo"
    session.save()
    payload = auth_client.get(f"/api/session/{session.pk}").json()
    assert payload["timestamp_start_timezone_label"] == "JST"
    assert payload["timestamp_end_timezone_label"] is None


def test_a_zone_matching_the_account_zone_gets_no_label(auth_client):
    session = _make_session(timestamp_end=None)
    session.timestamp_start_timezone = django_timezone.get_current_timezone_name()
    session.save()
    payload = auth_client.get(f"/api/session/{session.pk}").json()
    assert payload["timestamp_start_timezone"] is not None
    assert payload["timestamp_start_timezone_label"] is None


def test_an_unusable_stored_zone_gets_no_label(auth_client):
    """A zone dropped from tzdata must not 500 a list page."""
    session = _make_session(timestamp_end=None)
    Session.objects.filter(pk=session.pk).update(timestamp_start_timezone="Not/AZone")
    payload = auth_client.get(f"/api/session/{session.pk}").json()
    assert payload["timestamp_start_timezone"] == "Not/AZone"
    assert payload["timestamp_start_timezone_label"] is None


def test_patch_finish_stores_the_end_zone(auth_client):
    session = _make_session(timestamp_end=None)
    response = auth_client.patch(
        f"/api/session/{session.pk}",
        json.dumps(
            {
                "timestamp_end": "2026-07-01T13:00:00Z",
                "timestamp_end_timezone": "Asia/Tokyo",
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 200
    session.refresh_from_db()
    assert session.timestamp_end_timezone == "Asia/Tokyo"
    assert session.timestamp_start_timezone is None  # untouched


def test_patch_rejects_a_non_iana_zone(auth_client):
    session = _make_session(timestamp_end=None)
    response = auth_client.patch(
        f"/api/session/{session.pk}",
        json.dumps({"timestamp_end_timezone": "Not/AZone"}),
        content_type="application/json",
    )
    assert response.status_code == 422
    session.refresh_from_db()
    assert session.timestamp_end_timezone is None


def test_patch_null_clears_a_stored_zone(auth_client):
    session = _make_session(timestamp_end=None)
    session.timestamp_start_timezone = "Asia/Tokyo"
    session.save()
    response = auth_client.patch(
        f"/api/session/{session.pk}",
        json.dumps({"timestamp_start_timezone": None}),
        content_type="application/json",
    )
    assert response.status_code == 200
    session.refresh_from_db()
    assert session.timestamp_start_timezone is None
```

(If `_make_session` does not accept `timestamp_end=None`, pass whatever its override convention is — the helper already exists near the top of the file; keep its call shape. The zone-label tests need `from django.utils import timezone as django_timezone` and `Session` — extend the file's existing imports rather than adding a second import block.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test ARGS="tests/test_api.py -k zone -x"`
Expected: FAIL — `KeyError: 'timestamp_start_timezone'` on the first test (schema lacks the field), the same for the `_label` keys, and the PATCH tests leave the columns `None`/return 200 for the invalid zone.

- [ ] **Step 3: Implement the API changes**

In `games/api.py`:

1. Add to the imports: `from zoneinfo import ZoneInfo, ZoneInfoNotFoundError`, `from collections.abc import Mapping`, `from typing import Any` (extend the existing `typing` import), `from common.date_time_presentation import date_time_presentation_for_request`, and `from games.formatting import zone_label`.
2. Above `SessionOut`, the one label resolver both endpoints share:

```python
def _endpoint_zone_label(
    value: datetime | None,
    zone_name: str | None,
    context: Mapping[str, Any] | None,
) -> str | None:
    """The label the client appends verbatim, or ``None`` when there is nothing
    to label: no stored zone, an unusable one (dropped from tzdata — must not
    500 a list page), or one that equals this request's account display zone.

    Computed here rather than in the browser because ``tzname()`` says "JST"
    where Intl's ``timeZoneName: "short"`` says "GMT+9"; server-rendered and
    client-rebuilt rows share one table and must read identically.
    """
    request = context.get("request") if context else None
    if request is None or value is None or not zone_name:
        return None
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError, ValueError:
        return None
    if zone.key == date_time_presentation_for_request(request).timezone.key:
        return None
    return zone_label(value, zone)
```

3. `SessionOut` — after `timestamp_end`:

```python
    timestamp_start_timezone: str | None = None
    timestamp_end_timezone: str | None = None
    timestamp_start_timezone_label: str | None = None
    timestamp_end_timezone_label: str | None = None
```

and, beside the existing `resolve_*` staticmethods (django-ninja hands a resolver that declares `context` the response-serialization context, `{"request": …, "response_status": …}`):

```python
@staticmethod
def resolve_timestamp_start_timezone_label(obj: Session, context) -> str | None:
    return _endpoint_zone_label(
        obj.timestamp_start, obj.timestamp_start_timezone, context
    )


@staticmethod
def resolve_timestamp_end_timezone_label(obj: Session, context) -> str | None:
    return _endpoint_zone_label(obj.timestamp_end, obj.timestamp_end_timezone, context)
```

4. `SessionUpdate` — after `timestamp_end` (no label fields here: labels are output-only, derived from the stored zone):

```python
    # IANA zone each timestamp was committed in; present-null clears to NULL
    # ("assume the display zone").
    timestamp_start_timezone: str | None = None
    timestamp_end_timezone: str | None = None
```

5. In `partial_update_session`, after `data = payload.dict(exclude_unset=True)` and before the start/end ordering check:

```python
    for zone_field in ("timestamp_start_timezone", "timestamp_end_timezone"):
        if zone_field in data and data[zone_field] is not None:
            try:
                data[zone_field] = ZoneInfo(data[zone_field]).key
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise HttpError(
                    422, f"{zone_field} must be an IANA time zone name"
                ) from exc
```

In `ts/elements/session-actions.ts`:

1. Add near the imports:

```typescript
function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}
```

2. Finish handler body becomes:

```typescript
      this.patch(props.apiUrl, props.csrf, {
        timestamp_end: nowISOUTC(),
        timestamp_end_timezone: browserTimeZone(),
      });
```

3. Reset-confirm handler body becomes:

```typescript
      this.closeModal();
      this.patch(props.apiUrl, props.csrf, {
        timestamp_start: nowISOUTC(),
        timestamp_start_timezone: browserTimeZone(),
      });
```

In `games/views/session.py`, `clone_session_by_id` — after `clone.timestamp_end = None`:

```python
    # The clone's start is server-stamped now; a browser zone does not exist
    # here, and NULL already means "assume the display zone".
    clone.timestamp_start_timezone = None
    clone.timestamp_end_timezone = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test ARGS="tests/test_api.py -x"` and `make ts`
Expected: pytest PASS (whole file); `make ts` compiles cleanly.

- [ ] **Step 5: Commit**

```bash
git add games/api.py ts/elements/session-actions.ts games/views/session.py tests/test_api.py
git commit -m "feat: capture the browser zone on finish/reset and expose zones on the session API"
```

---

### Task 7: time-zone-row custom element (SearchSelect panel flag + component + TS + codegen)

**Files:**
- Modify: `common/components/search_select.py` (`SearchSelect(panel=…)`)
- Modify: `common/components/custom_elements.py`
- Create: `common/components/time_zone_row.py`
- Modify: `common/components/__init__.py` (export `TimeZoneRow`)
- Create: `ts/elements/time-zone-row.ts`
- Regenerate: `ts/generated/props.ts` (via `make gen-element-types`)
- Test: `tests/test_search_select.py` (append), `tests/test_time_zone_row.py`, `ts/elements/time-zone-row.test.ts`

**Interfaces:**
- Consumes: Task 3's `/api/timezones/search`; `ComboboxDropdown`/`SearchSelect` from `common/components/search_select.py`.
- Produces:
  - `SearchSelect(..., panel: bool = False)` — the panel-hosted personality. Hosting a *bare* `SearchSelect` inside a `ComboboxDropdown` panel is not a supported composition today: both existing panel-hosted precedents (`PresetSelect`, `FilterSelect(layout="panel")`) pass `always_visible=True` **and** swap in the module's static panel classes, which `SearchSelect`'s public signature does not expose. `panel=True` forces `always_visible=True` and uses `_PANEL_CONTAINER_CLASS` / `_PANEL_SEARCH_CLASS` / `_PANEL_OPTIONS_CLASS` — the very constants those two call sites already use, not new ones.
  - `TimeZoneRowProps(TypedDict)`: `field_name: str`, `stored_zone: str` (`""` = NULL), `display_zone: str`, `capture_default: bool` — registered as `register_element("time-zone-row", "TimeZoneRow", TimeZoneRowProps)`; codegen emits `readTimeZoneRowProps` whose bool reader is `getAttribute("capture-default") === "true"`.
  - `TimeZoneRow(*, field_name: str, label: str, stored_zone: str, display_zone: str, capture_default: bool) -> Node` — the component Task 8's widget renders. Markup contract, exactly two parts: (1) one hidden input `name={field_name}` with `data-time-zone-value` — the only submitted channel; (2) one **always-visible** ghost `ComboboxDropdown` (`aria-haspopup="dialog"`, label `"{label}: {stored_zone or display_zone + ' (display zone)'}"`) whose panel hosts a single-select `SearchSelect(panel=True)` named `{field_name}_picker` (never read server-side). No toggle button, no `hidden` wrapper, no `aria-expanded` bookkeeping of our own — the `<drop-down>` engine owns the trigger's expanded state.
  - `capture_default` is a Python `bool` on the function signature and in the props TypedDict, but reaches the element builder **as the string** `"true"`/`"false"`: `_attrs_from_kwargs` drops a `False` kwarg entirely and renders `True` as the bare boolean form, so a raw bool would emit no attribute at all in the common case. Explicit stringification is the repo's convention for custom-element bools (`active="true" if active else "false"` in `common/components/custom_elements.py`).
  - Client behavior (`time-zone-row.ts`): on connect, stamp the browser zone into an empty hidden input when `capture-default="true"`; add the `font-semibold` emphasis class to the trigger when the effective zone (input value or `display-zone`) differs from the browser zone — never auto-open the panel; mirror `search-select:change` picks into the hidden input and the trigger label, treating a `""` pick (Task 3's pinned clear row) as an explicit reset to NULL with the display-zone fallback label.
  - Declares `Media(js=("dist/elements/time-zone-row.js",))`.

- [ ] **Step 1: Write the failing Python component tests**

Create `tests/test_time_zone_row.py`:

```python
"""TimeZoneRow component markup: the hidden submitted channel, the single
always-visible picker trigger, and the kebab-cased element props the TS reads."""

from common.components import TimeZoneRow
from common.components.core import collect_media


def _render(**overrides) -> str:
    parameters = {
        "field_name": "timestamp_start_timezone",
        "label": "Start time zone",
        "stored_zone": "",
        "display_zone": "Europe/Prague",
        "capture_default": True,
    }
    parameters.update(overrides)
    return str(TimeZoneRow(**parameters))


def test_renders_element_with_kebab_cased_props():
    html = _render(stored_zone="Asia/Tokyo", capture_default=False)
    assert "<time-zone-row" in html
    assert 'field-name="timestamp_start_timezone"' in html
    assert 'stored-zone="Asia/Tokyo"' in html
    assert 'display-zone="Europe/Prague"' in html
    assert 'capture-default="false"' in html


def test_hidden_input_is_the_submitted_channel():
    html = _render(stored_zone="Asia/Tokyo")
    assert 'name="timestamp_start_timezone"' in html
    assert "data-time-zone-value" in html
    assert 'value="Asia/Tokyo"' in html


def test_trigger_is_always_visible_with_a_ghost_style():
    """One control per field, never collapsed: a second control named after the
    same field double-announces, and a hidden trigger is unreachable in exactly
    the case a mismatch check cannot detect."""
    html = _render()
    # An htpy `hidden=True` renders as hidden="hidden" — the exact thing this
    # row must not contain. Asserting on the bare word would be wrong: the
    # submitted input is type="hidden", and the dropdown panel is stamped
    # hidden="" by the <drop-down> engine, which owns its visibility.
    assert 'hidden="hidden"' not in html
    assert 'aria-haspopup="dialog"' in html
    assert "bg-transparent" in html  # the ghost ControlButton variant
    # NULL renders the display-zone fallback in the trigger label.
    assert "Start time zone: Europe/Prague (display zone)" in html


def test_stored_zone_names_itself_in_the_trigger_label():
    assert "Start time zone: Asia/Tokyo" in _render(stored_zone="Asia/Tokyo")


def test_picker_searches_the_timezone_api_without_submitting_itself():
    html = _render()
    assert "/api/timezones/search" in html
    assert 'name="timestamp_start_timezone_picker"' in html


def test_declares_its_module_media():
    media = collect_media(
        TimeZoneRow(
            field_name="timestamp_start_timezone",
            label="Start time zone",
            stored_zone="",
            display_zone="Europe/Prague",
            capture_default=True,
        )
    )
    assert "dist/elements/time-zone-row.js" in media.js
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test ARGS="tests/test_time_zone_row.py -x"`
Expected: FAIL — `ImportError: cannot import name 'TimeZoneRow'`.

- [ ] **Step 3: Give `SearchSelect` a panel-hosted personality**

The component in Step 4 hosts a `SearchSelect` inside a `ComboboxDropdown` panel, which needs the two knobs the existing panel-hosted widgets set by hand. Add them as one public flag first.

Append to `tests/test_search_select.py`:

```python
def test_panel_personality_is_always_visible_with_the_panel_classes():
    """The composition PresetSelect and FilterSelect(layout="panel") already
    use by hand: no hidden panel (the hosting dialog owns open/close) and the
    static panel classes instead of the absolutely-positioned field ones."""
    html = str(
        SearchSelect(name="zone", search_url="/api/timezones/search", panel=True)
    )
    assert 'always-visible="true"' in html
    assert "mt-2 overflow-y-auto" in html  # _PANEL_OPTIONS_CLASS
    assert "block text-type-body" in html  # _PANEL_CONTAINER_CLASS


def test_default_search_select_keeps_the_field_personality():
    html = str(SearchSelect(name="zone", search_url="/api/timezones/search"))
    assert 'always-visible="false"' in html
    assert "mt-2 overflow-y-auto" not in html
```

Run: `make test ARGS="tests/test_search_select.py -k panel_personality -x"`
Expected: FAIL — `TypeError: SearchSelect() got an unexpected keyword argument 'panel'`.

Then in `common/components/search_select.py`, add the keyword-only parameter to `SearchSelect` (after `host_dropdown`):

```python
panel: bool = (False,)
```

document it in the docstring:

```
    ``panel=True`` is the panel-hosted personality: an always-visible widget
    using the module's static panel classes, for content placed inside a
    :func:`ComboboxDropdown` dialog (which owns open/close/dismiss). The same
    composition :func:`PresetSelect` and a panel-layout :func:`FilterSelect`
    build by hand — the hosting dialog, not the widget, is the disclosure.
```

and thread it through the existing body — no new constants, no new branches beyond these:

```python
    if panel:
        always_visible = True
```

(placed with the other argument normalisation at the top), the search box's class becomes `_PANEL_SEARCH_CLASS if panel else _SEARCH_CLASS`, the `_combobox_children(...)` call passes
`options_class=_PANEL_OPTIONS_CLASS if panel else (_INLINE_OPTIONS_CLASS if host_dropdown else None)`,
and the container class picks `_PANEL_CONTAINER_CLASS` in place of `_CONTAINER_CLASS` when `panel` is set (the `show_marker` suffix composition is unchanged).

Run: `make test ARGS="tests/test_search_select.py -x"`
Expected: PASS (whole file — the field personality is byte-unchanged for every existing caller).

- [ ] **Step 4: Register the element and write the component**

In `common/components/custom_elements.py`, after the `DateTimeFieldProps` registration (line ~190):

```python
class TimeZoneRowProps(TypedDict):
    field_name: str  # the posted Django field, e.g. "timestamp_start_timezone"
    stored_zone: str  # bound IANA zone id; "" when NULL (assume display zone)
    display_zone: str  # account display zone NULL resolves to, e.g. "Europe/Prague"
    capture_default: bool  # unsaved record: stamp the browser zone when unset


register_element("time-zone-row", "TimeZoneRow", TimeZoneRowProps)
```

and with the other named tag builders:

```python
_TimeZoneRow = custom_element_builder("time-zone-row")
```

Create `common/components/time_zone_row.py`:

```python
"""TimeZoneRow: the per-timestamp "Time zone" row.

Composes pieces the quick-filter facets already use — a ghost
``ComboboxDropdown`` hosting a panel ``SearchSelect`` over
``/api/timezones/search`` — plus one hidden input that is the *only*
submitted channel (the picker's own input carries a ``_picker`` suffix the
server never reads). The trigger is always visible: one control per field, so
nothing double-announces and the picker is reachable even when the browser and
stored zones agree. The only ``hidden`` thing here is that input.
``ts/elements/time-zone-row.ts`` stamps the browser zone as the capture default
on unsaved records and emphasises the trigger when the zones disagree.
"""

from common.components.core import Media, Node
from common.components.custom_elements import _TimeZoneRow
from common.components.primitives import Div, Input
from common.components.search_select import ComboboxDropdown, SearchSelect

TIMEZONE_SEARCH_API_URL = "/api/timezones/search"


def TimeZoneRow(
    *,
    field_name: str,
    label: str,
    stored_zone: str,
    display_zone: str,
    capture_default: bool,
) -> Node:
    effective_label = stored_zone or f"{display_zone} (display zone)"
    picker = SearchSelect(
        name=f"{field_name}_picker",
        selected=(
            [{"value": stored_zone, "label": stored_zone, "data": {}}]
            if stored_zone
            else None
        ),
        search_url=TIMEZONE_SEARCH_API_URL,
        placeholder="Search time zones…",
        panel=True,
    )
    trigger = Div(class_="mt-1")[
        ComboboxDropdown(
            label=f"{label}: {effective_label}",
            content=picker,
            id=f"{field_name}-dropdown",
            ghost=True,
        )
    ]
    element = _TimeZoneRow(
        field_name=field_name,
        stored_zone=stored_zone,
        display_zone=display_zone,
        # A raw bool would vanish: _attrs_from_kwargs drops False and renders
        # True as the bare boolean form, while the generated reader compares
        # against the string "true".
        capture_default="true" if capture_default else "false",
        class_="block",
    )[
        Input(
            type="hidden",
            name=field_name,
            value=stored_zone,
            data_time_zone_value="",
        ),
        trigger,
    ]
    return element.with_media(Media(js=("dist/elements/time-zone-row.js",)))
```

Export it: in `common/components/__init__.py`, add `TimeZoneRow` to the imports/`__all__` alongside the other component re-exports (import from `common.components.time_zone_row`).

Note for the implementer: `custom_element_builder` already attaches `Media(js=("dist/elements/time-zone-row.js",))` to every node it builds, so the explicit `.with_media(...)` is a belt-and-braces restatement (`Media`'s merge dedups) that keeps the dependency visible at the call site.

- [ ] **Step 5: Run the codegen and Python tests**

Run: `make gen-element-types`
Expected: `ts/generated/props.ts` gains `TimeZoneRowProps` + `readTimeZoneRowProps` (attributes `field-name`, `stored-zone`, `display-zone`, `capture-default`).
Run: `make test ARGS="tests/test_time_zone_row.py -x"`
Expected: PASS (6 tests).

- [ ] **Step 6: Write the failing vitest cases**

Create `ts/elements/time-zone-row.test.ts`:

```typescript
// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "./time-zone-row.js";

const REAL_DATE_TIME_FORMAT = Intl.DateTimeFormat;

function stubBrowserZone(timeZone: string): void {
  vi.spyOn(Intl, "DateTimeFormat").mockImplementation((...formatArguments) => {
    const formatter = new REAL_DATE_TIME_FORMAT(...formatArguments);
    const realResolvedOptions = formatter.resolvedOptions.bind(formatter);
    formatter.resolvedOptions = () => ({ ...realResolvedOptions(), timeZone });
    return formatter;
  });
}

function mount({
  storedZone = "",
  displayZone = "Europe/Prague",
  captureDefault = true,
}: { storedZone?: string; displayZone?: string; captureDefault?: boolean } = {}): HTMLElement {
  document.body.innerHTML = `
    <time-zone-row field-name="timestamp_start_timezone"
        stored-zone="${storedZone}" display-zone="${displayZone}"
        capture-default="${captureDefault}" class="block">
      <input type="hidden" name="timestamp_start_timezone"
          value="${storedZone}" data-time-zone-value="">
      <div class="mt-1">
        <button type="button" aria-haspopup="dialog">Start time zone: ${
          storedZone || `${displayZone} (display zone)`
        }<svg></svg></button>
      </div>
    </time-zone-row>`;
  return document.querySelector("time-zone-row")!;
}

function valueInput(host: HTMLElement): HTMLInputElement {
  return host.querySelector<HTMLInputElement>("[data-time-zone-value]")!;
}

function trigger(host: HTMLElement): HTMLButtonElement {
  return host.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')!;
}

beforeEach(() => {
  document.body.replaceChildren();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("time-zone-row", () => {
  it("captures the browser zone into an empty input on a new record", () => {
    stubBrowserZone("Asia/Tokyo");
    const host = mount({ captureDefault: true });
    expect(valueInput(host).value).toBe("Asia/Tokyo");
  });

  it("leaves an existing record's empty value untouched (NULL stays NULL)", () => {
    stubBrowserZone("Asia/Tokyo");
    const host = mount({ captureDefault: false });
    expect(valueInput(host).value).toBe("");
  });

  it("emphasises the trigger when the effective zone disagrees with the browser zone", () => {
    stubBrowserZone("Asia/Tokyo");
    const host = mount({ storedZone: "Europe/Prague", captureDefault: false });
    expect(trigger(host).classList.contains("font-semibold")).toBe(true);
  });

  it("leaves the trigger unemphasised when the zones agree", () => {
    stubBrowserZone("Europe/Prague");
    const host = mount({ storedZone: "Europe/Prague", captureDefault: false });
    expect(trigger(host).classList.contains("font-semibold")).toBe(false);
  });

  it("never opens the panel by itself", () => {
    // Auto-opening a dialog on load steals focus and interrupts a screen
    // reader; the emphasis class is the whole mismatch signal.
    stubBrowserZone("Asia/Tokyo");
    const host = mount({ storedZone: "Europe/Prague", captureDefault: false });
    expect(trigger(host).getAttribute("aria-expanded")).not.toBe("true");
  });

  it("compares NULL against the display zone", () => {
    stubBrowserZone("Asia/Tokyo");
    const host = mount({ storedZone: "", displayZone: "Europe/Prague", captureDefault: false });
    expect(trigger(host).classList.contains("font-semibold")).toBe(true);
  });

  it("mirrors a picker selection into the value and the trigger label", () => {
    stubBrowserZone("Europe/Prague");
    const host = mount({ storedZone: "Europe/Prague", captureDefault: false });
    host.dispatchEvent(
      new CustomEvent("search-select:change", {
        bubbles: true,
        detail: {
          name: "timestamp_start_timezone_picker",
          values: ["Asia/Tokyo"],
          last: { value: "Asia/Tokyo", label: "Asia/Tokyo", data: {} },
        },
      }),
    );
    expect(valueInput(host).value).toBe("Asia/Tokyo");
    expect(trigger(host).textContent).toContain("Start time zone: Asia/Tokyo");
  });

  it("treats the pinned empty option as a clear back to NULL", () => {
    // The API's browse-all response pins {value: ""}; it is the only route
    // back to NULL once a zone has been captured.
    stubBrowserZone("Asia/Tokyo");
    const host = mount({ storedZone: "Asia/Tokyo", captureDefault: false });
    host.dispatchEvent(
      new CustomEvent("search-select:change", {
        bubbles: true,
        detail: {
          name: "timestamp_start_timezone_picker",
          values: [""],
          last: { value: "", label: "Use account display zone", data: {} },
        },
      }),
    );
    expect(valueInput(host).value).toBe("");
    expect(trigger(host).textContent).toContain(
      "Start time zone: Europe/Prague (display zone)",
    );
  });
});
```

- [ ] **Step 7: Run vitest to verify it fails**

Run: `make test-ts`
Expected: FAIL — the import of `./time-zone-row.js` cannot resolve (module does not exist yet).

- [ ] **Step 8: Write the element**

Create `ts/elements/time-zone-row.ts`:

```typescript
import { readTimeZoneRowProps } from "../generated/props.js";
import type { SearchSelectChangeDetail } from "./search-select.js";

// The per-timestamp "Time zone" row: one hidden input (the only submitted
// channel) and one always-visible picker trigger. Nothing here hides or
// reveals anything — the hosting <drop-down> owns the panel's open state. On a
// browser-vs-effective zone mismatch the trigger gains an emphasis class; the
// panel is never opened programmatically, which would steal focus on load.
const EMPHASIS_CLASS = "font-semibold";

function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

class TimeZoneRowElement extends HTMLElement {
  private labelPrefix = "";

  connectedCallback(): void {
    const props = readTimeZoneRowProps(this);
    const valueInput = this.querySelector<HTMLInputElement>("[data-time-zone-value]");
    const trigger = this.querySelector<HTMLElement>('button[aria-haspopup="dialog"]');
    if (!valueInput || !trigger) return;

    const triggerText = trigger.childNodes[0]?.textContent ?? "";
    this.labelPrefix = triggerText.split(":")[0] ?? "";
    // What a NULL value reads as, reused by the clear branch below.
    const fallbackLabel = `${props.displayZone} (display zone)`;

    const detectedZone = browserTimeZone();
    if (props.captureDefault && valueInput.value === "") {
      // The capture default: the browser was in this zone when the timestamp
      // was committed. Stamped only on unsaved records — an existing NULL
      // stays NULL (that IS today's behaviour) unless the user picks a zone.
      valueInput.value = detectedZone;
      this.updateTriggerLabel(trigger, detectedZone);
    }
    const effectiveZone = valueInput.value || props.displayZone;
    if (effectiveZone !== detectedZone) {
      // The zone this row will submit is not the zone this browser is in —
      // worth a look. Emphasis only: the trigger already names the value.
      trigger.classList.add(EMPHASIS_CLASS);
    }

    this.addEventListener("search-select:change", (event) => {
      const detail = (event as CustomEvent<SearchSelectChangeDetail>).detail;
      if (!detail || detail.last === null) return;
      // The API's pinned "" option is an explicit clear back to NULL.
      valueInput.value = detail.last.value;
      this.updateTriggerLabel(trigger, detail.last.value || fallbackLabel);
    });
  }

  private updateTriggerLabel(trigger: HTMLElement, zoneName: string): void {
    const textNode = trigger.childNodes[0];
    if (textNode) textNode.textContent = `${this.labelPrefix}: ${zoneName}`;
  }
}

customElements.define("time-zone-row", TimeZoneRowElement);
```

- [ ] **Step 9: Run vitest + checks to verify they pass**

Run: `make test-ts`
Expected: PASS (8 new cases).
Run: `make ts-check && make ts`
Expected: clean; `dist/elements/time-zone-row.js` exists.

- [ ] **Step 10: Commit**

```bash
git add common/components/custom_elements.py common/components/search_select.py common/components/time_zone_row.py common/components/__init__.py ts/elements/time-zone-row.ts ts/elements/time-zone-row.test.ts ts/generated/props.ts tests/test_search_select.py tests/test_time_zone_row.py
git commit -m "feat: time-zone-row element with browser-zone capture and a mismatch cue"
```

---

### Task 8: Session form wiring — widget, embedded rows, views

**Files:**
- Modify: `common/components/primitives.py` (`FormFields` gains `embedded=`)
- Modify: `games/forms.py` (`TimeZoneRowWidget`, SessionForm fields, `SESSION_TIMEZONE_EMBEDS`, skip-tuple)
- Modify: `games/views/session.py` (`add_session`, `edit_session`)
- Test: `tests/test_session_timezone_form.py`

**Interfaces:**
- Consumes: Task 7's `TimeZoneRow` and Task 1's model fields; `DISPLAY_TIME_ZONE_CHOICES` from `timetracker/settings_registry.py`.
- Produces:
  - `FormFields(form, *, presentations=None, groups=None, embedded: Mapping[str, str] | None = None)` — `embedded` maps a field name to the *host* field whose row renders it (full widget markup plus its errors, after the host's control) instead of a row of its own. Unknown names raise `ValueError`; combining `embedded` with `groups` raises `ValueError` (not needed here; keep the contract explicit).
  - `SESSION_TIMEZONE_EMBEDS: Final[dict[str, str]] = {"timestamp_start_timezone": "timestamp_start", "timestamp_end_timezone": "timestamp_end"}` exported from `games/forms.py`.
  - `SessionForm` binds `timestamp_start_timezone`/`timestamp_end_timezone` as `TypedChoiceField(required=False, empty_value=None, choices=…)` — `""` cleans to `None` (NULL), an invalid zone is a form error.
  - **Capture is decided per field, not per record.** `timestamp_start_timezone` captures on any unsaved record (a new session's start is always about to be committed). `timestamp_end_timezone` captures only when the end timestamp actually has a bound value — otherwise an *open* session would be stamped with the browser zone at creation time and keep that stale zone when it is finished later. (The finish flow sends its own end zone, but only through `session-actions.ts`'s PATCH; a session finished by editing the form would inherit the creation-time stamp.)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session_timezone_form.py`:

```python
"""SessionForm zone binding and the FormFields embedded-row mechanism."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from django import forms

from common.components import FormFields
from common.components.core import render
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.forms import SESSION_TIMEZONE_EMBEDS, SessionForm
from games.models import Game, Session

pytestmark = pytest.mark.django_db

_PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("Europe/Prague")
)


def _form_data(game: Game, **overrides) -> dict[str, str]:
    data = {
        "game": str(game.pk),
        "timestamp_start": "2026-07-01T21:00:00+09:00",
        "timestamp_start_timezone": "Asia/Tokyo",
        "timestamp_end": "",
        "timestamp_end_timezone": "",
        "duration_manual": "",
        "device": "",
        "note": "",
    }
    data.update(overrides)
    return data


def test_zone_binds_to_the_model_and_empty_cleans_to_null(db):
    game = Game.objects.create(name="Hades")
    form = SessionForm(data=_form_data(game), presentation=_PRESENTATION)
    assert form.is_valid(), form.errors
    session = form.save()
    session.refresh_from_db()
    assert session.timestamp_start_timezone == "Asia/Tokyo"
    assert session.timestamp_end_timezone is None


def test_invalid_zone_is_a_form_error(db):
    game = Game.objects.create(name="Hades")
    form = SessionForm(
        data=_form_data(game, timestamp_start_timezone="Not/AZone"),
        presentation=_PRESENTATION,
    )
    assert not form.is_valid()
    assert "timestamp_start_timezone" in form.errors


def test_unbound_add_form_captures_the_start_zone_only(db):
    """Both rows render, but only the start captures: an open session's end
    timestamp is committed later, in a zone this page cannot know."""
    form = SessionForm(presentation=_PRESENTATION)
    html = render(FormFields(form, embedded=SESSION_TIMEZONE_EMBEDS))
    assert html.count("<time-zone-row") == 2
    assert html.count('capture-default="true"') == 1
    assert html.count('capture-default="false"') == 1
    assert 'display-zone="Europe/Prague"' in html


def test_an_end_timestamp_on_the_add_form_captures_its_zone_too(db):
    """A retroactive add (or a duration shortcut that pre-fills the end)
    commits both timestamps now, so both capture."""
    form = SessionForm(
        presentation=_PRESENTATION,
        initial={"timestamp_end": datetime(2026, 7, 1, 14, 0, tzinfo=UTC)},
    )
    html = render(FormFields(form, embedded=SESSION_TIMEZONE_EMBEDS))
    assert html.count('capture-default="true"') == 2


def test_edit_form_carries_the_stored_zone_without_recapture(db):
    game = Game.objects.create(name="Hades")
    session = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        timestamp_start_timezone="Asia/Tokyo",
    )
    form = SessionForm(instance=session, presentation=_PRESENTATION)
    html = render(FormFields(form, embedded=SESSION_TIMEZONE_EMBEDS))
    assert 'stored-zone="Asia/Tokyo"' in html
    assert html.count('capture-default="false"') == 2


def test_embedded_field_renders_in_its_host_row_not_its_own(db):
    form = SessionForm(presentation=_PRESENTATION)
    html = render(FormFields(form, embedded=SESSION_TIMEZONE_EMBEDS))
    # No standalone label row for the zone fields; the widget's own trigger
    # carries the accessible label.
    assert "Timestamp start timezone" not in html
    # The row markup appears exactly once per field (no double render).
    assert html.count('name="timestamp_start_timezone"') == 1


def test_form_fields_embedded_rejects_unknown_names():
    class TinyForm(forms.Form):
        name = forms.CharField()

    with pytest.raises(ValueError):
        FormFields(TinyForm(), embedded={"missing": "name"})
    with pytest.raises(ValueError):
        FormFields(TinyForm(), embedded={"name": "missing"})
```

(If `render` is not importable from `common.components.core`, use `str(...)` on the node — match how `tests/test_components.py` stringifies nodes.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test ARGS="tests/test_session_timezone_form.py -x"`
Expected: FAIL — `ImportError: cannot import name 'SESSION_TIMEZONE_EMBEDS'`.

- [ ] **Step 3: Extend FormFields with embedded**

In `common/components/primitives.py`:

1. Extend the dataclass import: `from dataclasses import dataclass, replace`.
2. Change the signature and body of `FormFields`:

```python
def FormFields(
    form,
    *,
    presentations: Mapping[str, FormFieldPresentation] | None = None,
    groups: Sequence[FormFieldGroup] | None = None,
    embedded: Mapping[str, str] | None = None,
) -> Node:
```

Append to the docstring:

```
    ``embedded`` maps a field name to the *host* field whose row renders it —
    the embedded field's full widget markup (plus its own errors) is appended
    after the host's control instead of getting a labelled row of its own.
    For self-labelling controls that belong visually to another field.
```

3. After the existing `unknown_presentations` guard, add:

```python
embedded = dict(embedded or {})
if embedded and groups is not None:
    raise ValueError("FormFields embedded is not supported with groups.")
for embedded_name, host_name in embedded.items():
    if embedded_name not in form.fields:
        raise ValueError(f"FormFields embedded names unknown field {embedded_name!r}.")
    if host_name not in form.fields:
        raise ValueError(f"FormFields embedded names unknown host field {host_name!r}.")

embedded_by_host: dict[str, list[Node]] = {}
for embedded_name, host_name in embedded.items():
    embedded_field = form[embedded_name]
    embed_parts: list[Node] = [Safe(str(embedded_field))]
    embed_errors = _field_errors(embedded_field.errors)
    if embed_errors:
        embed_parts.append(embed_errors)
    embedded_by_host.setdefault(host_name, []).extend(embed_parts)


def _presentation_with_embeds(
    field_name: str,
) -> FormFieldPresentation | None:
    presentation = presentations.get(field_name)
    embeds = embedded_by_host.get(field_name)
    if not embeds:
        return presentation
    extra: Node = Fragment(*embeds)
    if presentation is None:
        return FormFieldPresentation(after_control=extra)
    combined = (
        Fragment(presentation.after_control, extra)
        if presentation.after_control is not None
        else extra
    )
    return replace(presentation, after_control=combined)
```

4. In the main loop, skip embedded fields and use the merged presentation:

```python
    for field in form:
        if field.is_hidden:
            rows.append(Safe(str(field)))
            continue
        if field.name in embedded:
            continue
        rows.append(_form_field_row(field, _presentation_with_embeds(field.name)))
```

- [ ] **Step 4: Wire the form**

In `games/forms.py`:

1. Add imports: `from common.components.time_zone_row import TimeZoneRow` and extend the `timetracker.settings_registry` import (or add one) with `DISPLAY_TIME_ZONE_CHOICES`. Add `Final` to the `typing` import if absent.
2. After `DateTimeFieldWidget` (line ~371):

```python
class TimeZoneRowWidget(forms.Widget):
    """Thin Django adapter that renders a `TimeZoneRow()` component for a
    per-timestamp zone field. The row's picker trigger is always visible; the
    hidden input inside the component is the submitted channel this widget
    reads back."""

    def __init__(
        self,
        *,
        label: str,
        display_zone: str,
        capture_default: bool,
        attrs=None,
    ):
        super().__init__(attrs)
        self.label = label
        self.display_zone = display_zone
        self.capture_default = capture_default

    def render(self, name, value, attrs=None, renderer=None):
        return render(
            TimeZoneRow(
                field_name=name,
                label=self.label,
                stored_zone=str(value) if value else "",
                display_zone=self.display_zone,
                capture_default=self.capture_default,
            )
        )

    def value_from_datadict(self, data, files, name):
        return data.get(name)
```

(`render` here is the same node-to-safe-string helper the neighbouring widgets already use in this module.)

3. Add `TimeZoneRowWidget` to the composite-widget skip in `apply_primitive_widget_classes`:

```python
        if isinstance(
            widget,
            (
                SearchSelectWidget,
                DatePickerWidget,
                DateTimeFieldWidget,
                TimeZoneRowWidget,
            ),
        ):
            continue
```

4. Next to `_TIMESTAMP_COPY_TARGETS`:

```python
_TIME_ZONE_FORM_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("", "Account display zone"),
    *DISPLAY_TIME_ZONE_CHOICES,
)
_TIMESTAMP_TIMEZONE_LABELS: Final[dict[str, str]] = {
    "timestamp_start_timezone": "Start time zone",
    "timestamp_end_timezone": "End time zone",
}
# The FormFields `embedded` mapping: each zone picker renders inside its
# timestamp's row, not as a labelled row of its own.
SESSION_TIMEZONE_EMBEDS: Final[dict[str, str]] = {
    "timestamp_start_timezone": "timestamp_start",
    "timestamp_end_timezone": "timestamp_end",
}
```

5. In `SessionForm`:

Declared fields (next to `duration_manual` etc.) — `empty_value=None` is what turns the unchosen "" into a stored NULL:

```python
    timestamp_start_timezone = forms.TypedChoiceField(
        required=False, choices=_TIME_ZONE_FORM_CHOICES, empty_value=None
    )
    timestamp_end_timezone = forms.TypedChoiceField(
        required=False, choices=_TIME_ZONE_FORM_CHOICES, empty_value=None
    )
```

In `__init__`, after the copy-target loop:

```python
        is_new_record = self.instance.pk is None
        # The end zone is only meaningful once an end timestamp exists: an open
        # session stamped at creation would carry that zone into a finish that
        # happens elsewhere, hours later. The start is always about to be
        # committed on a new record, so it captures unconditionally.
        end_timestamp_supplied = bool(
            self.initial.get("timestamp_end")
            or (self.is_bound and self.data.get("timestamp_end"))
        )
        captures_by_field = {
            "timestamp_start_timezone": is_new_record,
            "timestamp_end_timezone": is_new_record and end_timestamp_supplied,
        }
        for field_name, zone_label in _TIMESTAMP_TIMEZONE_LABELS.items():
            self.fields[field_name].widget = TimeZoneRowWidget(
                label=zone_label,
                display_zone=presentation.timezone.key,
                capture_default=captures_by_field[field_name],
            )
```

In `Meta.fields`, insert each zone field directly after its timestamp:

```python
        fields = (
            "game",
            "timestamp_start",
            "timestamp_start_timezone",
            "timestamp_end",
            "timestamp_end_timezone",
            "duration_manual",
            "emulated",
            "device",
            "note",
            "mark_as_played",
        )
```

6. In `games/views/session.py`: add `FormFields` to the `common.components` import and `SESSION_TIMEZONE_EMBEDS` to the `games.forms` import, then change both render calls (in `add_session` and `edit_session`):

```python
(
    AddForm(
        form,
        request=request,
        submit_class="",
        fields=FormFields(form, embedded=SESSION_TIMEZONE_EMBEDS),
    ),
)
```

(The existing `scripts=Fragment(ModuleScript(...))` lines stay — `time-zone-row.js` arrives via the component's declared `Media`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `make test ARGS="tests/test_session_timezone_form.py tests/test_datetime_field_binding.py tests/test_rendered_pages.py tests/test_paths_return_200.py -x"`
Expected: PASS — new suite green; the binding/rendering/smoke suites confirm nothing else on the session form regressed. (If `test_datetime_field_binding.py`'s `_session_form_data` posts no zone keys, the fields are `required=False` and clean to `None` — no fixture edits needed.)

- [ ] **Step 6: Commit**

```bash
git add common/components/primitives.py games/forms.py games/views/session.py tests/test_session_timezone_form.py
git commit -m "feat: per-timestamp time-zone rows on the session form"
```

---

### Task 9: End-to-end — capture on load, capture on submit, finish stamps the zone

**Files:**
- Create: `e2e/test_time_zone_row_e2e.py`

**Interfaces:**
- Consumes: everything above; the `browser.new_context(timezone_id=...)` pattern already used by `e2e/test_session_finish_e2e.py` and `e2e/test_datetime_field_e2e.py`.

- [ ] **Step 1: Write the failing e2e tests**

Create `e2e/test_time_zone_row_e2e.py`:

```python
"""Per-timestamp zone rows in a real browser pinned to Asia/Tokyo: the capture
default, the always-visible trigger, and the finish flow stamping the end
zone."""

from datetime import UTC, datetime

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game, Session

BROWSER_TIME_ZONE = "Asia/Tokyo"


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


@pytest.fixture
def tokyo_page(live_server, browser, django_user_model):
    """A logged-in page whose browser reports Asia/Tokyo while the account's
    display zone stays the default UTC — a guaranteed mismatch."""
    django_user_model.objects.create_user(username="tester", password="secret123")
    context = browser.new_context(timezone_id=BROWSER_TIME_ZONE)
    page = context.new_page()
    _login(page, live_server)
    yield page
    context.close()


@pytest.fixture
def matched_zone_page(live_server, browser, django_user_model):
    """The mirror of `tokyo_page`: a browser in the account's own display zone,
    where nothing about the zones is remarkable."""
    django_user_model.objects.create_user(username="tester", password="secret123")
    context = browser.new_context(timezone_id="UTC")
    page = context.new_page()
    _login(page, live_server)
    yield page
    context.close()


def test_add_form_captures_the_browser_zone(tokyo_page, live_server):
    Game.objects.create(name="Hades")
    tokyo_page.goto(f"{live_server.url}{reverse('games:add_session')}")

    start_row = tokyo_page.locator(
        'time-zone-row[field-name="timestamp_start_timezone"]'
    )
    # Capture default: the browser zone landed in the submitted channel.
    expect(start_row.locator("[data-time-zone-value]")).to_have_value(BROWSER_TIME_ZONE)
    # And the one control is right there, naming what it captured. (There is
    # nothing to "auto-expand" on an add form: capture just made the effective
    # zone equal the browser zone, so no mismatch can exist here by
    # construction — the mismatch cue is exercised in the vitest suite.)
    trigger = start_row.locator('button[aria-haspopup="dialog"]')
    expect(trigger).to_be_visible()
    expect(trigger).to_contain_text(BROWSER_TIME_ZONE)


def test_submitting_the_form_persists_the_captured_zone(tokyo_page, live_server):
    Game.objects.create(name="Hades")
    tokyo_page.goto(f"{live_server.url}{reverse('games:add_session')}")

    game_search = tokyo_page.locator("input[data-search-select-search]").first
    game_search.fill("Hades")
    tokyo_page.locator('[data-search-select-option]:has-text("Hades")').first.click()
    tokyo_page.click('button[type="submit"]')
    tokyo_page.wait_for_url(f"{live_server.url}{reverse('games:list_sessions')}**")

    session = Session.objects.get()
    assert session.timestamp_start_timezone == BROWSER_TIME_ZONE


def test_trigger_is_visible_regardless_of_zone_match(matched_zone_page, live_server):
    """Visibility does not depend on a detected mismatch. A browser in the
    account's own display zone still gets the picker — that is the case a
    mismatch check can never surface, and the reason there is no reveal
    mechanic at all."""
    Game.objects.create(name="Hades")
    matched_zone_page.goto(f"{live_server.url}{reverse('games:add_session')}")

    start_row = matched_zone_page.locator(
        'time-zone-row[field-name="timestamp_start_timezone"]'
    )
    trigger = start_row.locator('button[aria-haspopup="dialog"]')
    expect(trigger).to_be_visible()
    # Opening it is a user action, never something the page did on load.
    trigger.click()
    expect(start_row.locator("input[data-search-select-search]")).to_be_visible()


def test_finish_stamps_the_end_zone(tokyo_page, live_server):
    game = Game.objects.create(name="Hades")
    session = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        timestamp_end=None,
    )
    tokyo_page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    row = tokyo_page.locator(f"#session-row-{session.pk}")
    row.locator("[data-finish]").click()
    # The row is rebuilt from the server response after the write commits, so
    # waiting for the finish button to vanish is a server-state assertion.
    expect(row.locator("[data-finish]")).to_have_count(0)

    session.refresh_from_db()
    assert session.timestamp_end_timezone == BROWSER_TIME_ZONE
    assert session.timestamp_end is not None
```

(Adjust the option-row selector to the one the search-select suite uses — `e2e/test_search_select_e2e.py` clicks result rows; copy its locator verbatim rather than inventing one. Same for the post-login URL glob: mirror `e2e/test_widgets_e2e.py`.)

- [ ] **Step 2: Rebuild assets and run to verify current failure**

Run: `make ts`
Run: `make test-e2e ARGS="-k time_zone_row"`
Expected: with Tasks 1–8 complete these should PASS; run them now to catch integration gaps (a failure here is an integration bug — fix within this task, not by weakening the assertions). If a test fails only on selectors, align them with the existing e2e suites named above.

- [ ] **Step 3: Commit**

```bash
git add e2e/test_time_zone_row_e2e.py
git commit -m "test: e2e coverage for zone capture, the always-visible picker, and finish stamping"
```

---

### Task 10: Full verification gate + screen-reader pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full gate**

Run: `make check`
Expected: green across lint, format-check, mypy, ts-check (incl. `gen-element-types` drift), vitest, and the entire pytest suite **including `e2e/`**. This exact command is the gate; `ARGS` subsets and `check-fast` do not count.

- [ ] **Step 2: Fix anything red, re-run until green**

Likely trouble spots, in order: mypy on the new `TypedChoiceField`/widget annotations (mirror the module's existing untyped-widget style — the file's widgets are not fully annotated, do not introduce a stricter island that fights `django-stubs`); mypy on `SessionOut`'s `context` resolver parameter (django-ninja types it loosely — annotate as the plan writes it and do not tighten); ruff import ordering; the vitest contract fixtures, whose `configWith()` must carry `session_time_zone_display` now that the regenerated `DateTimePresentationConfig` requires it; and `tests/test_search_select.py` / the FilterSelect serializer-contract test, which assert the *field* personality's markup is unchanged — `panel=True` must not leak into the default path.

- [ ] **Step 3: Screen-reader pass (manual, with the user)**

Not automatable — ask the user for an Orca pass and hand them this recipe:

1. `make dev` + `make devlogin`, log in as `admin`/`admin`.
2. Start Orca. Open **Add session**. Tab through the form: after the "Session start" segmented group, the time-zone row must announce as a button named "Start time zone: <zone>" with `haspopup dialog`; activating it must land focus in a search box announced with combobox semantics; picking an option must update the button's announced name.
3. Confirm each zone field announces **exactly one** control — the field name must not be read twice in a row (the double announcement two adjacent same-named controls produce, which is why the separate toggle button was cut), and the accessible name must change after a picker selection.
4. On the sessions list with the preference set to "The session's own time zone" and a Tokyo-zoned session present, confirm the Date cell reads out the zone label ("… 21:00 JST") rather than a bare time.
5. Report any double announcements or unnamed controls back before merge — this pass has caught real defects the automated suite missed on the previous datetime work.

- [ ] **Step 4: Final commit (if fixes were made) and stop**

```bash
git add -A
git commit -m "chore: green make check for per-timestamp timezones"
```

Do not push or open a PR without the user's go-ahead.

---

## Self-review (performed while writing; findings merged in)

**1. Spec coverage** — every checklist requirement maps to a task:

| Requirement | Task |
|---|---|
| Two nullable `Session` zone fields + migration, NULL = display zone, no backfill | 1 |
| `/api/timezones/search` copying `/api/platforms/groups` (the `list[StringOption]` feed) | 3 |
| Browser-zone capture at commit: form flow + finish/reset flow | 7 (form, capture default) + 8 (per-field gating) + 6 (`session-actions.ts`) |
| Two editable "Time zone" rows built from `ComboboxDropdown(ghost=True, content=SearchSelect(panel=True))` | 7 + 8 |
| Post-load mismatch cue on browser-vs-stored disagreement (decision #1) | 7 (element + vitest) |
| Always-reachable picker, independent of match state — one always-visible trigger, no reveal mechanic | 7 (component + Python test) + 9 (e2e proof on a matched-zone browser context) |
| A reachable route back to NULL (pinned `""` option + clear branch) | 3 + 7 |
| Account-level display preference beside `DISPLAY_TIME_ZONE` | 2 |
| Own-zone display **with zone label** (server + the client row rebuild, one server-computed label) | 4 + 5 + 6 |
| Calculation unaffected — regression-tested, not asserted in prose | 1 (`test_duration_calculated_ignores_stored_zones`, `test_date_bucketing_ignores_stored_zones`) |
| `GameStatusChange` explicitly excluded, with rationale | Design decision 5 + Task 1 guard test |
| Codegen impact (`make gen-element-types`, vitest + Python component tests) | 7 |
| Full `make check` gate, exact command | 10 |
| Orca screen-reader recipe | 10 |
| Anonymizer interaction stated explicitly (deliberate no-op) | Design decision 6 |

**2. Placeholder scan** — no TBD/TODO-later/"appropriate handling"/"similar to Task N" remain. Two intentional adapt-in-place notes survive (`ts/date-time-presentation.test.ts` contract-helper names, e2e option-row selector): both point at a named existing file to copy from, with the semantic expectations fully written out — the harness names are the only unknowns and inventing them blind would be worse.

**3. Type consistency** — checked name-by-name across tasks: `timestamp_start_timezone`/`timestamp_end_timezone` (model, API schemas, form fields, element `field-name`, e2e selectors); `SESSION_TIME_ZONE_DISPLAY` / values `"account"`/`"own"` (registry, resolver call in Task 4, config key `session_time_zone_display`, TS `sessionTimeZoneDisplay`); `TimeZoneRowProps {field_name, stored_zone, display_zone, capture_default}` = component kwargs = kebab attributes = `readTimeZoneRowProps` camelCase (`captureDefault`, `displayZone`); `FormFields(embedded=...)` consumed with `SESSION_TIMEZONE_EMBEDS` in Task 8's tests and views; `formatSessionTimeRange(startISO, endISO, startTimeZone, endTimeZone)` matches the Task 5 vitest calls and the Task 5 `session-row.ts` call site (**superseded** — that signature now takes two `SessionEndpointZone` objects; see round 2, fix 4). One inconsistency found and fixed during review: the Task 4 formatting rewrite originally labelled via the *endpoint* presentation's zone only when it differed from `presentation.timezone.key` but compared against a stale variable name — now `_endpoint_text` takes both presentations explicitly.

---

## Self-review round 2 (post adversarial-review fixes)

A three-agent adversarial review found real defects. Each is merged into the tasks above; this section records what changed and re-runs the three checks over the edited plan.

**1. What changed, and why**

1. **Task 3 precedent corrected.** `/api/games/search` returns `list[GameOption]` (an `int` `value`); the endpoint being written returns `list[StringOption]`. The real precedent is `/api/platforms/groups` (`games/api.py:183-189`) — same shape, string value. Prose, test docstring and code comment now say so; the filtering logic is unchanged.
2. **The separate toggle button is gone (Tasks 7, 8, 9, 10).** One always-visible ghost `ComboboxDropdown` trigger per zone field, no `hidden` wrapper, no `[data-time-zone-toggle]`, no `[data-time-zone-disclosure]`, no `setExpanded`. This removes at the root: the double screen-reader announcement of two adjacent same-named controls; the WCAG 2.5.3 visible-text-vs-accessible-name mismatch ("Zone" vs "Start time zone options"); a listener-duplication risk on `connectedCallback`; and the auto-expand path that could never fire on an add form (capture makes the zones equal by construction). The mismatch signal is now a `font-semibold` class on the trigger — the panel is never opened programmatically, because auto-opening a dialog on load steals focus from a screen-reader user on every page whose zones happen to differ.
3. **`capture_default` renders as an explicit string.** `_attrs_from_kwargs` (`common/components/primitives.py:136-155`) drops a `False` kwarg entirely and renders `True` as the bare boolean form, while the generated reader is `getAttribute("capture-default") === "true"` — so a raw bool would emit nothing in the common case. `TimeZoneRow` now passes `capture_default="true" if capture_default else "false"`, matching `active="true" if active else "false"` in `common/components/custom_elements.py`. The Python parameter and the `TimeZoneRowProps` field stay typed `bool`; every test still asserts the plain substrings `capture-default="true"` / `"false"`.
4. **One zone label, computed server-side (Tasks 4, 5, 6).** `Intl`'s `timeZoneName: "short"` says "GMT+9" where Python's `tzname()` says "JST" — the same row would be worded differently depending on whether the server rendered it or the client rebuilt it after a finish/reset PATCH. `_zone_label` is now the public `zone_label()`; `SessionOut` gains `timestamp_start_timezone_label` / `timestamp_end_timezone_label`, resolved per request through django-ninja's serialization context (verified: `Resolver._takes_context` in `ninja/schema.py`, `context={"request": …}` in `ninja/operation.py:232/423`); the client appends the string verbatim. `zoneAbbreviation()` and `usableTimeZone()` are not written.
5. **`SearchSelect(panel=True)` added as its own TDD step (Task 7, Step 3).** Hosting a bare `SearchSelect` in a `ComboboxDropdown` panel was not a supported composition: both precedents (`PresetSelect`, `FilterSelect(layout="panel")`) also set `always_visible=True` and the module's static panel classes. The flag reuses `_PANEL_CONTAINER_CLASS` / `_PANEL_SEARCH_CLASS` / `_PANEL_OPTIONS_CLASS`; no new constants.
6. **A route back to NULL.** Every add-form session captures a zone, so the form's `("", "Account display zone")` choice was validated-but-unreachable. `/api/timezones/search` now pins `{"value": "", "label": "Use account display zone"}` on the browse-all response only (a filtered query is asking for zones), and the element treats a `""` pick as an explicit clear, restoring the display-zone fallback label.
7. **Capture is gated per field (Task 8).** A uniform `capture_default=self.instance.pk is None` stamped an *open* session's end zone at creation time, which then went stale when the session was finished elsewhere hours later (the finish PATCH refreshes it, but a session finished by editing the form would not). Resolution, matching the spec's "at the moment each timestamp is committed": the start captures unconditionally on a new record; the end captures only when an end timestamp actually has a bound value. `test_unbound_form_renders_two_capture_default_rows` is replaced by `test_unbound_add_form_captures_the_start_zone_only` (1 capture row) plus `test_an_end_timestamp_on_the_add_form_captures_its_zone_too` (2).
8. **A labelled endpoint carries its date.** Projecting an end into another zone can cross midnight; "06:00 JST" after "20:00" reads as the same evening. Both renderers now use the full `"datetime"` style whenever a label is shown, proven by `test_a_labelled_end_carries_its_own_date_across_the_date_line` (Python: `2026-07-01 14:00 — 2026-07-02 06:00 JST`) and the matching vitest case.

**2. Placeholder scan** — still clean: no TBD / "appropriate handling" / "similar to Task N". The adapt-in-place notes shrank to one (the e2e option-row selector, which points at `e2e/test_search_select_e2e.py` to copy verbatim): the vitest contract helpers are no longer a guess — `configWith`, `validConfig`, `installConfig`, `alteredConfig` and `importFormatter` are the file's real names (`ts/date-time-presentation.test.ts:70-110`) and the snippets call them directly. Grepped the whole file for `data-time-zone-toggle`, `data-time-zone-disclosure`, `setExpanded`, `toggleButton`, `zoneAbbreviation`, `usableTimeZone`: the only surviving mentions are the two prose lines that state these are deliberately *not* built.

**3. Type and name consistency across the edited files**

- `SessionEndpointZone { zone, label }` — declared and exported in `ts/date-time-presentation.ts` (Task 5, step 3), imported by name in `ts/session-row.ts` (same step), and constructed inline in every Task 5 vitest case. `NO_ENDPOINT_ZONE` is module-private and only backs the two default arguments.
- `timestamp_start_timezone_label` / `timestamp_end_timezone_label` — identical spelling in `SessionOut` (Task 6), the `SessionOut` interface in `ts/session-row.ts` (Task 5), the Task 6 pytest assertions, and the Task 5 `session-row.test.ts` fixture note. Absent from `SessionUpdate`: they are derived output, never input.
- `zone_label(value, zone)` — defined public in `games/formatting.py` (Task 4), imported by `games/api.py` (Task 6). No `_zone_label` reference survives.
- `capture_default` — `bool` in `TimeZoneRowProps` and in the `TimeZoneRow`/`TimeZoneRowWidget` signatures; `"true"`/`"false"` strings only at the element-builder boundary; `captureDefault` (boolean) on the TS side via the generated reader.
- `panel` — `SearchSelect(..., panel=True)` in Task 7 step 3's tests, step 3's implementation, and step 4's `TimeZoneRow`.
- `session_time_zone_display` (wire) / `SESSION_TIME_ZONE_DISPLAY` (registry) / `sessionTimeZoneDisplay` (compiled) — unchanged from round 1 and re-verified against the new Task 5 snippets, which now also add the key to the test file's `configWith()` because Task 4 makes it a required member of the regenerated `DateTimePresentationConfig`.

**4. One consequence to be aware of while implementing** — deleting `usableTimeZone()` means a stored zone name this *browser's* tzdata does not know no longer degrades to the account zone: `Temporal` throws, `formatSessionTimeRange` reports and returns `null`, and `ts/session-row.ts` leaves the server-rendered cell text in place. That is the correct value rather than a client guess, and it is asserted by the "returns null when the runtime does not know the stored zone" vitest case — but it is a behaviour change from round 1's design, recorded here rather than buried in a diff.
