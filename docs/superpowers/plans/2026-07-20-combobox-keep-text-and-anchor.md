# Combobox anchoring + "keep text unless deleted" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix issue #443 — a filter-shrunk dropdown panel that detaches from its trigger, and a single-select combobox that wipes typed/committed text on focus.

**Architecture:** Two independent fixes in one PR, two commits. (1) `attachMenu`'s `ResizeObserver` observes the menu panel too, so any content-height change re-runs the viewport-aware positioner. (2) The single-select combobox keeps its committed label on focus (select-all, full list) via a `currentQuery()` seam that reports an empty query while the field is untouched; multi-select stops discarding its query on tab-out.

**Tech Stack:** TypeScript custom elements (`ts/elements/`, compiled to `games/static/js/dist/` by `make ts`), vitest (`ts/**/*.test.ts`), pytest-playwright e2e (`e2e/`). All commands run inside the Nix dev shell via `direnv exec .`.

## Global Constraints

- Run every `make` / `pnpm` / `pytest` command through `direnv exec .` (Nix dev shell). In a fresh worktree run `direnv allow .` once first.
- After editing any `.ts`, run `direnv exec . make ts` before any e2e run so `dist/` is fresh (e2e serves compiled output).
- Name variables with complete words (`removeButton`, not `removeBtn`).
- Comments explain intent only; no issue/PR refs except forward TODOs. (Inline `Issue #443` markers below are for plan traceability — keep them terse and only where they explain non-obvious intent.)
- Final gate before done: `direnv exec . make check` green (lint + format-check + mypy + ts-check + vitest + full pytest incl. e2e).
- One PR, exactly two commits: Task 1–2 → commit 1 (anchoring); Task 3–4 → commit 2 (contract).

---

## File structure

- `ts/elements/menu-behavior.ts` — `attachMenu()`; add `observe(menu)` in `open()`. (commit 1)
- `ts/elements/menu-behavior.test.ts` — extend the #355 observe test. (commit 1)
- `e2e/test_search_select_e2e.py` — add an anchoring-regression view + test (commit 1); flip single-select focus assertions + rewrite the multi tab-out test (commit 2).
- `ts/elements/search-select.ts` — `currentQuery()` seam + focus/input/backspace/blur/focusout changes. (commit 2)

No new files; no server-side or Python-model changes.

---

## Task 1: Anchor the menu to its trigger on content-size change

