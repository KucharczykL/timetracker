# Table Widths Phase 4a — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin the first column of every data table so the row header stays readable while the rest of the table scrolls sideways, without the pinned cell swallowing the panels it hosts.

**Architecture:** One class constant on the first cell of every row (header row included), emitted by the same `data_table` gate Phase 2 introduced. The cell is `position: sticky`; while it holds an open panel it outranks its sibling pinned cells by one, which is what keeps a tooltip or menu nested inside it from being painted over. The trailing shadow lives inside a `scroll-state` container query, so the seam exists only while something is actually scrolled behind the column. No JavaScript.

**Tech Stack:** Django 6, Python 3.14, the Python component system (`common/components/`), Tailwind CSS v4, pytest, Playwright.

**Design:** `docs/superpowers/specs/2026-07-26-responsive-table-widths-design.md` § Phase 4 / 4a. **Tracked by** #523. **Needs** Phase 3 (#532, shipped).

## Global Constraints

- Run everything through `make`. Never `direnv exec . <cmd>` per command, never raw `uv run` / `pnpm` / `pytest`. Focused runs: `make test ARGS="tests/test_components.py -k pinned"`.
- `make test-e2e ARGS=…` does **not** scope the run to a file — `ARGS` is appended to `pytest e2e/`. Filter with `-k`, and never run e2e while `make dev` is up: its watchers rewrite the served assets mid-run.
- Python 3.14 is a hard prerequisite. A `SyntaxError` in an `except A, B:` line means the wrong interpreter, not broken code.
- Build UI with the component builders in `common.components`, htpy form only: `Builder(class_="x")[child]`. Never raw HTML strings.
- **Tailwind scans raw source text.** A utility class must appear as one contiguous string literal. Splitting `"[@container_scroll-state(scrollable:inline-start)]:" "shadow-[…]"` across two adjacent literals produces the right Python string and **no CSS rule** — the scanner never sees the joined token. Keep each class whole on one line even when the line is long; ruff does not split string literals and E501 is not enabled.
- Comments explain non-obvious intent only. No references to this plan, the spec, issues, or history.
- Name variables with complete words (`element` not `el`, `column` not `col`).
- The verification gate is a full `make check` — lint, format-check, mypy, ts-check, vitest, and the entire pytest suite **including `e2e/`**. `ARGS` is for iterating, never for the gate.

## What Phase 4a deliberately does NOT do

No top-layer/popover migration — that was Phase 1, now cut and tracked as #544. No vertical sticky header. No last-column pin (the session-reset `Modal` lives in the actions cell and would need its own treatment). No user column toggle.

## Already verified — do not re-litigate

Measured in Chrome 149 before this plan was written:

- All five utilities compile through `make css`: `z-[2]`, `z-[3]`, `start-0` → `inset-inline-start`, `has-[[data-pop-over-panel]:not([hidden])]:z-[3]` → `:has(*:is([data-pop-over-panel]:not([hidden])))`, `[container-type:scroll-state]`, and `shadow-[4px_0_6px_-4px_rgb(0_0_0/0.35)]`.
- `@container scroll-state(scrollable: inline-start)` flips correctly: no shadow at rest, shadow once scrolled, none again on return.
- `container-type: scroll-state` does **not** capture `position: fixed` descendants, so putting it on the scroll region does not trip the shell's containing-block prohibition.
- The elevation removes the occlusion (24/24 → 0/24) and `z-[30]` would instead cover an open `z-20` menu at 15/24. `z-[3]` is the value.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `common/components/primitives.py` | Owns the pinned-cell class and both `<th>` emitters | Add `PINNED_COLUMN_CLASS` beside `SHRINKABLE_COLUMN_CLASS` (490); `_header_cell` (2066) gains `pinned`; `TableRow` (1751) pins its row header; `StyledTable` (2150) passes the flag, moves the header background, and adds the container type |
| `tests/test_components.py` | Unit coverage | Extend `DataTableWidthPolicyTest` (2099) |
| `tests/test_rendered_pages.py` | Page-level HTML assertions | Re-anchor the header-background assertion (543) |
| `e2e/test_pinned_column_e2e.py` | Real-layout coverage | Create |

---

### Task 0: Rebase onto current main

**Files:** none (git only)

**Interfaces:**
- Consumes: nothing
- Produces: a branch based on current `origin/main`

- [ ] **Step 1: Fetch and rebase**

