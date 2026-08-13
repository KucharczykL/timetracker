# Library UI Component Kit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and visually approve every new reusable component needed by the Library page and account navigation before assembling the finished page.

**Architecture:** Extract the sectioned-page structure from the Settings-specific kit into neutral components, leave Settings field composition in its existing module, and add small server-rendered summary/navigation components. Extend the existing toast store compatibly and put conversion-specific persistence in its own TypeScript module. A DEBUG-only preview composes new pieces with existing primitives for desktop/mobile approval.

**Tech Stack:** htpy-style Python components, Tailwind CSS/container queries, TypeScript custom elements, Alpine toast store, Flowbite-compatible Dropdown primitives, pytest, Vitest, Playwright.

## Global Constraints

- Read `docs/superpowers/specs/2026-08-13-library-page-and-navigation-design.md` before editing.
- #630 must be merged first so preview conversion states can use the real status shape.
- New component names are neutral; do not retain `SettingsPageHeader`, `SettingsScaffold`, or `SettingsSectionNav` compatibility aliases.
- Settings must render and behave unchanged after migration to the neutral structure.
- Reuse existing buttons, dropdown behavior, icons, form fields, typography, panels, and tokens.
- The preview is DEBUG-only, absent from production and navigation, and focuses on new components.
- Do not implement `/library` or replace the production navbar in this issue.
- No inline one-off styling in later consumers; component contracts own their layout.
- Keep the PR draft until the product owner approves rendered desktop and mobile states in writing.
- Keep the normal parallel `PYTEST_WORKERS`; run full verification through the managed hidden Windows process required by `AGENTS.md`.

---

### Task 1: Extract the neutral sectioned-page structure

**Files:**
- Create: `common/components/sectioned_page.py`
- Modify: `common/components/settings_kit.py`
- Modify: `common/components/__init__.py`
- Rename: `ts/elements/settings-section-nav.ts` to `ts/elements/section-nav.ts`
- Rename: `ts/elements/settings-section-nav.test.ts` to `ts/elements/section-nav.test.ts`
- Modify: `games/views/settings.py`
- Modify: `tests/test_settings_ui_kit.py`
- Modify: `e2e/test_settings_page_e2e.py`

**Interfaces:**
- Produces: `SectionedPageHeader`, `SectionedPageSection`, `SectionNav`, and `SectionedPageScaffold`.

- [ ] **Step 1: Rename tests to the neutral public contract**

Update the component tests to import and render:

```python
sections = [
    SectionedPageSection("one", "One", Div()["First"]),
    SectionedPageSection("two", "Two", Div()["Second"], "Description"),
]
page = Div(class_="flex flex-col gap-6")[
    SectionedPageHeader("Settings"),
    SectionedPageScaffold(
        sections,
        navigation_label="Settings sections",
        jump_label="Jump to a section",
    ),
]
```

Keep byte-relevant class/data assertions unchanged except intentional neutral
attribute/custom-element names (`section-nav`, `data-sectioned-page-*`).

- [ ] **Step 2: Run focused Python and TypeScript tests and confirm missing names**

Run: `make test-fast ARGS="tests/test_settings_ui_kit.py -x"` and
`pnpm test:ts -- section-nav`.

Expected: FAIL until the neutral components/module exist.

- [ ] **Step 3: Move only generic layout code**

Move the section dataclass, ID validation, header, nav, section panel, and
scaffold to `sectioned_page.py`. Parameterize copy that was hard-coded to
Settings:

Expose exact signatures `SectionNav(sections, *, navigation_label: str,
jump_label: str) -> Node` and `SectionedPageScaffold(sections, *,
navigation_label: str, jump_label: str) -> Node`. Both call the shared section
validator; the scaffold passes both labels to its one `SectionNav` instance.

Replace the custom element tag with `section-nav` and update generated element
types through the normal generator. Keep LiveSettingFields, source badges,
readonly fields, and setting-field layouts in `settings_kit.py`.

- [ ] **Step 4: Migrate Settings and pass focused tests**

Run: `make test-fast ARGS="tests/test_settings_ui_kit.py tests/test_settings_page.py tests/test_admin_settings_page.py -x"` and `pnpm test:ts -- section-nav`.

Expected: PASS with unchanged Settings screenshots/behavior.

- [ ] **Step 5: Commit the neutral extraction**

