# OWN-02 Library Ownership Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Perform the single rehearsed offline cutover from globally scoped private data to a complete one-library-per-user ownership, preference, currency, and isolation boundary.

**Architecture:** One migration adds final ownership fields, selects either a pristine zero-User install or the versioned-manifest one-User legacy cutover, assigns the production library only on the legacy path, splits preferences, and installs final constraints without a temporary claim state. Runtime code resolves `request.user.library`, passes it explicitly, and uses thin queryset helpers. A per-library `PurchaseConversionState` provides atomic transitional FX publication until #728 replaces it.

**Tech Stack:** Django 6, PostgreSQL 18, Django Ninja, Django-Q2, htpy server components, pytest/pytest-django, Vitest/TypeScript.

## Global Constraints

- Read `docs/superpowers/specs/2026-08-13-user-library-ownership-cutover-design.md` before editing.
- #629 and #639 are hard prerequisites.
- The only supported populated legacy database has exactly one User and the inspected global data; it requires a version-1 manifest at `TIMETRACKER_OWN_CUTOVER_MANIFEST`.
- A pristine zero-User/zero-legacy-row database migrates without a manifest so fresh installs can apply the complete history; zero Users with orphaned legacy state aborts.
- Never commit a production dump or manifest. Retain the protected hash-matched pair and reconciliation output together.
- Abort on every input shape or manifest mismatch not explicitly covered above.
- No temporary legacy library, owner fallback, claim command/configuration, compatibility mode, or automatic repair.
- Normal code receives a library explicitly; no thread-local or selected active-library state.
- Cross-library object identifiers return 404 and staff/superusers have no normal bypass.
- Keep default managers unscoped; use `.for_library(library)` and Platform `.visible_to(library)` deliberately.
- Preserve original Purchase facts and publish converted cache rows atomically.
- `PurchaseConversionState` is a bridge that #728 must remove.
- Keep existing individual deletion semantics; add only whole-library cascade behavior.
- Keep the normal parallel `PYTEST_WORKERS`; run full verification through the managed hidden Windows process required by `AGENTS.md`.

---

### Task 1: Lock the production assumptions in migration tests

**Files:**
- Create: `tests/test_library_cutover_migration.py`
- Create: `games/migrations/0004_user_library_ownership_cutover.py`

**Interfaces:**
- Consumes: migration state `0003_userlibrary`.
- Produces: reusable `MigrationExecutor` fixtures for the success and refusal cases.

- [x] **Step 1: Write the successful legacy-shape fixture**

Build the pre-migration state with exactly one User, its existing
UserPreferences, the seven exact built-in Platforms, one unmatched custom
Platform, and representative Game/Purchase/Session/Device/PlayEvent/
GameStatusChange/FilterPreset links. Use the exact built-in pairs from
`games/fixtures/platforms.yaml`:

```python
BUILT_IN_PLATFORMS = {
    ("Steam", "PC"),
    ("Xbox Gamepass", "PC"),
    ("Epic Games Store", "PC"),
    ("Playstation 5", "Playstation"),
    ("Playstation 4", "Playstation"),
    ("Nintendo Switch", "Nintendo"),
    ("Nintendo 3DS", "Nintendo"),
}
FIRST_COMMIT_AT = datetime.fromisoformat("2022-12-31T14:18:27+01:00")
```

At the Task 1 checkpoint, assert that the manifest-matched User gets exactly
one `UserLibrary` with the exact timestamp while all legacy rows and settings
remain otherwise unchanged; Task 2 extends this same fixture with final owner,
Platform, Session, FilterPreset, constraint, and settings-split assertions when
those fields exist. Build a complete version-1 manifest in `tmp_path`, point
`TIMETRACKER_OWN_CUTOVER_MANIFEST` at it, and include every exact field from the
spec's `source`, `expected_legacy_state`, `observed_setting_state`,
`operator_confirmed_settings`, and `observed_purchase_state` objects. The
success case must prove the migration uses the manifest rather than a fixture
constant by changing a non-default User
id, username, currency, Device, and representative count.

Also add a pristine-install success case with zero Users, every legacy
private/link/preference/old-setting table empty, and the manifest environment
variable absent. Assert it creates no `UserLibrary` and reaches the final
schema so later normal User provisioning remains responsible for creation.

- [x] **Step 2: Write fresh-install and refusal matrices before migration code**

