# OWN-02 Library Ownership Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Perform the single rehearsed offline cutover from globally scoped private data to a complete one-library-per-user ownership, preference, currency, and isolation boundary.

**Architecture:** One migration adds final ownership fields, validates the one known production shape, assigns the production library, splits preferences, and installs final constraints without a temporary claim state. Runtime code resolves `request.user.library`, passes it explicitly, and uses thin queryset helpers. A per-library `PurchaseConversionState` provides atomic transitional FX publication until #728 replaces it.

**Tech Stack:** Django 6, PostgreSQL 18, Django Ninja, Django-Q2, htpy server components, pytest/pytest-django, Vitest/TypeScript.

## Global Constraints

- Read `docs/superpowers/specs/2026-08-13-user-library-ownership-cutover-design.md` before editing.
- #629 and #639 are hard prerequisites.
- The only supported legacy database has exactly one User and the inspected global data; abort on every unknown shape.
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

- [ ] **Step 1: Write the successful legacy-shape fixture**

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

Assert after migration that the library timestamp is exact, every direct owner
is assigned, built-ins are shared, the custom Platform is private, Session Game
is required, FilterPreset points to the library, and settings have the approved
split.

- [ ] **Step 2: Write refusal matrices before migration code**

Parameterize independent cases for zero Users, two Users, a null Session Game,
a saved Session Game-null predicate, duplicate future Game keys, ambiguous
built-in Platform rows, cross-linked Purchase/Game/Platform data, and an
incomplete or mixed converted-price cache. Each case must assert a specific
`RuntimeError` message naming the violated invariant and no partial ownership
assignment.

- [ ] **Step 3: Run the migration tests and confirm they fail at the missing migration**

Run: `make test-fast ARGS="tests/test_library_cutover_migration.py -x"`

Expected: FAIL because migration `0004_user_library_ownership_cutover` is absent.

- [ ] **Step 4: Add a migration skeleton with named preflight functions**

Keep migration helpers inside the migration file so historical execution does
not import mutable runtime code:

```python
def validate_legacy_shape(apps, schema_editor) -> None:
    User = apps.get_model("auth", "User")
    Session = apps.get_model("games", "Session")
    if User.objects.count() != 1:
        raise RuntimeError("OWN cutover requires exactly one User")
    if Session.objects.filter(game_id__isnull=True).exists():
        raise RuntimeError("OWN cutover requires every Session to have a Game")


def backfill_known_library(apps, schema_editor) -> None:
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    user = User.objects.get()
    UserLibrary.objects.create(user_id=user.pk, created_at=FIRST_COMMIT_AT)


def reconcile_cutover(apps, schema_editor) -> None:
    UserLibrary = apps.get_model("games", "UserLibrary")
    if UserLibrary.objects.count() != 1:
        raise RuntimeError("OWN cutover did not produce exactly one UserLibrary")
```

Extend these named functions with every refusal/reconciliation assertion from
Steps 1-2. Place `validate_legacy_shape` after additive nullable fields,
`backfill_known_library` before final non-null alterations, and
`reconcile_cutover` after ownership assignment and before the migration exits.

The reverse functions are intentionally no-op because the documented recovery
path is restoring the pre-cutover backup, not synthesizing global ownership.

- [ ] **Step 5: Commit the executable migration contract**

```bash
git add tests/test_library_cutover_migration.py games/migrations/0004_user_library_ownership_cutover.py
git commit -m "test: lock library cutover preconditions (#630)"
```

### Task 2: Add final ownership and preference models

**Files:**
- Modify: `games/models.py`
- Modify: `games/migrations/0004_user_library_ownership_cutover.py`
- Create: `tests/test_library_models.py`

**Interfaces:**
- Produces: `UserLibraryPreferences`, `PurchaseConversionState`, and
  `.for_library()`/`.visible_to()` queryset contracts.

- [ ] **Step 1: Write failing final-model tests**

