# Issue 826 Neutral Sectioned-Page Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the Settings page's proven responsive section-navigation shell into neutral `SectionedPage*` components, migrate every existing Settings consumer without visual or behavioral change, and land that extraction as the prerequisite PR for issue #826.

**Architecture:** Move the current server-rendered header, section model, navigation, validation, panel, and scaffold into `common/components/sectioned_page.py`; rename the registered custom element and TypeScript controller to `<section-nav>`; and update the bottom-sheet focus hook plus all consumers in one atomic implementation commit. Settings-only fields, badges, live save, secret handling, and preview fixtures remain in `settings_kit.py`. No compatibility aliases are retained.

**Tech Stack:** Django 6, htpy-style Python component trees, Tailwind CSS/container queries, typed custom-element code generation, TypeScript, Vitest, pytest, and Playwright.

## Global Constraints

- Read `docs/superpowers/specs/2026-08-16-issue-826-library-ui-component-kit-design.md` before editing.
- This is PR 1. Do not add Library components, `/library`, the Library showcase, CopyControl, AccountMenu, models, migrations, APIs, or production navbar changes.
- Preserve the current Settings DOM shape, classes, responsive breakpoint, same-DOM list movement, bottom-sheet behavior, focus restoration, URL hashes, and media dependencies except for the approved neutral names.
- Do not add `Settings*` compatibility aliases. All in-repository callers move in the same commit.
- Every `SectionedPageScaffold` caller supplies `navigation_label` and `jump_label`; the neutral layer does not bake in Settings copy.
- If genuinely dead #630 conversion runtime code is found, stop. Removing it belongs in its own separately reviewed prerequisite PR and is not part of this extraction.
- Keep the Makefile's default parallel `PYTEST_WORKERS`.
- On Windows Codex desktop, launch every Make test/check target as a managed hidden process and wait for the final log and exit status.

## Exact rename contract

| Existing contract | Neutral contract |
| --- | --- |
| `SettingsSection` | `SectionedPageSection` |
| `SettingsPageHeader` | `SectionedPageHeader` |
| `SettingsSectionNav` | `SectionNav` |
| `SettingsScaffold` | `SectionedPageScaffold` |
| `<settings-section-nav>` | `<section-nav>` |
| `SettingsSectionNavProps` | `SectionNavProps` |
| `readSettingsSectionNavProps` | `readSectionNavProps` |
| `data-settings-page-header` | `data-sectioned-page-header` |
| `data-settings-page-actions` | `data-sectioned-page-actions` |
| `data-settings-scaffold` | `data-sectioned-page-scaffold` |
| `data-settings-section` | `data-sectioned-page-section` |
| `data-settings-section-header` | `data-sectioned-page-section-header` |
| `data-settings-section-content` | `data-sectioned-page-section-content` |
| `data-settings-section-heading` | `data-sectioned-page-section-heading` |

All existing `data-section-nav-*` hooks remain unchanged.

## File map

| File | Responsibility |
| --- | --- |
| `common/components/sectioned_page.py` | Neutral section model, header, navigation, validation, panels, and scaffold |
| `common/components/settings_kit.py` | Settings-only components after extraction |
| `common/components/custom_elements.py` | Neutral `<section-nav>` registration |
| `common/components/__init__.py` | Neutral public exports and removal of old exports |
| `ts/elements/section-nav.ts` | Renamed same-DOM responsive navigation controller |
| `ts/elements/section-nav.test.ts` | Neutral custom-element contract and lifecycle coverage |
| `ts/generated/props.ts` | Regenerated `SectionNavProps` reader contract |
| `ts/elements/sheet-controller.ts` | Neutral section-heading focus hook |
| `ts/elements/sheet-controller.test.ts` | Neutral focus fixture |
| `games/views/settings.py` | Personal/Admin Settings callers with explicit labels |
| `games/views/settings_kit_preview.py` | Settings kit preview caller with explicit labels |
| `tests/test_settings_ui_kit.py` | Neutral unit contracts plus Settings-kit regression coverage |
| `tests/test_settings_page.py` | Personal Settings neutral hooks |
| `tests/test_admin_settings_page.py` | Admin Settings neutral hooks |
| `tests/test_settings_ui_kit_preview.py` | Preview neutral hooks and media path |
| `e2e/test_settings_page_e2e.py` | Personal Settings neutral scaffold selector |
| `e2e/test_admin_settings_page_e2e.py` | Unchanged Admin Settings regression coverage run in the focused gate |
| `e2e/test_settings_ui_kit_e2e.py` | Neutral host/scaffold selectors and responsive behavior |