Parameterize zero-User orphan cases for every independently representable
legacy root family and for dependent/link families together with their required
non-User parents. Keep UserPreferences and FilterPreset in the exhaustive
`legacy_rows_exist()` enumeration, but exercise them through the one-User
manifest/count refusal path: their database foreign keys cascade with User, so
they cannot honestly survive as zero-User rows without disabling constraints.
Do not create synthetic impossible database states. Also cover two Users, a null Session
Game, a saved Session Game-null predicate, ambiguous built-in Platform rows,
and an incomplete or mixed converted-price cache. Do not invent a
"cross-library" legacy fixture: migration state `0003` has no ownership columns,
and all valid relationships necessarily resolve to the one selected library.
Likewise, library-scoped Game uniqueness is a Task 2 final-schema contract, not
a representable Task 1 preflight failure.

Add manifest cases for an absent path on the one-User branch, missing file,
invalid JSON, unknown `schema_version`, missing and wrong-typed fields, changed
User id/username, every row-count mismatch, effective currency/source/lock
mismatch, raw preference/setting row presence/value drift, changed default
Device, original-currency distribution drift, and converted-cache
currency/completeness drift. Each case must assert a specific `RuntimeError`
naming the violated invariant and no partial ownership
assignment. A dump hash mismatch is caught by the restore/runbook tooling;
the migration emits the recorded hash but cannot read the archive itself.

- [x] **Step 3: Run the migration tests and confirm they fail at the missing migration**

Run: `make test-fast ARGS="tests/test_library_cutover_migration.py -x"`

Expected: FAIL because migration `0004_user_library_ownership_cutover` is absent.

- [x] **Step 4: Add a migration skeleton with named preflight functions**

Keep migration helpers inside the migration file so historical execution does
not import mutable runtime code:

```python
MANIFEST_ENV = "TIMETRACKER_OWN_CUTOVER_MANIFEST"


def select_cutover_input(apps):
    User = apps.get_model("auth", "User")
    user_count = User.objects.count()
    if user_count == 0:
        if legacy_rows_exist(apps):
            raise RuntimeError("OWN cutover found orphaned legacy state")
        return None
    if user_count != 1:
        raise RuntimeError("OWN cutover requires zero or exactly one User")
    return load_and_validate_manifest(apps, os.environ.get(MANIFEST_ENV))


def backfill_known_library(apps, manifest) -> None:
    UserLibrary = apps.get_model("games", "UserLibrary")
    UserLibrary.objects.create(
        user_id=manifest["expected_legacy_state"]["user_id"],
        created_at=FIRST_COMMIT_AT,
    )


def run_cutover(apps, schema_editor) -> None:
    manifest = select_cutover_input(apps)
    if manifest is None:
        return
    validate_legacy_shape(apps, manifest)
    backfill_known_library(apps, manifest)
    reconcile_preflight(apps, manifest)
```

Implement `legacy_rows_exist()` as an explicit enumeration of every legacy
private, link, preference, and old-setting model/table; do not infer emptiness
from only Sessions or Purchases. `load_and_validate_manifest()` uses only the
standard library plus historical models, validates the complete typed v1
schema before returning, and produces field-specific errors.

Task 1's migration checkpoint contains only
`RunPython(run_cutover, migrations.RunPython.noop)`: complete validation,
one known-library backfill, and reconciliation that proves the old rows remain
unchanged. Task 2 adds nullable ownership/preference/conversion fields around
that operation, extends `run_cutover()` with assignment/settings splitting,
and installs final constraints. The fresh path returns before any data
creation and still reaches the migration leaf in both checkpoints.

The reverse functions are intentionally no-op because the documented recovery
path is restoring the pre-cutover backup, not synthesizing global ownership.

- [x] **Step 5: Run the focused migration contract to GREEN**

Run: `make test-fast ARGS="tests/test_library_cutover_migration.py -x"`

Expected: PASS for legacy success, pristine success, and every refusal case.

- [x] **Step 6: Commit the executable migration contract**

```bash
git add tests/test_library_cutover_migration.py games/migrations/0004_user_library_ownership_cutover.py
git commit -m "test: lock library cutover preconditions (#630)"
```

### Task 2: Add final ownership and preference models

**Files:**
- Modify: `games/models.py`
- Modify: `games/migrations/0004_user_library_ownership_cutover.py`
- Modify: `tests/test_library_cutover_migration.py`
- Create: `tests/test_library_models.py`

