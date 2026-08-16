# Issue #630 Full-Suite Compatibility Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the complete issue #630 branch pass `make check` by updating stale tests to the already-finalized explicit-library contracts, without weakening production ownership or scoping.

**Architecture:** Treat the existing full-suite failure as several test-fixture compatibility families. Repair high-fan-out class fixtures first so failed setup no longer poisons xdist workers, then repair ordinary unit and browser fixtures, resolver cache tests, and filter compilation contexts. Production code is out of scope unless an isolated behavioral failure remains after its fixture is valid.

**Tech Stack:** Django 5.1, pytest/pytest-django/pytest-xdist, Playwright, PostgreSQL 18, GNU Make, uv.

## Global Constraints

- Run every project command through Make.
- On Windows, run every Make test/check target as a managed hidden process and retain its final exit status; keep the Makefile's default `PYTEST_WORKERS`.
- Do not add a hidden/global default owner, make ownership nullable, bypass model validation, or restore an unscoped filter fallback.
- Shared catalogue Platforms remain `library=None`; private Platforms, Games, Devices, Purchases, and FilterPresets use the same explicit library as the scenario's authenticated User.
- Preserve intentional negative tests that prove missing ownership, cross-library relations, or absent cutover manifests are rejected.
- Existing tests are the RED cases. Fixture-only corrections must leave their behavioral assertions intact.
- If a valid isolated test proves a production defect, stop and review it before changing production code; a production change would require re-evaluating the completed production rehearsal.
- The retained full-check baseline is 2695 passed, 233 failed, and 216 errors across 78 files.

---

### Task 1: Remove high-fan-out xdist worker poisoning

**Files:**
- Modify: `tests/test_components.py`
- Modify: `tests/test_search_select.py`
- Modify: `tests/test_table_width_policy.py`

**Interfaces:**
- Consumes: eager User provisioning (`user.library`, `user.preferences`, and `user.library.purchase_conversion_state`).
- Produces: valid class-level owned graphs that cannot leave a worker connection in a failed transaction during setup.

- [ ] **Step 1: Reproduce the focused RED**

Run through managed hidden Make:

```text
make test ARGS="tests/test_components.py tests/test_search_select.py tests/test_table_width_policy.py -x"
```

Expected: the first affected class setup fails because `Game.library_id` or `Device.library_id` is null.

- [ ] **Step 2: Make each class graph explicitly owned**

Create the class User before private objects, retain `library = user.library`, and pass that library to every private Game, Device, and Purchase. Keep catalogue Platforms shared when the scenario is testing a shared Platform. Ensure view tests authenticate the same User whose library owns the rows.

- [ ] **Step 3: Run the focused GREEN**

Run the exact Step 1 command. Expected: all three files pass with default xdist workers.

- [ ] **Step 4: Commit the bounded fix**

```text
git add tests/test_components.py tests/test_search_select.py tests/test_table_width_policy.py
git commit -m "test: own high-fanout fixtures for issue 630"
```

---

### Task 2: Repair ordinary unit and integration ownership fixtures

**Files:**
- Modify as confirmed by isolated REDs: `tests/test_action_origin_parity.py`
- Modify as confirmed by isolated REDs: `tests/test_column_priority_contract.py`
- Modify as confirmed by isolated REDs: `tests/test_date_picker.py`
- Modify as confirmed by isolated REDs: `tests/test_date_time_picker.py`
- Modify as confirmed by isolated REDs: `tests/test_date_time_presentation.py`
- Modify as confirmed by isolated REDs: `tests/test_date_time_rendering_paths.py`
- Modify as confirmed by isolated REDs: `tests/test_deletion_confirmation.py`
- Modify as confirmed by isolated REDs: `tests/test_game_detail_links.py`
- Modify as confirmed by isolated REDs: `tests/test_generated_days_to_finish.py`
- Modify as confirmed by isolated REDs: `tests/test_generated_duration_columns.py`
- Modify as confirmed by isolated REDs: `tests/test_generated_purchase_price_columns.py`
- Modify as confirmed by isolated REDs: `tests/test_html_validity.py`
- Modify as confirmed by isolated REDs: `tests/test_live_server_db_concurrency.py`
- Modify as confirmed by isolated REDs: `tests/test_middleware_integration.py`
- Modify as confirmed by isolated REDs: `tests/test_origin_partials.py`
- Modify as confirmed by isolated REDs: `tests/test_paths_return_200.py`
- Modify as confirmed by isolated REDs: `tests/test_purchase_related_game.py`
- Modify as confirmed by isolated REDs: `tests/test_purchase_separate_orders.py`
- Modify as confirmed by isolated REDs: `tests/test_returns_views.py`
- Modify as confirmed by isolated REDs: `tests/test_session_actions_component.py`
- Modify as confirmed by isolated REDs: `tests/test_session_date_filter.py`
- Modify as confirmed by isolated REDs: `tests/test_session_endpoints.py`
- Modify as confirmed by isolated REDs: `tests/test_session_finish_reset.py`
- Modify as confirmed by isolated REDs: `tests/test_session_formatting.py`
- Modify as confirmed by isolated REDs: `tests/test_session_querysets.py`
- Modify as confirmed by isolated REDs: `tests/test_session_time_range_timezones.py`
- Modify as confirmed by isolated REDs: `tests/test_session_timezones.py`
- Modify as confirmed by isolated REDs: `tests/test_sort_header_parity.py`
- Modify as confirmed by isolated REDs: `tests/test_sorting.py`
- Modify as confirmed by isolated REDs: `tests/test_stats_links.py`
- Modify as confirmed by isolated REDs: `tests/test_uuidv7.py`
- Modify as confirmed by isolated REDs: `tests/test_uuidv7_domain.py`
- Modify as confirmed by isolated REDs: `tests/test_view_authentication.py`

