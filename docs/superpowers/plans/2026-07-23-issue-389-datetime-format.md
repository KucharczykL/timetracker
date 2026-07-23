# Issue #389 — Per-user date/time format Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Allow each account to select the numeric date order, separators, and clock cycle used throughout Timetracker, with ISO-local 2026-07-02 19:05 as the default.

**Architecture:** DATETIME_FORMAT is a USER-scoped setting backed by a nullable UserPreferences.datetime_format column. The existing resolver supplies its effective stable identifier on each rendered request. date_time_presentation_for_request maps it to one immutable DateTimeFormatProfile and serializes the same existing version-1 browser contract, allowing the browser session row formatter to stay in lockstep without an API or TypeScript protocol change.

**Tech Stack:** Django 6 models, migrations, forms, Ninja API; Python date/time presentation; Temporal TypeScript and Vitest; pytest and Playwright.

## Global constraints

- Supported values are only iso_8601, dmy_24h, and mdy_12h. Registry validation rejects any other value before it reaches storage.
- iso_8601 is the built-in fallback: local display-zone YYYY-MM-DD HH:mm, without a T or UTC offset.
- Resolution is personal override, then the existing shared USER-setting chain: environment/file/INI (if configured), SiteSetting DB row, then iso_8601. A null write clears only the personal override. The brief and tests must preserve this existing env precedence rather than silently redefining it.
- Locale remains responsible for month names and localized AM/PM labels. This preference controls numeric order, separators, and hour cycle only.
- Keep DateTimePresentationConfig at version 1 with exactly the same fields. Do not emit a profile ID or version bump.
- Keep the generic /api/settings/user endpoint structurally unchanged. Registry validation supplies the new behavior.
- The Settings control live-saves and reloads after success so server markup and the root browser contract update together.
- Every make, pnpm, and uv command must run through direnv exec .; completion requires a fresh green direnv exec . make check.

## Supported profiles

| Identifier | Date order | Clock | datetime example |
|---|---|---|---|
| iso_8601 | YYYY-MM-DD | 24-hour | 2026-07-02 19:05 |
| dmy_24h | DD/MM/YYYY | 24-hour | 02/07/2026 19:05 |
| mdy_12h | MM/DD/YYYY | 12-hour | 07/02/2026 07:05 PM |

All profiles retain segmented_date_separator "-" because the date-range segmented input uses the same profile; visible date strings use the separator in the table.

## Files and responsibilities

| File | Responsibility |
|---|---|
| timetracker/settings_registry.py | Stable choices, strict validator, USER/LIVE registry entry, ISO fallback. |
| games/models.py | Nullable typed preference and resolver mapping. |
| games/migrations/0032_userpreferences_datetime_format.py | Add the nullable column with no backfill. |
| games/admin.py | Keep the typed field visible and validated in the admin editing path. |
| common/date_time_presentation.py | Map resolved profile ID to immutable presentation profile. |
| games/views/settings.py | Render a live, reload-after-save select with an inherited effective-label sentinel. |
| tests/test_settings_registry.py, tests/test_user_preferences_resolver.py, and tests/test_settings_resolver.py | Model, resolver precedence/validation, registry key sets, and admin-form guards. |
| tests/test_date_time_presentation.py, tests/test_session_formatting.py, ts/date-time-presentation.test.ts, ts/session-row.test.ts, tests/test_version_timestamp.py, e2e/test_session_finish_e2e.py | Server formatting, root contract, and browser session-row parity, including existing DMY assumptions that must be made explicit or updated to ISO. |
| tests/test_settings_api.py, tests/test_settings_page.py, ts/elements/live-setting-fields.test.ts, e2e/test_settings_page_e2e.py | Generic API, preference UI, reload behavior, browser persistence. |
| docs/configuration.md and CHANGELOG.md | User-facing precedence, supported profiles, and ISO default. |

---

### Task 1: Persist and resolve DATETIME_FORMAT

**Files:**
- Modify: timetracker/settings_registry.py, games/models.py, games/admin.py
- Create: games/migrations/0032_userpreferences_datetime_format.py
- Test: tests/test_settings_registry.py, tests/test_user_preferences_resolver.py