```bash
git add common/components games/views/settings.py tests e2e ts/elements
git commit -m "refactor: generalize sectioned page components"
```

### Task 2: Add statistic and fact components

**Files:**
- Create: `common/components/library_kit.py`
- Modify: `common/components/__init__.py`
- Create: `tests/test_library_ui_components.py`

**Interfaces:**
- Produces: `StatisticGrid`, `StatisticCard`, and `FactList`.

- [ ] **Step 1: Write linked/plain statistic and fact-list tests**

```python
def test_statistic_card_links_the_value_not_a_separate_browse_label():
    html = str(StatisticCard("Games", "851", href="/tracker/game/list"))
    assert 'href="/tracker/game/list"' in html
    assert "Games" in html and "851" in html
    assert "Browse" not in html


def test_plain_statistic_has_no_link():
    html = str(StatisticCard("Unavailable", "—"))
    assert "<a" not in html


def test_fact_list_keeps_uuid_and_copy_control_separate():
    html = str(FactList([("Library ID", "018f…"), ("Created", "31/12/2022")]))
    assert "Library ID" in html and "Created" in html
```

- [ ] **Step 2: Run tests and confirm components are absent**

Run: `make test-fast ARGS="tests/test_library_ui_components.py -x"`

Expected: import failure.

- [ ] **Step 3: Implement semantic responsive components**

`StatisticCard(label, value, href=None)` renders one card whose value is the
link when `href` is present; the accessible name combines value and label.
`StatisticGrid(*cards)` owns its responsive columns. `FactList(facts)` accepts
`Sequence[tuple[str, Child]]`, renders a semantic definition list, and does not
embed copy behavior.

- [ ] **Step 4: Pass component tests**

Run: `make test-fast ARGS="tests/test_library_ui_components.py -x"`

Expected: PASS.

- [ ] **Step 5: Commit statistics/facts**

```bash
git add common/components/library_kit.py common/components/__init__.py tests/test_library_ui_components.py
git commit -m "feat: add reusable statistic and fact components"
```

### Task 3: Add entity summary rows and responsive actions

**Files:**
- Modify: `common/components/library_kit.py`
- Modify: `tests/test_library_ui_components.py`
- Create: `e2e/test_library_ui_components_e2e.py`

**Interfaces:**
- Produces: `EntitySummaryList` and `EntitySummaryRow`.

- [ ] **Step 1: Write desktop/mobile composition tests**

Render Games with Browse/Add, Platforms with Browse/Add, and Devices with a
detail node. Assert one quiet divider list, no nested panel/card border,
right-aligned linked count, desktop actions, one accessible row-labelled
overflow trigger, and detail content below the row.

```python
EntitySummaryRow(
    label="Games",
    subtitle="Games currently tracked in this library.",
    count="851",
    count_href="/tracker/game/list",
    actions=(
        DropdownLinkItem(url="/tracker/game/list", label="Browse"),
        DropdownLinkItem(url="/tracker/game/add", label="Add"),
    ),
)
```

- [ ] **Step 2: Run focused tests and confirm missing rows**

Run: `make test-fast ARGS="tests/test_library_ui_components.py -k entity -x"`

Expected: FAIL on missing imports.

- [ ] **Step 3: Implement container-query row layout**

The component renders one action source through the existing Dropdown
machinery: visible Browse/Add controls in wide containers and the same actions
inside an ellipsis menu in narrow containers. Do not duplicate action URLs in
the caller. `detail` is optional and occupies a subtle full-width row below the
primary line.

- [ ] **Step 4: Verify keyboard and responsive behavior**

Run: `make test-fast ARGS="tests/test_library_ui_components.py -x"` and
`make test-e2e ARGS="e2e/test_library_ui_components_e2e.py -x"`.

Expected: PASS, including Escape, focus return, outside-click dismissal, and
container-width rather than viewport-width switching.

- [ ] **Step 5: Commit summary rows**

```bash
git add common/components/library_kit.py tests/test_library_ui_components.py e2e/test_library_ui_components_e2e.py
git commit -m "feat: add responsive entity summary rows"
```

### Task 4: Add the accessible CopyControl

**Files:**
- Modify: `common/components/library_kit.py`
- Create: `ts/elements/copy-control.ts`
- Create: `ts/elements/copy-control.test.ts`
- Modify: `tests/test_library_ui_components.py`
- Modify: `e2e/test_library_ui_components_e2e.py`

