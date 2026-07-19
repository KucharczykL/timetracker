# Typography Token System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a semantic `@theme` typography token layer (`text-type-*`) as the single source of truth for font size/weight/leading, migrate the whole app off scattered raw `text-<size>` utilities, and enforce it with a grep-guard test.

**Architecture:** Ten `--text-type-<role>` tokens are defined in Tailwind v4's `@theme` block in `common/input.css`; each bundles size + weight + line-height (+ tracking) via v4 token modifiers, so one `text-type-<role>` utility carries the whole treatment. Component builders and constants reference these tokens for *size*; color (`text-heading`/`text-body`) and weight-emphasis (`font-*`) stay composed as separate utilities. A test greps components for raw size utilities and fails on new ones.

**Tech Stack:** Django, Python server-side HTML component library (`common/components/`), Tailwind CSS v4.1 (`pnpm tailwindcss`), pytest, vitest.

## Global Constraints

- **Token naming:** every role token is prefixed `text-type-*`. Bare `text-heading`/`text-body` are **color** utilities (Flowbite `--color-*`); a same-named `--text-*` token would resolve to color and silently drop the font-size. Never define an unprefixed size token.
- **Tokens own size/weight/leading/tracking only — never color.** Color utilities (`text-heading`, `text-body`, `text-body-subtle`) stay composed alongside.
- **`font-*` weight utilities remain legal** as composition (button `font-medium`, badge `font-semibold`, serif accents `font-bold`). The guard bans raw *size* utilities only.
- **Tailwind v4 token modifier syntax:** `--text-type-x: <size>;` plus optional `--text-type-x--line-height`, `--text-type-x--font-weight`, `--text-type-x--letter-spacing`. Verified against repo Tailwind v4.1.18.
- **CSS is a build artifact:** after any class/token change run `make css` (regenerates `games/static/base.css`, which is git-ignored) before rendering/measuring.
- **Every commit must pass `make check`** (lint, format-check, typecheck, ts-check, check-icons, test-ts, test).
- **One branch (`feat/typography-token-system`), one PR, one atomic commit per task.**

## The 10 tokens (reference)

| Token | rem / px | line-height | weight | tracking |
|---|---|---|---|---|
| `text-type-title` | 1.875rem / 30 | 2.25rem | 700 | -0.025em |
| `text-type-heading` | 1.5rem / 24 | 2rem | 700 | — |
| `text-type-dialog` | 1.5rem / 24 | 1.5rem | 500 | — |
| `text-type-subheading` | 1.25rem / 20 | 1.75rem | 700 | — |
| `text-type-section` | 1.125rem / 18 | 1.75rem | 600 | — |
| `text-type-body` | 0.875rem / 14 | 1.25rem | 400 (default) | — |
| `text-type-label` | 0.875rem / 14 | 1.25rem | 500 | — |
| `text-type-micro` | 0.75rem / 12 | 1rem | 400 (default) | — |
| `text-type-micro-caps` | 0.75rem / 12 | 1rem | 500 | 0.025em |
| `text-type-input` | 1rem / 16 | 1.5rem | 400 (default) | — |

---

## File Structure

- `common/input.css` — add `@theme` tokens (P0); fix stale `--font-condensed` comment (P3).
- `common/components/primitives.py` — repoint `H1/H2/H3`, `PageHeading`, `DIALOG_TITLE_CLASS`, `MICRO_LABEL_CLASS`, `_LABEL_CLASS`, `_FIELD_ERROR_CLASS`, `_CONTROL_SIZE_CLASS`, `Badge`, `StyledTable`, and raw `text-sm`/`text-xs` sweeps.
- `common/components/*.py` (custom_elements, filters, search_select, quick_filter, date_range_picker, domain) — raw size-utility sweep.
- `common/layout.py` — sweep (navbar playtime `text-xs`, footer); wordmark stays raw + `# type-ok`.
- `games/forms.py` — `INPUT/SELECT/TEXTAREA_CLASS` → `text-type-input`.
- `games/views/stats_content.py` + `common/input.css` `.responsive-table` — legacy table type (P2).
- `tests/test_typography_tokens.py` — **new**, the grep-guard (P3).
- `tests/test_rendered_pages.py`, `tests/test_components.py`, `tests/test_search_select.py` — update the 3 class-string pins.
- `docs/visual-conventions.md` §7 — rewrite as canonical token reference (P3).

