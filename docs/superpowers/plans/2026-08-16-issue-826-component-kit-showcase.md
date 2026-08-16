# Issue 826 Library Component Kit and Showcase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and visually approve the reusable statistic, fact, entity-summary, copy, and account-menu components needed by the future Library page, exercised through an authenticated DEBUG-only showcase.

**Architecture:** Add pure server-rendered Library-facing components with explicit inputs and no data access. Limit new client behavior to a local clipboard custom element and a preview-only helper that invokes the already-shipped toast API. Compose every approved state on a static DEBUG-only sectioned page; do not implement `/library` or replace the production navbar.

**Tech Stack:** Django 6, htpy-style Python component trees, Tailwind CSS/container queries, existing Dropdown and ThemeToggle components, TypeScript custom elements, shipped toast globals, Vitest, pytest, Playwright.

## Global Constraints

- Read `docs/superpowers/specs/2026-08-16-issue-826-library-ui-component-kit-design.md` and the approved PR 1 neutral-sectioned-page implementation before editing.
- Branch PR 2 from merged PR 1, not from the pre-extraction branch.
- Do not implement `/library`, Library queries, persistence, forms, APIs, background work, migrations, or a production navbar replacement.
- Do not modify `ts/toast.ts`, `ts/library-conversion-status.ts`, their tests, or their global contracts. #630 already shipped the stable-ID/duration API and conversion coordinator.
- If genuinely dead #630 runtime code is found, stop and move that cleanup into a separately reviewed prerequisite PR.
- Keep `FactList` separate from tooltip-specific `TooltipDefinitionList`; do not change tooltip markup or typography.
- Components are pure renderers. Callers supply values, URLs, action descriptors, authorization decisions, CSRF tokens, and composed playtime nodes.
- Use one `EntitySummaryAction` source to render both wide links and narrow dropdown items; callers never duplicate URLs.
- Copy success/failure is local and never emits a toast or network request.
- The showcase is authenticated, DEBUG-only, absent from production URL patterns and all navigation, and uses static component fixtures.
- Keep the PR draft until written product-owner approval covers all required wide/narrow states.
- Stop and replan if this PR crosses 16 implementation/test files, adds a stateful client subsystem, needs real Library data/persistence, or changes a production page/navbar.
- Keep the Makefile's default parallel `PYTEST_WORKERS`.
- On Windows Codex desktop, launch every Make test/check target as a managed hidden process and wait for its final log and exit status.

## File map

| File | Responsibility |
| --- | --- |
| `common/components/library_kit.py` | Statistics, page facts, entity summaries, and CopyControl markup |
| `common/components/navigation.py` | Pure AccountMenu composition |
| `common/components/custom_elements.py` | Typed `<copy-control value="018f0000-0000-7000-8000-000000000000">` registration |
| `common/components/__init__.py` | Public component-kit exports |
| `ts/elements/copy-control.ts` | Clipboard write and local label state |
| `ts/elements/copy-control.test.ts` | Success, failure, reset, reconnect, and no-toast coverage |
| `ts/generated/props.ts` | Generated `CopyControlProps` reader contract |
| `ts/elements/library-kit-preview.ts` | Static preview buttons invoking the shipped toast API |
| `ts/elements/library-kit-preview.test.ts` | Exact toast-call coverage without conversion state |
| `games/views/library_kit_preview.py` | Static authenticated showcase composition |
| `games/urls.py` | DEBUG-only preview pattern helper |
| `tests/test_library_ui_components.py` | Server-rendered component contracts |
| `tests/test_library_kit_preview.py` | Auth, routing, static fixtures, media, and navigation absence |
| `e2e/test_library_kit_preview_e2e.py` | One wide/narrow integration and visual-state suite |

---

### Task 1: Add statistics and page-level facts

**Files:**
- Create: `common/components/library_kit.py`
- Modify: `common/components/__init__.py`
- Create: `tests/test_library_ui_components.py`

**Interfaces:**
- Produces: `StatisticGrid(*cards: Child) -> Node`.
- Produces: `StatisticCard(label: str, value: str | int, href: str | None = None) -> Node`.
- Produces: `FactList(facts: Sequence[tuple[str, Child]]) -> Node`.
- Preserves: `TooltipDefinitionList` byte-for-byte in `common/components/primitives.py`.

- [ ] **Step 1: Write failing statistic and fact contracts**

Create `tests/test_library_ui_components.py` with these tests:

```python
import pytest

from common.components import (
    Div,
    FactList,
    StatisticCard,
    StatisticGrid,
    TooltipDefinition,
    TooltipDefinitionList,
)


def test_statistic_card_links_the_value_with_a_subject_accessible_name():
    html = str(StatisticCard("Games", 851, href="/tracker/game/list"))

    assert 'data-statistic-card=""' in html
    assert 'href="/tracker/game/list"' in html
    assert 'aria-label="851 Games"' in html
    assert "Games" in html and ">851<" in html
    assert "Browse" not in html


def test_plain_and_zero_statistics_keep_the_same_card_shape():
    plain = str(StatisticCard("Unavailable", "—"))
    zero = str(StatisticCard("Devices", 0, href="/tracker/device/list"))

    assert "<a" not in plain
    assert 'aria-label="0 Devices"' in zero
    assert 'href="/tracker/device/list"' in zero
    grid = str(StatisticGrid(StatisticCard("Games", 0), StatisticCard("Devices", 0)))
    assert 'data-statistic-grid=""' in grid
    assert grid.count('data-statistic-card=""') == 2


def test_fact_list_accepts_arbitrary_value_children():
    html = str(
        FactList(
            [
                (
                    "Library ID",
                    Div()[
                        "018f0000-0000-7000-8000-000000000000",
                        "Copy",
                    ],
                ),
                ("Created", "31/12/2022"),
            ]
        )
    )

    assert '<dl data-fact-list=""' in html
    assert html.count("<dt") == 2
    assert html.count("<dd") == 2
    assert "Copy" in html


def test_fact_list_does_not_reuse_tooltip_presentation():
    fact_html = str(FactList([("Created", "31/12/2022")]))
    tooltip_html = str(TooltipDefinitionList([TooltipDefinition("Source", "Database")]))

    assert "data-tooltip-definition-list" not in fact_html
    assert "data-fact-list" not in tooltip_html
    assert 'data-tooltip-definition-list=""' in tooltip_html
```

Task 3 replaces the plain `"Copy"` child with the real control and adds its media assertion.