**Produces:** DATETIME_FORMAT_CHOICES, get_definition("DATETIME_FORMAT"), and UserPreferences.datetime_format. Existing generic set_user_preference and resolve_for_user_with_origin paths continue to work without special cases.

- [ ] **Step 1: Write failing registry and resolver tests.**

    def test_datetime_format_defaults_to_iso_8601(user):
        result = resolve_for_user_with_origin(user, "DATETIME_FORMAT")
        assert result.value == "iso_8601"
        assert result.source is SettingSource.DEFAULT

    def test_datetime_format_personal_clear_inherits_site_default(
        user, django_capture_on_commit_callbacks
    ):
        _write_setting(
            django_capture_on_commit_callbacks, "DATETIME_FORMAT", "dmy_24h"
        )
        _set_user(
            django_capture_on_commit_callbacks, user, "DATETIME_FORMAT", "mdy_12h"
        )
        _set_user(django_capture_on_commit_callbacks, user, "DATETIME_FORMAT", None)

        result = resolve_for_user_with_origin(user, "DATETIME_FORMAT")
        assert (result.value, result.source) == (
            "dmy_24h",
            SettingSource.DATABASE,
        )

    @pytest.mark.parametrize("value", ["ISO_8601", "rfc_3339", "", 1, True])
    def test_datetime_format_rejects_unsupported_values(user, value):
        with pytest.raises(ValidationError):
            set_user_preference(user, "DATETIME_FORMAT", value)

Update USER_KEYS, EXPECTED_KEYS, registry documentation/counts, and any registry introspection assertions; assert scope USER and timing LIVE, assert the model field is nullable, and assert the exact public choices.

- [ ] **Step 2: Verify the tests fail for the intended reason.**

Run:

    direnv exec . uv run --frozen pytest tests/test_settings_registry.py tests/test_user_preferences_resolver.py -q

Expected: DATETIME_FORMAT is unregistered or UserPreferences has no datetime_format column.

- [ ] **Step 3: Add strict registry metadata, typed storage, migration, and admin support.**

In timetracker/settings_registry.py, define choices alongside FORMAT_LOCALE_CHOICES and normalize only case/outer whitespace:

    DATETIME_FORMAT_CHOICES: Final[tuple[tuple[str, str], ...]] = (
        ("iso_8601", "ISO 8601"),
        ("dmy_24h", "DD/MM/YYYY, 24-hour"),
        ("mdy_12h", "MM/DD/YYYY, 12-hour"),
    )
    _DATETIME_FORMAT_VALUES: Final[frozenset[str]] = frozenset(
        value for value, _label in DATETIME_FORMAT_CHOICES
    )

    def _validate_datetime_format(value: object) -> str:
        normalized = value.strip().lower() if isinstance(value, str) else value
        if not isinstance(normalized, str) or normalized not in _DATETIME_FORMAT_VALUES:
            choices = ", ".join(sorted(_DATETIME_FORMAT_VALUES))
            raise ValidationError(
                f"Date/time format must be one of {choices} (got {value!r})."
            )
        return normalized

Register DATETIME_FORMAT as USER/LIVE with label Date/time format, widget select, this validator, ISO fallback, and help text explaining numeric date order and clock-cycle scope.

In games/models.py add the mapping and nullable column:

    "DATETIME_FORMAT": "datetime_format"

    datetime_format = models.CharField(
        max_length=20, null=True, blank=True, default=None
    )

Create migration 0032 with dependency on 0031_userpreferences_presentation_preferences and one AddField. Do not backfill: NULL is the deliberate inherit state.

In games/admin.py add the field/key to UserPreferencesForm._COLUMN_KEYS, Meta.fields, the CharField blank-to-None list, and UserPreferencesAdmin.list_display. Audit the existing presentation fields too: the current admin form does not yet expose DISPLAY_TIME_ZONE or DATE_FORMAT_LOCALE, so do not assume its typed-field list is complete. Add an explicit form test proving DATETIME_FORMAT is normalized through the registry and blank clears to NULL; this prevents admin from becoming an unvalidated back door.

