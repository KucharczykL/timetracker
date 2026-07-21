# Source Badge Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explain the blue source-badge treatment with the concise, color-independent status text `Non-default source (default source: “Default”)`.

**Architecture:** The server-rendered source badge owns the canonical tooltip copy and renders a stable status-row hook for unlocked badges. The live-setting custom element toggles that row from the resolved PATCH response at the same time it updates the source label and tone.

**Tech Stack:** Python 3.14, Django component builders, TypeScript custom elements, pytest, Vitest, Playwright, Makefile verification.

## Global Constraints

- Keep the existing `Source` row unchanged; it describes the current source.
- Show `Status: Non-default source (default source: “Default”)` only for unlocked non-default sources.
- Neutral `Default` badges and warning-colored locked badges do not expose the non-default status.
- Live source changes update status visibility without a page reload.

---

### Task 1: Server-rendered source status

**Files:**
- Modify: `common/components/settings_kit.py:48-72,281-340`
- Test: `tests/test_settings_ui_kit.py:107-175`

**Interfaces:**
- Consumes: `SettingSourceBadge(source: str, *, locked: bool = False, ...) -> Node` and `TooltipDefinition`.
- Produces: an unlocked tooltip row marked with `data-setting-source-status`; the row is visible exactly when `source != "default"`.

- [ ] **Step 1: Write failing server-rendering tests**

Add assertions covering the exact copy, the default hidden state, the non-default visible state, and the locked omission:

```python
def test_non_default_source_badge_explains_highlight(self):
    personal = str(SettingSourceBadge("user", id="personal-source-tip"))
    default = str(SettingSourceBadge("default", id="default-source-tip"))
    locked = str(SettingSourceBadge("env", locked=True, id="locked-source-tip"))

    assert "Non-default source (default source: “Default”)" in personal
    assert 'data-setting-source-status=""' in personal
    assert 'data-setting-source-status="" hidden=""' in default
    assert "Non-default source" not in locked
```

- [ ] **Step 2: Run the server test and verify RED**

Run:

```bash
direnv exec . make test PYTEST_ADDOPTS='tests/test_settings_ui_kit.py::SettingsBadgeAndFieldStateTest::test_non_default_source_badge_explains_highlight -q'
```

Expected: FAIL because `data-setting-source-status` and the approved copy are absent.

- [ ] **Step 3: Render the canonical status row**

In `common/components/settings_kit.py`, add:

```python
_NON_DEFAULT_SOURCE_STATUS = "Non-default source (default source: “Default”)"
```

After the `Source` tooltip definition, append a status definition only for unlocked badges. Keep a stable hidden hook for the default source so live updates can reveal it:

```python
if not locked:
    status_attributes: list[tuple[str, str]] = [
        ("data-setting-source-status", "")
    ]
    if source_value == "default":
        status_attributes.append(("hidden", ""))
    tooltip_definitions.append(
        TooltipDefinition(
            "Status",
            _NON_DEFAULT_SOURCE_STATUS,
            status_attributes,
        )
    )
```

- [ ] **Step 4: Run the server test and verify GREEN**

Run the Step 2 command again.

Expected: the targeted pytest test passes, and all 579 Vitest tests remain green through the Makefile prerequisite.

---

### Task 2: Live status synchronization

**Files:**
- Modify: `ts/elements/live-setting-fields.ts:151-190`
- Test: `ts/elements/live-setting-fields.test.ts:8-180`
- Test: `e2e/test_settings_page_e2e.py:31-90`

**Interfaces:**
- Consumes: the `data-setting-source-status` tooltip row from Task 1 and `ResolvedSetting.source` / `ResolvedSetting.locked` from the PATCH response.
- Produces: immediate status-row visibility synchronized with badge text, tooltip description, ARIA label, and tone.

- [ ] **Step 1: Write failing live-update assertions**

Add the stable status hook to the Vitest fixture:

```html
<div data-setting-source-status hidden>
  <dt>Status</dt>
  <dd>Non-default source (default source: “Default”)</dd>
</div>
```

In `updates source metadata from each resolved PATCH response`, assert:

```typescript
const status = badge.closest("pop-over")!
  .querySelector<HTMLElement>("[data-setting-source-status]")!;
expect(status.hidden).toBe(true);

// After the `user` response:
expect(status.hidden).toBe(false);

// After a final mocked `default` response:
expect(status.hidden).toBe(true);
```

Extend the mock with a third resolved response whose source is `default`, then fire the corresponding third change.

- [ ] **Step 2: Run Vitest and verify RED**

Run:

```bash
direnv exec . make test PYTEST_ADDOPTS='tests/test_settings_ui_kit.py -q'
```

Expected: the live-setting Vitest test fails because the status row remains hidden after the `user` response.

- [ ] **Step 3: Toggle status from resolved source metadata**

In `LiveSettingFieldsElement.updateSourceMetadata`, update the stable row after finding the badge popover:

```typescript
const status = popover?.querySelector<HTMLElement>(
  "[data-setting-source-status]",
);
if (status) status.hidden = resolved.locked || source === "default";
```

- [ ] **Step 4: Add browser-level accessibility coverage**

In `_save_select`, after the Personal badge assertions, verify the tooltip DOM exposes the status copy:

```python
status = badge.locator("xpath=ancestor::pop-over//*[@data-setting-source-status]")
expect(status).to_contain_text(
    "Non-default source (default source: “Default”)"
)
```

- [ ] **Step 5: Run targeted server, frontend, and browser tests**

Run:

```bash
direnv exec . make test PYTEST_ADDOPTS='tests/test_settings_ui_kit.py tests/test_settings_page.py -q'
direnv exec . uv run --frozen pytest e2e/test_settings_page_e2e.py -q
```

Expected: settings component/page tests, all 579 Vitest tests, and both mobile/desktop settings e2e cases pass.

- [ ] **Step 6: Run full verification**

Run:

```bash
direnv exec . make check
```

Expected: lint, formatting, mypy, TypeScript, generated-file checks, all frontend tests, and all Python/browser tests pass.

- [ ] **Step 7: Commit and push the implementation**

```bash
git add common/components/settings_kit.py \
  tests/test_settings_ui_kit.py \
  ts/elements/live-setting-fields.ts \
  ts/elements/live-setting-fields.test.ts \
  e2e/test_settings_page_e2e.py \
  docs/superpowers/plans/2026-07-21-source-badge-status.md
git commit -m "fix(settings): explain non-default source highlight"
git push
```