---

## Task 1 (P0): Define the `@theme` token layer

**Files:**
- Modify: `common/input.css` (the `@theme` block, ~line 17)
- Test: `tests/test_typography_tokens.py` (create)

**Interfaces:**
- Produces: CSS utilities `text-type-title|heading|dialog|subheading|section|body|label|micro|micro-caps|input`, available after `make css`.

- [ ] **Step 1: Write the failing test** — assert the built CSS contains each generated utility class.

Create `tests/test_typography_tokens.py`:

```python
"""Guards for the typography token system (docs/superpowers/specs/2026-07-19-typography-token-system-design.md)."""
from pathlib import Path

import pytest

BASE_CSS = Path(__file__).resolve().parent.parent / "games" / "static" / "base.css"

TOKENS = [
    "text-type-title", "text-type-heading", "text-type-dialog",
    "text-type-subheading", "text-type-section", "text-type-body",
    "text-type-label", "text-type-micro", "text-type-micro-caps",
    "text-type-input",
]


@pytest.mark.parametrize("token", TOKENS)
def test_token_utility_is_generated(token):
    """Each role token compiles to a real utility class in the built CSS.

    base.css is a build artifact — run `make css` after editing input.css.
    """
    assert BASE_CSS.exists(), "run `make css` first"
    css = BASE_CSS.read_text()
    assert f".{token}" in css, f"{token} missing from base.css — is it used anywhere / defined in @theme?"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make css && direnv exec . uv run --frozen python -m pytest tests/test_typography_tokens.py -q`
Expected: FAIL — tokens not defined, and Tailwind only emits a utility when it is *referenced*, so even after defining them base.css won't contain them until Task 2 uses them. (This test goes green at Task 2; keep it xfail-free by ordering — see Step 3 note.)

- [ ] **Step 3: Add the tokens to `@theme`**

In `common/input.css`, inside the existing `@theme { ... }` block (after the `--font-*` declarations), add:

```css
    /* Typography roles — single source of truth for size/weight/leading.
       Prefixed text-type-* to avoid the text-heading/text-body COLOR
       utilities (Flowbite --color-*); a same-named --text-* token would
       resolve to color and drop the size. Tokens own size/weight/leading/
       tracking only; color + font-* emphasis stay composed. */
    --text-type-title: 1.875rem;
    --text-type-title--line-height: 2.25rem;
    --text-type-title--font-weight: 700;
    --text-type-title--letter-spacing: -0.025em;
    --text-type-heading: 1.5rem;
    --text-type-heading--line-height: 2rem;
    --text-type-heading--font-weight: 700;
    --text-type-dialog: 1.5rem;
    --text-type-dialog--line-height: 1.5rem;
    --text-type-dialog--font-weight: 500;
    --text-type-subheading: 1.25rem;
    --text-type-subheading--line-height: 1.75rem;
    --text-type-subheading--font-weight: 700;
    --text-type-section: 1.125rem;
    --text-type-section--line-height: 1.75rem;
    --text-type-section--font-weight: 600;
    --text-type-body: 0.875rem;
    --text-type-body--line-height: 1.25rem;
    --text-type-label: 0.875rem;
    --text-type-label--line-height: 1.25rem;
    --text-type-label--font-weight: 500;
    --text-type-micro: 0.75rem;
    --text-type-micro--line-height: 1rem;
    --text-type-micro-caps: 0.75rem;
    --text-type-micro-caps--line-height: 1rem;
    --text-type-micro-caps--font-weight: 500;
    --text-type-micro-caps--letter-spacing: 0.025em;
    --text-type-input: 1rem;
    --text-type-input--line-height: 1.5rem;
```

- [ ] **Step 4: Reference every token once so Tailwind emits it**

Tailwind v4 only generates a utility that appears in scanned source. Add a safelist comment file that references each. Create `common/components/_type_safelist.py`:

```python
"""Safelist: forces Tailwind to emit every text-type-* utility even before
all call sites are migrated (Tasks 2-7). Delete individual entries as real
usages replace them; the grep-guard (tests/test_typography_tokens.py) keeps
the set honest. Referenced nowhere at runtime — scanned as source only."""

TYPE_TOKEN_SAFELIST = (
    "text-type-title text-type-heading text-type-dialog text-type-subheading "
    "text-type-section text-type-body text-type-label text-type-micro "
    "text-type-micro-caps text-type-input"
)
```