- [ ] **Step 2: Run the tests and verify the intended import failure**

Run `make test ARGS="tests/test_library_ui_components.py -x"` through the managed hidden process.

Expected: FAIL during collection because `StatisticGrid`, `StatisticCard`, and `FactList` are absent.

- [ ] **Step 3: Implement the three semantic server components**

Start `common/components/library_kit.py` with:

```python
"""Pure reusable presenters for Library-shaped summary surfaces."""

from collections.abc import Sequence

from common.components.core import Child, Node
from common.components.primitives import (
    Dd,
    Div,
    Dl,
    Dt,
    Link,
    P,
    Span,
)


def StatisticGrid(*cards: Child) -> Node:
    return Div(
        data_statistic_grid="",
        class_="grid grid-cols-2 gap-3 @3xl:grid-cols-4",
    )[*cards]


def StatisticCard(
    label: str,
    value: str | int,
    href: str | None = None,
) -> Node:
    value_text = str(value)
    value_node = (
        Link(
            href=href,
            aria_label=f"{value_text} {label}",
            class_="text-type-title text-heading",
        )[value_text]
        if href is not None
        else Span(class_="text-type-title text-heading")[value_text]
    )
    return Div(
        data_statistic_card="",
        class_=(
            "flex min-w-0 flex-col gap-1 rounded-base border border-default "
            "bg-neutral-secondary-medium p-4"
        ),
    )[
        P(class_="text-type-body text-body")[label],
        value_node,
    ]


def FactList(facts: Sequence[tuple[str, Child]]) -> Node:
    return Dl(
        data_fact_list="",
        class_="grid grid-cols-1 gap-4 @xl:grid-cols-2",
    )[
        *[
            Div(class_="flex min-w-0 flex-col gap-1")[
                Dt(class_="text-type-micro-caps uppercase text-body")[label],
                Dd(class_="min-w-0 text-type-body text-heading")[value],
            ]
            for label, value in facts
        ]
    ]
```

Do not add a shared definition-list helper or edit `TooltipDefinitionList`; the two outputs intentionally have independent typography and hooks.

- [ ] **Step 4: Export and pass the focused tests**

Export `StatisticGrid`, `StatisticCard`, and `FactList` through `common/components/__init__.py`. Keep Task 1's plain `"Copy"` child until Task 3 replaces it, then run `make test ARGS="tests/test_library_ui_components.py -x"` through the managed hidden process.

Expected: PASS.

- [ ] **Step 5: Commit statistics and facts**

```bash
git add common/components/library_kit.py common/components/__init__.py tests/test_library_ui_components.py
git commit -m "feat: add statistic and fact components"
```

### Task 2: Add structured responsive entity summaries

**Files:**
- Modify: `common/components/library_kit.py`
- Modify: `common/components/__init__.py`
- Modify: `tests/test_library_ui_components.py`

**Interfaces:**
- Produces: immutable `EntitySummaryAction(label: str, href: str)`.
- Produces: `EntitySummaryList(*rows: Child) -> Node`.
- Produces: `EntitySummaryRow(*, label: str, subtitle: str, count: str | int, count_href: str | None = None, actions: Sequence[EntitySummaryAction] = (), detail: Child | None = None) -> Node`.
- Consumes: existing `Dropdown`, `DropdownLinkItem`, `DropdownMenuPanel`, `ControlButton`, `Link`, and `Icon`.

- [ ] **Step 1: Write failing descriptor and row-shape tests**

Add `EntitySummaryAction`, `EntitySummaryList`, and `EntitySummaryRow` to the `common.components` test imports, then append:

```python
def test_entity_row_renders_both_presentations_from_one_action_source():
    actions = (
        EntitySummaryAction("Browse", "/tracker/game/list"),
        EntitySummaryAction("Add", "/tracker/game/add"),
    )
    html = str(
        EntitySummaryRow(
            label="Games",
            subtitle="Games currently tracked in this library.",
            count=851,
            count_href="/tracker/game/list",
            actions=actions,
        )
    )

    assert html.count('href="/tracker/game/list"') == 3
    assert html.count('href="/tracker/game/add"') == 2
    assert 'data-entity-summary-wide-actions=""' in html
    assert 'data-entity-summary-overflow=""' in html
    assert 'aria-label="Games actions"' in html
    assert 'aria-label="851 Games"' in html


def test_entity_list_is_divider_separated_without_a_nested_card_border():
    html = str(
        EntitySummaryList(
            EntitySummaryRow(
                label="Devices",
                subtitle="Hardware you use to play.",
                count=2,
                detail="Preselected when logging a game.",
            )
        )
    )

    opening = html[: html.index(">")]
    assert 'data-entity-summary-list=""' in opening
    assert "divide-y" in opening
    assert "border" not in opening
    assert 'data-entity-summary-detail=""' in html


def test_entity_row_with_no_actions_renders_no_empty_overflow_menu():
    html = str(
        EntitySummaryRow(
            label="Play events",
            subtitle="No management surface.",
            count=0,
        )
    )

    assert "data-entity-summary-overflow" not in html
    assert "<drop-down" not in html
```

The Browse URL appears once as the count, once as the wide Browse link, and once as the narrow dropdown item; this verifies derivation from the one descriptor without asking callers to duplicate it.

- [ ] **Step 2: Run the entity tests and verify the intended failure**

Run `make test ARGS="tests/test_library_ui_components.py -k entity -x"` through the managed hidden process.

Expected: FAIL because the entity APIs are absent.

- [ ] **Step 3: Implement immutable actions and container-responsive rows**

Add `dataclass` and `randomid` imports plus the required primitive/custom-element imports, then add this implementation:

```python
@dataclass(frozen=True, slots=True)
class EntitySummaryAction:
    label: str
    href: str


def EntitySummaryList(*rows: Child) -> Node:
    return Div(
        data_entity_summary_list="",
        class_="flex flex-col divide-y divide-default-medium",
    )[*rows]


def _entity_action_menu(label: str, actions: Sequence[EntitySummaryAction]) -> Node:
    menu_id = randomid(
        seed="entity-actions-",
        content=f"{label}:" + ":".join(action.href for action in actions),
        length=24,
    )
    trigger = ControlButton(
        [
            ("aria-label", f"{label} actions"),
            ("aria-haspopup", "menu"),
            ("class", "rounded-base p-2"),
        ],
        variant="ghost",
    )[Icon("ellipsis", [("aria-hidden", "true")])].as_element()
    return Dropdown(
        trigger_element=trigger,
        target_element=DropdownMenuPanel(
            items=[DropdownLinkItem(action.href, action.label) for action in actions],
            aria_label=f"{label} actions",
        ),
        id=menu_id,
        placement="bottom-end",
    )


def EntitySummaryRow(
    *,
    label: str,
    subtitle: str,
    count: str | int,
    count_href: str | None = None,
    actions: Sequence[EntitySummaryAction] = (),
    detail: Child | None = None,
) -> Node:
    count_text = str(count)
    count_node = (
        Link(
            href=count_href,
            aria_label=f"{count_text} {label}",
            class_="text-type-subheading text-heading tabular-nums",
        )[count_text]
        if count_href is not None
        else Span(class_="text-type-subheading text-heading tabular-nums")[count_text]
    )
    primary_children: list[Child] = [
        Div(class_="flex min-w-0 flex-col gap-1")[
            P(class_="text-type-subheading text-heading")[label],
            P(class_="text-type-body text-body")[subtitle],
        ],
        Div(class_="justify-self-end text-right")[count_node],
    ]
    if actions:
        primary_children.extend(
            [
                Div(
                    data_entity_summary_overflow="",
                    class_="justify-self-end @2xl:hidden",
                )[_entity_action_menu(label, actions)],
                Div(
                    data_entity_summary_wide_actions="",
                    class_="hidden items-center justify-end gap-4 @2xl:flex",
                )[*[Link(href=action.href)[action.label] for action in actions]],
            ]
        )
    row_children: list[Child] = [
        Div(
            class_=(
                "grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-4 "
                "@2xl:grid-cols-[minmax(0,1fr)_auto_auto]"
            )
        )[*primary_children]
    ]
    if detail is not None:
        row_children.append(
            Div(
                data_entity_summary_detail="",
                class_="text-type-body text-body",
            )[detail]
        )
    return Div(
        data_entity_summary_row="",
        class_="@container flex min-w-0 flex-col gap-3 py-4 first:pt-0 last:pb-0",
    )[*row_children]
```

Import `Dropdown`, `DropdownLinkItem`, and `DropdownMenuPanel` from `custom_elements`, and `ControlButton` and `Icon` from `primitives`; reuse Task 1's `Link`. The section panel already establishes an `@container`; the row adds one as a safe standalone boundary. Do not use viewport `sm:`/`md:` visibility switches for actions.

- [ ] **Step 4: Export and pass all component tests**

Export `EntitySummaryAction`, `EntitySummaryList`, and `EntitySummaryRow`, then run `make test ARGS="tests/test_library_ui_components.py -x"` through the managed hidden process.

Expected: PASS.

- [ ] **Step 5: Commit entity summaries**

```bash
git add common/components/library_kit.py common/components/__init__.py tests/test_library_ui_components.py
git commit -m "feat: add responsive entity summary rows"
```

### Task 3: Add CopyControl with local success and failure state

**Files:**
- Modify: `common/components/library_kit.py`
- Modify: `common/components/custom_elements.py`
- Modify: `common/components/__init__.py`
- Create: `ts/elements/copy-control.ts`
- Create: `ts/elements/copy-control.test.ts`
- Modify: `ts/generated/props.ts`
- Modify: `tests/test_library_ui_components.py`

**Interfaces:**
- Produces: `CopyControl(value: str, *, label: str = "Copy", description: str = "Copy value to clipboard") -> Node`.
- Produces: `<copy-control value="018f0000-0000-7000-8000-000000000000">` using generated `readCopyControlProps`.
- State contract: `Copy` -> `Copied` -> original label after 2,000 ms; rejection -> `Couldn't copy` until the next attempt.

- [ ] **Step 1: Add failing server and client tests**

Add `CopyControl` and `collect_media` to the test imports, replace Task 1's plain `"Copy"` child with `CopyControl("018f0000-0000-7000-8000-000000000000")`, then add:

```python
def test_copy_control_exposes_value_description_live_label_and_media():
    control = CopyControl(
        "018f0000-0000-7000-8000-000000000000",
        description="Copy Library ID",
    )
    html = str(control)

    assert '<copy-control value="018f0000-0000-7000-8000-000000000000"' in html
    assert 'data-copy-control=""' in html
    assert 'data-copy-label=""' in html
    assert 'aria-live="polite"' in html
    assert 'aria-label="Copy Library ID"' in html
    assert "dist/elements/copy-control.js" in collect_media(control).js
```

Create `ts/elements/copy-control.test.ts` with jsdom, fake timers, a `writeText` mock, a `window.toast` spy, and these cases:

```typescript
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import "./copy-control.js";

beforeEach(() => {
  document.body.innerHTML = "";
  window.toast = vi.fn();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
```

```typescript
it("copies, announces success, and restores the original label after two seconds", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  document.body.innerHTML = `
    <copy-control value="full-value">
      <button data-copy-control aria-label="Copy Library ID">
        <span data-copy-label aria-live="polite" aria-atomic="true">Copy ID</span>
      </button>
    </copy-control>`;

  document.querySelector<HTMLButtonElement>("[data-copy-control]")!.click();
  await Promise.resolve();
  expect(writeText).toHaveBeenCalledWith("full-value");
  expect(document.querySelector("[data-copy-label]")?.textContent).toBe("Copied");
  expect(window.toast).not.toHaveBeenCalled();
  vi.advanceTimersByTime(2_000);
  expect(document.querySelector("[data-copy-label]")?.textContent).toBe("Copy ID");
});

it("keeps failure visible until a new attempt", async () => {
  const writeText = vi.fn().mockRejectedValueOnce(new Error("denied"));
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  document.body.innerHTML = `
    <copy-control value="full-value">
      <button data-copy-control>
        <span data-copy-label aria-live="polite">Copy</span>
      </button>
    </copy-control>`;

  const button = document.querySelector<HTMLButtonElement>("[data-copy-control]")!;
  button.click();
  await Promise.resolve();
  await Promise.resolve();
  expect(document.querySelector("[data-copy-label]")?.textContent).toBe("Couldn't copy");
  vi.advanceTimersByTime(10_000);
  expect(document.querySelector("[data-copy-label]")?.textContent).toBe("Couldn't copy");
  expect(window.toast).not.toHaveBeenCalled();

  writeText.mockResolvedValueOnce(undefined);
  button.click();
  expect(document.querySelector("[data-copy-label]")?.textContent).toBe("Copy");
  await Promise.resolve();
  expect(document.querySelector("[data-copy-label]")?.textContent).toBe("Copied");
});

it("restores the original label when disconnected during a reset delay", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  document.body.innerHTML = `
    <copy-control value="full-value">
      <button data-copy-control>
        <span data-copy-label aria-live="polite">Copy</span>
      </button>
    </copy-control>`;

  const control = document.querySelector<HTMLElement>("copy-control")!;
  control.querySelector<HTMLButtonElement>("[data-copy-control]")!.click();
  await Promise.resolve();
  expect(control.querySelector("[data-copy-label]")?.textContent).toBe("Copied");

  control.remove();
  vi.advanceTimersByTime(2_000);
  document.body.append(control);
  expect(control.querySelector("[data-copy-label]")?.textContent).toBe("Copy");
});
```