**Interfaces:**
- Produces: `UserLibraryPreferences`, `PurchaseConversionState`, and
  `.for_library()`/`.visible_to()` queryset contracts.

- [x] **Step 1: Write failing final-model tests**

Cover the direct/derived ownership table, `UserLibraryPreferences.library` as
its primary key, no-op-aware preference timestamp updates, required
`Session.game`, Game per-library uniqueness, Platform shared/private visibility,
and case-insensitive trimmed Platform duplicate rejection.

Extend Task 1's successful historical fixture to assert every direct owner,
built-in/shared and custom/private Platform classification, required Session
Game, FilterPreset library ownership, final uniqueness constraints, approved
settings split, and complete `PurchaseConversionState` seeding.
Exercise cross-library relationship rejection and library-scoped Game
uniqueness against the final schema in this task and the later scoped-path/audit
tasks; neither state can be constructed honestly at migration state `0003`.

```python
assert Game.objects.for_library(library_a).count() == 1
assert Session.objects.for_library(library_a).count() == 1
assert Platform.objects.visible_to(library_a).contains(shared)
assert Platform.objects.visible_to(library_a).contains(private_a)
assert not Platform.objects.visible_to(library_a).contains(private_b)
```

- [x] **Step 2: Run the model tests and confirm missing fields/helpers**

Run: `make test-fast ARGS="tests/test_library_models.py -x"`

Expected: FAIL on missing ownership fields and querysets.

- [x] **Step 3: Implement the model/queryset surface**

Add direct required `library` FKs to Game, Purchase, Device, and FilterPreset;
add nullable `library` to Platform. Replace FilterPreset's User uniqueness with
`(library, mode, name)`. Add derived querysets:

```python
class LibraryOwnedQuerySet(models.QuerySet):
    def for_library(self, library):
        return self.filter(library=library)


class SessionQuerySet(models.QuerySet):
    def for_library(self, library):
        return self.filter(game__library=library)


class PlatformQuerySet(LibraryOwnedQuerySet):
    def visible_to(self, library):
        return self.filter(Q(library__isnull=True) | Q(library=library))
```

Give PlayEvent and GameStatusChange equivalent derived `.for_library()`
querysets. Do not replace default managers with pre-scoped managers.

Implement:

```python
class UserLibraryPreferences(models.Model):
    library = models.OneToOneField(
        UserLibrary,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    default_device = models.ForeignKey(
        Device, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(default=timezone.now)

    def set_default_device(self, device):
        if self.default_device_id == getattr(device, "pk", None):
            return False
        self.default_device = device
        self.updated_at = timezone.now()
        self.save(update_fields=["default_device", "updated_at"])
        return True
```

Add the conversion-state fields described in the spec: requested version and
currency, published version and currency, status, retry time, and last error.

- [x] **Step 4: Complete migration operations and pass model/migration tests**

Add nullable fields before Task 1's `run_cutover()`, extend that function with
ownership assignment, Platform classification, preference splitting and
conversion-state seeding, then place final non-null/uniqueness alterations and
the full reconciliation after it.

Run: `make test-fast ARGS="tests/test_library_models.py tests/test_library_cutover_migration.py -x"`

Expected: PASS.

- [x] **Step 5: Commit final schema**

```bash
git add games/models.py games/migrations/0004_user_library_ownership_cutover.py tests/test_library_models.py tests/test_library_cutover_migration.py
git commit -m "feat: add final library ownership schema (#630)"
```

### Task 3: Finish provisioning and structural readiness

**Files:**
- Modify: `games/signals.py`
- Create: `games/readiness.py`
- Modify: `timetracker/asgi.py`
- Modify: `timetracker/wsgi.py`
- Create: `games/management/commands/qcluster.py`
- Create: `tests/test_library_readiness.py`
- Modify: `tests/test_user_library.py`

**Interfaces:**
- Produces: `assert_library_structure() -> None` and complete three-record User provisioning.

- [x] **Step 1: Add failing provisioning/readiness tests**

Assert ordinary User creation produces UserLibrary, UserPreferences, and
UserLibraryPreferences; repeated User saves create nothing new; missing any one
relationship raises `ImproperlyConfigured` with the affected User/library id;
and the repair/audit command loader can import without invoking readiness.

- [x] **Step 2: Run focused tests to prove the missing behavior**

Run: `make test-fast ARGS="tests/test_user_library.py tests/test_library_readiness.py -x"`