Cover the direct/derived ownership table, `UserLibraryPreferences.library` as
its primary key, no-op-aware preference timestamp updates, required
`Session.game`, Game per-library uniqueness, Platform shared/private visibility,
and case-insensitive trimmed Platform duplicate rejection.

```python
assert Game.objects.for_library(library_a).count() == 1
assert Session.objects.for_library(library_a).count() == 1
assert Platform.objects.visible_to(library_a).contains(shared)
assert Platform.objects.visible_to(library_a).contains(private_a)
assert not Platform.objects.visible_to(library_a).contains(private_b)
```

- [ ] **Step 2: Run the model tests and confirm missing fields/helpers**

Run: `make test-fast ARGS="tests/test_library_models.py -x"`

Expected: FAIL on missing ownership fields and querysets.

- [ ] **Step 3: Implement the model/queryset surface**

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

- [ ] **Step 4: Complete migration operations and pass model/migration tests**

Run: `make test-fast ARGS="tests/test_library_models.py tests/test_library_cutover_migration.py -x"`

Expected: PASS.

- [ ] **Step 5: Commit final schema**

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

- [ ] **Step 1: Add failing provisioning/readiness tests**

Assert ordinary User creation produces UserLibrary, UserPreferences, and
UserLibraryPreferences; repeated User saves create nothing new; missing any one
relationship raises `ImproperlyConfigured` with the affected User/library id;
and the repair/audit command loader can import without invoking readiness.

- [ ] **Step 2: Run focused tests to prove the missing behavior**

Run: `make test-fast ARGS="tests/test_user_library.py tests/test_library_readiness.py -x"`

Expected: FAIL on missing companion records/readiness function.

- [ ] **Step 3: Extend the created-only signal atomically**

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

- [ ] **Step 4: Run readiness tests**

Run: `make test-fast ARGS="tests/test_user_library.py tests/test_library_readiness.py -x"`

Expected: PASS.

- [ ] **Step 5: Commit provisioning/readiness**

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
- Create: `tests/test_library_conversion.py`
- Modify: `tests/test_price_update.py`
- Modify: `tests/test_site_settings_currency.py`

**Interfaces:**
- Produces: `request_conversion(library, target_currency) -> int`,
  `convert_library_prices(library_id, requested_version) -> None`, and a
  read-only authenticated conversion-status endpoint.

- [ ] **Step 1: Write conversion state-machine tests**

Cover same-currency/zero-price conversion, missing-rate failure, one 15-minute
retry, daily recovery, five rapid requests coalescing to the last target, an old
job unable to publish, an intervening Purchase edit invalidating a candidate,
and one transaction publishing every row and state version together.

- [ ] **Step 2: Run conversion tests against the old row-by-row task**

Run: `make test-fast ARGS="tests/test_library_conversion.py tests/test_price_update.py tests/test_site_settings_currency.py -x"`

Expected: FAIL because conversion is global and publishes per row.

- [ ] **Step 3: Implement the bridge and single-writer publication**

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

- [ ] **Step 4: Pass conversion and scheduler tests**

Run: `make test-fast ARGS="tests/test_library_conversion.py tests/test_price_update.py tests/test_site_settings_currency.py tests/test_tasks.py -x"`

Expected: PASS; if `tests/test_tasks.py` does not exist, create it for the daily
schedule contract rather than dropping the assertion.

- [ ] **Step 5: Commit atomic conversion**

```bash
git add games/conversion.py games/tasks.py games/signals.py games/api.py games/management/commands/schedule_convert_prices.py tests
git commit -m "feat: publish library conversions atomically (#630)"
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

Document: take site offline; make fresh backup; record old effective currency
and default Device; materialize the effective Device as the User's explicit old
preference if it was inherited; set both new site currency keys to the recorded
site value; ensure the existing converted cache is complete; run migration;
retain reconciliation output and new UUID; run audit and representative parity
checks; bring web/worker up only after all pass.

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

Run the documented preflight, migration, reconciliation, audit, and page/API
smoke checks. Preserve stdout and assert the production UUID, counts, totals,
and relationship checks match the preflight record.

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