---

### Task 1: Neutralize the sectioned-page contract atomically

**Files:**
- Create: `common/components/sectioned_page.py`
- Modify: `common/components/settings_kit.py`
- Modify: `common/components/custom_elements.py`
- Modify: `common/components/__init__.py`
- Rename: `ts/elements/settings-section-nav.ts` to `ts/elements/section-nav.ts`
- Rename: `ts/elements/settings-section-nav.test.ts` to `ts/elements/section-nav.test.ts`
- Modify: `ts/elements/sheet-controller.ts`
- Modify: `ts/elements/sheet-controller.test.ts`
- Modify: `games/views/settings.py`
- Modify: `games/views/settings_kit_preview.py`
- Modify: `tests/test_settings_ui_kit.py`
- Modify: `tests/test_settings_page.py`
- Modify: `tests/test_admin_settings_page.py`
- Modify: `tests/test_settings_ui_kit_preview.py`
- Modify: `e2e/test_settings_page_e2e.py`
- Review: `e2e/test_admin_settings_page_e2e.py`
- Modify: `e2e/test_settings_ui_kit_e2e.py`

**Interfaces:**
- Produces: immutable `SectionedPageSection(id: str, label: str, content: Child, description: str = "")`.
- Produces: `SectionedPageHeader(title: str, *, description: str = "", actions: Children = None) -> Node`.
- Produces: `SectionNav(sections: Sequence[SectionedPageSection], *, navigation_label: str, jump_label: str) -> Node`.
- Produces: `SectionedPageScaffold(sections: Sequence[SectionedPageSection], *, navigation_label: str, jump_label: str) -> Node`.
- Produces: typed, prop-free `<section-nav>` with `SectionNavProps` and `readSectionNavProps`.
- Removes: all four old Python exports, the old custom-element tag/reader/class, and all old sectioned-page data hooks.

- [ ] **Step 1: Change the server tests to the neutral contract before production code**

In `tests/test_settings_ui_kit.py`, import the four neutral APIs from `common.components`, rename `SettingsPageHeaderTest` to `SectionedPageHeaderTest`, and rename `SettingsScaffoldTest` to `SectionedPageScaffoldTest`. Convert the helper and calls as follows:

```python
class SectionedPageScaffoldTest(SimpleTestCase):
    def _sections(self):
        return [
            SectionedPageSection("general", "General", Div()["General fields"]),
            SectionedPageSection("privacy", "Privacy", Div()["Privacy fields"]),
        ]

    def _scaffold(self, sections=None):
        return SectionedPageScaffold(
            self._sections() if sections is None else sections,
            navigation_label="Settings sections",
            jump_label="Jump to a section",
        )
```

Update assertions to expect `<section-nav>`, `dist/elements/section-nav.js`, and the `data-sectioned-page-*` hooks from the rename table. Preserve every assertion about one shared list, sticky placement, overflow, container breakpoint, dialog semantics, validation, headings, focusability, and dropdown media.

Add a direct label contract so neutral copy cannot regress back to Settings defaults:

```python
def test_section_nav_uses_caller_supplied_labels():
    html = str(
        SectionNav(
            [SectionedPageSection("overview", "Overview", Div())],
            navigation_label="Library kit sections",
            jump_label="Jump to a component group",
        )
    )

    assert 'aria-label="Library kit sections"' in html
    assert "Library kit sections" in html
    assert "Jump to a component group" in html
    assert 'aria-label="Close library kit sections"' in html
```

Keep the validation cases, but assert the exact neutral messages:

```python
with pytest.raises(
    ValueError,
    match="SectionedPageScaffold requires at least one section",
):
    self._scaffold([])
with pytest.raises(ValueError, match="Invalid sectioned-page section id"):
    self._scaffold([SectionedPageSection("not valid", "Bad", Div())])
with pytest.raises(ValueError, match="Duplicate sectioned-page section id"):
    self._scaffold(
        [
            SectionedPageSection("same", "One", Div()),
            SectionedPageSection("same", "Two", Div()),
        ]
    )
```

