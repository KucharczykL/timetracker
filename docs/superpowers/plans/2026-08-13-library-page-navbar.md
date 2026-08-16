# Library Page and Navbar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the approved Library Overview, Activity, Customization, and Purchases sections together with the replacement navbar/account menu.

**Architecture:** A new library view builds all section data from `request.user.library` and composes only the visually approved component kit. Exact statistic links reuse the existing filter URL contract. `common.layout.Navbar` is simplified to logo + Log game + Library + reusable AccountMenu while retaining its request-scoped playtime data.

**Tech Stack:** Django 6 views/URLs, htpy server components, approved sectioned-page/library components, existing filters and dropdowns, pytest, Vitest, Playwright.

## Global Constraints

- Read `docs/superpowers/specs/2026-08-13-library-page-and-navigation-design.md` before editing.
- The component-kit PR and its recorded desktop/mobile approval are hard prerequisites.
- Do not add inline one-off component styling; use or extend an approved reusable contract.
- If a genuine component is missing, pause, consult the product owner, add it to the showcase, and obtain approval before resuming.
- “Library” is capitalized only as the page/navigation title; ordinary prose uses “library.”
- All statistics are all-time, library-scoped, and link to their exact contributing records when such a list surface exists.
- Log game appears only in the navbar.
- Keep existing entity and PlayEvent routes even when removing Menu/Manage navigation.
- Remove the DEBUG showcase only after the real page exercises its components.
- Keep the normal parallel `PYTEST_WORKERS`; run full verification through the managed hidden Windows process required by `AGENTS.md`.

---

### Task 1: Add the Library route, header, and Overview facts

**Files:**
- Create: `games/views/library.py`
- Modify: `games/views/__init__.py`
- Modify: `games/urls.py`
- Create: `tests/test_library_page.py`
- Create: `e2e/test_library_page_e2e.py`

**Interfaces:**
- Produces: authenticated `games:library` at `/tracker/library` and `library_page(request)`.

- [ ] **Step 1: Write route, authentication, and identity tests**

Assert anonymous access redirects to login; authenticated access renders the
exact title/subtitle; the full UUID appears once in monospace; CopyControl owns
the same UUID; Created is date-only through the request's presentation; username
and an updated timestamp are absent.

```python
response = client.get(reverse("games:library"))
html = response.content.decode()
assert (
    "Your games, play history, purchases, and customizations belong to this library"
    in html
)
assert str(user.library.pk) in html
assert 'data-copy-value="' + str(user.library.pk) + '"' in html
```

- [ ] **Step 2: Run the focused tests and confirm the route is missing**

Run: `make test-fast ARGS="tests/test_library_page.py -x"`

Expected: FAIL on `NoReverseMatch`.

- [ ] **Step 3: Implement the route and Overview fact composition**

Resolve `library = request.user.library` once. Compose:

```python
sections = [
    SectionedPageSection("overview", "Overview", overview_content),
    SectionedPageSection("activity", "Activity", activity_content),
    SectionedPageSection("customization", "Customization", customization_content),
    SectionedPageSection("purchases", "Purchases", purchases_content),
]
```

Use `FactList` with Library ID + `CopyControl` and Created. Use the exact header
subtitle from the spec and call `SectionedPageScaffold(sections,
navigation_label="Library sections", jump_label="Jump to a section")`.

- [ ] **Step 4: Pass route and identity tests**

Run: `make test-fast ARGS="tests/test_library_page.py -x"`

Expected: PASS.

- [ ] **Step 5: Commit route/identity**

```bash
git add games/views/library.py games/views/__init__.py games/urls.py tests/test_library_page.py e2e/test_library_page_e2e.py
git commit -m "feat: add Library identity page"
```

### Task 2: Add exact Overview statistics and Activity placeholder

**Files:**
- Modify: `games/views/library.py`
- Modify: `tests/test_library_page.py`

**Interfaces:**
- Produces: library-owned Games/Sessions/Purchases/Devices cards and static Activity copy.

- [ ] **Step 1: Write two-library count/link tests**