- [ ] **Step 4: Verify the persistence/resolver slice.**

Run:

    direnv exec . uv run --frozen pytest tests/test_settings_registry.py tests/test_user_preferences_resolver.py -q

Expected: pass, including personal → env/INI/file → site DB → ISO precedence, NULL persistence, invalid-value rejection, and registry/introspection key coverage. Include an anonymous-user resolution test so the request formatter has a documented non-user fallback.

- [ ] **Step 5: Commit the slice.**

    git add timetracker/settings_registry.py games/models.py games/migrations/0032_userpreferences_datetime_format.py games/admin.py tests/test_settings_registry.py tests/test_user_preferences_resolver.py
    git commit -m "feat: add datetime format preference"

### Task 2: Select registered profiles in the presentation layer

**Files:**
- Modify: common/date_time_presentation.py
- Test: tests/test_date_time_presentation.py, tests/test_session_formatting.py, ts/date-time-presentation.test.ts

**Consumes:** the validated string from resolve_for_user(request.user, "DATETIME_FORMAT").

**Produces:** an immutable ID-to-DateTimeFormatProfile lookup and a DateTimePresentation whose to_client_config shape remains identical.

- [ ] **Step 1: Write failing formatting, root-contract, and client-parity tests.**

    @pytest.mark.parametrize(
        ("profile_id", "expected"),
        [
            ("iso_8601", "2026-07-02 19:05"),
            ("dmy_24h", "02/07/2026 19:05"),
            ("mdy_12h", "07/02/2026 07:05 PM"),
        ],
    )
    def test_registered_profiles_format_datetime(profile_id, expected):
        presentation = DateTimePresentation(
            profile=date_time_format_profile(profile_id),
            locale="en-us",
            timezone=ZoneInfo("UTC"),
        )
        value = datetime(2026, 7, 2, 19, 5, tzinfo=UTC)
        assert presentation.format(value, "datetime") == expected

Also test every semantic style (date, time, datetime, month, month_year) under each profile. Pin mdy_12h midnight as 12:05 AM and noon as 12:05 PM. Write request tests for personal mdy_12h, anonymous ISO fallback, and an environment-selected profile; check the root profile is correct and contains no profile_id. Make the Vitest default contract ISO, then add DMY and MDY/12-hour session-range examples matching the server literals. Search all consumers of DEFAULT_DATE_TIME_FORMAT_PROFILE and all date/time literals before editing; update existing Python, TypeScript, and e2e fixtures whose expected default is intentionally changing, or replace them with explicit profile construction when they are testing an unrelated behavior.

- [ ] **Step 2: Verify the formatter tests fail under the old singleton profile.**

Run:

    direnv exec . uv run --frozen pytest tests/test_date_time_presentation.py tests/test_session_formatting.py -q
    direnv exec . pnpm exec vitest run ts/date-time-presentation.test.ts

Expected: ISO lookup/default is missing and the current default still produces DMY output; any newly added consumer-regression tests should fail for the old singleton contract.

- [ ] **Step 3: Implement immutable profiles and per-request selection.**

Add a profile map for the three identifiers. All profiles have two-digit day/month, four-digit year, colon time separator, single-space date/time separator, and segmented dash. Vary only date-part order, visible date separator, and hour_cycle according to the table. Retain DEFAULT_DATE_TIME_FORMAT_PROFILE as an ISO alias if unrelated unit fixtures import it; update request-default assertions and fixtures that intentionally describe the application default rather than silently changing the meaning of unrelated tests.

Expose a narrow lookup that fails loudly for a programming error:

    def date_time_format_profile(profile_id: str) -> DateTimeFormatProfile:
        try:
            return DATE_TIME_FORMAT_PROFILES[profile_id]
        except KeyError as error:
            raise ValueError(
                f"Unsupported date/time format {profile_id!r}."
            ) from error

In date_time_presentation_for_request(), resolve the user's DATETIME_FORMAT with resolve_for_user (or resolve_for_user_with_origin when the source is needed), require a string, and pass the lookup result to DateTimePresentation. Confirm the resolver's existing env/file/INI → SiteSetting → default behavior with a request-level test. Leave timezone activation and request formatting locale unchanged: this preference is not a Django-global setting and does not belong in timezone middleware.