- [ ] **Step 2: Rename the client tests to the neutral tag before production code**

Rename `ts/elements/settings-section-nav.test.ts` to `ts/elements/section-nav.test.ts`, change its import to `./section-nav.js`, its fixture host to `<section-nav>`, its element lookup to `section-nav`, and its suite title to `<section-nav> same-DOM sheet/rail layout`. Preserve every existing observer, reconnect, narrow/wide, open-sheet transition, and link-list identity assertion.

In `ts/elements/sheet-controller.test.ts`, change only the destination heading fixture:

```html
<h2 data-sectioned-page-section-heading tabindex="-1">Privacy</h2>
```

- [ ] **Step 3: Run the intended-red contract checks**

Run managed-hidden:

```bash
make test ARGS="tests/test_settings_ui_kit.py -x"
```

Expected: FAIL during collection because the neutral Python exports do not exist.

Run:

```bash
pnpm test:ts -- ts/elements/section-nav.test.ts
```

Expected: FAIL because `ts/elements/section-nav.ts` does not exist.

- [ ] **Step 4: Extract the complete neutral server implementation**

Create `common/components/sectioned_page.py` by moving the current `SettingsSection`, `SettingsPageHeader`, `_validate_sections`, `_section_link`, `SettingsSectionNav`, `_section_panel`, and `SettingsScaffold` implementation out of `settings_kit.py`. Preserve the current classes and DOM ordering, but apply the exact rename table and these signature/copy changes:

```python
@dataclass(frozen=True, slots=True)
class SectionedPageSection:
    id: str
    label: str
    content: Child
    description: str = ""


def SectionNav(
    sections: Sequence[SectionedPageSection],
    *,
    navigation_label: str,
    jump_label: str,
) -> Node:
    _validate_sections(sections)
    sheet_id = randomid(
        seed="section-nav-",
        content=":".join(section.id for section in sections),
        length=20,
    )
```

Use `navigation_label` for the trigger title, bottom-sheet title, and rail `aria-label`; use `jump_label` for the trigger subtitle; and pass this exact close label:

```python
close_label = f"Close {navigation_label.lower()}"
```

Use these exact validation messages:

```python
if not sections:
    raise ValueError("SectionedPageScaffold requires at least one section.")
if not _SECTION_ID.fullmatch(section.id):
    raise ValueError(
        f"Invalid sectioned-page section id {section.id!r}; use an HTML-safe id."
    )
if section.id in seen:
    raise ValueError(f"Duplicate sectioned-page section id {section.id!r}.")
```

The scaffold must forward both labels rather than silently choosing them:

```python
SectionNav(
    sections,
    navigation_label=navigation_label,
    jump_label=jump_label,
)
```

Delete the moved definitions and now-unused imports/constants from `settings_kit.py`. Do not re-export or alias the old names there.

- [ ] **Step 5: Register and implement the neutral custom element**

In `common/components/custom_elements.py`, replace the current prop-free registration with:

```python
class SectionNavProps(TypedDict):
    pass


register_element("section-nav", "SectionNav", SectionNavProps)
```

Rename the TypeScript source to `ts/elements/section-nav.ts` and make only these identity changes while preserving its implementation:

```typescript
import { readSectionNavProps } from "../generated/props.js";

class SectionNavElement extends HTMLElement {
  connectedCallback(): void {
    readSectionNavProps(this);
  }
}

customElements.define("section-nav", SectionNavElement);
```

The snippet identifies the renamed lines; retain all current fields and lifecycle methods between them.

In `ts/elements/sheet-controller.ts`, change the destination lookup to:

```typescript
destination.querySelector<HTMLElement>(
  "[data-sectioned-page-section-heading]",
) ?? destination;
```

- [ ] **Step 6: Export only the neutral public APIs**

Import `SectionedPageHeader`, `SectionedPageScaffold`, `SectionedPageSection`, and `SectionNav` from `common.components.sectioned_page` in `common/components/__init__.py` and add them to `__all__`. Remove `SettingsPageHeader`, `SettingsScaffold`, `SettingsSection`, and `SettingsSectionNav` from both the import block and `__all__`.