Create different counts in two libraries. Assert the current User sees only
their counts, each value links directly to the corresponding complete list,
labels are exactly Games/Sessions/Purchases/Devices, and zero remains a normal
linked value. Assert Overview contains neither Play Events nor status-history
statistics.

- [ ] **Step 2: Run the focused tests and confirm cards are absent**

Run: `make test-fast ARGS="tests/test_library_page.py -k 'overview or activity' -x"`

Expected: FAIL.

- [ ] **Step 3: Query scoped counts and render the approved copy**

```python
overview_cards = StatisticGrid(
    StatisticCard(
        "Games",
        Game.objects.for_library(library).count(),
        href=reverse("games:list_games"),
    ),
    StatisticCard(
        "Sessions",
        Session.objects.for_library(library).count(),
        href=reverse("games:list_sessions"),
    ),
    StatisticCard(
        "Purchases",
        Purchase.objects.for_library(library).count(),
        href=reverse("games:list_purchases"),
    ),
    StatisticCard(
        "Devices",
        Device.objects.for_library(library).count(),
        href=reverse("games:list_devices"),
    ),
)
```

Activity contains only:

```text
Activity is coming later
This section will be added as part of the Player's Journal.
```

- [ ] **Step 4: Pass Overview/Activity tests**

Run: `make test-fast ARGS="tests/test_library_page.py -k 'overview or activity' -x"`

Expected: PASS.

- [ ] **Step 5: Commit Overview/Activity**

```bash
git add games/views/library.py tests/test_library_page.py
git commit -m "feat: add Library overview and activity placeholder"
```

### Task 3: Add Customization rows and default Device editing

**Files:**
- Modify: `games/views/library.py`
- Modify: `games/api.py`
- Modify: `games/urls.py`
- Modify: `tests/test_library_page.py`
- Modify: `tests/test_library_preferences.py`
- Modify: `e2e/test_library_page_e2e.py`

**Interfaces:**
- Consumes: approved `EntitySummaryList`/`EntitySummaryRow` and #630 library-preference mutation.
- Produces: live optional default-Device update endpoint scoped to the current library.

- [ ] **Step 1: Write exact-copy/action/count tests**

Assert the transitional explanation and all three subtitles exactly match the
spec. Games count all current library Games, Platforms count private only, and
Devices count current-library Devices. Count links and Browse point to the
correct lists; Add points to the correct forms. Shared/foreign Platforms never
enter the private count.

Add API tests that a current-library Device or null saves, a foreign Device
404s, and a no-op leaves `UserLibraryPreferences.updated_at` unchanged.

- [ ] **Step 2: Run Customization tests and confirm content/API are missing**

Run: `make test-fast ARGS="tests/test_library_page.py -k customization tests/test_library_preferences.py -x"`

Expected: FAIL.

- [ ] **Step 3: Compose the three approved rows**

Use `EntitySummaryList` and `EntitySummaryRow`; do not add nested panels.
Pass Browse/Add action objects once and let the component choose desktop versus
mobile presentation. The Devices `detail` contains the current optional
live-saving dropdown and “Preselected when logging a game.” Use the existing
dropdown appearance; do not introduce SearchSelect in this issue.

- [ ] **Step 4: Implement and verify the scoped Device mutation**

The endpoint obtains `request.user.library`, resolves Device through
`Device.objects.for_library(library)`, and calls the no-op-aware preference
method. Return the same success/error trigger contract as existing live
settings.

Run: `make test-fast ARGS="tests/test_library_page.py tests/test_library_preferences.py -x"` and
`make test-e2e ARGS="e2e/test_library_page_e2e.py -k customization -x"`.

Expected: PASS, including mobile overflow actions and immediate save.

- [ ] **Step 5: Commit Customization**

```bash
git add games/views/library.py games/api.py games/urls.py tests/test_library_page.py tests/test_library_preferences.py e2e/test_library_page_e2e.py
git commit -m "feat: add Library customization section"
```

### Task 4: Add transitional Purchases statistics

**Files:**
- Modify: `games/views/library.py`
- Modify: `games/views/stats_links.py`
- Modify: `tests/test_library_page.py`
- Modify: `tests/test_stats_links.py`