Expected: FAIL on missing companion records/readiness function.

- [x] **Step 3: Extend the created-only signal atomically**

```python
with transaction.atomic():
    library, _ = UserLibrary.objects.get_or_create(user=instance)
    UserPreferences.objects.get_or_create(user=instance)
    UserLibraryPreferences.objects.get_or_create(library=library)
```

`assert_library_structure()` performs three `Exists`-style checks, accumulates
short identifiers, logs once, and raises rather than repairing. Call it after
ASGI/WSGI application construction and before the overridden Django-Q2 command
delegates to its superclass. Do not call it from `AppConfig.ready()`, because
that would block migration and repair commands.

- [x] **Step 4: Run readiness tests**

Run: `make test-fast ARGS="tests/test_user_library.py tests/test_library_readiness.py -x"`

Expected: PASS.

- [x] **Step 5: Commit provisioning/readiness**

```bash
git add games/signals.py games/readiness.py timetracker/asgi.py timetracker/wsgi.py games/management/commands/qcluster.py tests/test_user_library.py tests/test_library_readiness.py
git commit -m "feat: enforce library structure at runtime (#630)"
```

### Task 4: Split settings and make Purchase currency explicit

**Files:**
- Modify: `timetracker/settings.py`
- Modify: `timetracker/settings_registry.py`
- Modify: `timetracker/settings_resolver.py`
- Modify: `timetracker/settings_commands.py`
- Modify: `games/settings_forms.py`
- Modify: `games/models.py`
- Modify: `games/forms.py`
- Modify: `games/api.py`
- Modify: `games/views/settings.py`
- Modify: `games/views/general.py`
- Modify: `tests/test_settings_registry.py`
- Modify: `tests/test_settings_resolver.py`
- Modify: `tests/test_settings_api.py`
- Modify: `tests/test_purchase_defaults.py`
- Create: `tests/test_library_preferences.py`

**Interfaces:**
- Produces: effective `DEFAULT_PURCHASE_CURRENCY`, effective
  `DEFAULT_DISPLAY_CURRENCY`, and library `default_device` mutation.

- [ ] **Step 1: Replace old-setting assertions with the approved hierarchy**

Add tests that both currency keys resolve site -> User, a site Display change
affects inheriting users only, no-op writes report `changed=False`, Default
purchase currency preselects a form but never rewrites a Purchase, and missing
`Purchase.price_currency` raises `ValidationError`.

Add `("games:library", "Library")` to landing-page tests and assert unset still
redirects to Sessions.

- [ ] **Step 2: Run the settings tests and confirm old names fail**

Run: `make test-fast ARGS="tests/test_settings_registry.py tests/test_settings_resolver.py tests/test_settings_api.py tests/test_purchase_defaults.py tests/test_library_preferences.py -x"`

Expected: FAIL until registry/model/form consumers use the two new names.

- [ ] **Step 3: Implement the settings split**

Replace `DEFAULT_CURRENCY` with two definitions using exact copy:

```python
SettingDefinition(
    "DEFAULT_PURCHASE_CURRENCY",
    scope=SettingScope.USER,
    apply_timing=ApplyTiming.LIVE,
    label="Default purchase currency",
    default_factory=lambda: settings.DEFAULT_PURCHASE_CURRENCY,
    validator=_validate_currency,
    widget=SettingWidget.TEXT,
    user_help_text="Preselected when adding a purchase.",
)
SettingDefinition(
    "DEFAULT_DISPLAY_CURRENCY",
    scope=SettingScope.USER,
    apply_timing=ApplyTiming.LIVE,
    label="Display currency",
    default_factory=lambda: settings.DEFAULT_DISPLAY_CURRENCY,
    validator=_validate_currency,
    widget=SettingWidget.TEXT,
    user_help_text="Converted totals and statistics.",
)
```

Map both to nullable typed UserPreferences columns. Remove `DEFAULT_DEVICE`
from the settings registry/UserPreferences and move its mutation into a small
library-preference command that verifies Device ownership. Update
`PurchaseForm.__init__(*args, library: UserLibrary, user: User, **kwargs)` to resolve the entry default and set
the initial value. Change `Purchase.save()` to raise when currency is empty;
every caller and fixture must pass an explicit value.

- [ ] **Step 4: Pass all settings and Purchase-default tests**

Run: `make test-fast ARGS="tests/test_settings_registry.py tests/test_settings_resolver.py tests/test_settings_api.py tests/test_purchase_defaults.py tests/test_library_preferences.py tests/test_settings_page.py -x"`