**Interfaces:**
- Produces: `CopyControl(value: str, *, label: str = "Copy") -> Node` and `<copy-control>` behavior.

- [ ] **Step 1: Write server and client failure/success tests**

Assert the full value lives in a data attribute, the button has an accessible
target description, clipboard success changes Copy -> Copied temporarily and
announces it, clipboard rejection shows/announces “Couldn't copy”, and neither
path emits a global toast.

- [ ] **Step 2: Run focused tests and confirm missing behavior**

Run: `make test-fast ARGS="tests/test_library_ui_components.py -k copy -x"` and
`pnpm test:ts -- copy-control`.

Expected: FAIL.

- [ ] **Step 3: Implement the custom element**

```typescript
class CopyControlElement extends HTMLElement {
  async copy(): Promise<void> {
    const value = this.dataset.copyValue ?? "";
    try {
      await navigator.clipboard.writeText(value);
      this.setState("Copied");
      window.setTimeout(() => this.setState("Copy"), 2000);
    } catch {
      this.setState("Couldn't copy");
    }
  }
}
```

Use the repository custom-element registration/generation pattern and an
`aria-live="polite"` label owned by the control.

- [ ] **Step 4: Pass unit and browser tests**

Run: `pnpm test:ts -- copy-control` and
`make test-e2e ARGS="e2e/test_library_ui_components_e2e.py -k copy -x"`.

Expected: PASS.

- [ ] **Step 5: Commit CopyControl**

```bash
git add common/components/library_kit.py ts/elements/copy-control.ts ts/elements/copy-control.test.ts tests/test_library_ui_components.py e2e/test_library_ui_components_e2e.py
git commit -m "feat: add reusable copy control"
```

### Task 5: Add the reusable circular AccountMenu

**Files:**
- Create: `common/components/navigation.py`
- Modify: `common/components/__init__.py`
- Modify: `tests/test_library_ui_components.py`
- Modify: `e2e/test_library_ui_components_e2e.py`

**Interfaces:**
- Produces: `AccountMenu(username, initials, today, last_7, stats_url, settings_url, admin_settings_url, theme, logout_url)`.

- [ ] **Step 1: Write composition and authorization tests**

Assert the trigger is circular, exposes the username/menu purpose, displays
initials or a generic user icon, and the menu order/separators exactly match the
spec. Pass `admin_settings_url=None` and assert the item is absent rather than
disabled.

- [ ] **Step 2: Run tests and confirm AccountMenu is absent**

Run: `make test-fast ARGS="tests/test_library_ui_components.py -k account -x"`

Expected: import failure.

- [ ] **Step 3: Compose the account menu from existing primitives**

Use the existing Dropdown/MenuDropdown behavior, `Duration` nodes supplied by
the caller, `ThemeToggle`, and `DropdownDivider`. The component owns grouping,
ordering, and trigger shape; it does not query User or Session itself.

- [ ] **Step 4: Verify keyboard/menu behavior**

Run: `make test-fast ARGS="tests/test_library_ui_components.py -k account -x"` and
`make test-e2e ARGS="e2e/test_library_ui_components_e2e.py -k account -x"`.

Expected: PASS.

- [ ] **Step 5: Commit AccountMenu**

```bash
git add common/components/navigation.py common/components/__init__.py tests/test_library_ui_components.py e2e/test_library_ui_components_e2e.py
git commit -m "feat: add reusable account menu"
```

### Task 6: Extend toasts and connect conversion status

**Files:**
- Modify: `ts/toast.ts`
- Modify: `ts/toast.test.ts`
- Modify: `ts/globals.d.ts`
- Create: `ts/conversion-status.ts`
- Create: `ts/conversion-status.test.ts`
- Modify: `common/layout.py`
- Modify: `tests/test_rendered_pages.py`

**Interfaces:**
- Produces: `window.toast(message, type?, {id?, persistent?})`,
  `window.dismissToast(id)`, and conversion-specific status reconciliation.

- [ ] **Step 1: Write backward-compatibility and persistent-toast tests**

Existing two-argument callers must retain current timers. Add tests that a
stable id replaces instead of duplicates, `persistent=true` creates no timer,
explicit removal works, running dismissal is stored per tab/version/phase,
failure appears even after running was dismissed, and completion always emits
one normal five-second success toast for a tab that observed the operation.