```bash
git fetch origin
git rebase origin/main
```

- [ ] **Step 2: Confirm the spec amendment is present**

Run: `git log --oneline -3 && git status --short`
Expected: the `docs(specs): fix phase 4a's occlusion in CSS and cut phase 1` commit is in history; no unmerged paths.

---

### Task 1: The first cell of a data table is pinned

**Files:**
- Modify: `common/components/primitives.py` (constant beside `SHRINKABLE_COLUMN_CLASS` 490, `_header_cell` 2066, `TableRow` 1792, `StyledTable`'s header comprehension 2226-2232 and its `TableRow` call 2254)
- Test: `tests/test_components.py` (`DataTableWidthPolicyTest`, 2099)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `PINNED_COLUMN_CLASS: str` — module-level constant in `primitives.py`, unexported (like `SHRINKABLE_COLUMN_CLASS`)
  - `_header_cell(column, sort_terms, request, *, data_table=False, pinned=False)` — new keyword-only `pinned: bool`
  - The first `<th>` of the header row and the row-header `<th>` of every body row carry `PINNED_COLUMN_CLASS` when `data_table=True`

- [ ] **Step 1: Write the failing tests**

Append to `DataTableWidthPolicyTest` in `tests/test_components.py`:

```python
    @staticmethod
    def _first_header_cell(thead):
        return thead.split("<th")[1].split(">")[0]

    @staticmethod
    def _row_header_cell(tbody):
        return tbody.split("<th")[1].split(">")[0]

    def test_data_table_pins_the_header_and_row_header_of_the_first_column(self):
        result = self._data_table(
            [components.Column("Name"), components.Column("Date")],
            [components.make_row("Game", "2025-01-01")],
        )
        for cell in (
            self._first_header_cell(self._thead(result)),
            self._row_header_cell(self._tbody(result)),
        ):
            self.assertIn("sticky", cell)
            self.assertIn("start-0", cell)
            self.assertIn("bg-inherit", cell)

    def test_only_the_first_column_is_pinned(self):
        result = self._data_table(
            [components.Column("Name"), components.Column("Date")],
            [components.make_row("Game", "2025-01-01")],
        )
        self.assertEqual(self._thead(result).count("sticky"), 1)
        self.assertEqual(self._tbody(result).count("sticky"), 1)

    def test_non_data_table_pins_nothing(self):
        result = self._render(
            [components.Column("Name"), components.Column("Value")],
            [components.make_row("Total", "5")],
        )
        self.assertNotIn("sticky", result)

    def test_an_open_panel_raises_the_pinned_cell_above_its_siblings(self):
        """A panel nested in a sticky cell is trapped in that cell's stacking
        context, so a later row would paint over it unless the host cell
        outranks its siblings while the panel is open."""
        result = self._data_table(
            [components.Column("Name")], [components.make_row("Game")]
        )
        cell = self._row_header_cell(self._tbody(result))
        self.assertIn("has-[[data-pop-over-panel]:not([hidden])]:z-[3]", cell)
        self.assertIn("has-[[data-menu]:not([hidden])]:z-[3]", cell)

    def test_the_pinned_cell_never_outranks_the_panel_strata(self):
        """Popovers sit at z-10 and dropdown panels at z-20. A pinned cell that
        reached either would cover the panels of *other* rows: measured, a cell
        at z-30 hides an overlapping open menu at 15 of 24 sample points."""
        from common.components.primitives import PINNED_COLUMN_CLASS

        levels = [int(value) for value in re.findall(r"z-\[(\d+)\]", PINNED_COLUMN_CLASS)]
        self.assertTrue(levels, "the pinned class declares no z-index")
        self.assertLess(max(levels), 10)
```

`re` is already imported at the top of `tests/test_components.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_components.py -k pinned -v"`
Expected: FAIL — `AssertionError: 'sticky' not found`, and `ImportError` on `PINNED_COLUMN_CLASS`.

- [ ] **Step 3: Add the constant**

In `common/components/primitives.py`, directly below `SHRINKABLE_COLUMN_CLASS` (490):

```python
# The pinned first column of a data table. `start-0`, not `left-0`: the table
# flips to rtl:text-right, where the scroll start edge is the right one.
# `bg-inherit` picks up the row's zebra and hover surface — a sticky cell is
# transparent by default and would let the scrolled content show through it.
# The cell outranks its sibling pinned cells only while it holds an open panel:
# a panel nested inside a sticky cell is scoped to that cell's stacking context,
# so a later row's cell would paint over it. 3 clears the siblings at 2 and
# stays under the popover (10) and menu (20) strata, which a higher value would
# cover instead.
PINNED_COLUMN_CLASS = " ".join(
    [
        "sticky start-0 z-[2] bg-inherit",
        "has-[[data-pop-over-panel]:not([hidden])]:z-[3]",
        "has-[[data-menu]:not([hidden])]:z-[3]",
    ]
)
```

- [ ] **Step 4: Emit it from the header cell**

In `_header_cell` (2066), add the parameter and the branch. The signature becomes:

```python
def _header_cell(
    column: "Column",
    sort_terms: Sequence[SortTerm],
    request,
    *,
    data_table: bool = False,
    pinned: bool = False,
) -> Node:
```

and after the existing `column.shrinkable` branch:

```python
    if pinned:
        base_class = f"{base_class} {PINNED_COLUMN_CLASS}"
```

- [ ] **Step 5: Pass the flag from the header comprehension**

In `StyledTable` (2226-2232), the header row becomes:

```python
        header_row = Tr()[
            [
                _header_cell(
                    column,
                    sort_terms,
                    request,
                    data_table=data_table,
                    pinned=data_table and index == 0,
                )
                for index, column in enumerate(columns)
            ]
        ]
```

- [ ] **Step 6: Emit it from the row header**

In `TableRow` (1792), inside the `if i == 0:` branch, after the `shrinkable` line:

```python
            if data_table:
                column_class = f"{column_class} {PINNED_COLUMN_CLASS}".strip()
```

`TableRow` already receives `data_table`; `StyledTable` already passes it at 2254.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_components.py -v"`
Expected: PASS, all tests in the file.

- [ ] **Step 8: Commit**

```bash
git add common/components/primitives.py tests/test_components.py
git commit -m "feat(table): pin the first column of a data table"
```

---

### Task 2: The header background moves to the header row

**Files:**
- Modify: `common/components/primitives.py` (`StyledTable`, `thead_class` 2233-2236)
- Test: `tests/test_rendered_pages.py:543`, `tests/test_components.py`

**Interfaces:**
- Consumes: the pinned header cell from Task 1
- Produces: `<thead>` no longer carries `bg-neutral-tertiary`; its `<tr>` does

`bg-inherit` on the pinned header cell resolves against its parent `<tr>`, not the `<thead>`. Left alone, the header's pinned cell is transparent and the scrolled columns show through it — the one place the Task 1 classes are not enough on their own.

- [ ] **Step 1: See the bug before fixing it**

Add to `DataTableWidthPolicyTest`:

```python
    def test_the_header_row_carries_the_header_surface(self):
        """The pinned header cell inherits its background from the row, so the
        surface has to live there — on <thead> it resolves to transparent and
        the scrolled columns show through the pinned cell."""
        result = self._data_table(
            [components.Column("Name")], [components.make_row("Game")]
        )
        thead = self._thead(result)
        header_row = thead.split("<tr")[1].split(">")[0]
        self.assertIn("bg-neutral-tertiary", header_row)
```

Run: `make test ARGS="tests/test_components.py -k header_surface -v"`
Expected: FAIL — the class is on `<thead>`, not on the row.

- [ ] **Step 2: Move the surface onto the header row**

In `StyledTable`, replace the `thead_class` block (2233-2236) with:

```python
        # The surface sits on the row, not on <thead>: the pinned first cell
        # takes its background from its parent row, and a <thead>-level surface
        # would leave it transparent.
        header_row_class = "bg-neutral-tertiary"
        header_row = Tr(class_=header_row_class)[
            [
                _header_cell(
                    column,
                    sort_terms,
                    request,
                    data_table=data_table,
                    pinned=data_table and index == 0,
                )
                for index, column in enumerate(columns)
            ]
        ]
        thead_class = "text-type-micro text-body uppercase"
        if data_table:
            thead_class = f"{thead_class} {_FALLBACK_HIDE_HEADER_CLASS}"
        table_children.append(Thead(class_=thead_class)[header_row])
```

Note this replaces the `header_row = Tr()[…]` assignment written in Task 1 Step 5 — the comprehension moves into this block unchanged.

- [ ] **Step 3: Re-anchor the page-level assertion**

`tests/test_rendered_pages.py:543` asserts `<thead[^>]*bg-neutral-tertiary`, deliberately anchored on `<thead>` so a row's `hover:bg-neutral-tertiary-medium` cannot false-match. Keep that property while matching the new location — anchor on the `<tr>` that directly follows `<thead`:

```python
        # Anchored on the header row rather than any <tr>: a body row's
        # hover:bg-neutral-tertiary-medium would otherwise false-match.
        self.assertRegex(html, r"<thead[^>]*>\s*<tr[^>]*bg-neutral-tertiary")
```

- [ ] **Step 4: Run both suites**

Run: `make test ARGS="tests/test_components.py tests/test_rendered_pages.py -v"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/components/primitives.py tests/test_components.py tests/test_rendered_pages.py
git commit -m "fix(table): move the header surface onto the header row"
```

---

### Task 3: The edge shadow appears only while content is behind it

**Files:**
- Modify: `common/components/primitives.py` (`PINNED_COLUMN_CLASS` from Task 1, `StyledTable`'s `scroll_class` 2265-2277)
- Test: `tests/test_components.py`

**Interfaces:**
- Consumes: `PINNED_COLUMN_CLASS` from Task 1
- Produces: the scroll region carries `[container-type:scroll-state]`; the pinned cell's `box-shadow` is scoped to `@container scroll-state(scrollable: inline-start)`

Priority-plus (#532) makes most tables fit at most widths, so an unconditional shadow would draw a permanent seam down every list page for a scroll that is usually not happening.

- [ ] **Step 1: Write the failing tests**

Add to `DataTableWidthPolicyTest`:

```python
    def test_the_scroll_region_is_a_scroll_state_container(self):
        result = self._data_table(
            [components.Column("Name")], [components.make_row("Game")]
        )
        region = result.split('role="region"')[0].split("<div")[-1]
        self.assertIn("[container-type:scroll-state]", region)

    def test_the_pinned_shadow_is_scoped_to_a_scrolled_region(self):
        """An unconditional shadow would draw a seam down every table that fits,
        which after priority-plus is most of them at most widths."""
        from common.components.primitives import PINNED_COLUMN_CLASS

        self.assertIn(
            "[@container_scroll-state(scrollable:inline-start)]:shadow-",
            PINNED_COLUMN_CLASS,
        )

    def test_the_pinned_cell_casts_no_filter_shadow(self):
        """`filter` would make the cell a containing block for the fixed panels
        it hosts; `box-shadow` has no such side effect."""
        from common.components.primitives import PINNED_COLUMN_CLASS

        self.assertNotIn("drop-shadow", PINNED_COLUMN_CLASS)

    def test_non_data_table_gets_no_scroll_state_container(self):
        result = self._render(
            [components.Column("Name"), components.Column("Value")],
            [components.make_row("Total", "5")],
        )
        self.assertNotIn("container-type", result)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_components.py -k scroll_state or shadow -v"`
Expected: FAIL — neither the container type nor the shadow exists yet.

- [ ] **Step 3: Add the shadow to the pinned class**

Extend `PINNED_COLUMN_CLASS`. The scroll-state entry must stay one contiguous literal — see the Tailwind constraint at the top of this plan:

```python
PINNED_COLUMN_CLASS = " ".join(
    [
        "sticky start-0 z-[2] bg-inherit",
        "has-[[data-pop-over-panel]:not([hidden])]:z-[3]",
        "has-[[data-menu]:not([hidden])]:z-[3]",
        # A box-shadow, never a filter: a filtered cell becomes the containing
        # block for the fixed panels it hosts. Scoped to a region that actually
        # has something scrolled behind the column, so a table that fits shows
        # no seam.
        "[@container_scroll-state(scrollable:inline-start)]:shadow-[4px_0_6px_-4px_rgb(0_0_0/0.35)]",
    ]
)
```

- [ ] **Step 4: Make the region a scroll-state container**

In `StyledTable`, in the `if data_table:` branch that builds `scroll_class` (2277), append the container type:

```python
        scroll_class = f"{scroll_class} md:scroll-ps-[19rem] [container-type:scroll-state]"
```

The comment above that line already explains the scroll padding; add one line to it:

```python
        # The scroll-state container type lets the pinned column show its seam
        # only while something is scrolled behind it. It is not a containing
        # block, so the fixed panels inside the table are unaffected.
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_components.py -v"`
Expected: PASS.

- [ ] **Step 6: Confirm Tailwind actually emitted the rules**

Run: `make css && grep -c 'container-type: scroll-state' games/static/base.css && grep -c '@container scroll-state' games/static/base.css`
Expected: both counts ≥ 1. A zero means a class got split across string literals and the scanner never saw it.

- [ ] **Step 7: Commit**

```bash
git add common/components/primitives.py tests/test_components.py
git commit -m "feat(table): show the pinned column's seam only while scrolled"
```

---

### Task 4: Browser coverage

**Files:**
- Create: `e2e/test_pinned_column_e2e.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3
- Produces: no exported helpers; this file is self-contained (pytest fixtures do not cross files unless they live in `conftest.py`)

Purchases and games are the pages under test: purchases has the widest natural column total of the set and is the first to overflow.

- [ ] **Step 1: Write the file**

```python
"""Real-layout coverage for the pinned first column.

The pin is only correct if three things hold at once: the column stays put
while the rest scrolls, its surface is opaque in both themes, and it does not
swallow the panels that live inside it.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.urls import reverse
from playwright.sync_api import Page

from games.models import Device, Game, Platform, Purchase, Session

ZONEINFO = ZoneInfo(settings.TIME_ZONE)
BASE = datetime(2025, 3, 1, 10, 0, tzinfo=ZONEINFO)

LONG_NAME = (
    "A Deliberately Extraordinary Game Name That Is Much Wider Than Any Practical "
    "Name Column And Therefore Must Be Clipped By Its Rendered Width"
)

# A narrow viewport guarantees the region overflows even after priority-plus has
# dropped what it can, which is the only state where a pinned column does
# anything at all.
NARROW = {"width": 420, "height": 900}

PAGES = ["games:list_purchases", "games:list_games"]


@pytest.fixture
def populated(db) -> None:
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    device = Device.objects.create(name="A Desktop Computer Of Some Kind", type="p")
    game = Game.objects.create(name=LONG_NAME, platform=platform, year_released=2024)
    short = Game.objects.create(name="Short", platform=platform, year_released=2023)
    for index, subject in enumerate((game, short)):
        Session.objects.create(
            game=subject,
            device=device,
            timestamp_start=BASE + timedelta(days=index),
            timestamp_end=BASE + timedelta(days=index, hours=2),
        )
        purchase = Purchase.objects.create(
            platform=platform,
            date_purchased=BASE + timedelta(days=index),
            price=1234,
            price_currency="USD",
        )
        purchase.games.add(subject)


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def _open_page(page: Page, live_server, url_name: str) -> None:
    page.set_viewport_size(NARROW)
    page.goto(f"{live_server.url}{reverse(url_name)}")
    page.evaluate("() => document.fonts.ready")


SCROLL_TO_END = """
() => {
  const region = document.querySelector('[role="region"]');
  region.scrollLeft = region.scrollWidth;
  return region.scrollLeft > 0;
}
"""

PIN_OFFSET = """
() => {
  const region = document.querySelector('[role="region"]');
  const cell = document.querySelector('tbody tr th');
  return Math.round(
    cell.getBoundingClientRect().left - region.getBoundingClientRect().left
  );
}
"""


@pytest.mark.parametrize("url_name", PAGES)
def test_the_pinned_column_stays_at_the_regions_start_edge(
    authenticated_page: Page, live_server, populated, url_name: str
):
    page = authenticated_page
    _open_page(page, live_server, url_name)
    at_rest = page.evaluate(PIN_OFFSET)
    scrolled = page.evaluate(SCROLL_TO_END)
    if not scrolled:
        pytest.skip(f"{url_name} does not overflow at {NARROW['width']}px")
    assert page.evaluate(PIN_OFFSET) == at_rest


def test_the_pinned_column_pins_to_the_right_edge_under_rtl(
    authenticated_page: Page, live_server, populated
):
    """`start-0` is a logical inset: under rtl the scroll start edge is the
    right one, where a physical `left-0` would pin to the wrong side."""
    page = authenticated_page
    _open_page(page, live_server, "games:list_purchases")
    page.evaluate("() => document.documentElement.setAttribute('dir', 'rtl')")
    offset = page.evaluate(
        """() => {
            const region = document.querySelector('[role="region"]');
            const cell = document.querySelector('tbody tr th');
            region.scrollLeft = -region.scrollWidth;
            return Math.round(
                region.getBoundingClientRect().right - cell.getBoundingClientRect().right
            );
        }"""
    )
    assert offset == 0


@pytest.mark.parametrize("dark", [False, True])
def test_the_pinned_surface_is_opaque_in_both_themes(
    authenticated_page: Page, live_server, populated, dark: bool
):
    """A transparent sticky cell lets the scrolled columns show through it."""
    page = authenticated_page
    _open_page(page, live_server, "games:list_purchases")
    if dark:
        page.evaluate("() => document.documentElement.classList.add('dark')")
    backgrounds = page.evaluate(
        """() => [
            document.querySelector('thead tr th'),
            document.querySelector('tbody tr th'),
        ].map((cell) => getComputedStyle(cell).backgroundColor)"""
    )
    for background in backgrounds:
        assert background not in ("rgba(0, 0, 0, 0)", "transparent"), backgrounds


OCCLUSION = """
(selector) => {
  const panel = document.querySelector(selector);
  const box = panel.getBoundingClientRect();
  let occluded = 0;
  let total = 0;
  for (let row = 0; row < 6; row++) {
    for (let column = 0; column < 4; column++) {
      const x = box.left + 2 + (column * (box.width - 4)) / 3;
      const y = box.top + 2 + (row * (box.height - 4)) / 5;
      total++;
      const hit = document.elementFromPoint(x, y);
      if (hit !== panel && !panel.contains(hit)) occluded++;
    }
  }
  return [occluded, total];
}
"""


def test_a_tooltip_inside_the_pinned_cell_is_not_occluded(
    authenticated_page: Page, live_server, populated
):
    """The defect this phase had to solve: a panel nested in a sticky cell is
    scoped to that cell's stacking context, so later rows paint over it.

    Purchases renders its first cell through `LinkedPurchase` → `TruncatedText`
    with `reveal="auto"`, so the tooltip exists only while the name is actually
    clipped — which the long fixture name guarantees at this width.
    """
    page = authenticated_page
    _open_page(page, live_server, "games:list_purchases")
    page.locator("tbody tr th truncated-text").first.hover()
    panel = page.locator("tbody tr th [data-pop-over-panel]").first
    panel.wait_for(state="visible")
    occluded, total = page.evaluate(OCCLUSION, "tbody tr th [data-pop-over-panel]")
    assert occluded == 0, f"{occluded}/{total} points occluded"


def test_the_open_panel_raises_its_host_cell_and_releases_it(
    authenticated_page: Page, live_server, populated
):
    """The elevation is keyed off the `hidden` attribute. If a panel ever hides
    itself with a class instead, the selector goes blind and the occlusion
    above comes back silently."""
    page = authenticated_page
    _open_page(page, live_server, "games:list_purchases")
    cell = page.locator("tbody tr th").first
    assert cell.evaluate("(node) => getComputedStyle(node).zIndex") == "2"
    page.locator("tbody tr th truncated-text").first.hover()
    page.locator("tbody tr th [data-pop-over-panel]").first.wait_for(state="visible")
    assert cell.evaluate("(node) => getComputedStyle(node).zIndex") == "3"
    page.mouse.move(0, 0)
    page.locator("tbody tr th [data-pop-over-panel]").first.wait_for(state="hidden")
    assert cell.evaluate("(node) => getComputedStyle(node).zIndex") == "2"


MENU_OVERLAPS_PIN = """
() => {
  const menu = document.querySelector('tbody tr [data-menu]:not([hidden])');
  const pin = document.querySelector('tbody tr th');
  if (!menu) return false;
  const menuBox = menu.getBoundingClientRect();
  const pinBox = pin.getBoundingClientRect();
  return menuBox.left < pinBox.right && menuBox.right > pinBox.left;
}
"""


def test_an_open_row_menu_is_not_covered_by_a_pinned_cell(
    authenticated_page: Page, live_server, populated
):
    """The other direction: the pin must stay under the panel strata, or it
    covers the menus of the rows it overlaps. The sessions list carries a
    <drop-down> device selector in every row (`SessionDeviceSelector`), which is
    the panel the pinned column can get in front of."""
    page = authenticated_page
    _open_page(page, live_server, "games:list_sessions")
    toggle = page.locator("tbody tr [data-toggle]").first
    if toggle.count() == 0:
        pytest.skip("no row menu rendered at this width")
    toggle.click()
    page.locator("tbody tr [data-menu]").first.wait_for(state="visible")
    # Without horizontal overlap the occlusion count is trivially zero and the
    # assertion below would pass while measuring nothing.
    assert page.evaluate(MENU_OVERLAPS_PIN), (
        "the open menu does not overlap the pinned column at this width; widen "
        "NARROW or pick a page whose menu column sits beside the first"
    )
    occluded, total = page.evaluate(OCCLUSION, "tbody tr [data-menu]:not([hidden])")
    assert occluded == 0, f"{occluded}/{total} points occluded"


def test_the_seam_appears_only_once_the_region_is_scrolled(
    authenticated_page: Page, live_server, populated
):
    page = authenticated_page
    _open_page(page, live_server, "games:list_purchases")
    cell = page.locator("tbody tr th").first
    assert cell.evaluate("(node) => getComputedStyle(node).boxShadow") == "none"
    if not page.evaluate(SCROLL_TO_END):
        pytest.skip("the purchases table does not overflow at this width")
    page.evaluate(
        "() => new Promise((resolve) => requestAnimationFrame("
        "() => requestAnimationFrame(resolve)))"
    )
    assert cell.evaluate("(node) => getComputedStyle(node).boxShadow") != "none"


def test_a_control_tabbed_into_from_off_screen_is_not_hidden_by_the_pin(
    authenticated_page: Page, live_server, populated
):
    """The scroll padding reserves the region's start edge; without it a focused
    control parks exactly where the pinned cell paints."""
    page = authenticated_page
    _open_page(page, live_server, "games:list_purchases")
    if not page.evaluate(SCROLL_TO_END):
        pytest.skip("the purchases table does not overflow at this width")
    last_action = page.locator("tbody tr td a, tbody tr td button").last
    last_action.focus()
    overlap = page.evaluate(
        """() => {
            const cell = document.querySelector('tbody tr th');
            const focused = document.activeElement.getBoundingClientRect();
            const pin = cell.getBoundingClientRect();
            return focused.left < pin.right && focused.right > pin.left;
        }"""
    )
    assert overlap is False
```

- [ ] **Step 2: Run the new file**

Run: `make test-e2e ARGS="-k pinned_column -v"`
Expected: PASS. A `skip` on the overflow-dependent tests means the page fits even at 420px — widen `NARROW` until it does not, rather than deleting the assertion.

- [ ] **Step 3: Commit**

```bash
git add e2e/test_pinned_column_e2e.py
git commit -m "test(e2e): cover the pinned first column"
```

---

### Task 5: Dark-mode divider continuity

**Files:**
- Modify (only if the check fails): `common/components/primitives.py` (`tbody_class` 2242), `tests/test_components.py`

**Interfaces:**
- Consumes: the pinned cell from Task 1
- Produces: either a recorded "no discontinuity" result, or the divider moved onto the cells

`border-collapse: collapse` puts row borders in the table's collapsed-border layer rather than in the cell box, so a sticky cell painting its own background may cover the 1px divider that `dark:divide-y` draws on `<tbody>`. It is dark-mode-only and a background-transparency check cannot see it — this needs eyes on a real render. There is no Pillow in the environment, so this is a screenshot inspection, not a pixel assertion.

- [ ] **Step 1: Capture the boundary in dark mode**

Add a temporary test to `e2e/test_pinned_column_e2e.py`:

```python
def test_zz_capture_dark_divider(authenticated_page: Page, live_server, populated):
    page = authenticated_page
    _open_page(page, live_server, "games:list_purchases")
    page.evaluate("() => document.documentElement.classList.add('dark')")
    page.evaluate(SCROLL_TO_END)
    region = page.locator('[role="region"]')
    region.screenshot(path="/tmp/pinned-dark.png")
```

Run: `make test-e2e ARGS="-k zz_capture_dark_divider"`

- [ ] **Step 2: Look at it**

Open `/tmp/pinned-dark.png` and follow the row dividers across the boundary between the pinned column and the scrolled columns.

- If the dividers run continuously across the pinned column: delete the temporary test, note the result in the PR body, and skip to Task 6.
- If they break at the pinned column's edge: continue to Step 3.

- [ ] **Step 3 (only if broken): Move the divider onto the cells**

The divider travels with a sticky cell when it belongs to the cell box rather than the collapsed-border layer. In `StyledTable`, replace `dark:divide-y` in `tbody_class` (2242):

```python
    # The divider lives on the cells, not on the row: a row border sits in the
    # collapsed-border layer, which a sticky cell's own background paints over.
    tbody_class = "font-condensed dark:[&_tr:not(:last-child)>*]:border-b"
```

Add the safelist entry to `common/input.css`, beside the existing nth-child families:

```css
@source inline("dark:[&_tr:not(:last-child)>*]:border-b");
```

and a component test:

```python
    def test_the_row_divider_lives_on_the_cells(self):
        """A row-level border sits in the collapsed-border layer, which the
        pinned cell's background paints over."""
        result = self._data_table(
            [components.Column("Name")], [components.make_row("Game")]
        )
        tbody = self._tbody(result).split(">")[0]
        self.assertIn("dark:[&_tr:not(:last-child)>*]:border-b", tbody)
        self.assertNotIn("divide-y", tbody)
```

- [ ] **Step 4: Re-capture and confirm**

Re-run Step 1 and look again. The dividers must now be continuous.

- [ ] **Step 5: Delete the temporary capture test and commit**

```bash
git add -A
git commit -m "fix(table): keep row dividers continuous across the pinned column"
```

(If Step 2 found nothing wrong, this commit is just the deletion of the temporary test — or nothing at all, if it was never committed.)

---

### Task 6: Full verification gate and PR

**Files:** none

**Interfaces:**
- Consumes: everything above
- Produces: a branch ready for a PR against #523

- [ ] **Step 1: Run the whole gate**

Run: `make check`
Expected: green — lint, format-check, mypy, ts-check, vitest, and the entire pytest suite including `e2e/`.

Do not substitute a subset.

- [ ] **Step 2: Check for stray whitespace damage**

Run: `git diff --check origin/main`
Expected: no output.

- [ ] **Step 3: Confirm no generated or scratch files were committed**

Run: `git diff --stat origin/main -- games/static/base.css db.sqlite3 '*.png'`
Expected: no output (`base.css` is gitignored build output).

- [ ] **Step 4: Open the PR**

```bash
git push -u origin <branch>
```

The PR body states: what the pin does and where it is visible (only when a table overflows, which priority-plus already makes rare); that the occlusion is fixed in CSS rather than by the cut Phase 1 (#544), with the 24/24 → 0/24 measurement and the `z-[3]`-not-`z-[30]` reason; that the header surface moved from `<thead>` to its `<tr>` and why `tests/test_rendered_pages.py` was re-anchored rather than relaxed; the dark-divider result from Task 5; and `Part of #523`.

Merge with `gh pr merge --merge`. Never squash or rebase.

---

## Self-Review

**Spec coverage.** § Phase 4a asks for: the sticky cell with `start-0`/`z-[2]`/`bg-inherit` (Task 1); the `:has()` elevation at `z-[3]` (Task 1); the invariant that the pin stays below 10 (Task 1, Step 1) and that panels toggle the `hidden` attribute (Task 4, `test_the_open_panel_raises_its_host_cell_and_releases_it` — asserted through behaviour rather than by policing the TypeScript, so it fails if any panel ever switches to a class); the background-bleed and header-background traps (Tasks 1-2); the `box-shadow`-not-`filter` rule and the scroll-state scoping (Task 3); the collapsed-border trap (Task 5); and the acceptance list — flush after `scrollLeft` in ltr and rtl, opaque in both themes, 0/24 both directions, seam only when scrolled, focus not parking under the pin, measured on purchases and games (Task 4). All covered.

**Placeholders.** None. Task 5 is conditional rather than open-ended: both branches are written out, including the exact replacement class, its safelist entry, and its test.

**Type consistency.** `PINNED_COLUMN_CLASS` is defined once (Task 1, Step 3), extended once (Task 3, Step 3), and referenced by that name in both tasks' tests. `_header_cell` gains one keyword-only `pinned: bool`, passed from the single call site, which Task 2 Step 2 rewrites wholesale rather than patching twice. `TableRow` needs no signature change — it already takes `data_table`.

**One risk worth flagging to the reviewer.** Task 2 moves a background that has been on `<thead>` for the life of the component. Any style or test that reaches for `thead.bg-neutral-tertiary` breaks — `make check` catches the tests, but a screenshot of a list page in both themes is the cheap confirmation that the header still looks right, and it costs one browser visit.
