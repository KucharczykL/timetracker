# Table Widths Phase 0 — Implementation Plan

> **Shipped in #525.** Kept as the record of what was planned and where the
> implementation went elsewhere — see **What shipped, and where it deviated**
> below. Line references are current as of #532 (Phases 2 and 3 have since
> moved the code this plan touched).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Name column's slack-absorbing behaviour apply only below the `md` breakpoint, removing 247px of dead space and the wrapped DATE column at desktop widths.

**Architecture:** `Column` gains a semantic `shrinkable` flag that owns the Tailwind, replacing a hand-written `class_="w-full max-w-0"` at four view call sites. The classes become `max-md:` variants, so above 768px the table falls back to plain auto layout and the Name column hugs its content up to the existing 16rem cap. No JS, no new breakpoint, no threshold constant.

**Tech Stack:** Django 6, Python 3.14, the project's Python component system (`common/components/`), Tailwind CSS v4, pytest, Playwright.

**Design:** `docs/superpowers/specs/2026-07-26-responsive-table-widths-design.md` § Phase 0. **Tracked by** #523.

## Global Constraints

- Run everything through `make`. Never `direnv exec . <cmd>` per command, never raw `uv run` / `pnpm` / `pytest`. Focused runs: `make test ARGS="tests/test_components.py -k shrinkable"`.
- Python 3.14 is a hard prerequisite. A `SyntaxError` in an `except A, B:` line means the wrong interpreter, not broken code.
- Build UI with the component builders in `common.components`, htpy form only: `Builder(class_="x")[child]`. Never raw HTML strings.
- Comments explain non-obvious intent only. No references to this plan, the spec, issues, or history.
- Name variables with complete words (`element` not `el`, `column` not `col`).
- The verification gate is a full `make check` — lint, format-check, mypy, ts-check, vitest, and the entire pytest suite **including `e2e/`**. `ARGS` is for iterating, never for the gate.

## What Phase 0 deliberately does NOT do

Do not add `whitespace-nowrap`, a sticky column, a scroll region, a caption, or priority-based column dropping. Those are Phases 2–4 and each has blocking prerequisites. Phase 0 is one flag and four call sites.

## What shipped, and where it deviated

All five tasks landed in #525. Four places where the shipped code is not what the
task steps originally said — the first three are merged into the steps below,
since as written they could not pass:

- **The mobile-only assertion scans cells, not the whole document.** The first
  draft walked every `class="…"` for a bare `w-full`; `StyledTable`'s own
  `<table>` carries one (`primitives.py:2259`), so it could never pass. Shipped
  narrowed to `<th>`/`<td>` attributes.
- **`test_shrinkable_column_reaches_header_and_body_cell` asserts per section.**
  A whole-document `assertIn` is satisfied by the body cell alone, so it proved
  nothing about the header. Shipped asserts against `_thead()` and `_tbody()`
  separately.