Expected: PASS with no runtime reference to `DEFAULT_CURRENCY` or
`DEFAULT_DEVICE` outside migration history.

- [ ] **Step 5: Commit the preference split**

```bash
git add timetracker games tests
git commit -m "feat: split library and currency preferences (#630)"
```

### Task 5: Scope forms, services, page reads, and writes

**Files:**
- Create: `games/ownership.py`
- Modify: `games/forms.py`
- Modify: `games/views/game.py`
- Modify: `games/views/session.py`
- Modify: `games/views/purchase.py`
- Modify: `games/views/device.py`
- Modify: `games/views/platform.py`
- Modify: `games/views/playevent.py`
- Modify: `games/views/statuschange.py`
- Modify: `games/views/deletion.py`
- Modify: `common/layout.py`
- Create: `tests/test_library_page_isolation.py`
- Create: `tests/test_library_form_isolation.py`

**Interfaces:**
- Produces: explicit library-bound forms and `owned_or_404(queryset, library, **lookup)`.

- [ ] **Step 1: Write two-library read/write tests for every HTML path**

For each entity, create own and foreign rows. Assert own list/detail/edit/delete
works, lists omit foreign rows, foreign detail/edit/delete returns 404, and a
POST containing a foreign Game/Device/Platform is rejected without mutation.
Assert shared Platforms remain selectable while foreign private Platforms do
not.

- [ ] **Step 2: Run the isolation tests and observe current leaks**

Run: `make test-fast ARGS="tests/test_library_page_isolation.py tests/test_library_form_isolation.py -x"`

Expected: FAIL because current querysets are global.

- [ ] **Step 3: Bind every form and view to an explicit library**

Use a common constructor contract:

```python
class SessionForm(PrimitiveWidgetsMixin, forms.ModelForm):
    def __init__(self, *args, library: UserLibrary, **kwargs):
        super().__init__(*args, **kwargs)
        self.library = library
        self.fields["game"].queryset = Game.objects.for_library(library)
        self.fields["device"].queryset = Device.objects.for_library(library)
```

Apply equivalent scoping to Purchase, Game, Platform, PlayEvent, and
GameStatusChange forms. Views resolve `library = request.user.library` once,
scope their base queryset, and pass `library=`. `owned_or_404` is a thin wrapper
around an already scoped queryset; it never reads the request itself.

Scope `recent_session_resumes` and all navbar playtime queries by library even
though the final navbar is delivered later.

- [ ] **Step 4: Pass HTML isolation and existing page tests**

Run: `make test-fast ARGS="tests/test_library_page_isolation.py tests/test_library_form_isolation.py tests/test_rendered_pages.py tests/test_navbar_playtime.py tests/test_navbar_log_button.py -x"`

Expected: PASS.

- [ ] **Step 5: Commit HTML scoping**

```bash
git add games/ownership.py games/forms.py games/views common/layout.py tests
git commit -m "feat: scope pages and forms to libraries (#630)"
```

### Task 6: Scope APIs, filters, presets, and statistics

**Files:**
- Modify: `games/api.py`
- Modify: `games/filters.py`
- Modify: `common/criteria.py`
- Modify: `common/filter_execution.py`
- Modify: `games/views/filtering.py`
- Modify: `games/views/general.py`
- Modify: `games/views/stats_data.py`
- Modify: `games/views/stats_links.py`
- Modify: `tests/test_filter_presets.py`
- Modify: `tests/test_filters.py`
- Modify: `tests/test_stats.py`
- Modify: `tests/test_stats_links.py`
- Create: `tests/test_library_api_isolation.py`

**Interfaces:**
- Produces: library-bound search/options, CRUD APIs, filter counts, presets, and `compute_stats(library, year=None)`.

- [ ] **Step 1: Add a two-library API/filter/statistics matrix**

Assert search returns shared Platforms plus own private records, foreign IDs
404, generic filter counts start from a library-scoped queryset, preset
uniqueness is per library, saved presets never cross users, and every statistic
equals the contribution from one library only.

- [ ] **Step 2: Run the matrix and confirm global reads fail**

Run: `make test-fast ARGS="tests/test_library_api_isolation.py tests/test_filter_presets.py tests/test_stats.py tests/test_stats_links.py -x"`

Expected: FAIL on current global querysets and User-owned presets.