Keep all three cases in this file. The setup above imports the element once, resets DOM and toast state per case, and restores fake timers and mocks afterward.

- [ ] **Step 2: Run both focused tests and verify failure**

Run `make gen-element-types`, `pnpm test:ts -- ts/elements/copy-control.test.ts`, and managed-hidden `make test ARGS="tests/test_library_ui_components.py -k copy -x"`.

Expected: the TypeScript import and Python `CopyControl` import fail.

- [ ] **Step 3: Register and render the typed custom element**

In `common/components/custom_elements.py` add:

```python
class CopyControlProps(TypedDict):
    value: str


register_element("copy-control", "CopyControl", CopyControlProps)
```

In `library_kit.py`, add `custom_element_builder`, `ControlButton`, and `_CopyControl = custom_element_builder("copy-control")`, then:

```python
def CopyControl(
    value: str,
    *,
    label: str = "Copy",
    description: str = "Copy value to clipboard",
) -> Node:
    return _CopyControl(value=value, class_="inline-flex")[
        ControlButton(
            [
                ("data-copy-control", ""),
                ("aria-label", description),
            ],
            variant="ghost",
        )[
            Span(
                data_copy_label="",
                aria_live="polite",
                aria_atomic="true",
            )[label]
        ],
    ]
```

- [ ] **Step 4: Implement the client state machine**

Create `ts/elements/copy-control.ts`:

```typescript
import { readCopyControlProps } from "../generated/props.js";

class CopyControlElement extends HTMLElement {
  private button: HTMLButtonElement | null = null;
  private label: HTMLElement | null = null;
  private value = "";
  private initialLabel = "Copy";
  private resetTimer: ReturnType<typeof setTimeout> | null = null;

  connectedCallback(): void {
    this.value = readCopyControlProps(this).value;
    this.button = this.querySelector<HTMLButtonElement>("[data-copy-control]");
    this.label = this.querySelector<HTMLElement>("[data-copy-label]");
    this.initialLabel = this.label?.textContent?.trim() || "Copy";
    this.button?.addEventListener("click", this.onCopy);
  }

  disconnectedCallback(): void {
    this.button?.removeEventListener("click", this.onCopy);
    if (this.resetTimer !== null) window.clearTimeout(this.resetTimer);
    this.resetTimer = null;
    this.setLabel(this.initialLabel);
  }

  private setLabel(value: string): void {
    if (this.label) this.label.textContent = value;
  }

  private readonly onCopy = async (): Promise<void> => {
    if (this.resetTimer !== null) window.clearTimeout(this.resetTimer);
    this.resetTimer = null;
    this.setLabel(this.initialLabel);
    try {
      await navigator.clipboard.writeText(this.value);
      this.setLabel("Copied");
      this.resetTimer = window.setTimeout(() => {
        this.resetTimer = null;
        this.setLabel(this.initialLabel);
      }, 2_000);
    } catch {
      this.setLabel("Couldn't copy");
    }
  };
}

customElements.define("copy-control", CopyControlElement);
```

Do not import toast code, dispatch events, fetch, or store state outside the element.

- [ ] **Step 5: Export, regenerate, and pass server/client tests**

Export `CopyControl`, run `make gen-element-types`, then:

```bash
pnpm test:ts -- ts/elements/copy-control.test.ts
pnpm exec tsc --noEmit -p tsconfig.check.json
```

Run `make test ARGS="tests/test_library_ui_components.py -x"` through the managed hidden process.

Expected: all exit 0.

- [ ] **Step 6: Commit CopyControl**

```bash
git add common/components/library_kit.py common/components/custom_elements.py common/components/__init__.py ts/elements/copy-control.ts ts/elements/copy-control.test.ts ts/generated/props.ts tests/test_library_ui_components.py
git commit -m "feat: add accessible copy control"
```

### Task 4: Add the pure circular AccountMenu

**Files:**
- Create: `common/components/navigation.py`
- Modify: `common/components/__init__.py`
- Modify: `tests/test_library_ui_components.py`

**Interfaces:**
- Produces: `AccountMenu(*, username: str, initials: str, today_played: Child, last_7_played: Child, stats_url: str, settings_url: str, admin_settings_url: str | None, theme_disabled: bool, logout_url: str, csrf_token: str, id: str = "account-menu") -> Node`.
- Consumes: existing `Dropdown`, `DropdownMenuPanel`, link/POST items, `ThemeToggle`, and caller-composed playtime nodes.
- Requires: non-empty caller-supplied initials as the visible future-avatar fallback.
- Performs: no User, Session, authorization, URL reversal, database query, or icon fallback.

- [ ] **Step 1: Write failing order, separator, authorization, and initials tests**

Add `AccountMenu` to the `common.components` test imports, then append:

```python
def _account_menu(**overrides):
    values = {
        "username": "alexandra-with-a-long-name",
        "initials": "AW",
        "today_played": Div()["Today value"],
        "last_7_played": Div()["Last 7 days value"],
        "stats_url": "/tracker/stats/2026",
        "settings_url": "/tracker/settings",
        "admin_settings_url": "/tracker/admin-settings",
        "theme_disabled": False,
        "logout_url": "/logout/",
        "csrf_token": "token",
    }
    values.update(overrides)
    return AccountMenu(**values)


def test_account_menu_has_exact_order_groups_and_circular_trigger():
    html = str(_account_menu())
    trigger = html[: html.index("data-menu")]
    panel = html[html.index("data-menu") :]

    assert 'aria-label="Open account menu for alexandra-with-a-long-name"' in trigger
    assert "rounded-full" in trigger
    assert ">AW<" in trigger
    ordered = [
        "alexandra-with-a-long-name",
        "Today",
        "Today value",
        "Last 7 days",
        "Last 7 days value",
        "Stats",
        "Settings",
        "Admin settings",
        "theme-toggle",
        "Log out",
    ]
    positions = [panel.index(value) for value in ordered]
    assert positions == sorted(positions)
    assert panel.count('role="separator"') == 3
    assert 'action="/logout/"' in panel
    assert 'name="csrfmiddlewaretoken" value="token"' in panel


def test_account_menu_omits_admin_without_changing_the_initials_trigger():
    html = str(_account_menu(admin_settings_url=None))

    assert "Admin settings" not in html
    assert ">AW<" in html
    assert "Open account menu for alexandra-with-a-long-name" in html


def test_account_menu_rejects_empty_initials():
    with pytest.raises(ValueError, match="initials must not be empty"):
        _account_menu(initials="")


def test_account_menu_forwards_the_theme_disabled_state():
    html = str(_account_menu(theme_disabled=True))

    assert '<theme-toggle disabled="true"' in html
```

- [ ] **Step 2: Run the account tests and verify the intended failure**

Run `make test ARGS="tests/test_library_ui_components.py -k account -x"` through the managed hidden process.

Expected: FAIL because `AccountMenu` is absent.

- [ ] **Step 3: Implement pure account composition**

Create `common/components/navigation.py`:

```python
"""Pure reusable navigation compositions."""

from common.components.core import Child, Node
from common.components.custom_elements import (
    Dropdown,
    DropdownDivider,
    DropdownLinkItem,
    DropdownMenuPanel,
    DropdownPostItem,
)
from common.components.primitives import Button, Div, Li, PlainH4, Span
from common.components.theme import ThemeToggle


def _account_value(label: str, value: Child) -> Node:
    return Li(role="presentation")[
        Div(class_="flex items-center justify-between gap-4 px-4 py-2")[
            Span(class_="text-type-micro-caps uppercase text-body")[label],
            Div(class_="min-w-0 text-right text-type-body text-heading")[value],
        ]
    ]


def AccountMenu(
    *,
    username: str,
    initials: str,
    today_played: Child,
    last_7_played: Child,
    stats_url: str,
    settings_url: str,
    admin_settings_url: str | None,
    theme_disabled: bool,
    logout_url: str,
    csrf_token: str,
    id: str = "account-menu",
) -> Node:
    if not initials.strip():
        raise ValueError("AccountMenu initials must not be empty.")
    trigger_content = Span(aria_hidden="true", class_="text-type-body font-semibold")[
        initials
    ]
    trigger = Button(
        [
            ("type", "button"),
            ("aria-haspopup", "menu"),
            ("aria-label", f"Open account menu for {username}"),
            ("data-account-menu-trigger", ""),
            (
                "class",
                "inline-flex h-10 w-10 shrink-0 items-center justify-center "
                "rounded-full border border-default-medium bg-neutral-secondary-medium "
                "text-heading hover:bg-neutral-tertiary-medium focus:outline-hidden "
                "focus:ring-2 focus:ring-fg-brand",
            ),
        ]
    )[trigger_content]
    items: list[Node] = [
        Li(role="presentation", class_="px-4 py-3")[
            PlainH4(class_="text-type-body font-semibold text-heading break-words")[
                username
            ]
        ],
        _account_value("Today", today_played),
        _account_value("Last 7 days", last_7_played),
        DropdownDivider(),
        DropdownLinkItem(stats_url, "Stats"),
        DropdownLinkItem(settings_url, "Settings"),
    ]
    if admin_settings_url is not None:
        items.append(DropdownLinkItem(admin_settings_url, "Admin settings"))
    items.extend(
        [
            DropdownDivider(),
            Li(role="presentation", class_="px-2 py-1")[
                ThemeToggle(instance_key=f"{id}-theme", disabled=theme_disabled)
            ],
            DropdownDivider(),
            DropdownPostItem(logout_url, "Log out", csrf_token=csrf_token),
        ]
    )
    return Dropdown(
        trigger_element=trigger,
        target_element=DropdownMenuPanel(
            items=items,
            aria_label=f"{username} account menu",
            menu_width="w-72 max-w-[calc(100vw-2rem)]",
        ),
        id=id,
        placement="bottom-end",
    )


__all__ = ["AccountMenu"]
```

The panel uses the existing Dropdown lifecycle; do not add account-specific TypeScript or a second trigger fallback.

- [ ] **Step 4: Export and pass tests**

Export `AccountMenu` through `common/components/__init__.py`, then run managed-hidden `make test ARGS="tests/test_library_ui_components.py -x"`.

Expected: exit 0.

- [ ] **Step 5: Commit AccountMenu**

```bash
git add common/components/navigation.py common/components/__init__.py tests/test_library_ui_components.py
git commit -m "feat: add reusable account menu"
```

### Task 5: Build the DEBUG-only static showcase and toast-state helper

**Files:**
- Create: `ts/elements/library-kit-preview.ts`
- Create: `ts/elements/library-kit-preview.test.ts`
- Create: `games/views/library_kit_preview.py`
- Modify: `games/urls.py`
- Create: `tests/test_library_kit_preview.py`
- Create: `e2e/test_library_kit_preview_e2e.py`

**Interfaces:**
- Produces: authenticated DEBUG-only `games:library_kit_preview` at `/tracker/library-kit-preview/`.
- Produces: `<library-kit-preview>` media host and three static toast triggers.
- Consumes: all components from Tasks 1-4, merged PR 1 sectioned-page components, and existing `window.toast`/`window.removeToast`.

- [ ] **Step 1: Write the preview-helper unit test before its implementation**

Create `ts/elements/library-kit-preview.test.ts` with a `window.toast` spy, `window.removeToast` spy, and this fixture:

```typescript
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import "./library-kit-preview.js";

beforeEach(() => {
  document.body.innerHTML = "";
  window.toast = vi.fn();
  window.removeToast = vi.fn();
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});
```

Start one test case immediately before the fixture:

```typescript
it("renders static conversion toast appearances without conversion work", () => {
```

Place the fixture and all assertions below inside it, then add `});` after the final `expect(fetchSpy).not.toHaveBeenCalled()` assertion.

```typescript
document.body.innerHTML = `
  <library-kit-preview>
    <button data-preview-conversion-toast="running">Running</button>
    <button data-preview-conversion-toast="failed">Failed</button>
    <button data-preview-conversion-toast="complete">Complete</button>
  </library-kit-preview>`;
```

