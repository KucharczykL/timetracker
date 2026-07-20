# Issue #443 — Combobox anchoring + "keep text unless deleted"

## Context

On the **Add session** page the **Device** field is a single-select `<search-select>`
combobox hosted in `<drop-down behavior="inline-combobox">`. Two defects, both in
[issue #443](https://github.com/KucharczykL/timetracker/issues/443):

1. **Panel detaches on filter.** The field sits low on the page, so its panel opens
   *upward* (flipped to the `top` side). Typing to filter shrinks the option list, but
   the panel stays pinned where the taller panel's top edge was — it floats up, detached
   from the trigger, instead of shrinking while staying attached.
2. **Typed text vanishes.** The only way to re-anchor the panel today is to blur and
   refocus, which wipes the typed query. More broadly, the single-select combobox clears
   the committed label on focus — text disappearing without a user keystroke is
   confusing and unlike every other combobox (address bar, GitHub jumper).

Root causes are independent:

- **#1** — `attachMenu`'s `ResizeObserver` observes only the *toggle*, never the *menu*.
  Nothing fires `reposition()` when the menu's own content height changes. A top-resolved
  panel's `top = rect.top - panel.offsetHeight - gap` (`anchored-position.ts:147`)
  depends on height *at open time*; a shrinking panel keeps a stale `top`. A bottom panel
  is immune (`top = rect.bottom`, height-independent).
- **#2** — The single-select combobox contract deliberately clears the label on focus
  (`search-select.ts:477-482`). The maintainer now considers that contract wrong.

The user decided: **one PR, two commits**; the contract change applies to **all**
single-selects and multi-selects for consistency.

## Commit 1 — anchoring fix

**File:** `ts/elements/menu-behavior.ts`, `open()` (~line 187–207).

Add `resizeObserver?.observe(menu)` beside the existing `resizeObserver?.observe(toggle)`
(~line 199). Now any menu content-height change (client-side `filterRows` shrink, async
`renderRows` grow) fires `reposition()`, which re-runs `positionMenu()` → re-anchors and
re-flips against the live height.

**Safety (verified against the code):**
- `close()` (~216) `resizeObserver?.disconnect()` drops *both* targets; `reposition()`
  guards `!menu.hidden` (~160), so any stray post-close callback is a no-op.
- No infinite loop: `positionAnchored` writes `max-height`/`min-width`/`width` (size-
  affecting), so the observer may re-fire *once*. The flip decision uses `scrollHeight`
  (content height, unaffected by the `max-height` cap) and an invariant anchor rect, so
  the same values are re-written; ResizeObserver skips no-change notifications and the
  cycle ends after one pass. No `top`↔`bottom` oscillation — flip inputs are invariant.
- Submenu path (`right-start` → `positionSubmenu`) writes `left/top/maxHeight` similarly
  and settles the same way; observing `menu` is safe there too.

**Tests:**
- Extend the #355 test in `ts/elements/menu-behavior.test.ts` (~72–98): assert `observe`
  is called with **both** the toggle and the menu (call count 2, not 1), and `disconnect`
  on close.
- New e2e regression beside `e2e/test_dropdown_clipping_e2e.py`
  (`test_device_dropdown_flips_up_near_viewport_bottom`, ~73): open the up-flipped Device
  panel, type to filter, assert the panel's `bottom` still meets the trigger's `top`
  (panel stays anchored, not floating).

## Commit 2 — "keep text unless deleted" contract

**File:** `ts/elements/search-select.ts`.

### Core seam: `currentQuery()`

The widget reads `search.value` as the query in several places. Once focus keeps the
committed label in the box, those reads would collapse the list to the single committed
match (including the async `fetchFromServer` re-filter at ~420). Introduce one helper:

```
const currentQuery = (): string =>
  (!multi && !container._searchSelectDirty) ? "" : search.value.trim();
```

An untouched committed single-select reports an empty query (⇒ full list shown while the
label stays visible); once the user types (`_searchSelectDirty` set), it reports the real
text. Route the focus/fetch query reads through `currentQuery()`:
- `runFocus` (~491, 493, 494, 497, 498) — `filterRows`/`autoHighlight` use `currentQuery()`.
- `fetchFromServer` `.then` (~420–421) — the re-filter + `autoHighlight` use `currentQuery()`.

`runSearch` (~452) only runs from the `input` handler (already dirty), so it may keep
`search.value.trim()`, but routing it through `currentQuery()` too is harmless and uniform.
The free-text focus branch (`rebuildFreeTextRow(search.value.trim())`, ~478) should also
use `currentQuery()` — verify first whether any free-text single-select actually exists
(free-text is a filter/multi mode today; if none exists this is defensive only).

### Single-select behavior changes

- **`runFocus` (~477):** remove `search.value = ""`. Keep the committed label, call
  `search.select()` (select-all so a keystroke replaces it), keep
  `_searchSelectDirty = false`, and show the full list via `currentQuery()` (now `""`).
- **`input` handler (~504):** replace the label-prefix-strip block (~507–513) with just
  `if (!multi) container._searchSelectDirty = true;` — the browser already replaces the
  selected label on the first keystroke, so no string surgery is needed; we only need to
  mark dirty so `currentQuery()` switches to the real text.
- **Backspace handler (~540):** remove the `!multi && Backspace && !dirty` special-clear.
  Backspace now edits normally (deletes the selected label, or one char), fires `input`,
  sets dirty, and re-searches — no special case.
- **`blur` handler (~519–533):** logic unchanged, but the deselect branch (~522–527)
  must also set `_searchSelectDirty = false`. Today it clears pills/label/`emitChange`
  but leaves `dirty === true`, which would violate the `currentQuery()` invariant
  ("committed-and-untouched ⇒ `!dirty`"). Guard behavior otherwise unchanged:
  - box `===` committed label → no-op (untouched);
  - box empty (user deleted) → deselect (`emitChange(null)`) + reset dirty;
  - box holds a non-matching partial and no pick was made → revert to committed label.
  The revert is the one *forced* discard: a non-freetext single-select must hold a valid
  value, so an unmatched partial cannot survive blur. This is standard combobox behavior.

- **Ordering constraint:** the replacement input block must set `_searchSelectDirty = true`
  *before* `runSearch()` runs (same slot as the removed strip block), so `currentQuery()`
  already reports the real text on the first keystroke.

### Multi-select behavior change

- **`focusout` handler (~901–918):** remove the query-clearing branch (~908–916); keep
  `hidePanel()`. The typed query now persists across tab-out/refocus (the multi box is a
  query-only buffer — committed values live in pills — so there is no label to fight).

### Unaffected (verified)

- Autofocus block (~934–951): a pre-committed autofocused field has `startedEmpty=false`
  and already skips `runFocus`, keeping its label — matches the new model. An empty add
  form (`startedEmpty=true`) runs `runFocus`, box empty, `currentQuery()==""`, full list.
- `selectOption` (~737), `_searchSelectRefetch` (~770), `_searchSelectClear` (~783):
  each already sets `_searchSelectDirty = false` after committing/clearing, so the next
  focus reports an empty query and shows the full list with the label visible.

### Test churn (exact, `e2e/test_search_select_e2e.py`)

These assert `input_value() == ""` right after `search_input.focus()` on a committed
single-select — each flips to "label stays, selected":
- `test_search_select_backspace_clears_single_select` (~66): the `focus` → `== ""`
  (lines ~93–94, ~108) assertions flip; the Backspace-to-clear step must be re-expressed
  as normal editing (select-all label, Backspace deletes selection → deselect).
- `test_search_select_typing_replaces_single_select` (~114): focus → `== ""` (~122)
  flips; type `X` → `"X"` (~125) still holds (keystroke replaces the selected label);
  blur → `"Game A"` restore (~130) unchanged.
- `test_search_select_arrow_and_enter_selects` (~216): focus → `== ""` (~224) flips.
- `test_search_select_type_filters_and_highlights` (~238), `..._click_commit_clears_highlight`
  (~306), `..._aria_combobox_semantics` (~258): re-check any post-focus empty-box assumption.
- `test_multi_select_clears_query_on_tab_out` (~354): the `to_have_value("")` after tab-out
  (~370) flips to assert the query **persists**; rename to `..._keeps_query_on_tab_out` and
  rewrite the docstring (drop the #119-follow-up "clears" rationale).

Other suites:
- `ts/elements/search-select.*.test.ts`: any assertion that focus clears the value.
- `tests/test_search_select.py`: server-render assertions on the initial box value are
  unaffected (server still renders the committed label; only client focus behavior changes).

## Verification

Run the full gate inside the Nix shell:

```
direnv exec . make check
```

(lint + format-check + mypy + ts-check + vitest + full pytest incl. e2e). Then manual /
e2e confirmation of both defects on the Add session page:

1. Focus Device low on the page → panel flips up. Type to filter → panel stays anchored to
   the trigger (bottom edge meets the field), shrinks in place, does not float.
2. Commit a Device, refocus → label stays, selected, full list shown. Type → replaces.
   Blur without a valid pick → reverts to the committed label. Delete all → deselects.
3. Multi-select (e.g. add-purchase games): type a query, Tab away, refocus → query persists.