**Files:**
- Modify: `ts/elements/menu-behavior.ts` (in `open()`, ~line 199)
- Test: `ts/elements/menu-behavior.test.ts` (the #355 block, ~72–98)

**Interfaces:**
- Consumes: `attachMenu(host, toggle, menu, options?)` → `MenuController`; the `mount()` helper in the test returns `{ host, menu, controller }`.
- Produces: `open()` now calls `resizeObserver?.observe(menu)` in addition to `observe(toggle)`; `close()`'s single `disconnect()` still drops both.

- [ ] **Step 1: Update the #355 vitest to expect the menu is observed too**

In `ts/elements/menu-behavior.test.ts`, change the test body (currently lines ~86–93). Replace:

```typescript
      const { controller } = mount();
      const toggle = document.querySelector("[data-toggle]") as HTMLElement;
      expect(observe).not.toHaveBeenCalled();
      controller.open();
      expect(observe).toHaveBeenCalledWith(toggle);
      expect(disconnect).not.toHaveBeenCalled();
      controller.close();
      expect(disconnect).toHaveBeenCalledTimes(1);
```

with:

```typescript
      const { menu, controller } = mount();
      const toggle = document.querySelector("[data-toggle]") as HTMLElement;
      expect(observe).not.toHaveBeenCalled();
      controller.open();
      expect(observe).toHaveBeenCalledWith(toggle);
      expect(observe).toHaveBeenCalledWith(menu);
      expect(observe).toHaveBeenCalledTimes(2);
      expect(disconnect).not.toHaveBeenCalled();
      controller.close();
      expect(disconnect).toHaveBeenCalledTimes(1);
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `direnv exec . pnpm vitest run ts/elements/menu-behavior.test.ts`
Expected: FAIL — `observe` was called 1 time (toggle only), so `toHaveBeenCalledWith(menu)` / `toHaveBeenCalledTimes(2)` fail.

- [ ] **Step 3: Observe the menu in `open()`**

In `ts/elements/menu-behavior.ts`, inside `open()`, find:

```typescript
    resizeObserver?.observe(toggle);
```

and change to:

```typescript
    resizeObserver?.observe(toggle);
    // Also observe the panel: filtering shrinks its content (and an async fetch
    // grows it) with no scroll/resize to fire, so a top-flipped panel would keep
    // a stale `top` and detach. reposition() re-anchors and re-flips. Issue #443.
    resizeObserver?.observe(menu);
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `direnv exec . pnpm vitest run ts/elements/menu-behavior.test.ts`
Expected: PASS.

(No commit yet — commit lands at the end of Task 2 with the e2e regression.)

---

## Task 2: End-to-end regression — a filtered top-flipped combobox stays anchored

**Files:**
- Modify: `e2e/test_search_select_e2e.py` (add a view + a `urlpatterns` entry + a test)

**Interfaces:**
- Consumes: the existing module-level `e2e_test_view` pattern, `SearchSelect` from `common.components`, `urlpatterns`, `@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")`.
- Produces: URL `/test-anchor/`; test `test_single_select_panel_stays_anchored_when_filtered`.

- [ ] **Step 1: Add a synthetic page that flips its combobox upward**

In `e2e/test_search_select_e2e.py`, after the `e2e_test_view` function (before `urlpatterns`), add:

```python
def anchor_test_view(request):
    options = [{"value": str(i), "label": f"Option {i:02d}", "data": {}} for i in range(15)]
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Anchor E2E Test</title>
        <link rel="stylesheet" href="/static/base.css">
        <script src="/static/js/htmx.min.js"></script>
        <script type="module" src="/static/js/dist/elements/search-select.js"></script>
        <script type="module" src="/static/js/dist/elements/drop-down.js"></script>
    </head>
    <body>
        <div style="height: 1400px"></div>
        <div style="padding: 8px;">
            {
        SearchSelect(
            name="thing",
            options=options,
            multi_select=False,
            host_dropdown=True,
        )
    }
        </div>
    </body>
    </html>
    """
    return HttpResponse(html)
```

Then add the route to `urlpatterns` (alongside the existing `path("test-search-select/", ...)`):

```python
    path("test-anchor/", anchor_test_view),
```

- [ ] **Step 2: Add the regression test**

At the end of `e2e/test_search_select_e2e.py`, add:

```python
@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_single_select_panel_stays_anchored_when_filtered(live_server, page):
    """Issue #443: a top-flipped combobox panel must stay anchored to its trigger
    as filtering shrinks it — not keep the taller panel's stale top and float up."""
    page.set_viewport_size({"width": 1280, "height": 520})
    page.goto(live_server.url + "/test-anchor/")

    search_input = page.locator(
        'search-select[name="thing"] input[data-search-select-search]'
    )
    panel = page.locator('search-select[name="thing"] [data-search-select-options]')

    # Field sits near the viewport bottom → the panel cannot fit below and flips up.
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    search_input.focus()
    expect(panel).to_be_visible()

    def measure():
        return page.evaluate(
            """() => {
                const input = document.querySelector('search-select[name="thing"] input[data-search-select-search]');
                const panel = document.querySelector('search-select[name="thing"] [data-search-select-options]');
                const ir = input.getBoundingClientRect();
                const pr = panel.getBoundingClientRect();
                return { flippedUp: pr.top < ir.top, gap: Math.abs(pr.bottom - ir.top) };
            }"""
        )

    before = measure()
    assert before["flippedUp"], before
    assert before["gap"] <= 2, before

    # Filter to a single row — the panel shrinks sharply.
    search_input.type("Option 01")
    page.wait_for_timeout(100)

    after = measure()
    # Still anchored: the panel's bottom edge meets the trigger's top edge.
    assert after["gap"] <= 2, after
```

- [ ] **Step 3: Compile TS, then run the regression test**

Run:
```bash
direnv exec . make ts
direnv exec . pytest e2e/test_search_select_e2e.py::test_single_select_panel_stays_anchored_when_filtered -v
```
Expected: PASS (Task 1 already added `observe(menu)`; the panel re-anchors after filtering).

- [ ] **Step 4: Sanity-check that the fix is what makes it pass**

Temporarily comment out the `resizeObserver?.observe(menu);` line in `ts/elements/menu-behavior.ts`, then:
```bash
direnv exec . make ts
direnv exec . pytest e2e/test_search_select_e2e.py::test_single_select_panel_stays_anchored_when_filtered -v
```
Expected: FAIL — after filtering, `after["gap"]` exceeds 2 (panel detached). Restore the line and re-run `make ts` (Step 3 passes again).

- [ ] **Step 5: Commit 1 (anchoring)**

```bash
git add ts/elements/menu-behavior.ts ts/elements/menu-behavior.test.ts e2e/test_search_select_e2e.py
git commit -m "fix(dropdown): re-anchor menu to its trigger on content-size change

The ResizeObserver observed only the toggle, so filtering (or an async fetch)
that changed the menu's own height never repositioned it — a top-flipped panel
kept its stale top and floated away from the trigger. Observe the menu too.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Single-select keeps its committed label on focus

**Files:**
- Modify: `ts/elements/search-select.ts` (`currentQuery` seam; `runFocus`; input/backspace/blur handlers)
- Test: `e2e/test_search_select_e2e.py` (flip the three post-focus assertions)

**Interfaces:**
- Consumes (already in `initWidget` scope): `multi`, `search`, `container._searchSelectDirty`, `container._searchSelectLabel`, `filterRows`, `autoHighlight`, `rebuildFreeTextRow`, `setNoResults`, `fetchFromServer`, `showPanel`.
- Produces: `const currentQuery = (): string` — returns `""` for an untouched single-select (`!multi && !_searchSelectDirty`), else `search.value.trim()`. Used by `runFocus` and `fetchFromServer`.

- [ ] **Step 1: Flip the three e2e focus assertions (they must fail first)**

In `e2e/test_search_select_e2e.py`:

In `test_search_select_backspace_clears_single_select`, change line ~94:
```python
    search_input.focus()
    assert search_input.input_value() == ""
```
to:
```python
    search_input.focus()
    # Focus keeps the committed label (selected), it is not wiped. Issue #443.
    assert search_input.input_value() == "Game A"
```

In `test_search_select_typing_replaces_single_select`, change line ~122:
```python
    search_input.focus()
    assert search_input.input_value() == ""
```
to:
```python
    search_input.focus()
    assert search_input.input_value() == "Game A"
```

In `test_search_select_arrow_and_enter_selects`, change line ~224:
```python
    search_input.focus()
    assert search_input.input_value() == ""
```
to:
```python
    search_input.focus()
    assert search_input.input_value() == "Game A"
```

- [ ] **Step 2: Run the three tests to verify they fail**

Run:
```bash
direnv exec . make ts
direnv exec . pytest e2e/test_search_select_e2e.py -k "backspace_clears_single_select or typing_replaces_single_select or arrow_and_enter_selects" -v
```
Expected: FAIL — current code clears the box on focus, so `input_value()` is `""`, not `"Game A"`.

- [ ] **Step 3: Add the `currentQuery()` seam**

In `ts/elements/search-select.ts`, right after `let hasPrefetched = false;` (~line 127), add:

```typescript
  // An untouched committed single-select shows its label in the box, but the
  // query it represents is empty (the full list should show). Once the user
  // edits (dirty), the box text IS the query. Multi-select has no committed
  // label — its box is always the query. Issue #443.
  const currentQuery = (): string =>
    !multi && !container._searchSelectDirty ? "" : search.value.trim();
```

- [ ] **Step 4: Keep the label on focus (select-all), route reads through `currentQuery`**

Replace the `runFocus` body (~477–501). Change:

```typescript
  const runFocus = () => {
    if (!multi) {
      // Hide the committed label so the box becomes a fresh search field.
      search.value = "";
      container._searchSelectDirty = false;
    }
    if (freeText) {
      rebuildFreeTextRow(search.value.trim());
    } else if (searchUrl) {
      if (prefetch && !hasPrefetched) {
        // Seed the window immediately on first open (not debounced).
        hasPrefetched = true;
        fetchFromServer("");
      } else {
        // Show whatever is already loaded; the server decides no-results.
        filterRows(search.value.trim());
        setNoResults(false);
        autoHighlight(search.value.trim());
      }
    } else {
      setNoResults(filterRows(search.value.trim()) === 0);
      autoHighlight(search.value.trim());
    }
    showPanel();
  };
```

to:

```typescript
  const runFocus = () => {
    if (!multi) {
      // Keep the committed label but select it: the full list shows (currentQuery
      // reports "" until the user edits) and the first keystroke replaces it.
      search.select();
      container._searchSelectDirty = false;
    }
    if (freeText) {
      rebuildFreeTextRow(currentQuery());
    } else if (searchUrl) {
      if (prefetch && !hasPrefetched) {
        // Seed the window immediately on first open (not debounced).
        hasPrefetched = true;
        fetchFromServer("");
      } else {
        // Show whatever is already loaded; the server decides no-results.
        filterRows(currentQuery());
        setNoResults(false);
        autoHighlight(currentQuery());
      }
    } else {
      setNoResults(filterRows(currentQuery()) === 0);
      autoHighlight(currentQuery());
    }
    showPanel();
  };
```

- [ ] **Step 5: Route the async re-filter through `currentQuery`**

In `fetchFromServer`'s `.then` (~420–421), change:

```typescript
        // Re-apply the live query: the box may hold more text than was sent.
        setNoResults(filterRows(search.value.trim()) === 0);
        autoHighlight(search.value.trim());
```

to:

```typescript
        // Re-apply the live query: the box may hold more text than was sent.
        setNoResults(filterRows(currentQuery()) === 0);
        autoHighlight(currentQuery());
```

- [ ] **Step 6: Simplify the input handler (drop the label-prefix string surgery)**

Replace the input listener (~504–516). Change:

```typescript
  search.addEventListener("input", () => {
    clearHighlight();
    if (!multi) {
      if (!container._searchSelectDirty) {
        const label = container._searchSelectLabel || "";
        if (search.value.startsWith(label)) {
          search.value = search.value.slice(label.length);
        }
        container._searchSelectDirty = true;
      }
    }
    runSearch();
  });
```

to:

```typescript
  search.addEventListener("input", () => {
    clearHighlight();
    // The first keystroke replaces the selected label natively; just flip dirty
    // (before runSearch) so currentQuery switches to the real box text.
    if (!multi) container._searchSelectDirty = true;
    runSearch();
  });
```

- [ ] **Step 7: Remove the Backspace special-clear**

In the search `keydown` listener, delete this block (~540–545):

```typescript
    if (!multi && key === "Backspace" && !container._searchSelectDirty) {
      event.preventDefault();
      search.value = "";
      search.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
```

(Backspace now edits normally — it deletes the selected label or a character, fires `input`, sets dirty, re-searches.)

- [ ] **Step 8: Reset dirty in the blur deselect branch**

In the single-select `blur` handler (~519–533), add the dirty reset. Change:

```typescript
        if (container._searchSelectDirty && search.value.trim() === "") {
          // User intentionally cleared the box → deselect.
          pills.innerHTML = "";
          container._searchSelectLabel = "";
          emitChange(null);
        } else {
```

to:

```typescript
        if (container._searchSelectDirty && search.value.trim() === "") {
          // User intentionally cleared the box → deselect. Reset dirty so the
          // next focus reports an empty query (the committed-and-untouched
          // invariant currentQuery relies on).
          pills.innerHTML = "";
          container._searchSelectLabel = "";
          container._searchSelectDirty = false;
          emitChange(null);
        } else {
```

- [ ] **Step 9: Compile and run the flipped tests + the full single-select suite**

Run:
```bash
direnv exec . make ts
direnv exec . pytest e2e/test_search_select_e2e.py -v
```
Expected: PASS for all — the three flipped assertions now see `"Game A"`; `typing_replaces` still ends at `"Game A"` after blur (line ~130); `option_click_selects`, `type_filters_and_highlights`, `arrow_and_enter` (commit `"Game B"`), and the aria tests stay green. The `test_multi_select_clears_query_on_tab_out` test is still the OLD one here and must still pass (multi path is untouched by Task 3) — it is rewritten in Task 4.

(No commit yet — commit 2 lands at the end of Task 4.)

---

## Task 4: Multi-select keeps its query on tab-out

**Files:**
- Modify: `ts/elements/search-select.ts` (the container `focusout` handler)
- Test: `e2e/test_search_select_e2e.py` (rewrite `test_multi_select_clears_query_on_tab_out`)

**Interfaces:**
- Consumes: the container `focusout` handler and its `hidePanel()` call.
- Produces: focusout no longer clears/refilters the multi-select box; the typed query persists.

- [ ] **Step 1: Rewrite the multi tab-out test to expect persistence (must fail first)**

In `e2e/test_search_select_e2e.py`, replace the whole `test_multi_select_clears_query_on_tab_out` function (~354–373) with:

```python
@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_multi_select_keeps_query_on_tab_out(live_server, page):
    """Issue #443: the uncommitted query must persist across tab-out/refocus
    (matching single-select, which now keeps its committed label). Text must not
    disappear unless the user deletes it."""
    multi_search = page.locator("#multi-search")
    banana_row = page.locator('[data-search-select-option][data-value="2"]')

    page.goto(live_server.url + "/test-search-select/")

    multi_search.focus()
    multi_search.type("App")
    # Filtering is active: the non-matching row is hidden while the panel is open.
    expect(banana_row).to_be_hidden()

    page.keyboard.press("Tab")

    # The transient query persists after tabbing out.
    expect(multi_search).to_have_value("App")
    # Re-opening keeps the query applied (list stays filtered).
    multi_search.focus()
    expect(banana_row).to_be_hidden()
```

- [ ] **Step 2: Run it to verify it fails**

Run:
```bash
direnv exec . pytest e2e/test_search_select_e2e.py::test_multi_select_keeps_query_on_tab_out -v
```
Expected: FAIL — current focusout clears the box, so after Tab the value is `""` (not `"App"`).

- [ ] **Step 3: Stop clearing the multi query on focusout**

In `ts/elements/search-select.ts`, the container `focusout` handler (~901–918). Change:

```typescript
  container.addEventListener("focusout", (event) => {
    if (!container.contains(event.relatedTarget as Node)) {
      hidePanel(); // also clears the highlight
      // The search box is a transient query buffer; pills hold the committed
      // values. Drop any uncommitted query on exit so it matches single-select
      // (whose blur handler already clears/restores the box). Reset row
      // visibility without reopening the panel — never call runSearch() here.
      if (multi && search.value !== "") {
        search.value = "";
        if (freeText) {
          rebuildFreeTextRow("");
        } else {
          filterRows("");
          setNoResults(false);
        }
      }
    }
  });
```

to:

```typescript
  container.addEventListener("focusout", (event) => {
    if (!container.contains(event.relatedTarget as Node)) {
      hidePanel(); // also clears the highlight
      // Keep any uncommitted query in the box across tab-out/refocus: the box is
      // the query buffer and text must not vanish unless the user deletes it.
      // Issue #443.
    }
  });
```

- [ ] **Step 4: Compile and run the rewritten test**

Run:
```bash
direnv exec . make ts
direnv exec . pytest e2e/test_search_select_e2e.py::test_multi_select_keeps_query_on_tab_out -v
```
Expected: PASS.

- [ ] **Step 5: Full gate**

Run: `direnv exec . make check`
Expected: PASS — lint, format-check, mypy, ts-check, the full vitest suite, and the full pytest suite (including all of `e2e/`) are green.

- [ ] **Step 6: Commit 2 (contract)**

```bash
git add ts/elements/search-select.ts e2e/test_search_select_e2e.py
git commit -m "feat(combobox): keep typed and committed text unless deleted

Single-select combobox no longer clears its committed label on focus: it keeps
and selects the label (full list still shown, via a currentQuery seam that reads
empty until the user edits), so the first keystroke replaces it and nothing
vanishes without a keystroke. Multi-select likewise keeps its query across
tab-out. Matches standard combobox behavior.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Verification

1. `direnv exec . make check` is green (the CI-equivalent gate).
2. Manual smoke on a running dev server (`direnv exec . make dev`), Add session page:
   - Focus the Device field low on the page → panel flips up. Type to filter → the panel shrinks in place, its bottom edge staying on the field (not floating above).
   - Commit a Device, refocus → the label stays, selected, with the full list shown. Type → replaces the label. Blur without picking a valid option → reverts to the committed label. Delete all → deselects.
   - Add-purchase `games` (multi-select): type a query, Tab away, refocus → the query is still there and the list stays filtered.

## Self-review notes

- **Spec coverage:** Commit 1 (`observe(menu)` + tests) = Tasks 1–2. Commit 2 (`currentQuery`, focus/input/backspace/blur, multi focusout, test churn) = Tasks 3–4. Blur "revert on non-matching partial" is unchanged and already correct — no task needed. Free-text focus branch is routed through `currentQuery()` in Task 3 Step 4 (defensive; no free-text single-select exists today).
- **Type consistency:** `currentQuery` returns `string`; every replaced call site (`filterRows`, `autoHighlight`, `rebuildFreeTextRow`, `setNoResults(filterRows(...))`) already takes/returns the same types as the `search.value.trim()` string it replaces.