Keep DateTimePresentation.format and to_client_config structurally unchanged; their profile contents are the browser contract. The existing TypeScript compiler already uses date_parts, separators, hour_cycle, and localized day_periods.

- [ ] **Step 4: Regenerate type declarations only as a drift check.**

Run:

    direnv exec . make gen-element-types
    git diff -- ts/generated/date-time-presentation.ts

Expected: no semantic generated change because the version-1 contract shape is unchanged. Revert only unrelated generated drift if it appears.

- [ ] **Step 5: Verify server/browser presentation parity.**

Run:

    direnv exec . uv run --frozen pytest tests/test_date_time_presentation.py tests/test_session_formatting.py -q
    direnv exec . pnpm exec vitest run ts/date-time-presentation.test.ts

Expected: pass for all three profiles; server markup and dynamic session rows agree.

- [ ] **Step 6: Commit the presentation slice.**

    git add common/date_time_presentation.py tests/test_date_time_presentation.py tests/test_session_formatting.py ts/date-time-presentation.test.ts ts/generated/date-time-presentation.ts
    git commit -m "feat: resolve datetime presentation profiles per user"

### Task 3: Add the live Preferences control and test the unchanged API

**Files:**
- Modify: games/views/settings.py
- Test: tests/test_settings_api.py, tests/test_settings_page.py, ts/elements/live-setting-fields.test.ts, e2e/test_settings_page_e2e.py

**Consumes:** DATETIME_FORMAT_CHOICES, resolver origins, and the existing generic live-setting custom element.

**Produces:** a datetime_format select with data-setting-key DATETIME_FORMAT and data-reload-after-save, backed by PATCH /api/settings/user/DATETIME_FORMAT.

- [ ] **Step 1: Write failing API and page tests.**

    def test_user_datetime_format_patch_and_clear_to_site_default(auth_client):
        set_site_setting("DATETIME_FORMAT", "dmy_24h")
        saved = _patch(
            auth_client, _user_patch_url("DATETIME_FORMAT"), "mdy_12h"
        )
        cleared = _patch(auth_client, _user_patch_url("DATETIME_FORMAT"), None)

        assert (saved.json()["value"], saved.json()["source"]) == (
            "mdy_12h",
            "user",
        )
        assert (cleared.json()["value"], cleared.json()["source"]) == (
            "dmy_24h",
            "database",
        )

    def test_settings_page_renders_datetime_format_and_inherit_label(
        auth_client, user
    ):
        UserPreferences.objects.create(user=user, datetime_format="mdy_12h")
        html = auth_client.get(reverse("games:settings")).content.decode()

        assert '<select name="datetime_format"' in html
        assert '<option value="mdy_12h" selected>MM/DD/YYYY, 12-hour</option>' in html
        assert 'data-setting-key="DATETIME_FORMAT"' in html
        assert "data-reload-after-save" in html

Add invalid API cases for every unsupported value. Add an unset test requiring exactly:

    <option value="" selected>Use site default (ISO 8601)</option>

Extend the TypeScript live-field fixture with DATETIME_FORMAT and assert a successful save invokes reloadAfterSettingSave. Extend the desktop/mobile Playwright presentation test: select mdy_12h, wait for the reloaded root contract to report month first and h12, reload once more, and assert the choice persists.

- [ ] **Step 2: Verify the focused UI/API tests fail because the control is absent.**

Run:

    direnv exec . uv run --frozen pytest tests/test_settings_api.py tests/test_settings_page.py -q
    direnv exec . pnpm exec vitest run ts/elements/live-setting-fields.test.ts
    direnv exec . uv run --frozen pytest e2e/test_settings_page_e2e.py -q

Expected: missing datetime_format control/selection or key.

- [ ] **Step 3: Add the select following existing inherited-control conventions.**

In games/views/settings.py:

1. Import DATETIME_FORMAT_CHOICES and map datetime_format to DATETIME_FORMAT in _FIELD_KEYS.
2. Add datetime_format = forms.ChoiceField(required=False, choices=()).
3. Add default_datetime_format_label: str = "ISO 8601" to UserSettingsForm.__init__.
4. Assign the blank option then the registry choices:

    datetime_format_field.choices = (
        ("", f"Use site default ({default_datetime_format_label})"),
        *DATETIME_FORMAT_CHOICES,
    )

5. Add _datetime_format_label() using dict(DATETIME_FORMAT_CHOICES), resolve the shared DATETIME_FORMAT in _form_and_states(), and pass that label to the form. A bare installation therefore renders the exact ISO sentinel; a site override accurately names its effective profile.
6. Add datetime_format to the data-reload-after-save field tuple. The generic states loop already marks every non-theme preference live-save.

Do not add endpoint code or a new Ninja schema: the existing generic listing, PATCH, null clear, and string response support this key automatically once it is registered. Extend generic registry/API tests to assert the new key appears with its choices represented by the existing registry-driven UI, and cover an environment-backed effective value in the inherited-label test.

- [ ] **Step 4: Verify API, page, TypeScript, and browser behavior.**

Run:

    direnv exec . uv run --frozen pytest tests/test_settings_api.py tests/test_settings_page.py -q
    direnv exec . pnpm exec vitest run ts/elements/live-setting-fields.test.ts
    direnv exec . uv run --frozen pytest e2e/test_settings_page_e2e.py -q

Expected: pass; clearing returns the actual inherited source and a successful browser save reloads into the active profile.

- [ ] **Step 5: Commit the settings slice.**

    git add games/views/settings.py tests/test_settings_api.py tests/test_settings_page.py ts/elements/live-setting-fields.test.ts e2e/test_settings_page_e2e.py
    git commit -m "feat: add datetime format setting control"

### Task 4: Document and run the repository gate

**Files:**
- Modify: docs/configuration.md, CHANGELOG.md
- Test: migration/codegen sanity checks and full make check.

- [ ] **Step 1: Update configuration documentation.**

In docs/configuration.md, add DISPLAY_TIME_ZONE, DATE_FORMAT_LOCALE, and DATETIME_FORMAT to the USER-scoped runtime-settings list. In Personal settings, explain the three formats, that a user override wins over the site default and ISO fallback, that clearing inherits again, and that locale still provides month/day-period language rather than selecting numeric order.

- [ ] **Step 2: Update the Unreleased changelog.**

Under New, add a concise entry that dates now default to ISO-local display and accounts can choose DMY 24-hour or MDY 12-hour formats.

- [ ] **Step 3: Verify documentation, migration, and type-codegen integrity.**

Run:

    git diff --check
    direnv exec . uv run --frozen python manage.py makemigrations --check --dry-run
    direnv exec . uv run --frozen pytest tests/test_ts_codegen.py -q

Expected: all exit successfully; no missing migration or generated type drift. Before this check, verify the migration dependency is the actual leaf migration (currently expected to be 0031, but derive it from the migration graph rather than assuming the filename).

- [ ] **Step 4: Run the required complete gate.**

Run:

    direnv exec . make check

Expected: exit 0, covering formatting/lint/mypy, TypeScript, Vitest, pytest, and e2e.

- [ ] **Step 5: Review the complete diff and commit documentation.**

    git diff --check
    git status --short
    git add docs/configuration.md CHANGELOG.md
    git commit -m "docs: describe datetime format preferences"

## Final acceptance checklist

- [ ] A new account with no site row formats a UTC instant in UTC as 2026-07-02 19:05 and emits year/month/day plus h23 in the root contract.
- [ ] Site dmy_24h is inherited through NULL; personal mdy_12h wins; clearing restores dmy_24h.
- [ ] Invalid IDs are rejected by resolver/API/admin validation and do not write storage.
- [ ] Server formatter, root browser contract, and TypeScript session-row formatter agree for ISO, DMY/24-hour, and MDY/12-hour—including midnight/noon labels.
- [ ] The Preferences select displays its inherited effective format, PATCHes via the unchanged endpoint, clears to inherit, and reloads after a successful save.
- [ ] The browser contract remains version 1 with its previous field shape.
- [ ] direnv exec . make check has fresh green evidence before completion.
