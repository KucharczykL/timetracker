# Server-render free-text filter search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the free-text filter search input + its "Exclude matches" toggle from imperative TypeScript (`injectSearchInput`) to server-rendered Python components, restoring the single-source-of-truth pattern.

**Architecture:** A new `_filter_search_field(existing)` helper in `common/components/filters.py` renders a labelled field (label + `Input` primitive + `Checkbox` primitive) using canonical classes. It is rendered once in the shared `_FilterBarBase.render()` (top of every bar's form). The TypeScript loses `injectSearchInput` entirely; its `buildFilterJSON` reader (which already reads the controls by `name`) is untouched.

**Tech Stack:** Django, Python component system (`common/components`), TypeScript (`ts/elements`), pytest + Playwright (e2e).

## Global Constraints

- Build UI with Python components (`Div`, `Input`, `Checkbox`, …), never raw HTML strings or Python f-strings. (CLAUDE.md)
- Builders take htpy form: static attrs as kwargs, children via `[]`; dynamic attrs via the single positional slot.
- Elements carry their own classes (no styling-at-a-distance); reuse shared class constants, don't hand-roll.
- `games.forms` ↔ `common.components` is an import cycle: any import of `games.forms` from `common/components/filters.py` MUST be **deferred (inside the function)**, mirroring `FieldComparisonSet`'s `from games.forms import SELECT_CLASS` at line 748.
- Control names are a fixed contract with `ts/elements/filter-bar.ts`: text input `name="filter-search"`, checkbox `name="filter-search-exclude"`. Do not rename.
- Name variables with complete words.
- Spec: `docs/superpowers/specs/2026-06-28-issue-153-server-render-filter-search-design.md`.

---

### Task 1: Server-render the search field in Python (TDD)

Add the component, wire it into the base bar, and pin the contract with unit tests. Single deliverable: the rendered bar HTML carries the search controls (prefilled), produced entirely by Python.

**Files:**
- Modify: `common/components/filters.py` (add `_filter_search_field`; call it in `_FilterBarBase.render`)
- Test: `tests/test_filter_bars.py` (add methods to `FilterBarRenderingTest`)

**Interfaces:**
- Produces: `_filter_search_field(existing: dict) -> Node` (module-private helper in `common/components/filters.py`). Renders a `_filter_field("Search", widget)` whose widget is a `Div` (class `mb-4`) containing an `Input` (`type="text"`, `name="filter-search"`, `class_=INPUT_CLASS`, `placeholder="Search…"`, `value` from `existing["search"]`) and a `Checkbox` (`name="filter-search-exclude"`, `label="Exclude matches"`, `checked` when the search modifier is `EXCLUDES`).
- Consumes: existing helpers `_filter_field` and `_string_from_field` (both already in the file); `Checkbox` from `common.components.primitives`; `INPUT_CLASS` from `games.forms` (deferred import).

- [ ] **Step 1: Write the failing tests**

Add `Checkbox` to the existing primitives import in `common/components/filters.py` is NOT needed yet (that's Step 3) — these tests only touch `tests/test_filter_bars.py`. Add these three methods inside `class FilterBarRenderingTest`:

```python
    def test_filter_bar_renders_search_controls(self):
        """The free-text search input + exclude toggle are server-rendered."""
        html = str(
            FilterBar(
                preset_list_url="/presets/list",
                preset_save_url="/presets/save",
            )
        )
        self.assertIn('name="filter-search"', html)
        self.assertIn('name="filter-search-exclude"', html)
        self.assertIn("Exclude matches", html)
        self.assertNoEscapedTags(html)

    def test_filter_bar_search_prefills_value_and_exclude(self):
        """A stored EXCLUDES search prefills the input value and checks the box."""
        filter_json = json.dumps(
            {"search": {"value": "Witcher", "modifier": "EXCLUDES"}}
        )
        html = str(FilterBar(filter_json=filter_json))
        self.assertIn('value="Witcher"', html)
        # The checkbox renders with a checked attribute (Checkbox uses checked="true").
        self.assertIn('name="filter-search-exclude"', html)
        self.assertIn('checked', html)

    def test_filter_bar_search_includes_leaves_box_unchecked(self):
        """An INCLUDES search prefills the value but does not check exclude."""
        filter_json = json.dumps(
            {"search": {"value": "Witcher", "modifier": "INCLUDES"}}
        )
        html = str(FilterBar(filter_json=filter_json))
        self.assertIn('value="Witcher"', html)
        # Isolate the exclude checkbox's own markup and assert it is unchecked.
        marker = 'name="filter-search-exclude"'
        start = html.index(marker)
        fragment = html[start - 120 : start + 120]
        self.assertNotIn("checked", fragment)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --with pytest-django pytest tests/test_filter_bars.py -k search -v`
Expected: 3 FAILs — `name="filter-search"` not found in the rendered HTML (the field is not server-rendered yet).

- [ ] **Step 3: Add the `_filter_search_field` helper**

In `common/components/filters.py`, add `Checkbox` to the existing import from `common.components.primitives` (the block starting `from common.components.primitives import (`), keeping the list alphabetised where it already is:

```python
    Checkbox,
```

Then add the helper just above `class _FilterBarBase` (after `_filter_action_row`):

```python
def _filter_search_field(existing: dict) -> Node:
    """The free-text search field: a text input plus an EXCLUDES toggle.

    Shared chrome rendered once at the top of every bar (see
    ``_FilterBarBase.render``). ``filter-bar.ts`` reads ``filter-search`` /
    ``filter-search-exclude`` by name into the search criterion; this is the
    server-rendered source of those controls (formerly built imperatively by
    the deleted ``injectSearchInput``). ``INPUT_CLASS`` is imported here, not at
    module top, because ``games.forms`` imports ``common.components`` — a module
    import would be circular.
    """
    from games.forms import INPUT_CLASS

    value, modifier = _string_from_field(existing.get("search", {}))
    widget = Div(class_="mb-4")[
        Input(
            type="text",
            name="filter-search",
            value=value,
            placeholder="Search…",
            class_=INPUT_CLASS,
        ),
        Checkbox(
            name="filter-search-exclude",
            label="Exclude matches",
            checked=(modifier == "EXCLUDES"),
        ),
    ]
    return _filter_field("Search", widget)
```

- [ ] **Step 4: Wire it into the base bar**

In `_FilterBarBase.render`, insert the search field immediately after the hidden `filter` input inside the `Form`:

```python
                    Form(id_=_FILTER_FORM_ID)[
                        Input(
                            type="hidden",
                            id_=_FILTER_INPUT_ID,
                            name="filter",
                            # NB: attribute values are escaped, so the
                            # raw JSON passes through (no double-escape).
                            value=self.filter_json,
                        ),
                        _filter_search_field(self.existing),
                        *self._body_fields(),
                        _filter_action_row(),
                    ],
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --with pytest-django pytest tests/test_filter_bars.py -k search -v`
Expected: 3 PASS.

- [ ] **Step 6: Run the full filter-bar test file (no regressions)**

Run: `uv run --with pytest-django pytest tests/test_filter_bars.py -v`
Expected: all PASS (existing characterization tests + the 3 new ones).

- [ ] **Step 7: Commit**

```bash
git add common/components/filters.py tests/test_filter_bars.py
git commit -m "feat(filters): server-render free-text search input + exclude toggle (#153)"
```

---

### Task 2: Remove the imperative TypeScript and recompile

Delete `injectSearchInput` and its call; the server now owns the markup and prefill. The `buildFilterJSON` reader stays.

**Files:**
- Modify: `ts/elements/filter-bar.ts` (delete `injectSearchInput`; delete its call in `connectedCallback`)

**Interfaces:**
- Consumes: the server-rendered controls from Task 1 (`filter-search`, `filter-search-exclude`).
- Produces: nothing new; `buildFilterJSON` (unchanged) continues to read those controls.

- [ ] **Step 1: Delete the `injectSearchInput` function**

In `ts/elements/filter-bar.ts`, remove the entire function (the block beginning `function injectSearchInput(form: HTMLElement): void {` through its closing `}` — currently lines 332–372).

- [ ] **Step 2: Delete the call site**

In `connectedCallback`, remove the line:

```typescript
    injectSearchInput(form);
```

- [ ] **Step 3: Confirm no references remain**

Run: `grep -rn injectSearchInput ts/`
Expected: no output.

- [ ] **Step 4: Type-check and recompile**

Run: `make ts-check`
Expected: PASS (no `tsc` errors; no unused-symbol or missing-reference errors).

Run: `make ts`
Expected: recompiles `games/static/js/dist/` cleanly.

- [ ] **Step 5: Commit**

```bash
git add ts/elements/filter-bar.ts
git commit -m "refactor(filters): drop imperative injectSearchInput; search is server-rendered (#153)"
```

---

### Task 3: End-to-end verification

The existing e2e suite already asserts the full search behavior. It must pass unchanged against the server-rendered field; the prefill assertion now exercises the Python render path instead of TS.

**Files:**
- Verify only: `e2e/test_search_filter_e2e.py` (no edits expected)

**Interfaces:**
- Consumes: the compiled `dist/elements/filter-bar.js` from Task 2 and the server-rendered field from Task 1.

- [ ] **Step 1: Run the search-filter e2e file**

Run: `uv run --with pytest-django --with pytest-playwright pytest e2e/test_search_filter_e2e.py -v`
Expected: all PASS —
- `test_search_defaults_to_includes` (input present; empty exclude → INCLUDES),
- `test_search_exclude_emits_excludes_modifier` (checked → EXCLUDES),
- `test_search_exclude_prefills_from_filter_json` (now prefilled server-side),
- `test_excluded_search_term_filters_game_list` (real-app list filter).

If a browser is not installed: `uv run playwright install chromium` first (see `e2e/conftest.py`).

- [ ] **Step 2: Full aggregate check**

Run: `make check`
Expected: lint + format check + mypy + ts-check + tests all PASS.

- [ ] **Step 3: Commit (only if `make check` produced changes, e.g. formatting)**

```bash
git add -A
git commit -m "chore(filters): verification fixups for #153"
```

If `make check` produced no changes, skip this commit.

---

## Self-Review

**Spec coverage:**
- New `_filter_search_field` component (spec §1) → Task 1 Step 3.
- Reuse `Input` + `Checkbox` primitives, `INPUT_CLASS`, deferred import (spec §1) → Task 1 Step 3.
- `mb-4` spacing (spec §1) → Task 1 Step 3.
- Prefill via `_string_from_field`, `checked` when EXCLUDES (spec §1) → Task 1 Step 3 + tests.
- Render wiring in `_FilterBarBase.render` after hidden input (spec §2) → Task 1 Step 4.
- Delete `injectSearchInput` + call; keep `buildFilterJSON`; recompile; grep clean (spec §3) → Task 2.
- New Python unit assertions (spec Testing) → Task 1 Steps 1–6.
- Existing e2e unchanged + `make check` + `make test-e2e` (spec Verification) → Task 3.

No gaps.

**Placeholder scan:** No TBD/TODO/"handle edge cases"/vague steps. All code steps show complete code.

**Type consistency:** `_filter_search_field(existing: dict) -> Node` named identically in the interface block, helper definition, and call site (`_filter_search_field(self.existing)`). Control names `filter-search` / `filter-search-exclude` match the TS reader's selectors verbatim. `_string_from_field` and `_filter_field` used with their existing signatures.