**Interfaces:**
- Produces: exact all/refunded/non-refunded Purchase links and last-complete Total spent.

- [ ] **Step 1: Write contribution-set tests**

Create paid, zero-price, refunded, foreign-library, and different-currency
Purchases. Assert Purchases includes every own row, Refunded is the exact
refunded subset, Total spent excludes refunded but includes zero, and the sum
uses only one complete published converted currency. Follow every statistic
href and assert the returned Purchase primary keys exactly equal the records
used by the displayed value.

- [ ] **Step 2: Run Purchase-section tests and confirm missing statistics**

Run: `make test-fast ARGS="tests/test_library_page.py -k purchases tests/test_stats_links.py -x"`

Expected: FAIL.

- [ ] **Step 3: Render the temporary-home block and cards**

Use exact copy from the spec, an Add purchase header action, and three
StatisticCards. Build the subset links with existing `PurchaseFilter.where` and
`filter_url`; the all-Purchases link is the unfiltered list. Do not add a
separate Browse button or an inline conversion message.

- [ ] **Step 4: Pass contribution/link tests**

Run: `make test-fast ARGS="tests/test_library_page.py -k purchases tests/test_stats_links.py -x"`

Expected: PASS.

- [ ] **Step 5: Commit Purchases**

```bash
git add games/views/library.py games/views/stats_links.py tests/test_library_page.py tests/test_stats_links.py
git commit -m "feat: add Library purchase summary"
```

### Task 5: Replace the desktop navbar with the approved structure

**Files:**
- Modify: `common/layout.py`
- Modify: `games/views/general.py`
- Modify: `tests/test_navbar_playtime.py`
- Modify: `tests/test_navbar_log_button.py`
- Create: `tests/test_account_navbar.py`

**Interfaces:**
- Consumes: approved `AccountMenu` and existing `NavbarLogButton`.
- Produces: logo -> Home, Log game, Library, and account trigger.

- [ ] **Step 1: Write exact navbar/menu tests**

Assert authenticated HTML has no Home text link, Menu entity dropdown, or
hamburger; logo links to Home; Log game and Library are direct controls; and
there is one circular account trigger. Assert menu order, separators, exact
today/last-seven filter links, current-year Stats URL, Settings, conditional
Admin settings, Theme, and Logout. Assert username is a heading, not a link.

- [ ] **Step 2: Run navbar tests and confirm the old structure fails**

Run: `make test-fast ARGS="tests/test_account_navbar.py tests/test_navbar_playtime.py tests/test_navbar_log_button.py -x"`

Expected: FAIL on current Menu/Home/hamburger markup.

- [ ] **Step 3: Simplify `Navbar` and scope its supplied data**

Keep `NavbarLogButton` and its recent-session behavior. Replace `NavbarMenu`
entity construction with `AccountMenu`. The layout may resolve current route
and authorization, but all playtime/count queries remain in the request context
function and are scoped to `request.user.library`.

Derive one or two non-whitespace initials deterministically from the non-empty
username and pass them to `AccountMenu`; there is no generic-icon fallback. The
Stats URL is `reverse("games:stats_by_year", args=[localdate().year])`.

- [ ] **Step 4: Pass desktop navbar tests**

Run: `make test-fast ARGS="tests/test_account_navbar.py tests/test_navbar_playtime.py tests/test_navbar_log_button.py tests/test_theme_layout.py -x"`

Expected: PASS, including Theme disabled with the current explanation on both
Settings pages and enabled on Library.

- [ ] **Step 5: Commit desktop navigation**

```bash
git add common/layout.py games/views/general.py tests/test_account_navbar.py tests/test_navbar_playtime.py tests/test_navbar_log_button.py tests/test_theme_layout.py
git commit -m "feat: replace entity Menu with account navigation"
```

### Task 6: Implement the approved mobile navbar behavior

**Files:**
- Modify: `common/layout.py`
- Modify: `common/input.css`
- Modify: `e2e/test_library_page_e2e.py`
- Create: `e2e/test_account_navbar_e2e.py`

**Interfaces:**
- Produces: mobile logo icon + visible Log game/Library/account controls with no hamburger.

- [ ] **Step 1: Add narrow-width browser assertions**