- [ ] **Step 3: Thread library through generic boundaries**

Change generic filter entry points to require a scoped base queryset instead of
calling `model.objects.all()` internally. Use:

```python
def execute_filter(filter_object, queryset):
    return filter_object.apply(queryset)


def compute_stats(library: UserLibrary, year: int | None = None) -> StatsData:
    sessions = Session.objects.for_library(library)
    purchases = Purchase.objects.for_library(library)
    return _compute_stats_from_scoped_querysets(
        sessions=sessions,
        purchases=purchases,
        year=year,
    )
```

Extract the current calculation body into
`_compute_stats_from_scoped_querysets(*, sessions, purchases, year)` without
allowing that helper to query an unscoped model manager.

Scope all Ninja endpoints from `request.user.library`, including search,
PlayEvent CRUD, Session mutation, filter count, and FilterPreset APIs. Foreign
private Platform IDs remain undisclosed.

- [ ] **Step 4: Run affected API/filter/statistics suites**

Run: `make test-fast ARGS="tests/test_library_api_isolation.py tests/test_filter_presets.py tests/test_filters.py tests/test_stats.py tests/test_stats_links.py tests/test_stats_content_links.py -x"`

Expected: PASS.

- [ ] **Step 5: Commit non-HTML scoping**

```bash
git add games/api.py games/filters.py games/views common/criteria.py common/filter_execution.py tests
git commit -m "feat: scope APIs filters and stats to libraries (#630)"
```

### Task 7: Implement versioned atomic conversion and scheduling

**Files:**
- Create: `games/conversion.py`
- Rewrite: `games/tasks.py`
- Modify: `games/signals.py`
- Modify: `games/api.py`
- Modify: `games/management/commands/schedule_convert_prices.py`
- Modify: `common/layout.py`
- Modify: `ts/globals.d.ts`
- Modify: `ts/toast.ts`
- Modify: `ts/toast.test.ts`
- Create: `ts/library-conversion-status.ts`
- Create: `ts/library-conversion-status.test.ts`
- Create: `tests/test_library_conversion.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_rendered_pages.py`
- Modify: `tests/test_price_update.py`
- Modify: `tests/test_site_settings_currency.py`

**Interfaces:**
- Produces: `request_conversion(library, target_currency) -> int`,
  `convert_library_prices(library_id, requested_version) -> None`, and a
  read-only authenticated conversion-status endpoint carrying requested and
  published versions/currencies, status, retry time, and concise error state.
- Produces: generic stable-id/no-timer toast operations plus a page-global
  conversion coordinator that reconstructs server state, owns per-tab
  dismissal, and observes completion across navigation.

- [ ] **Step 1: Write backend conversion state-machine tests**

Cover same-currency/zero-price conversion, missing-rate failure, one 15-minute
retry, daily recovery, five rapid requests coalescing to the last target, an old
job unable to publish, an intervening Purchase edit invalidating a candidate,
one transaction publishing every row and state version together, and strict
per-library authorization/response fields on the status endpoint.

- [ ] **Step 2: Write toast and conversion-coordinator tests**

First extend `ts/toast.test.ts` for stable string ids, replacement/removal by id,
and `duration: null` with no timer while preserving the existing five-second
default and pause/resume behavior.

In `ts/library-conversion-status.test.ts`, cover initial server-state
reconstruction on every authenticated page; persistent running/failure text;
sessionStorage keys scoped by library, requested version, and phase; dismissal
surviving navigation in the same tab while polling continues; another tab
remaining independent; running -> success; running -> failure; waiting until
`retry_at`; retry as a new phase; a later version bypassing old dismissal; and
no historical success toast in a tab that never observed the operation.

Add rendered-page/API assertions that authenticated pages include only their
library's initial state and status URL, while anonymous pages include neither.

- [ ] **Step 3: Run the focused tests against the old implementation**

Run: `make test-fast ARGS="tests/test_library_conversion.py tests/test_api.py tests/test_rendered_pages.py tests/test_price_update.py tests/test_site_settings_currency.py -x"`

Expected: FAIL because conversion is global, publishes per row, and has no
status/coordinator contract. The Make prerequisite also runs the TypeScript
suite, where the new client tests fail.

- [ ] **Step 4: Implement the bridge and single-writer publication**