- [ ] **Step 7: Migrate all three server consumers with explicit Settings labels**

In `games/views/settings.py` and `games/views/settings_kit_preview.py`, apply the four Python renames. Every scaffold call must become:

```python
SectionedPageScaffold(
    sections,
    navigation_label="Settings sections",
    jump_label="Jump to a section",
)
```

This includes personal Settings, Admin Settings, and the Settings UI kit preview. Keep their copy, permissions, data access, fields, URLs, actions, and `render_page` arguments unchanged.

- [ ] **Step 8: Migrate server-rendered and browser regression selectors**

Apply the hook/tag/media rename table in:

- `tests/test_settings_page.py`
- `tests/test_admin_settings_page.py`
- `tests/test_settings_ui_kit_preview.py`
- `e2e/test_settings_page_e2e.py`
- `e2e/test_settings_ui_kit_e2e.py`

`e2e/test_admin_settings_page_e2e.py` already uses the unchanged `data-section-nav-*` hooks; review it without editing and retain it in the focused browser run.

Keep `data-section-nav-*` selectors unchanged. Replace `settings-section-nav` with `section-nav` and `dist/elements/settings-section-nav.js` with `dist/elements/section-nav.js`. Do not weaken counts, focus expectations, narrow/wide assertions, or visual screenshots.

- [ ] **Step 9: Regenerate typed props and run the focused gate**

Run:

```bash
make gen-element-types
pnpm test:ts -- ts/elements/section-nav.test.ts ts/elements/sheet-controller.test.ts
pnpm exec tsc --noEmit -p tsconfig.check.json
```

Then run these Make targets through the managed hidden process:

```bash
make test ARGS="tests/test_settings_ui_kit.py tests/test_settings_page.py tests/test_admin_settings_page.py tests/test_settings_ui_kit_preview.py -x"
make test ARGS="e2e/test_settings_ui_kit_e2e.py e2e/test_settings_page_e2e.py e2e/test_admin_settings_page_e2e.py -x"
```

Expected: all commands exit 0.

- [ ] **Step 10: Prove the old contract is gone**

Run:

```bash
rg -n "SettingsPageHeader|SettingsScaffold|SettingsSectionNav|SettingsSection|settings-section-nav|data-settings-page-header|data-settings-page-actions|data-settings-scaffold|data-settings-section" common games tests e2e ts
```

Expected: no matches. Inspect the diff to confirm Settings-only fields, badges, source metadata, secret handling, and live-save behavior did not move.

- [ ] **Step 11: Commit the buildable neutralization as one unit**

Do not commit Steps 4-8 separately; deleting old exports before all consumers move would create non-buildable intermediate commits.

```bash
git add -A common/components games/views tests e2e ts/elements ts/generated/props.ts
git commit -m "refactor: extract neutral sectioned page components"
```

---

### Task 2: Run the full gate and prepare PR 1

**Files:**
- Review: every file changed by Task 1
- External record: issue #826 and PR 1 description

**Interfaces:**
- Produces: a standalone, buildable neutral-foundation PR that PR 2 can branch from after merge.

- [ ] **Step 1: Audit the complete diff and scope**

Run:

```bash
git diff main...HEAD --stat
git diff main...HEAD --name-only
git diff main...HEAD -- ts/toast.ts ts/toast.test.ts ts/library-conversion-status.ts ts/library-conversion-status.test.ts common/layout.py
```

Expected: the final command has no output. Confirm there is no Library route/component, production navbar change, model/migration/API work, dead-code cleanup, or compatibility alias.

- [ ] **Step 2: Run the complete verification gate**

Run `make check` through the managed hidden Windows process and wait for its final log and exit status.

Expected: exit 0 using the Makefile's default parallel workers.

- [ ] **Step 3: Verify the committed worktree state**

Run:

```bash
git status --short
git log -1 --oneline
```

Expected: the worktree is clean and the latest commit is `refactor: extract neutral sectioned page components`.

- [ ] **Step 4: Open PR 1 and keep PR 2 dependent on it**

Describe this as a behavior-preserving neutral extraction for issue #826. Include the exact rename contract, focused-test results, full `make check` result, and the absence of #630 cleanup. Do not start the component-kit PR from this branch until PR 1 is merged; then branch PR 2 from the updated `main`.