At the approved mobile width, assert the wordmark text is hidden but its icon
link remains, all three controls fit without horizontal overflow, AccountMenu
opens/closes by keyboard and touch, and each link reaches the expected page.

- [ ] **Step 2: Run the browser test against desktop-only output**

Run: `make test-e2e ARGS="e2e/test_account_navbar_e2e.py -x"`

Expected: FAIL until responsive classes are applied.

- [ ] **Step 3: Apply responsive classes owned by Navbar**

Use existing logo assets and design tokens. Do not reintroduce a collapse
container or duplicate Log game for breakpoints. Verify long usernames remain
inside the account menu rather than affecting navbar width.

- [ ] **Step 4: Pass mobile navbar and Library responsive tests**

Run: `make test-e2e ARGS="e2e/test_account_navbar_e2e.py e2e/test_library_page_e2e.py -x"`.

Expected: PASS with no viewport overflow.

- [ ] **Step 5: Commit mobile navigation**

```bash
git add common/layout.py common/input.css e2e/test_account_navbar_e2e.py e2e/test_library_page_e2e.py
git commit -m "feat: keep primary navigation visible on mobile"
```

### Task 7: Remove the superseded Menu/showcase surfaces without deleting routes

**Files:**
- Modify: `games/urls.py`
- Delete: `games/views/library_kit_preview.py`
- Delete: `tests/test_library_kit_preview.py`
- Delete: `e2e/test_library_kit_preview_e2e.py`
- Modify: `tests/test_paths.py`
- Modify: `tests/test_rendered_pages.py`

**Interfaces:**
- Produces: final production navigation and no temporary preview route.

- [ ] **Step 1: Add route-preservation assertions**

Assert Game/Session/Purchase/Device/Platform/PlayEvent list/add routes still
resolve and contextual Game PlayEvent links still render. Assert the old Menu
navigation/route (if separately routed) and preview route do not resolve.

- [ ] **Step 2: Run route tests before cleanup**

Run: `make test-fast ARGS="tests/test_paths.py tests/test_rendered_pages.py -x"`

Expected: the new negative assertions fail while preview/Menu remain.

- [ ] **Step 3: Remove only superseded navigation/preview code**

Delete the DEBUG preview view, route, and preview-only browser tests. Remove the
old entity Menu surface and Manage links. Do not delete entity handlers, generic
PlayEvent URLs, filter/preset surfaces, or Home.

- [ ] **Step 4: Pass route/render tests**

Run: `make test-fast ARGS="tests/test_paths.py tests/test_rendered_pages.py tests/test_game_detail_links.py -x"`

Expected: PASS.

- [ ] **Step 5: Commit cleanup**

```bash
git add -A games/urls.py games/views/library_kit_preview.py tests/test_library_kit_preview.py e2e/test_library_kit_preview_e2e.py tests/test_paths.py tests/test_rendered_pages.py
git commit -m "refactor: retire Menu and Library kit preview"
```

### Task 8: Visual approval and full verification

**Files:**
- Review: complete real Library page and navbar
- Update: the page issue/PR approval record only after product-owner approval

**Interfaces:**
- Produces: approved initial Library experience.

- [ ] **Step 1: Exercise representative real data states**

Render desktop/mobile with zero and populated statistics, long UUID/username,
long entity names, shared/private Platforms, no default Device, selected
default Device, active conversion, conversion failure, superuser, and ordinary
User.

- [ ] **Step 2: Verify exact-link reproducibility manually**

Open every Overview/Purchases/Customization statistic and compare returned
records to its displayed value. Confirm old complete currency labels remain
honest during conversion.

- [ ] **Step 3: Pause for product-owner desktop/mobile approval**

Keep the PR draft and correct any visual/component gap through the required
component consultation process.

- [ ] **Step 4: Run the complete gate after approval changes**

Run the managed hidden Windows `make check` process and wait for its final log
and exit status.

Expected: exit 0 with default parallel workers.

- [ ] **Step 5: Record approval and mark the PR ready**

Add a dated issue/PR comment linking the approved desktop/mobile real-page
captures, then mark the PR ready for ordinary code review.