**Interfaces:**
- Consumes: the scenario's explicit User and provisioned `UserLibrary`.
- Produces: model/view fixtures satisfying final ownership constraints while preserving the original behavioral assertions.

- [ ] **Step 1: Capture the post-Task-1 non-browser RED**

Run through managed hidden Make:

```text
make test-fast ARGS="-x"
```

Expected: the first genuine remaining compatibility failure identifies a specific invalid fixture rather than a poisoned worker cascade.

- [ ] **Step 2: Repair one module at a time at the source of its graph**

For function fixtures, create or accept the authenticated User before private rows and return that User with the graph when callers need to log in. For `TestCase.setUpTestData`, store `cls.user` and `cls.library` before constructing rows. Pass the same library through Game, Device, Purchase, Session Game/Device, Purchase Game, related Game, and private Platform relationships. Do not add defaults to production factories or models.

- [ ] **Step 3: Verify every changed module immediately**

After each small module group, run:

```text
make test ARGS="tests/test_action_origin_parity.py tests/test_deletion_confirmation.py -x"
```

Expected: the same behavioral tests now execute and pass; their assertions are unchanged.

- [ ] **Step 4: Run the complete non-browser GREEN**

```text
make test-fast
```

Expected: every non-E2E test passes with default xdist workers. Migration tests such as `tests/test_library_cutover_migration.py`, `tests/test_user_library.py`, and UUID migration tests must be changed only if they still fail when run alone; worker-poison errors are not reasons to modify their historical fixtures.

- [ ] **Step 5: Commit the owned-fixture sweep**

```text
git add tests
git commit -m "test: align legacy fixtures with library ownership"
```

---

### Task 3: Repair resolver, preference, and filter test contracts

**Files:**
- Modify: `tests/test_duration_setting.py`
- Modify: `tests/test_filter_execution.py`
- Modify: `tests/test_filter_tree_contract.py`
- Modify: `tests/test_sentinel_removal.py`
- Modify: `tests/test_settings_api.py`
- Modify: `tests/test_settings_landing.py`
- Modify: `tests/test_settings_page.py`
- Modify: `tests/test_signals.py`
- Modify: `tests/test_tasks.py`
- Modify: `tests/test_theme_layout.py`
- Modify: `tests/test_timezone_activation_middleware.py`
- Modify: `tests/test_timezone_search_api.py`
- Modify: `tests/test_user_library.py` only if its isolated historical-migration test genuinely fails
- Modify: `tests/test_user_preference_consumers.py`

**Interfaces:**
- Consumes: `django_capture_on_commit_callbacks(execute=True)`, `FilterQueryContext`, and eager User preference provisioning.
- Produces: tests that exercise the final cache invalidation and scoped compiler contracts without adding a production fallback.

- [ ] **Step 1: Reproduce each contract family independently**

Run managed hidden Make with exact files, first preferences/settings, then filters:

```text
make test ARGS="tests/test_duration_setting.py tests/test_settings_api.py tests/test_settings_landing.py tests/test_settings_page.py tests/test_signals.py tests/test_user_preference_consumers.py -x"
make test ARGS="tests/test_filter_execution.py tests/test_filter_tree_contract.py tests/test_sentinel_removal.py -x"
```

Expected: preference duplicates/cache staleness and missing filter context fail for their specific contract.