- [ ] **Step 2: Run Vitest and confirm the option/status APIs are absent**

Run: `pnpm test:ts -- toast conversion-status`.

Expected: FAIL.

- [ ] **Step 3: Extend the generic store without operation concepts**

```typescript
interface ToastOptions {
  id?: string;
  persistent?: boolean;
}

function toast(message: string, type = "info", options: ToastOptions = {}): void {
  document.dispatchEvent(new CustomEvent("show-toast", {
    detail: { message, type, id: options.id, persistent: options.persistent },
    bubbles: true,
  }));
}
```

The Alpine store upserts by stable string id and starts no timer for persistent
entries. Keep numeric generated ids for old calls.

- [ ] **Step 4: Implement conversion-specific reconciliation**

Read server-rendered initial status, use the authenticated #630 status endpoint
while running, pause until `retry_at` after failure, and store dismissals under
`sessionStorage` keys containing library UUID, requested version, and phase.
Stop all timers on terminal success. A tab with no observed version does not
replay success.

- [ ] **Step 5: Pass toast/status tests and commit**

Run: `pnpm test:ts -- toast conversion-status` and
`make test-fast ARGS="tests/test_rendered_pages.py -k toast -x"`.

Expected: PASS.

```bash
git add ts/toast.ts ts/toast.test.ts ts/globals.d.ts ts/conversion-status.ts ts/conversion-status.test.ts common/layout.py tests/test_rendered_pages.py
git commit -m "feat: add persistent conversion toasts"
```

### Task 7: Build the DEBUG-only component showcase

**Files:**
- Create: `games/views/library_kit_preview.py`
- Modify: `games/urls.py`
- Create: `tests/test_library_kit_preview.py`
- Create: `e2e/test_library_kit_preview_e2e.py`

**Interfaces:**
- Produces: DEBUG-only `/tracker/library-kit-preview/`.

- [ ] **Step 1: Write route-boundary tests**

Assert `reverse("games:library_kit_preview")` works under `DEBUG=True`, route
resolution returns 404/NoReverseMatch under `DEBUG=False`, and the preview
never appears in navbar HTML.

- [ ] **Step 2: Run route tests and confirm preview is absent**

Run: `make test-fast ARGS="tests/test_library_kit_preview.py -x"`

Expected: FAIL.

- [ ] **Step 3: Compose every new state without implementing Library**

Show neutral headers/scaffolds, linked/plain/zero statistics, identity facts
with CopyControl success/error affordances, all entity-row variants, AccountMenu
with and without admin, and running/failed/success conversion toast triggers.
Use existing primitives for surrounding context. Do not make counts query real
library data or save the default Device.

- [ ] **Step 4: Pass route and browser smoke tests**

Run: `make test-fast ARGS="tests/test_library_kit_preview.py tests/test_library_ui_components.py -x"` and
`make test-e2e ARGS="e2e/test_library_kit_preview_e2e.py -x"`.

Expected: PASS at representative narrow and wide container widths.

- [ ] **Step 5: Commit the showcase**

```bash
git add games/views/library_kit_preview.py games/urls.py tests/test_library_kit_preview.py e2e/test_library_kit_preview_e2e.py
git commit -m "feat: showcase Library UI components"
```

### Task 8: Visual approval and final gate

**Files:**
- Review: all component-kit files
- Update: the component issue/PR approval record only after product-owner approval

**Interfaces:**
- Produces: approved stable component contracts consumed by the Library-page plan.

- [ ] **Step 1: Run the preview in a production-representative theme/data set**

Open the DEBUG route at desktop and mobile sizes and capture every new component
state, including long username, full UUID, zero counts, long row labels, no-admin
account menu, and all conversion toast states.

- [ ] **Step 2: Pause for product-owner visual review**

Keep the PR draft. Record requested changes and implement them through the same
component contracts; do not defer visual fixes to the Library page.

- [ ] **Step 3: Record explicit approval**

After approval, add a dated issue/PR comment linking the approved desktop and
mobile captures. Do not treat test passage as visual approval.

- [ ] **Step 4: Run the complete gate**

Run the managed hidden Windows `make check` process and wait for the final log
and exit status.

Expected: exit 0 with default parallel workers.

- [ ] **Step 5: Mark the PR ready for review**

The DEBUG preview remains in this issue and is removed only when the finished
Library page exercises every component.