```python
@transaction.atomic
def request_conversion(library, target_currency):
    state = PurchaseConversionState.objects.select_for_update().get(library=library)
    state.requested_version += 1
    state.requested_currency = target_currency
    state.status = PurchaseConversionState.Status.PENDING
    state.save(update_fields=["requested_version", "requested_currency", "status"])
    transaction.on_commit(
        lambda: async_task(
            "games.tasks.convert_library_prices",
            str(library.pk),
            state.requested_version,
        )
    )
    return state.requested_version
```

The task snapshots the latest version and all Purchase inputs, fetches/caches
rates outside the publication transaction, then locks the state and rechecks
the version before one `bulk_update` plus published-state update. Relevant
Purchase writes increment the version in their transaction. A stale task exits
without changing rows.

Schedule only one daily recovery sweep. Remove the `Schedule.MINUTES` behavior.
On failure, record the concise error and `retry_at`, enqueue one retry for about
15 minutes, and let the daily sweep recover anything still stale.

- [ ] **Step 5: Implement persistent conversion notification behavior**

Give the generic toast store an optional stable string id and nullable duration;
replacement clears the previous timer and removal works whether visible or
dismissed. Keep all conversion-specific decisions out of `toast.ts`.

Render the authenticated User's current conversion state and endpoint URL into
page-global data in `common/layout.py`, then load
`library-conversion-status.js`. The coordinator uses one stable toast id, the
exact approved messages from the spec, and sessionStorage dismissal keyed by
library/version/phase. Poll only after a tab has observed active state; use a
bounded active interval, honor `retry_at` after failure, continue completion
detection after dismissal, and stop when the observed version is published or
superseded. Completion removes the persistent toast and emits the ordinary
five-second success toast even when the running notice was dismissed.

- [ ] **Step 6: Pass backend, client, and scheduler tests**

Run: `make test-fast ARGS="tests/test_library_conversion.py tests/test_price_update.py tests/test_site_settings_currency.py tests/test_tasks.py -x"`

Expected: PASS; if `tests/test_tasks.py` does not exist, create it for the daily
schedule contract rather than dropping the assertion.

Then run: `make test-fast ARGS="tests/test_api.py tests/test_rendered_pages.py -x"`

Expected: PASS, including the full TypeScript suite run by the Make target.

- [ ] **Step 7: Commit atomic conversion and notification**

```bash
git add common/layout.py games/conversion.py games/tasks.py games/signals.py games/api.py games/management/commands/schedule_convert_prices.py ts tests
git commit -m "feat: publish and report library conversions atomically (#630)"
```

### Task 8: Add explicit operator commands and sample-data ownership

**Files:**
- Create: `games/management/commands/audit_library_ownership.py`
- Create: `games/management/commands/delete_user_library.py`
- Create: `games/management/commands/load_sample_data.py`
- Modify: `games/management/commands/bootstrap_container.py`
- Modify: `games/management/commands/anonymize_sample.py`
- Modify: `Makefile`
- Modify: `games/fixtures/sample.yaml.gz`
- Create: `tests/test_library_commands.py`
- Modify: `tests/test_anonymize_sample.py`
- Modify: `tests/test_bootstrap_container.py`

**Interfaces:**
- Produces: read-only audit, dry-run-first deletion, and explicit-owner sample loading.

- [ ] **Step 1: Write command-boundary tests**

Assert audit requires exactly one of `--user`, `--library`, or
`--all-libraries` and exits nonzero on an injected violation. Assert deletion is
dry-run by default and only deletes for matching `--user USERNAME --confirm
USERNAME`. Assert sample load rejects a missing User and attaches every private
row to the chosen existing User's library while reusing exact shared Platforms.

- [ ] **Step 2: Run command tests and confirm commands are absent**

Run: `make test-fast ARGS="tests/test_library_commands.py tests/test_bootstrap_container.py tests/test_anonymize_sample.py -x"`

Expected: FAIL on unknown commands/options.

- [ ] **Step 3: Implement commands without hidden fallbacks**

The audit prints direct owners, derived relationships, cross-library links, and
preference structure; it never writes. The deletion command prints counts and a
conspicuous cascade warning in both modes, then deletes the User only after the
exact confirmation match. The sample command resolves an existing explicit
User first; fixtures do not create or infer one.

Update `loadsample` to require `USER=<username>` and call
`manage.py load_sample_data --user $(USER)`. Update container bootstrap to pass
its explicitly created/default User to the same command.

- [ ] **Step 4: Pass command and fixture round-trip tests**