- [ ] **Step 2: Make preference/cache tests transaction-aware**

Mutate the eagerly provisioned `user.preferences` row instead of creating a duplicate. Wrap setting-command writes whose result is resolved in the same pytest transaction with `django_capture_on_commit_callbacks(execute=True)` so the production `on_commit` cache invalidation executes exactly as it does after a real request transaction.

- [ ] **Step 3: Give compiler-only tests an explicit test context**

Define a module-local unrestricted `FilterQueryContext` in pure serialization/structural contract tests, matching the established pattern in `tests/test_filters.py`. Tests of request/runtime execution must instead use `filter_query_context_for_library(library)`. Never make production context optional.

- [ ] **Step 4: Run both focused commands to GREEN, then rerun `make test-fast`**

Expected: both contract families and the complete non-browser suite pass.

- [ ] **Step 5: Commit the contract adaptations**

```text
git add tests
git commit -m "test: align settings and filter contracts with cutover"
```

---

### Task 4: Repair browser-test ownership and provisioned preferences

**Files:**
- Modify as confirmed by isolated REDs: `e2e/test_admin_settings_page_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_api_csrf_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_control_sizing_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_custom_elements_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_date_picker_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_datetime_field_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_device_clear_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_dropdown_clipping_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_duration_format_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_filter_builder_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_filter_count_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_pinned_column_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_played_dropdown_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_purchase_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_quick_filter_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_responsive_table_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_return_to_origin_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_session_finish_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_session_reset_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_table_width_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_theme_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_time_zone_row_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_touch_targets_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_truncated_text_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_widgets_e2e.py`
- Modify as confirmed by isolated REDs: `e2e/test_year_picker_e2e.py`

**Interfaces:**
- Consumes: each test's login User and its eagerly provisioned library/preferences.
- Produces: browser scenarios whose rows are visible to the authenticated User under final library scoping.

- [ ] **Step 1: Capture browser REDs in small exact groups**

Use managed hidden `make test ARGS="e2e/test_api_csrf_e2e.py e2e/test_control_sizing_e2e.py -x"` for the first small group, then substitute the next exact changed paths; do not use `test-e2e` for a focused file list because that target already supplies the entire `e2e/` directory.

- [ ] **Step 2: Own each browser scenario explicitly**

Create the login User before private objects and pass `library=user.library` to every Game, Device, Purchase, and private Platform. Keep Session and Purchase relations within that same library. Replace `UserPreferences.objects.create(user=user, ...)` with mutation of `user.preferences`; where a test previously expected no preference row after user creation, assert the relevant field retained its provisioned default instead.

- [ ] **Step 3: Run each changed browser group to GREEN**

Keep behavioral browser assertions unchanged. A test that fails after its graph and preferences are valid requires root-cause investigation, not a looser assertion.

- [ ] **Step 4: Run the complete browser suite**

```text
make test-e2e
```

Expected: all E2E tests pass with default xdist workers.

- [ ] **Step 5: Commit the browser fixture sweep**

```text
git add e2e
git commit -m "test: own browser fixtures after library cutover"
```

---

### Task 5: Prove the branch and finish Task 10

**Files:**
- Modify only if required by verification: tests already listed above
- Update ignored evidence: `.superpowers/sdd/2026-08-13-own-02-library-ownership-cutover/progress.md`
- Update ignored evidence: `.superpowers/sdd/2026-08-13-own-02-library-ownership-cutover/task-10-report.md`

**Interfaces:**
- Consumes: Tasks 1-4, the preserved production rehearsal artifacts, and the issue #630 design/plan.
- Produces: a green branch ready for final review and PR update.

- [ ] **Step 1: Run static gates on the exact changed Python files**

Run Make lint, format-check, and typecheck targets. Correct test-only typing/style defects without changing application behavior.

- [ ] **Step 2: Run the complete managed hidden verification gate**

```text
make check
```

Expected: exit 0 with the Makefile's default Windows worker count.

- [ ] **Step 3: Verify migration state explicitly**

```text
make check-migrations
```

Expected: `No changes detected`.

- [ ] **Step 4: Audit the final diff**

Confirm there are no production-file changes, no relaxed ownership constraints, no hidden owner factory, and no altered behavioral expectations. Confirm both main checkout and linked worktree contain no unintended untracked files.

- [ ] **Step 5: Commit and push the final repair**

Commit any final test-only corrections, push `codex/issue-630`, update the ignored Task 10 evidence, and request final review. Do not mark the PR mergeable until the reviewer and complete verification are green.