(Confirm `common/**/*.py` is in Tailwind's content scan — check `common/input.css` `@source` / the Tailwind config. If a config lists sources explicitly, add this path.)

- [ ] **Step 5: Rebuild and run the test**

Run: `make css && direnv exec . uv run --frozen python -m pytest tests/test_typography_tokens.py -q`
Expected: PASS (10 params).

- [ ] **Step 6: Commit**

```bash
git add common/input.css common/components/_type_safelist.py tests/test_typography_tokens.py
git commit -m "feat(type): define text-type-* @theme token layer (P0)"
```

---

## Task 2 (P0): Repoint heading builders + named constants at tokens

**Files:**
- Modify: `common/components/primitives.py` — `H1/H2/H3` (~226-228), `DIALOG_TITLE_CLASS` (~102), `MICRO_LABEL_CLASS` (~97), `_LABEL_CLASS` (~980), `_FIELD_ERROR_CLASS` (~981), `PageHeading` `heading_class` (~1087)
- Test: `tests/test_rendered_pages.py` (fix the `_LABEL_CLASS` pin ~line 255), `tests/test_typography_tokens.py` (add builder assertions)

**Interfaces:**
- Consumes: the `text-type-*` utilities from Task 1.
- Produces: `H1`→`text-type-title`, `H2`→`text-type-heading`, `H3`→`text-type-subheading`, `PageHeading`→`text-type-title`, `DIALOG_TITLE_CLASS` starts `text-type-dialog`, `MICRO_LABEL_CLASS` starts `text-type-micro-caps`, `_LABEL_CLASS` starts `text-type-label`, `_FIELD_ERROR_CLASS` uses `text-type-body`.

- [ ] **Step 1: Write the failing test** — assert builders emit tokens.

Add to `tests/test_typography_tokens.py`:

```python
from common.components import render
from common.components.primitives import (
    H1, H2, H3, DIALOG_TITLE_CLASS, MICRO_LABEL_CLASS,
)


def test_heading_builders_emit_tokens():
    assert "text-type-title" in render(H1["x"])
    assert "text-type-heading" in render(H2["x"])
    assert "text-type-subheading" in render(H3["x"])


def test_named_constants_use_tokens():
    assert DIALOG_TITLE_CLASS.split()[0] == "text-type-dialog"
    assert MICRO_LABEL_CLASS.split()[0] == "text-type-micro-caps"
    # size utility removed from both:
    for raw in ("text-2xl", "text-xs"):
        assert raw not in DIALOG_TITLE_CLASS and raw not in MICRO_LABEL_CLASS
```

- [ ] **Step 2: Run to verify it fails**

Run: `direnv exec . uv run --frozen python -m pytest tests/test_typography_tokens.py -k "builders or constants" -q`
Expected: FAIL — builders still emit `text-3xl`/`text-2xl`.

- [ ] **Step 3: Repoint the builders and constants**

In `common/components/primitives.py`:

```python
H1 = _html_element("h1", default_class="text-type-title mb-2")
H2 = _html_element("h2", default_class="text-type-heading mb-2")
H3 = _html_element("h3", default_class="text-type-subheading mb-2")
```
(Drop `text-3xl/2xl/xl font-bold` — size + weight now live in the token.)

```python
MICRO_LABEL_CLASS = "text-type-micro-caps uppercase"
```
(Token owns 12px/500/tracking; `uppercase` stays composed — it is not a font token property.)

```python
DIALOG_TITLE_CLASS = "text-type-dialog text-heading text-center"
```
(Token owns 24px/500/leading-6; `text-heading` is the color; drop `text-2xl leading-6 font-medium`.)

```python
_LABEL_CLASS = "mb-2.5 text-type-label text-heading"
_FIELD_ERROR_CLASS = "mt-4 mb-1 pl-3 py-2 solid-danger w-full text-type-body rounded-base"
```

In `PageHeading` (`heading_class`, ~1087):
```python
    heading_class = "mb-4 text-type-title leading-none text-heading"
```
(Token owns 30px/700/tracking-tight; keep `leading-none` composed to preserve PageHeading's tight leading, `text-heading` colour; drop `text-3xl font-bold tracking-tight`.)

- [ ] **Step 4: Fix the `_LABEL_CLASS` test pin**

In `tests/test_rendered_pages.py` (~line 255) find the assertion pinning the old `_LABEL_CLASS` string (`mb-2.5 text-sm font-medium text-heading`) and update it to `mb-2.5 text-type-label text-heading`.

- [ ] **Step 5: Rebuild + run full suite**

Run: `make css && direnv exec . uv run --frozen python -m pytest tests/test_typography_tokens.py tests/test_rendered_pages.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add common/components/primitives.py tests/test_rendered_pages.py tests/test_typography_tokens.py
git commit -m "feat(type): repoint heading builders + constants at tokens (P0)"
```

---

## Task 3 (P1): Inputs → `text-type-input` (flat 16px)

**Files:**
- Modify: `games/forms.py` — `INPUT_CLASS` (~41), `SELECT_CLASS` (~53), `TEXTAREA_CLASS` (~58)
- Test: `tests/test_rendered_pages.py` (login input assertion, added in #427)

**Interfaces:**
- Consumes: `text-type-input`.
- Produces: all `PrimitiveWidgetsMixin` fields render `text-type-input` (16px flat).

- [ ] **Step 1: Write/adjust the failing test**

In `tests/test_rendered_pages.py`, the #427 login test asserts `text-base sm:text-sm`. Change it to:
```python
        self.assertRegex(
            html, r'name="username"[^>]*class="[^"]*\btext-type-input\b'
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `direnv exec . uv run --frozen python -m pytest tests/test_rendered_pages.py -k login -q`
Expected: FAIL — input still `text-base sm:text-sm`.

- [ ] **Step 3: Swap the three constants**

In `games/forms.py`, replace the `text-base sm:text-sm` fragment with `text-type-input` in all three, and replace the `# text-base sm:text-sm` comment block (lines ~37-40) with:

```python
# text-type-input owns the 16px flat size — 16px everywhere stops iOS
# Safari auto-zooming focused inputs (#427) and needs no responsive pair.
# text-heading is the colour; placeholder:text-body the placeholder colour.
```
Result e.g. `INPUT_CLASS`:
```python
INPUT_CLASS = (
    "mb-3 bg-neutral-secondary-medium border border-default-medium text-heading "
    "text-type-input rounded-base focus:ring-brand focus:border-brand block w-full "
    f"px-3 py-2.5 shadow-xs placeholder:text-body {_DISABLED_CONTROL}"
)
```
(Apply the same `text-base sm:text-sm` → `text-type-input` swap to `SELECT_CLASS` and `TEXTAREA_CLASS`.)

- [ ] **Step 4: Rebuild + run**

Run: `make css && direnv exec . uv run --frozen python -m pytest tests/test_rendered_pages.py -k login -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/forms.py tests/test_rendered_pages.py
git commit -m "feat(type): inputs use flat text-type-input token (P1, supersedes #427 interim)"
```

---

## Task 4 (P1): Button de-special-case

**Files:**
- Modify: `common/components/primitives.py` — `_CONTROL_SIZE_CLASS` (~381), verify `_CONTROL_BASE_CLASS` (~367) keeps `font-medium`
- Test: `tests/test_components.py` (~line 916, the button CQ pin)

**Interfaces:**
- Consumes: `text-type-body`.
- Produces: buttons render `text-type-body` for size, keep composed `font-medium`; no `@md:text-sm` scaling.

- [ ] **Step 1: Update the failing test**

In `tests/test_components.py` (~916), the assertion pins `px-3 py-2 text-xs` and `@md:px-5 @md:py-2.5 @md:text-sm`. Split it: keep the padding assertions, drop the `text-xs`/`@md:text-sm` size expectations, and add:
```python
    assert "text-type-body" in rendered
    assert "text-xs" not in rendered  # size no longer container-scaled
```
(Preserve whatever padding container-query assertions exist — only the text-size part changes.)

- [ ] **Step 2: Run to verify it fails**

Run: `direnv exec . uv run --frozen python -m pytest tests/test_components.py -k "control or button" -q`
Expected: FAIL.

- [ ] **Step 3: Strip text scaling from `_CONTROL_SIZE_CLASS`**

```python
_CONTROL_SIZE_CLASS = "px-3 py-2 @md:px-5 @md:py-2.5"
```
Add the size token where buttons compose their classes. Find where `_CONTROL_SIZE_CLASS` and `_CONTROL_BASE_CLASS` combine (the `ControlButton` builder) and ensure `text-type-body` is in the class list; `_CONTROL_BASE_CLASS` already carries `font-medium` — leave it. If `_CONTROL_BASE_CLASS` needs the size, add `text-type-body` to it:
```python
_CONTROL_BASE_CLASS = (
    "... existing ... font-medium text-type-body ..."  # keep font-medium; add size token
)
```

- [ ] **Step 4: Rebuild + run**

Run: `make css && direnv exec . uv run --frozen python -m pytest tests/test_components.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/components/primitives.py tests/test_components.py
git commit -m "feat(type): buttons use text-type-body, drop container-query text scaling (P1)"
```

---

## Task 5 (P1): Body/micro raw-size sweep across components

**Files:**
- Modify: `common/components/primitives.py`, `common/components/custom_elements.py`, `common/components/filters.py`, `common/components/search_select.py`, `common/components/quick_filter.py`, `common/components/date_range_picker.py`, `common/components/domain.py`, `common/layout.py`
- Test: `tests/test_search_select.py` (~913, `block text-sm` pin); `tests/test_typography_tokens.py` (guard added in Task 8 will backstop)

**Interfaces:**
- Consumes: `text-type-body`, `text-type-micro`, `text-type-section`.
- Produces: no raw `text-sm`/`text-xs`/`text-lg` size utilities remain in these files except the wordmark (`# type-ok`).

**Sweep rule (apply uniformly):**
- `text-sm` (as a size) → `text-type-body`
- `text-xs` (as a size) → `text-type-micro`
- `text-lg font-semibold` block/section headings (e.g. `TableHeader` caption) → `text-type-section` (drop `text-lg font-semibold`; token owns both)
- Leave `font-*`, `text-heading`/`text-body`/`text-body-subtle` (colors), and non-size `text-*` (e.g. `text-center`, `text-left`) untouched.
- Wordmark in `common/layout.py` (`text-lg sm:text-2xl lg:text-4xl font-alien`) stays raw; append `# type-ok: wordmark brand scale` on that line.

- [ ] **Step 1: Update the failing pin**

In `tests/test_search_select.py` (~913) the assertion pins `class="block text-sm"`. Change `text-sm` → `text-type-body`.

- [ ] **Step 2: Inventory the raw usages (drives the sweep)**

Run: `direnv exec . rg -n "text-(xs|sm|lg|xl|2xl|3xl|4xl)\b" common/components common/layout.py`
Record the list. Each hit is either a size (migrate) or part of a color/other utility (skip — none of the size tokens above are colors, so all `text-<size>` hits migrate except the wordmark).

- [ ] **Step 3: Apply the sweep**

Edit each file per the sweep rule. Representative examples:
- `common/layout.py` navbar playtime `text-xs` → `text-type-micro`; footer `text-xs` → `text-type-micro`; wordmark line gets `# type-ok`.
- `common/components/search_select.py` group header (post-#426 `font-medium uppercase`) size `text-xs` → `text-type-micro`; option rows `text-sm` → `text-type-body`.
- `common/components/filters.py` chip `text-xs font-semibold` → `text-type-micro font-semibold`.
- `common/components/primitives.py` remaining `StyledTable` body `text-sm` → `text-type-body`, `thead` `text-xs` → `text-type-micro`, pagination/toast/`TableHeader` caption per rule.

- [ ] **Step 4: Rebuild + run affected suites**

Run: `make css && direnv exec . uv run --frozen python -m pytest tests/test_search_select.py tests/test_components.py tests/test_quick_filter_bar.py tests/test_navbar_playtime.py tests/test_rendered_pages.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/ tests/test_search_select.py
git commit -m "feat(type): sweep components onto text-type-body/micro/section (P1)"
```

---

## Task 6 (P1): Badge → tokens

**Files:**
- Modify: `common/components/primitives.py` — `Badge` size map (~841-845)
- Test: `tests/test_components.py` (Badge test if present; else add one)

**Interfaces:**
- Consumes: `text-type-micro`, `text-type-body`, `text-type-heading`.
- Produces: Badge sm→`text-type-micro`, base→`text-type-body`, lg→`text-type-heading`, keeps `font-semibold`.

- [ ] **Step 1: Write the failing test**

```python
def test_badge_sizes_use_tokens():
    from common.components import render
    from common.components.primitives import Badge
    assert "text-type-micro" in render(Badge("x", size="sm"))
    assert "text-type-body" in render(Badge("x", size="base"))
    assert "text-type-heading" in render(Badge("x", size="lg"))
    assert "font-semibold" in render(Badge("x"))
```
(Confirm the actual `Badge` signature/size kwarg first; adjust call to match.)

- [ ] **Step 2: Run to verify it fails**

Run: `direnv exec . uv run --frozen python -m pytest tests/test_components.py -k badge -q`
Expected: FAIL.

- [ ] **Step 3: Repoint the Badge size scale**

In the Badge size dict (currently `{"sm": "text-xs px-2 py-0.5", "base": "text-sm ...", "lg": "text-2xl ..."}`), swap the size utilities:
```python
    "sm": "text-type-micro px-2 py-0.5",
    "base": "text-type-body px-2.5 py-0.5",
    "lg": "text-type-heading px-2.5 py-0.5",
```
(Keep the existing padding + the shared `font-semibold`. Match the exact current padding values — only the `text-<size>` token changes.)

- [ ] **Step 4: Rebuild + run**

Run: `make css && direnv exec . uv run --frozen python -m pytest tests/test_components.py -k badge -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/components/primitives.py tests/test_components.py
git commit -m "feat(type): Badge sizes use type tokens, keep font-semibold (P1)"
```

---

## Task 7 (P2): Legacy `.responsive-table` typography

**Files:**
- Modify: `common/input.css` (`.responsive-table thead th` `text-xl`, ~line 220-222), `games/views/stats_content.py` (the `_table()` consumer)
- Test: `tests/test_rendered_pages.py` (stats page render)

**Interfaces:**
- Consumes: `text-type-body`, `text-type-micro`.
- Produces: stats tables render token sizes; no `text-xl`/inherited-16px table type.

- [ ] **Step 1: Write the failing test**

Add a stats-page assertion in `tests/test_rendered_pages.py` that the rendered stats table does not contain `text-xl` header type and does contain a token size (adjust to the actual stats markup):
```python
    def test_stats_table_uses_type_tokens(self):
        html = self.get("games:stats_alltime").content.decode()
        assert "text-type-micro" in html or "text-type-body" in html
```

- [ ] **Step 2: Run to verify it fails**

Run: `direnv exec . uv run --frozen python -m pytest tests/test_rendered_pages.py -k stats -q`
Expected: FAIL.

- [ ] **Step 3: Migrate the table type**

In `common/input.css`, change `.responsive-table thead th { @apply ... text-xl; }` → drop `text-xl` (headers inherit token size from the migrated markup). In `games/views/stats_content.py` `_table()`, add `text-type-micro` to header cells and `text-type-body` to body cells (or, if folding #409, migrate the whole table to `StyledTable` — out of scope here unless #409 is done jointly; the minimal P2 is the type only).

- [ ] **Step 4: Rebuild + run**

Run: `make css && direnv exec . uv run --frozen python -m pytest tests/test_rendered_pages.py -k stats -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/input.css games/views/stats_content.py tests/test_rendered_pages.py
git commit -m "feat(type): migrate legacy stats-table type to tokens (P2)"
```

---

## Task 8 (P3): Grep-guard test + remove safelist

**Files:**
- Modify: `tests/test_typography_tokens.py` (add the guard), delete `common/components/_type_safelist.py`
- Test: itself

**Interfaces:**
- Consumes: the migrated codebase (Tasks 2-7).
- Produces: a test that fails on any new raw `text-<size>` utility in guarded files.

- [ ] **Step 1: Write the guard test**

Add to `tests/test_typography_tokens.py`:

```python
import re

REPO = Path(__file__).resolve().parent.parent
GUARDED = [
    REPO / "common" / "components",
    REPO / "common" / "layout.py",
    REPO / "games" / "forms.py",
]
# Raw font-size utilities (with optional variant prefixes like sm: @md:) —
# the type system owns size via text-type-*. font-* weights stay legal.
RAW_SIZE = re.compile(
    r'(?<![\w-])(?:[a-z@\[\]:.-]+:)?text-(?:xs|sm|base|lg|xl|\dxl|\[[^\]]+\])(?![\w-])'
)


def _py_files():
    for path in GUARDED:
        if path.is_file():
            yield path
        else:
            yield from path.rglob("*.py")


def test_no_raw_size_utilities_in_components():
    offenders = []
    for f in _py_files():
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if "# type-ok" in line:
                continue
            if RAW_SIZE.search(line):
                offenders.append(f"{f.relative_to(REPO)}:{i}: {line.strip()}")
    assert not offenders, "raw size utilities — use text-type-* (or add `# type-ok: reason`):\n" + "\n".join(offenders)
```

- [ ] **Step 2: Run — expect real offenders or clean**

Run: `direnv exec . uv run --frozen python -m pytest tests/test_typography_tokens.py -k raw_size -q`
Expected: FAIL initially, listing any stragglers the sweeps missed (and `text-type-*` must NOT match — the regex excludes it via the trailing `(?![\w-])` since `type` continues the word). Fix each straggler by migrating it or adding `# type-ok: reason`.

- [ ] **Step 3: Delete the safelist**

Every token now has a real usage, so `make css` still emits them. Delete `common/components/_type_safelist.py`. Rebuild and confirm Task 1's generation test still passes.

Run: `git rm common/components/_type_safelist.py && make css && direnv exec . uv run --frozen python -m pytest tests/test_typography_tokens.py -q`
Expected: PASS (all params + guard). If a token vanished from base.css, it has no real consumer — re-check its migration.

- [ ] **Step 4: Commit**

```bash
git add tests/test_typography_tokens.py
git commit -m "test(type): grep-guard against raw size utilities; drop safelist (P3)"
```

---

## Task 9 (P3): Documentation

**Files:**
- Modify: `docs/visual-conventions.md` §7, `common/input.css` (stale `--font-condensed` comment)

- [ ] **Step 1: Fix the stale comment**

In `common/input.css`, the `--font-condensed` `@font-face` block comment says "No current uses". Badge/dense surfaces now use it — change to reflect the real role (dense list surfaces / Badge).

- [ ] **Step 2: Rewrite §7 of `docs/visual-conventions.md`**

Replace the §7 "Type scale" narrative with the canonical token table (the 10 `text-type-*` roles, their px/weight/leading) and the rule: **"Use `text-type-*` for size; compose color (`text-heading`/`text-body`) and weight (`font-*`) separately. Never a raw `text-<size>` in a component — the grep-guard (`tests/test_typography_tokens.py`) enforces it. The wordmark is the one `# type-ok` exception."** Note inputs are 16px flat and cross-link the design spec.

- [ ] **Step 3: Verify docs build/no broken refs + full check**

Run: `make check`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add docs/visual-conventions.md common/input.css
git commit -m "docs(type): canonical §7 token reference; fix font-condensed comment (P3)"
```

---

## Final verification (before PR)

- [ ] `make css && make check` — all green.
- [ ] Visual sweep with Playwright at 375 / 768 / 1440px on login, a list page, an add/edit form, a modal, and stats: computed `font-size`/`font-weight` match the token table; confirm the deliberate shifts only — inputs 16px flat, buttons 14px + medium (dense-table buttons no longer shrink to 12px), PageHeading/H1 leading, dialog leading-6 preserved.
- [ ] Open the PR; body lists the intended visual shifts and links the spec.

---

## Self-review notes (author)

- **Spec coverage:** P0 (Tasks 1-2), P1 inputs/button/sweep/badge (Tasks 3-6), P2 (Task 7), P3 guard+docs (Tasks 8-9). All 10 tokens defined (Task 1) and each given a real consumer by Task 8. ✔
- **Test pins:** `_LABEL_CLASS` (Task 2), button CQ (Task 4), `block text-sm` (Task 5) — each fixed in the task that breaks it. ✔
- **Type consistency:** token names identical across tasks (the 10-token table is the contract). ✔
- **Known risk carried into execution:** dense-table button text 12→14 (Task 4) and desktop input 14→16 (Task 3) are deliberate — verify in the final visual sweep.