Run: `make test-fast ARGS="tests/test_library_commands.py tests/test_bootstrap_container.py tests/test_anonymize_sample.py -x"`

Expected: PASS.

- [ ] **Step 5: Commit operator tooling**

```bash
git add games/management/commands Makefile games/fixtures/sample.yaml.gz tests
git commit -m "feat: add library operator commands (#630)"
```

### Task 9: Remove nullable-Game filter support and complete parity coverage

**Files:**
- Modify: `games/filters.py`
- Modify: `tests/test_filters.py`
- Modify: `tests/test_navbar_log_button.py`
- Create: `tests/test_library_reconciliation.py`
- Modify: `docs/configuration.md`

**Interfaces:**
- Produces: final no-null Session domain contract and the operator runbook.

- [ ] **Step 1: Delete tests/sample builders that create Game-less Sessions**

Replace them with required-Game fixtures. Add assertions that Session filter
metadata no longer offers Game `IS_NULL`/`IS_NOT_NULL` choices.

- [ ] **Step 2: Add a full two-library parity scenario**

Create representative data in both libraries and shared Platforms, then assert
row/link counts, playtime, purchase totals, pages, APIs, exact statistic links,
filters, presets, and conversion outputs independently for each library.

- [ ] **Step 3: Run the parity scenario and fix every remaining global access**

Run: `make test-fast ARGS="tests/test_library_reconciliation.py tests/test_filters.py tests/test_navbar_log_button.py -x"`

Expected: PASS only after `rg` confirms every production ORM access point is
classified as scoped, shared, or intentionally operator-global.

- [ ] **Step 4: Write the exact production runbook**

Document the exact legacy sequence: query the still-running old app for the
site and personal `DEFAULT_CURRENCY` value/source/lock state and deployment
version; take the site and worker offline; create a fresh custom-format
`--no-owner --no-privileges` dump; restore it into a disposable database; and
generate the version-1 manifest from that exact restore plus the captured
runtime values. Verify the dump SHA-256 equals `source.dump_sha256`, and keep
the dump/manifest outside Git with identical protected retention.

Materialize an inherited effective Device as the User's explicit old
preference before the final dump. Configure both new site currency keys from
the recorded old site value, mount the manifest read-only, set
`TIMETRACKER_OWN_CUTOVER_MANIFEST` only for the migration command, and ensure
the existing converted cache is complete in the manifest's recorded Display
currency. Run migration, retain stdout/new UUID with the dump and manifest,
run the ownership audit and representative parity checks, and bring web/worker
up only after all pass. Include the pristine-install no-manifest path and an
explicit warning that a manifest from an earlier dump must never be reused.

- [ ] **Step 5: Commit parity and runbook**

```bash
git add games/filters.py tests docs/configuration.md
git commit -m "test: prove complete library cutover parity (#630)"
```

### Task 10: Final audit and full verification

**Files:**
- Review: all files changed in Tasks 1-9

**Interfaces:**
- Produces: release-ready #630 cutover with no old runtime assumptions.

- [ ] **Step 1: Search for forbidden legacy/global patterns**

Run targeted `rg` searches for `DEFAULT_CURRENCY`, `DEFAULT_DEVICE`, nullable
Session Game creation, `FilterPreset.*user`, unscoped `.objects.all()`, and
unscoped `get_object_or_404` across production code. Classify and fix every hit;
migration-history references are the only expected old-setting matches.

- [ ] **Step 2: Rehearse migration on a restored production copy**

Verify the archive hash first, restore the manifest-matched production dump
into a new disposable database, and point only that migration process at the
manifest. Run the documented preflight, migration, reconciliation, audit, and
page/API smoke checks. Preserve stdout and assert the source deployment/hash,
production UUID, row/link/original-currency counts, converted-cache state,
totals, settings split, and relationship checks match the manifest. Separately
apply the full migration history to an empty database with no manifest.

- [ ] **Step 3: Run the complete gate**

Run the managed hidden Windows `make check` process and wait for its final log
and exit status.

Expected: exit 0 with default parallel workers.

- [ ] **Step 4: Run migration drift check once more**

Run: `make check-migrations`

Expected: “No changes detected” and exit 0.

- [ ] **Step 5: Commit only if the audit required corrections**

Review `git diff --name-only`, stage each corrected file explicitly, and commit
with `fix: close library cutover verification gaps (#630)`. Do not create an
empty verification commit and do not stage unrelated files.