- **The dead-space test is proportional, not absolute.** Renamed to
  `test_desktop_name_column_does_not_absorb_the_tables_slack` and bounded at
  under 10% of the container: the measured floor is 69px on this fixture, not
  1px, because a capped column keeps its proportional share of slack (#522).
- **The 768 branch has since lost its column-visibility assertions.** Phase 0
  shipped exactly the loop below. Phase 3 (#532) then removed the
  `to_be_visible()`/`to_be_hidden()` checks from it, because which columns render
  at a given width is now `<responsive-table>`'s emergent decision and is covered
  by `e2e/test_responsive_table_e2e.py`.

Task 1's `_header_cell` and `TableRow` edits were also reshaped by Phase 2 (#531):
the row header now reads its column through a guarded `column_at()` helper and
both cells apply the nowrap policy alongside the shrinkable class.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `common/components/primitives.py` | Owns `Column`, the shrinkable class constant, and both `<th>` emitters | Modify: `Column` (1690), `_header_cell` (2066), `TableRow` (1751). The constant stays unexported, matching `NAME_MAX_WIDTH_CLASS`. |
| `games/views/session.py` | Sessions list columns | Modify line 97 |
| `games/views/game.py` | Games list + game-detail purchases table columns | Modify lines 112, 635 |
| `games/views/purchase.py` | Purchases list columns | Modify line 116 |
| `tests/test_components.py` | Unit coverage for the flag | Modify `test_first_column_class_reaches_header_and_body_cell` (1809), `test_direct_table_row_keeps_columns_optional` (1871) |
| `e2e/test_truncated_text_e2e.py` | Browser coverage at real widths | Modify `test_table_constraints_hold_at_mobile_and_intermediate_widths` (203); add one dead-space test |

---

### Task 0: Rebase onto current main

**Files:** none (git only)

**Interfaces:**
- Consumes: nothing
- Produces: a branch whose base is current `origin/main`

- [x] **Step 1: Fetch and rebase**

```bash
git fetch origin
git rebase origin/main
```

- [x] **Step 2: Confirm the tree is clean and the spec commits survived**

Run: `git status --short && git log --oneline -4`
Expected: no unmerged paths; the `docs(specs):` commits for the design are present.

Note: `.claude/launch.json` may carry an uncommitted `DEV_PORT=9999` change and there may be an untracked `db.sqlite3` from design-time measurement. Both are local scratch. Leave them uncommitted; do not add them.

---

### Task 1: `Column.shrinkable` emits the mobile-only classes

**Files:**
- Modify: `common/components/primitives.py` (`Column` 1690, `_header_cell` 2066, `TableRow` 1751)
- Test: `tests/test_components.py` (1809)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `SHRINKABLE_COLUMN_CLASS: str` — module-level constant in `primitives.py`, exact value `"max-md:w-full max-md:max-w-0"`
  - `Column(label, sort_key=None, align="left", class_="", shrinkable=False)` — new trailing field, `shrinkable: bool`
  - Both the header `<th>` (from `_header_cell`) and the row-header `<th>` (from `TableRow`) carry `SHRINKABLE_COLUMN_CLASS` when the first column sets `shrinkable=True`

- [x] **Step 1: Write the failing tests**

Replace `test_first_column_class_reaches_header_and_body_cell` (`tests/test_components.py:1809`) and `test_direct_table_row_keeps_columns_optional` (1871) with these four tests. Keep them in the same class, in this order:

```python
def test_first_column_class_reaches_header_and_body_cell(self):
    result = str(
        components.StyledTable(
            columns=[
                components.Column("Name", class_="w-64"),
                components.Column("Actions"),
            ],
            rows=[components.make_row("Game", "Edit")],
        )
    )
    self.assertIn('class="px-2 sm:px-3 lg:px-6 py-3 w-64"', result)
    tbody = self._tbody(result)
    self.assertIn("w-64", tbody)


def test_shrinkable_column_reaches_header_and_body_cell(self):
    from common.components.primitives import SHRINKABLE_COLUMN_CLASS

    result = str(
        components.StyledTable(
            columns=[
                components.Column("Name", shrinkable=True),
                components.Column("Actions"),
            ],
            rows=[components.make_row("Game", "Edit")],
        )
    )
    # Assert against each section separately: the whole-document form is
    # satisfied by the body cell alone, so it cannot prove the header
    # emitted anything.
    self.assertIn(SHRINKABLE_COLUMN_CLASS, self._thead(result))
    self.assertIn(SHRINKABLE_COLUMN_CLASS, self._tbody(result))


def test_shrinkable_classes_are_mobile_only(self):
    """Above md the column must carry no width constraint at all: an
    unprefixed w-full or max-w-0 would reintroduce the desktop dead space."""
    result = str(
        components.StyledTable(
            columns=[
                components.Column("Name", shrinkable=True),
                components.Column("Actions"),
            ],
            rows=[components.make_row("Game", "Edit")],
        )
    )
    for token in re.findall(r'<(?:th|td)\b[^>]*class="([^"]*)"', result):
        for css_class in token.split():
            if css_class in {"w-full", "max-w-0"}:
                self.fail(f"unprefixed {css_class} found in: {token}")


def test_non_shrinkable_column_emits_no_width_classes(self):
    result = str(
        components.StyledTable(
            columns=[
                components.Column("Name"),
                components.Column("Actions"),
            ],
            rows=[components.make_row("Game", "Edit")],
        )
    )
    self.assertNotIn("max-md:w-full", result)
    self.assertNotIn("max-md:max-w-0", result)


def test_direct_table_row_keeps_columns_optional(self):
    result = str(components.TableRow(components.make_row("Game", "Edit")))
    self.assertIn('th scope="row"', result)
    self.assertNotIn("max-md:w-full", result)
```

`re` is already imported at the top of `tests/test_components.py`. If it is not, add `import re`.

- [x] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_components.py -k shrinkable -v"`
Expected: FAIL — `TypeError: Column.__new__() got an unexpected keyword argument 'shrinkable'`

- [x] **Step 3: Add the constant**

In `common/components/primitives.py`, directly above `NAME_MAX_WIDTH_CLASS` (491):

```python
# Below md the name cell must be able to shrink under its content so the
# actions column survives on a phone; max-w-0 is the only way to tell the
# auto-table algorithm that, and w-full then hands it the leftover. Above md
# the same pair makes the column eat every spare pixel, so it stops there and
# ordinary auto layout takes over.
SHRINKABLE_COLUMN_CLASS = "max-md:w-full max-md:max-w-0"
```

- [x] **Step 4: Add the field to `Column`**

In the `Column` NamedTuple (1690), append the field and extend the docstring's last sentence:

```python
class Column(NamedTuple):
    """One table column header. ``sort_key`` (a public key in the view's
    ``*_SORTS`` map) makes the header clickable-to-sort; ``None`` → a static
    header (e.g. an "Actions" column). ``align`` aligns *the header*; the body
    cell owns its own alignment (e.g. an Actions ``ButtonGroup`` right-aligns
    itself), so set both to "right" together for an Actions column. ``class_``
    supplies column sizing classes to the header and, for the row-header first
    column, its body ``<th>``. ``shrinkable`` marks a column that may shrink
    below its content width when the table is crowded; its content is expected
    to self-clip."""

    label: str
    sort_key: str | None = None
    align: Align = "left"
    class_: str = ""
    shrinkable: bool = False
```

The field is appended, so every existing positional construction keeps working.

- [x] **Step 5: Emit from the header cell**

In `_header_cell` (2075), after the existing `column.class_` branch:

```python
    base_class = "px-2 sm:px-3 lg:px-6 py-3" + (
        " text-right" if column.align == "right" else ""
    )
    if column.class_:
        base_class = f"{base_class} {column.class_}"
    if column.shrinkable:
        base_class = f"{base_class} {SHRINKABLE_COLUMN_CLASS}"
```

- [x] **Step 6: Emit from the row-header cell**

In `TableRow` (1792), replace the `column_class` assignment:

```python
        if i == 0:
            column_class = columns[0].class_ if columns else ""
            if columns and columns[0].shrinkable:
                column_class = f"{column_class} {SHRINKABLE_COLUMN_CLASS}".strip()
```

The `if columns` guard is already the established pattern here and keeps the `columns=None` path (used by `tests/test_components.py:1872` and `tests/test_session_row.py:30`) working.

- [x] **Step 7: Do NOT export the constant**

Leave `common/components/__init__.py` untouched. `NAME_MAX_WIDTH_CLASS` — the closest analogue, defined four lines away — is likewise unexported: it is consumed only inside the component layer (`common/components/domain.py:11`). Views declare intent with `shrinkable=True` and never name the string, so exporting it would widen the package surface for no caller. Tests reach it with a local `from common.components.primitives import SHRINKABLE_COLUMN_CLASS`, the pattern already used for `ICON_SIZE_CLASS` at `tests/test_components.py:578`.

- [x] **Step 8: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_components.py -v"`
Expected: PASS, all tests in the file.

- [x] **Step 9: Commit**

```bash
git add common/components/primitives.py tests/test_components.py
git commit -m "feat(table): add a shrinkable Column flag scoped below md"
```

---

### Task 2: Convert the four call sites

**Files:**
- Modify: `games/views/session.py:97`, `games/views/game.py:112`, `games/views/game.py:635`, `games/views/purchase.py:116`

**Interfaces:**
- Consumes: `Column(..., shrinkable=True)` from Task 1
- Produces: no view passes `class_="w-full max-w-0"` anywhere in the codebase

- [x] **Step 1: Confirm the exact call sites before editing**

Run: `grep -rn 'w-full max-w-0' --include=*.py .`
Expected: exactly four hits, in `games/views/session.py`, `games/views/game.py` (twice), `games/views/purchase.py`. Any hit in `tests/` means Task 1 was left incomplete.

- [x] **Step 2: Convert the three sortable Name columns**

`games/views/session.py:97`, `games/views/game.py:112`, `games/views/purchase.py:116` each become:

```python
(Column("Name", "name", shrinkable=True),)
```

- [x] **Step 3: Convert the static Name column**

`games/views/game.py:635` (the game-detail purchases table, which has no sort key) becomes:

```python
(Column("Name", shrinkable=True),)
```

- [x] **Step 4: Verify the literal is gone**

Run: `grep -rn 'w-full max-w-0' --include=*.py .`
Expected: no output.

- [x] **Step 5: Run the page-level suites**

Run: `make test ARGS="tests/test_rendered_pages.py tests/test_paths_return_200.py -v"`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add games/views/session.py games/views/game.py games/views/purchase.py
git commit -m "refactor(views): declare the name column shrinkable"
```

---

### Task 3: Update the browser coverage

**Files:**
- Modify: `e2e/test_truncated_text_e2e.py` (`test_table_constraints_hold_at_mobile_and_intermediate_widths`, 203)

**Interfaces:**
- Consumes: the converted views from Task 2
- Produces: `_name_cell_dead_space(page)` helper, reusable by later phases

The existing test asserts `scrollWidth <= clientWidth` at 390, **640 and 768**. Tailwind's `max-md` is `@media (width < 48rem)`, so at exactly 768 the greed is off *and* all columns are visible — peak pressure. Measured on this test's own fixture, wrapper overflow goes **0 → 132px**. That repeals the prior design's Step-0 criterion 4, deliberately. The 390 and 640 branches are unaffected and must keep asserting no scroll.

- [x] **Step 1: Add the dead-space helper**

Add near `_center_x` (53):

```python
def _name_cell_dead_space(page: Page) -> float:
    """Pixels the first body cell is wider than the truncated-text inside it.

    The host is w-full, so it fills whatever the cell gets until the 16rem cap;
    a positive result means the cell outgrew the cap and the surplus is unusable.
    """
    return page.evaluate(
        """() => {
            const host = document.querySelector('tbody truncated-text');
            const cell = host.closest('th, td');
            const style = getComputedStyle(cell);
            const inner = cell.clientWidth
                - parseFloat(style.paddingLeft)
                - parseFloat(style.paddingRight);
            return inner - host.getBoundingClientRect().width;
        }"""
    )
```

- [x] **Step 2: Rewrite the width loop**

Replace the body of `test_table_constraints_hold_at_mobile_and_intermediate_widths` from `for width in (390, 640, 768):` to the end of the function:

```python
for width in (390, 640, 768):
    page.set_viewport_size({"width": width, "height": 844})
    _wait_for_fonts(page)
    host = _host(page, LONG_NAME)
    wrapper = host.locator(
        "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), "
        "' overflow-x-auto ')][1]"
    )
    dimensions = wrapper.evaluate(
        "element => ({client: element.clientWidth, scroll: element.scrollWidth})"
    )
    row = host.locator("xpath=ancestor::tr[1]")
    action_cell = row.locator("td").last
    expect(action_cell).to_be_visible()

    if width == 768:
        # At exactly md the shrink allowance is already off and every
        # column is back, so the table is wider than its wrapper. The
        # wrapper scrolls; what must not happen is the name being crushed
        # to the platform icon to avoid it.
        assert host.evaluate("element => element.getBoundingClientRect().width") >= 200
        expect(row.locator("td").first).to_be_visible()
        continue

    assert dimensions["scroll"] <= dimensions["client"]
    if width == 390:
        assert (
            host.locator("[data-truncated-clip]").evaluate(
                "element => element.clientWidth"
            )
            < 256
        )
        host_box = host.bounding_box()
        action_box = action_cell.bounding_box()
        assert host_box is not None and action_box is not None
        assert host_box["x"] + host_box["width"] <= action_box["x"]
    else:
        expect(row.locator("td").first).to_be_hidden()
```

The `>= 200` floor discriminates the fix from the bug: on this fixture the name cell measured 148px before the change and 280px after.

- [x] **Step 3: Add the desktop dead-space test**

Add immediately after the test above:

```python
def test_desktop_name_column_does_not_absorb_the_tables_slack(
    authenticated_page: Page, live_server
):
    """The reported bug: the name cell took every spare pixel — 551px of a
    1217px table for 256px of text — starving its neighbours.

    A capped name column still receives its proportional share of slack, so a
    small surplus is expected and correct; only hoarding is the defect. The
    bound is a fraction of the container so it holds at any window size.

    Measured on this fixture at 1280: 69px surplus of a 1232px container (5.6%)
    as shipped, against 229px (18.6%) with the allowance reapplied unscoped.
    The bound sits between the two; a drift back toward the upper figure is the
    regression it exists to catch.
    """
    page = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    Game.objects.create(name=LONG_NAME, platform=platform)
    Game.objects.create(name="Short", platform=platform)

    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    _wait_for_fonts(page)

    container_width = page.evaluate(
        "() => document.querySelector('.overflow-x-auto').clientWidth"
    )
    assert _name_cell_dead_space(page) < container_width * 0.1
```

An absolute `<= 1` bound — the first draft of this step — cannot pass: the
measured floor on this fixture is 69px, because a capped column still takes a
proportional share of the table's slack (#522).

- [x] **Step 4: Run the e2e file**

Run: `make test-e2e ARGS="e2e/test_truncated_text_e2e.py -v"`
Expected: PASS, including the two changed tests and the new one.

If `test_desktop_name_column_does_not_absorb_the_tables_slack` fails with a surplus near the container's fifth, Task 2 did not take effect — re-check `grep -rn 'w-full max-w-0'`.

- [x] **Step 5: Commit**

```bash
git add e2e/test_truncated_text_e2e.py
git commit -m "test(e2e): cover the mobile-only shrink allowance"
```

---

### Task 4: Record the interim mid-width behaviour

**Files:**
- Modify: `docs/superpowers/specs/2026-07-26-responsive-table-widths-design.md` (Phase 0 § Acceptance)

**Interfaces:**
- Consumes: the working implementation from Tasks 1–3
- Produces: measured numbers in the spec, so the 768–1140 band is a recorded decision rather than a surprise

Between roughly 768 and each table's overflow-clears width (sessions 848, games 1016, purchases 1140) Phase 0 *introduces* wrapper scroll that the greed used to absorb, while the wrapping bug persists there until Phase 2. That is accepted, but it must be written down with real numbers.

- [x] **Step 1: Measure at 1024**

Start the dev server via the Browser pane (`preview_start`, config `dev`), log in, and for each of `/tracker/session/list`, `/tracker/game/list`, `/tracker/purchase/list` at a 1024px viewport, run:

```js
(() => {
  const table = document.querySelector('table');
  const wrap = table.closest('.overflow-x-auto');
  const header = table.querySelector('thead th');
  const host = table.querySelector('truncated-text');
  return {
    page: document.title,
    container: wrap.clientWidth,
    scrollOverflow: wrap.scrollWidth - wrap.clientWidth,
    nameColumn: Math.round(header.getBoundingClientRect().width),
    nameContent: Math.round(host.getBoundingClientRect().width),
  };
})()
```

Never use Bash to run the dev server.

- [x] **Step 2: Write the numbers into the spec**

Under Phase 0's `### Acceptance`, replace the `~1024 is a recorded interim regression` bullet's final sentence with a three-row table of the measured `scrollOverflow` and `nameColumn` per page, and state plainly that Phase 2 removes the wrapping and Phase 3 removes the overflow.

- [x] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-07-26-responsive-table-widths-design.md
git commit -m "docs(specs): record phase 0 interim behaviour at 1024"
```

---

### Task 5: Full verification gate

**Files:** none

**Interfaces:**
- Consumes: everything above
- Produces: a branch ready for a PR against #523

- [x] **Step 1: Run the whole gate**

Run: `make check`
Expected: green — lint, format-check, mypy, ts-check, vitest, and the entire pytest suite including `e2e/`.

Do not substitute a subset. A hand-picked selection is how removed-widget e2e breakage reaches CI.

- [x] **Step 2: Check for stray whitespace damage**

Run: `git diff --check origin/main`
Expected: no output.

- [x] **Step 3: Confirm the scratch files never got committed**

Run: `git diff --stat origin/main -- .claude/launch.json db.sqlite3`
Expected: no output.

- [x] **Step 4: Open the PR**

```bash
git push -u origin claude/game-name-truncation-spacing-c3a9df
```

Then open a PR whose body states: the measured before/after (sessions at a 1217px container, name cell 551px → 234px, the dead space gone bar the proportional residue of #522, DATE unwrapped), that the 768 e2e branch was deliberately repealed with the measured 0 → 132px overflow, and `Part of #523`.

Merge with `gh pr merge --merge`. Never squash or rebase.

---

## Self-Review

**Spec coverage.** Phase 0 of the spec asks for: the `shrinkable` field (Task 1), the four call-site conversions (Task 2), the repealed 768 e2e branch with its measured 0 → 132px (Task 3), replacement of the literal-string assertions in `test_first_column_class_reaches_header_and_body_cell` and `test_direct_table_row_keeps_columns_optional` (Task 1, Step 1), and the recorded 1024 interim behaviour (Task 4). All covered. Phases 1–4 and the refund change are explicitly out of scope and called out at the top.

**Placeholders.** None. Every code step carries the literal code; the only step without a code block is Task 4 Step 2, which describes a documentation edit whose input is the measurement from Step 1 — that number cannot be invented here and inventing it is precisely the failure mode the spec's review caught twice.

**Type consistency.** `SHRINKABLE_COLUMN_CLASS` is defined once in Task 1 Step 3 and referenced by that exact name in Steps 5 and 6 and in the tests, which reach it by local import rather than through the package. `Column.shrinkable` is a trailing `bool` field, appended so existing positional construction is unaffected. `_name_cell_dead_space(page) -> float` is defined in Task 3 Step 1 and used in Step 3.

**One risk worth flagging to the reviewer.** `SHRINKABLE_COLUMN_CLASS` is a Python string constant, and Tailwind v4 discovers classes by scanning source text. The existing `max-md:[&_th:not(:first-child):not(:last-child)]:hidden` in the same file proves both that `.py` files are scanned and that `max-md:` variants are generated from them, so `max-md:w-full max-md:max-w-0` will compile. If the classes appear in the HTML but have no effect, check `games/static/base.css` for the generated rules before touching anything else.