Click each button and assert these exact calls:

```typescript
const fetchSpy = vi.spyOn(globalThis, "fetch");
const buttons = Array.from(
  document.querySelectorAll<HTMLButtonElement>("[data-preview-conversion-toast]"),
);
buttons[0].click();
expect(window.toast).toHaveBeenCalledWith(
  "Prices are being converted. Totals will update when conversion is complete.",
  "info",
  { id: "library-kit-preview:conversion", duration: null },
);
buttons[1].click();
expect(window.toast).toHaveBeenCalledWith(
  "Prices couldn't be converted. Existing totals are still available. We'll retry automatically.",
  "error",
  { id: "library-kit-preview:conversion", duration: null },
);
buttons[2].click();
expect(window.removeToast).toHaveBeenCalledWith("library-kit-preview:conversion");
expect(window.toast).toHaveBeenCalledWith(
  "Prices converted. Totals are now up to date.",
  "success",
);

const host = document.querySelector<HTMLElement>("library-kit-preview")!;
host.remove();
document.body.append(host);
vi.mocked(window.toast).mockClear();
host.querySelector<HTMLButtonElement>(
  '[data-preview-conversion-toast="running"]',
)!.click();
expect(window.toast).toHaveBeenCalledTimes(1);
expect(fetchSpy).not.toHaveBeenCalled();
```


- [ ] **Step 2: Run the preview-helper test and verify the import failure**

Run: `pnpm test:ts -- ts/elements/library-kit-preview.test.ts`

Expected: FAIL because the helper does not exist.

- [ ] **Step 3: Implement the stateless preview helper**

Create `ts/elements/library-kit-preview.ts`:

```typescript
const TOAST_ID = "library-kit-preview:conversion";
const RUNNING =
  "Prices are being converted. Totals will update when conversion is complete.";
const FAILED =
  "Prices couldn't be converted. Existing totals are still available. We'll retry automatically.";
const COMPLETE = "Prices converted. Totals are now up to date.";

class LibraryKitPreviewElement extends HTMLElement {
  connectedCallback(): void {
    this.addEventListener("click", this.onClick);
  }

  disconnectedCallback(): void {
    this.removeEventListener("click", this.onClick);
  }

  private readonly onClick = (event: Event): void => {
    const button = (event.target as HTMLElement).closest<HTMLElement>(
      "[data-preview-conversion-toast]",
    );
    if (!button || !this.contains(button)) return;
    const state = button.dataset.previewConversionToast;
    if (state === "running") {
      window.toast(RUNNING, "info", { id: TOAST_ID, duration: null });
    } else if (state === "failed") {
      window.toast(FAILED, "error", { id: TOAST_ID, duration: null });
    } else if (state === "complete") {
      window.removeToast(TOAST_ID);
      window.toast(COMPLETE, "success");
    }
  };
}

customElements.define("library-kit-preview", LibraryKitPreviewElement);
```

This file must not import or instantiate `LibraryConversionCoordinator`, read dataset conversion state, access session storage, poll, or fetch.

- [ ] **Step 4: Pass helper tests and TypeScript checking**

Run:

```bash
pnpm test:ts -- ts/elements/library-kit-preview.test.ts
pnpm exec tsc --noEmit -p tsconfig.check.json
```

Expected: both exit 0.

- [ ] **Step 5: Write failing preview route and gallery tests**

Create `tests/test_library_kit_preview.py` covering:

```python
import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from games.urls import _library_kit_preview_urlpatterns


@pytest.fixture
def preview_client(db):
    user = get_user_model().objects.create_user(
        username="library-kit-preview-user",
        password="pw",
    )
    client = Client()
    client.force_login(user)
    return client


def test_preview_requires_authentication(db):
    response = Client().get(reverse("games:library_kit_preview"))

    assert response.status_code == 302
    assert response.url.startswith("/login/?next=/tracker/library-kit-preview/")


def test_preview_renders_static_component_states(preview_client):
    body = preview_client.get(reverse("games:library_kit_preview")).content.decode()
    assert "Library UI component kit" in body
    assert body.count('data-statistic-card=""') >= 3
    assert 'aria-label="0 Devices"' in body
    assert 'data-fact-list=""' in body
    assert "018f0000-0000-7000-8000-000000000000" in body
    assert "<copy-control" in body
    assert body.count('data-entity-summary-row=""') >= 3
    assert body.count('data-account-menu-trigger=""') == 2
    assert body.count("Admin settings") == 1
    assert body.count("data-preview-conversion-toast") == 3
    assert "dist/elements/copy-control.js" in body
    assert "dist/elements/library-kit-preview.js" in body


@override_settings(DEBUG=False)
def test_preview_patterns_are_absent_when_debug_is_off():
    assert _library_kit_preview_urlpatterns() == []


def test_preview_is_absent_from_production_navigation(preview_client):
    body = preview_client.get(reverse("games:list_sessions")).content.decode()
    assert "library-kit-preview" not in body
    assert "Library UI component kit" not in body
```


- [ ] **Step 6: Run route tests and verify the missing reverse**

Run `make test ARGS="tests/test_library_kit_preview.py -x"` through the managed hidden process.

Expected: FAIL with `NoReverseMatch`.

- [ ] **Step 7: Add the DEBUG-only pattern helper**

Append to `games/urls.py` after the existing Settings-preview helper:

```python
def _library_kit_preview_urlpatterns():
    """Keep the Library component gallery absent from production routing."""

    if not settings.DEBUG:
        return []
    from games.views import library_kit_preview

    return [
        path(
            "library-kit-preview/",
            library_kit_preview.library_kit_preview,
            name="library_kit_preview",
        )
    ]


urlpatterns += _library_kit_preview_urlpatterns()
```

Do not add the route to `games/views/__init__.py` or any navbar/menu list.

- [ ] **Step 8: Compose the static showcase**

Create `games/views/library_kit_preview.py` with `@login_required`, `_LibraryKitPreview = custom_element_builder("library-kit-preview")`, and the four exact neutral fixtures below.

Use this page shell:

```python
@login_required
def library_kit_preview(request: HttpRequest) -> HttpResponse:
    library_id = "018f0000-0000-7000-8000-000000000000"
    statistics_and_facts = Div(class_="@container flex flex-col gap-6")[
        StatisticGrid(
            StatisticCard("Games", 851, href=reverse("games:list_games")),
            StatisticCard("Total spent", "CZK 12,345.67"),
            StatisticCard("Devices", 0, href=reverse("games:list_devices")),
        ),
        FactList(
            [
                (
                    "Library ID",
                    Div(class_="flex min-w-0 items-center gap-2")[
                        Span(class_="min-w-0 break-all font-mono")[library_id],
                        CopyControl(library_id, description="Copy Library ID"),
                    ],
                ),
                ("Created", "31/12/2022"),
            ]
        ),
    ]
    games_actions = (
        EntitySummaryAction("Browse", reverse("games:list_games")),
        EntitySummaryAction("Add", reverse("games:add_game")),
    )
    platform_actions = (
        EntitySummaryAction("Browse", reverse("games:list_platforms")),
        EntitySummaryAction("Add", reverse("games:add_platform")),
    )
    device_actions = (
        EntitySummaryAction("Browse", reverse("games:list_devices")),
        EntitySummaryAction("Add", reverse("games:add_device")),
    )
    entity_summaries = EntitySummaryList(
        EntitySummaryRow(
            label="Games",
            subtitle="Games currently tracked in this library.",
            count=851,
            count_href=reverse("games:list_games"),
            actions=games_actions,
        ),
        EntitySummaryRow(
            label="Platforms",
            subtitle="Platforms you added manually.",
            count=7,
            count_href=reverse("games:list_platforms"),
            actions=platform_actions,
        ),
        EntitySummaryRow(
            label="Devices",
            subtitle="Hardware you use to play.",
            count=0,
            count_href=reverse("games:list_devices"),
            actions=device_actions,
            detail="Preselected when logging a game.",
        ),
    )
    sessions_url = reverse("games:list_sessions")
    stats_url = reverse("games:stats_by_year", args=[localdate().year])
    csrf_token = get_token(request)
    account_menus = Div(class_="flex flex-wrap items-start gap-6")[
        AccountMenu(
            username="alexandra-with-a-deliberately-long-username",
            initials="AL",
            today_played=Link(href=f"{sessions_url}?preview=today")["1h 20m"],
            last_7_played=Link(href=f"{sessions_url}?preview=last-7")["8h 15m"],
            stats_url=stats_url,
            settings_url=reverse("games:settings"),
            admin_settings_url=reverse("games:admin_settings"),
            theme_disabled=False,
            logout_url=reverse("logout"),
            csrf_token=csrf_token,
            id="preview-account-admin",
        ),
        AccountMenu(
            username="preview-normal-user",
            initials="PN",
            today_played=Link(href=f"{sessions_url}?preview=today")["0m"],
            last_7_played=Link(href=f"{sessions_url}?preview=last-7")["2h"],
            stats_url=stats_url,
            settings_url=reverse("games:settings"),
            admin_settings_url=None,
            theme_disabled=False,
            logout_url=reverse("logout"),
            csrf_token=csrf_token,
            id="preview-account-user",
        ),
    ]
    conversion_toasts = Div(class_="flex flex-wrap gap-3")[
        ControlButton(data_preview_conversion_toast="running", color="gray")[
            "Show running"
        ],
        ControlButton(data_preview_conversion_toast="failed", color="gray")[
            "Show failed"
        ],
        ControlButton(data_preview_conversion_toast="complete", color="gray")[
            "Show completed"
        ],
    ]
    sections = [
        SectionedPageSection(
            "statistics-and-facts",
            "Statistics and facts",
            statistics_and_facts,
        ),
        SectionedPageSection(
            "entity-summaries",
            "Entity summaries",
            entity_summaries,
        ),
        SectionedPageSection(
            "account-menus",
            "Account menus",
            account_menus,
        ),
        SectionedPageSection(
            "conversion-toasts",
            "Conversion toast appearances",
            conversion_toasts,
        ),
    ]
    content = Div(class_="flex flex-col gap-6")[
        SectionedPageHeader(
            "Library UI component kit",
            description=(
                "Authenticated DEBUG-only fixtures for issue #826; values are "
                "static and nothing on this page changes Library data."
            ),
        ),
        _LibraryKitPreview()[
            SectionedPageScaffold(
                sections,
                navigation_label="Library kit sections",
                jump_label="Jump to a component group",
            )
        ],
    ]
    return render_page(request, content, title="Library UI component kit")


__all__ = ["library_kit_preview"]
```

Import every component named in the fixture block, plus `get_token`, `reverse`, `localdate`, `HttpRequest`, and `HttpResponse`. Do not read `request.user.library`, import Library models, or add a mutation endpoint. The ordinary authenticated `render_page` shell may perform its existing request-scoped navbar work.

- [ ] **Step 9: Pass route and component tests**

Run managed-hidden:

```bash
make test ARGS="tests/test_library_kit_preview.py tests/test_library_ui_components.py -x"
```

Expected: exit 0.

- [ ] **Step 10: Add one risk-focused Playwright suite**

Create `e2e/test_library_kit_preview_e2e.py` with an authenticated user fixture and a single parametrized test for `390x844` and `1280x900`. It must assert:

- the neutral section trigger is visible only in the narrow case and the rail only in the wide case;
- wide entity links versus narrow row overflow visibility changes with the section container;
- one entity overflow and one AccountMenu open, close on Escape, and return focus to their triggers;
- Admin is present only in the admin example;
- clipboard resolve shows `Copied` and returns to `Copy` after two seconds;
- clipboard rejection shows `Couldn't copy`, remains after two seconds, and does not add a global toast;
- each conversion preview button renders the exact existing running/failed/completed toast appearance;
- no request URL contains `library-conversion` while exercising preview buttons.

Override clipboard per state with:

```python
page.evaluate(
    """mode => {
        Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: {
                writeText: () => mode === 'resolve'
                    ? Promise.resolve()
                    : Promise.reject(new Error('denied')),
            },
        });
    }""",
    "resolve",
)
```

Use this complete test shape rather than leaving the interactions implicit:

```python
import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.mark.parametrize(
    ("width", "height", "wide"),
    [(390, 844, False), (1280, 900, True)],
)
def test_library_kit_responsive_interactions_and_static_toasts(
    authenticated_page: Page,
    live_server,
    width: int,
    height: int,
    wide: bool,
):
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": height})
    requested_urls: list[str] = []
    page.on("request", lambda request: requested_urls.append(request.url))
    page.goto(f"{live_server.url}{reverse('games:library_kit_preview')}")

    section_nav = page.locator("section-nav")
    section_trigger = section_nav.locator("[data-section-nav-trigger]")
    section_rail = section_nav.locator("[data-section-nav-rail]")
    wide_actions = page.locator("[data-entity-summary-wide-actions]").first
    overflow = page.locator("[data-entity-summary-overflow]").first
    if wide:
        expect(section_trigger).to_be_hidden()
        expect(section_rail).to_be_visible()
        expect(wide_actions).to_be_visible()
        expect(overflow).to_be_hidden()
    else:
        expect(section_trigger).to_be_visible()
        expect(section_rail).to_be_hidden()
        expect(wide_actions).to_be_hidden()
        expect(overflow).to_be_visible()

        entity_trigger = page.get_by_role("button", name="Games actions")
        entity_menu = entity_trigger.locator("xpath=ancestor::drop-down").locator(
            "[data-menu]"
        )
        entity_trigger.click()
        expect(entity_menu).to_be_visible()
        page.keyboard.press("Escape")
        expect(entity_menu).to_be_hidden()
        expect(entity_trigger).to_be_focused()

    admin_trigger = page.get_by_role(
        "button",
        name="Open account menu for alexandra-with-a-deliberately-long-username",
    )
    admin_menu = admin_trigger.locator("xpath=ancestor::drop-down").locator(
        "[data-menu]"
    )
    admin_trigger.click()
    expect(admin_menu).to_be_visible()
    expect(admin_menu.get_by_role("menuitem", name="Admin settings")).to_have_count(1)
    page.keyboard.press("Escape")
    expect(admin_menu).to_be_hidden()
    expect(admin_trigger).to_be_focused()

    user_trigger = page.get_by_role(
        "button",
        name="Open account menu for preview-normal-user",
    )
    user_menu = user_trigger.locator("xpath=ancestor::drop-down").locator("[data-menu]")
    user_trigger.click()
    expect(user_menu).to_be_visible()
    expect(user_menu.get_by_role("menuitem", name="Admin settings")).to_have_count(0)
    page.keyboard.press("Escape")
    expect(user_trigger).to_be_focused()

    copy_button = page.locator("[data-copy-control]")
    copy_label = page.locator("[data-copy-label]")
    notifications = page.locator(
        '[aria-label="Notifications"] [x-text="toast.message"]'
    )
    page.evaluate(
        """mode => {
            Object.defineProperty(navigator, 'clipboard', {
                configurable: true,
                value: {
                    writeText: () => mode === 'resolve'
                        ? Promise.resolve()
                        : Promise.reject(new Error('denied')),
                },
            });
        }""",
        "resolve",
    )
    copy_button.click()
    expect(copy_label).to_have_text("Copied")
    page.wait_for_timeout(2_100)
    expect(copy_label).to_have_text("Copy")

    page.evaluate(
        """Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: { writeText: () => Promise.reject(new Error('denied')) },
        })"""
    )
    copy_button.click()
    expect(copy_label).to_have_text("Couldn't copy")
    page.wait_for_timeout(2_100)
    expect(copy_label).to_have_text("Couldn't copy")
    expect(notifications).to_have_count(0)

    running = (
        "Prices are being converted. Totals will update when conversion is complete."
    )
    failed = (
        "Prices couldn't be converted. Existing totals are still available. "
        "We'll retry automatically."
    )
    complete = "Prices converted. Totals are now up to date."
    page.get_by_role("button", name="Show running").click()
    expect(notifications).to_have_text(running)
    page.get_by_role("button", name="Show failed").click()
    expect(notifications).to_have_text(failed)
    page.get_by_role("button", name="Show completed").click()
    expect(notifications).to_have_text(complete)
    assert not any("library-conversion" in url for url in requested_urls)
```

This suite is integration smoke coverage. Do not duplicate the generic Dropdown suite's arrow-roving, typeahead, outside-click, submenu, and positioning matrix.

- [ ] **Step 11: Run the preview browser suite and commit**

Run `make test ARGS="e2e/test_library_kit_preview_e2e.py -x"` through the managed hidden process.

Expected: exit 0.

```bash
git add ts/elements/library-kit-preview.ts ts/elements/library-kit-preview.test.ts games/views/library_kit_preview.py games/urls.py tests/test_library_kit_preview.py e2e/test_library_kit_preview_e2e.py
git commit -m "feat: showcase Library UI components"
```

### Task 6: Gate, visually approve, and ready PR 2

**Files:**
- Review: every file changed by Tasks 1-5
- External record: issue #826 and the draft PR comments after product-owner approval

**Interfaces:**
- Produces: tested and explicitly approved component contracts for the future Library-page/navbar issue.

- [ ] **Step 1: Audit scope and #630 boundaries before the broad gate**

Run:

```bash
git diff main...HEAD --stat
git diff main...HEAD --name-only
git diff main...HEAD -- ts/toast.ts ts/toast.test.ts ts/library-conversion-status.ts ts/library-conversion-status.test.ts common/layout.py
```

Expected: no diff in the final command. Count implementation/test files; if the count exceeds 16, stop and replan instead of rationalizing the growth. Confirm there is no `/library` route, production navbar edit, model/migration/API change, or compatibility cleanup.

- [ ] **Step 2: Run the complete verification gate before visual review**

Run `make check` through the managed hidden Windows process and wait for its final log and exit status.

Expected: exit 0 with default parallel workers.

- [ ] **Step 3: Render every required visual state inside Timetracker**

Run the normal development server and capture the authenticated preview at a representative wide viewport and at `390x844`. The review set includes:

- linked, plain, and linked-zero statistic cards;
- full UUID FactList value with Copy, Copied, and `Couldn't copy` states;
- entity rows with/without detail, wide actions, and narrow overflow;
- AccountMenu with a long username and initials, with Admin present and absent;
- existing running, failed, and completed toast appearances; and
- neutral section navigation in rail and bottom-sheet modes.

- [ ] **Step 4: Pause with the PR in draft for product-owner review**

Share the wide/narrow captures and keep the PR draft. Automated checks are not visual approval. Apply requested changes through the component contracts and preview; do not defer them to the future Library page.

- [ ] **Step 5: Re-run the complete gate after approved visual adjustments**

After the product owner approves the final renders, run managed-hidden `make check` again.

Expected: exit 0.

- [ ] **Step 6: Record approval and mark the PR ready**

Add a dated comment to issue #826 and the PR linking the exact approved wide/narrow captures and noting both successful full-gate runs. Mark the PR ready only after that written approval. Keep the DEBUG preview in the codebase until the future finished Library page exercises every component and removes it.
