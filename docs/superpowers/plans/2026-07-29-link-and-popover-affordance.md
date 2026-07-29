# Link appearance and popover affordance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every popover advertise itself with an always-visible ⓘ, and give every inline
text link one look owned by a component.

**Architecture:** Two independent PRs sharing one rule — *underline = navigates, ⓘ = there's
more*. PR 1 changes `_popover_html`'s default anatomy and the eight popover call sites. PR 2
introduces a dedicated `--color-fg-link` token, four anchor builders, and an AST guard that
makes bare `A()` calls fail `make check`.

**Spec:** [`docs/superpowers/specs/2026-07-29-link-and-popover-affordance-design.md`](../specs/2026-07-29-link-and-popover-affordance-design.md)
— read it first. It carries the rationale, the measured contrast basis, and the rejected
alternatives. This plan names files, interfaces, test cases, and gotchas; it does not restate
the spec's reasoning.

**Tech stack:** Django 6 + the Python component system (`common/components/`), Tailwind v4 with
Flowbite semantic tokens, pytest + pytest-playwright.

## Global constraints

- Run everything through `make`. Never `direnv exec .`, never raw `uv run` / `pnpm` / `pytest`.
- Iterate on `make check-fast`; **gate on the full `make check` including `e2e/`** before
  declaring a PR done.
- Components own their classes. No styling-at-a-distance, no `input.css` selectors reaching
  into components (`CLAUDE.md`).
- Builders take htpy form: `Builder(class_="x")[children]`. `attributes=` / `children=` kwargs
  raise `TypeError` on the generic and styled builders.
- Complete words in identifiers — `element` not `el`, `removeButton` not `removeBtn`.
- Comments explain intent, never history. No issue or PR numbers in comments.
- Two PRs, in order. PR 1 must land before PR 2 starts: PR 1 removes dotted underlines from
  popover triggers, PR 2 claims the underline for links.

## File structure

**PR 1**

| File | Responsibility |
|---|---|
| `common/components/primitives.py` | `_popover_html` anatomy, the reveal-visibility constant, `symbol_trigger`, `TruncatedText` clip reservation |
| `common/components/domain.py` | `PurchasePrice`, `Duration` ×2 — lose dotted underline, lose hand-rolled glyph classes |
| `common/components/theme.py`, `common/components/custom_elements.py` | declare `symbol_trigger=True` |
| `common/components/settings_kit.py`, `games/views/game.py` | inherit the default glyph |
| `tests/test_components.py`, `e2e/test_truncated_text_e2e.py`, `e2e/test_widgets_e2e.py` | coverage |

**PR 2**

| File | Responsibility |
|---|---|
| `common/input.css` | `--color-fg-link` + hover shade, light and `.dark` |
| `common/components/primitives.py` | `Link`, `IconLink`, `ControlLink`; `TableRow` loses `[&_a]:*` |
| `common/components/__init__.py` | exports |
| `scripts/contrast_audit.py` | the new token in both themes |
| `tests/test_anchor_builders.py` | **new** — the AST guard |
| call sites | `common/layout.py`, `common/components/{domain,quick_filter,custom_elements,settings_kit}.py`, `games/views/{game,purchase,stats_content}.py` |

---

# PR 1 — popover affordance (#589)

### Task 1: Centralize the reveal glyph in `_popover_html`

**Files:**
- Modify: `common/components/primitives.py` — `_popover_html` (~line 326), new module constant
- Test: `tests/test_components.py`

**Interfaces:**
- Produces: `Popover(..., symbol_trigger: bool = False)` and the same parameter on
  `_popover_html`. `symbol_trigger=True` suppresses the glyph.
- Produces: `_POPOVER_REVEAL_CLASS` — the module constant holding the glyph's classes,
  including its visibility. **This is the spec's pare-back lever**: swapping the visibility
  fragment for `hidden [@media(hover:none)]:inline-flex` reverts every call site.
- Consumes: `Icon("info", size="size-[1.1em]")`, already used by `TruncatedText` and
  `Duration(link=…)`.

**Behaviour:** the default anatomy is trigger content + a sibling ⓘ `<button>`, always visible.
`preface` stops being a distinct shape — a preface node and plain content take the same path.

**Three shapes still suppress the glyph, all deliberate:**
1. `tap=False` — the host nests inside a caller's interactive element; a sibling `<button>`
   would be illegal nesting.
2. `symbol_trigger=True` — the trigger is already a symbol.
3. `trigger_disabled` — untouched; keep today's wrapper-span anatomy exactly.

**Decisions this task must land (spec leaves the choice, not the requirement):**
- `selectable_text` is removed. It existed only because the price sat *inside* the button.
- `aria-describedby` moves to the ⓘ button (it is now the control); the content span keeps none.
  `describedby=False` continues to suppress it entirely for `Duration`, whose `sr-only` text
  already carries the value.

- [ ] **Step 1: Write failing tests** in `tests/test_components.py`:
  - default `Popover` renders exactly one `<button data-pop-over-control>` containing the info
    icon, with no `[@media(hover:none)]` fragment in its class
  - `symbol_trigger=True` renders no info icon
  - `tap=False` renders no `<button>` at all
  - `trigger_disabled=True` still renders the `<span role="button" aria-disabled="true">`
    wrapper (regression — this shape is easy to lose in the refactor)
  - the panel id is still referenced by exactly one `aria-describedby`, on the button
- [ ] **Step 2:** `make test ARGS="tests/test_components.py -k popover -x"` — expect failures
- [ ] **Step 3:** Implement in `_popover_html`
- [ ] **Step 4:** `make test ARGS="tests/test_components.py -k popover"` — expect pass
- [ ] **Step 5:** Commit

**Gotcha — check `ts/elements/pop-over.ts` before writing code.** It queries
`[data-pop-over-trigger]` and `[data-pop-over-control]`. Moving the control onto the glyph while
the *host* keeps hover-to-open changes which element carries which attribute. Read the element's
listener wiring and keep the contract intact; if the attributes move, `make ts` and re-run the
popover e2e tests.

---

### Task 2: Migrate the eight popover call sites

**Files:**
- Modify: `common/components/domain.py` — `PurchasePrice` (~277), `Duration` standalone (~410)
  and linked (~418)
- Modify: `games/views/game.py` — `_stat_popover` (~346), release year (~513)
- Modify: `common/components/theme.py` (~84), `common/components/custom_elements.py` (~344)
- Modify: `common/components/settings_kit.py` (~410) — inherits the default, verify only
- Test: `tests/test_components.py`, `tests/test_duration_component.py`

**Per the spec's table:** `theme.py` and `custom_elements.py` pass `symbol_trigger=True`;
everything else inherits the default.

**Removals this task must make:**
- `PurchasePrice`: `wrapped_classes="underline decoration-dotted"` → dropped, plus its
  `selectable_text=True`
- `Duration` standalone: `wrapped_classes="tabular-nums underline decoration-dotted"` → keep
  `tabular-nums`, drop the dotted underline, drop `selectable_text=True`
- `Duration(link=…)`: delete the hand-rolled glyph classes and the `[@media(hover:none)]`
  fragment — Task 1 now owns them. The `preface=A(href=link, …)` stays.

- [ ] **Step 1:** Write failing tests — no rendered popover anywhere emits `decoration-dotted`;
  a linked `Duration` and a standalone `Duration` both emit exactly one info icon; the theme
  toggle and the incomplete badge emit none
- [ ] **Step 2:** `make test ARGS="tests/test_components.py tests/test_duration_component.py -x"`
- [ ] **Step 3:** Apply the call-site changes
- [ ] **Step 4:** `make check-fast`
- [ ] **Step 5:** Commit

**Gotcha:** `PurchasePrice` passes an explicit `id=f"purchase-price-{purchase.pk}"` because
content-hashed ids collide across rows. Do not drop it while editing the call.

---

### Task 3: `TruncatedText` — always-visible info glyph, unconditional clip reservation

**Files:**
- Modify: `common/components/primitives.py` — `TruncatedText` (~550), `_TRUNCATED_REVEAL_CLASS`
- Test: `tests/test_components.py`, `e2e/test_truncated_text_e2e.py`

**The coupled change:** the 24px right padding (`[@media(hover:none)]:pe-6`) that stops text
painting under the button is touch-gated today. For **informative** instances (`tooltip_content`
set) it becomes unconditional. The `ellipsis` variant keeps both its touch gate and its
`data-overflowing` gate — the fade is its desktop affordance.

Add a comment at the branch explaining why the two policies differ, or it reads as an oversight.

- [ ] **Step 1:** Write failing tests — informative instance emits the info icon with no
  `hover:none` fragment and carries unconditional `pe-6`; overflow-only instance still carries
  the `hover:none` fragment on both the button and the padding
- [ ] **Step 2:** `make test ARGS="tests/test_components.py -k truncated -x"`
- [ ] **Step 3:** Implement
- [ ] **Step 4:** `make test ARGS="tests/test_components.py -k truncated"`
- [ ] **Step 5:** Commit

---

### Task 4: E2E coverage and PR 1 gate

**Files:**
- Modify: `e2e/test_widgets_e2e.py` (or a new `e2e/test_popover_affordance_e2e.py` if the
  additions crowd it), `e2e/test_truncated_text_e2e.py`
- Modify: `docs/visual-conventions.md`

**Test cases (desktop viewport — the regression touch-only visibility hid):**
- a price popover shows its ⓘ without hovering
- clicking that ⓘ opens the panel; hovering the value also opens it
- the theme toggle shows no second glyph
- `NavbarLogButton`'s menu item contains **no nested `<button>`** — the `tap=False` guarantee
- an informative truncated name does not paint under its glyph (assert the clip's computed
  `padding-inline-end`, not a screenshot)

**Docs:** add the rule and the pare-back lever to `docs/visual-conventions.md`. The link half of
the section lands in PR 2.

- [ ] **Step 1:** Write the e2e tests
- [ ] **Step 2:** `make test-e2e` (never while `make dev` is running — its watchers rewrite the
  served assets and cause mass phantom failures)
- [ ] **Step 3:** Fix fallout
- [ ] **Step 4:** Full `make check` — the gate
- [ ] **Step 5:** Commit, push, open the PR closing #589

---

# PR 2 — link unification

### Task 5: The `--color-fg-link` token

**Files:**
- Modify: `common/input.css` — `@theme` block (~line 41 area) and the `.dark` block (~line 113)
- Modify: `scripts/contrast_audit.py`
- Test: `tests/test_color_tokens.py` if the guard needs to know the token; otherwise the audit
  script is the check

**Values (spec decision 2):** `purple-700` light, `purple-300` dark, plus a one-step hover shade
(`purple-800` / `purple-200`). Follow the `--color-surface-overlay` precedent exactly: light
value in `@theme`, dark override in `.dark`.

**Audit entries:** the token against page / zebra / hover surfaces in both themes. Expected
worst case **5.78 WCAG / Lc 60**, on the dark hover surface.

**Fallbacks to record in a comment on the token** (one line, no history): the low-chroma pair
`oklch(45% 0.15 295)` / `oklch(80% 0.10 295)`, and underline-only coloring.

- [ ] **Step 1:** Add the token and the audit entries
- [ ] **Step 2:** Run the audit; confirm the new rows pass and no existing row regressed
- [ ] **Step 3:** Commit

---

### Task 6: The four anchor builders

**Files:**
- Modify: `common/components/primitives.py`
- Modify: `common/components/__init__.py` — exports and `__all__`
- Test: `tests/test_components.py`

**Interfaces produced:**
- `Link(href: str, **attributes) -> Node` — owns
  `text-fg-link underline underline-offset-4 decoration-2` + the hover shade. **Must merge
  caller classes, never overwrite**: `GameLink` keeps `font-condensed`, `TruncatedText`'s anchor
  keeps `inline-flex w-full min-w-0 items-center gap-2`. The node layer accumulates `class`
  already — the builder must not stomp it.
- `IconLink(href: str, **attributes) -> Node` — no underline; the hover treatment stats' play
  glyph uses today (`hover:text-heading`).
- `ControlLink(href: str, **attributes) -> Node` — renders a bare `<a>`, adds **nothing**. Its
  entire purpose is declaring "deliberately not a text link" so the guard in Task 8 has
  something to allow. Docstring must say so, or someone will delete it as pointless.

All three take htpy form and the positional attrs slot, like every other builder.

- [ ] **Step 1:** Write failing tests — `Link` emits the token classes; `Link(class_="font-condensed")`
  emits *both*; `IconLink` and `ControlLink` emit no `underline`; `ControlLink` emits no class
  attribute at all when given none
- [ ] **Step 2:** `make test ARGS="tests/test_components.py -k link -x"`
- [ ] **Step 3:** Implement + export
- [ ] **Step 4:** `make test ARGS="tests/test_components.py -k link"`
- [ ] **Step 5:** Commit

---

### Task 7: Migrate every anchor

**Files:**
- `common/components/domain.py` — `GameLink`
- `games/views/stats_content.py` — `_count_link`, `_FILTER_LINK_CLASS`, `_session_link`
  (→ `IconLink`), `_year_nav`'s "All-time stats" (→ real `ControlButton`)
- `common/components/quick_filter.py` — both links (~369, ~374)
- `games/views/purchase.py` — the bare game link (~436)
- `games/views/game.py` — status-change **Edit and Delete** (~413, ~416) → `Link`, *not*
  `IconLink`: they are bare text anchors and `IconLink` would leave them unmarked
- `common/components/primitives.py` — `TruncatedText`'s anchor, pagination (~2086–2108), sort
  header (~2239)
- `common/layout.py` — navbar Home (~262), Stats (~318), brand (~470) → `ControlLink`
- `common/components/custom_elements.py` — `DropdownLinkItem` (~848) → `ControlLink`
- `common/components/settings_kit.py` — rail nav (~193) → `ControlLink`

**Delete, do not migrate:** `NavbarPlaytime`'s `total()` url branch in `common/layout.py`
(~185–190). It is dead — its only caller passes no urls, deliberately, because each `Duration`
owns its own link and a popover trigger may not sit inside an `<a>`. Reviving it via `Link()`
would nest a `<button>` inside an anchor. Delete the branch and the `url` parameters that feed
it.

**Assignment rule:** inline text inside content → `Link`. Icon-only → `IconLink`. Chrome that
owns its own appearance → `ControlLink`. Already a button → `ControlButton`.

- [ ] **Step 1:** Write failing tests in `tests/test_stats_content_links.py` and
  `tests/test_game_detail_links.py` — a game name renders `text-fg-link`; the play glyph renders
  no underline; a pagination link renders no `text-fg-link`
- [ ] **Step 2:** `make test ARGS="tests/test_stats_content_links.py tests/test_game_detail_links.py -x"`
- [ ] **Step 3:** Migrate, file by file, in the order above
- [ ] **Step 4:** `make check-fast`
- [ ] **Step 5:** Commit

---

### Task 8: The AST guard

**Files:**
- Create: `tests/test_anchor_builders.py`

**What it does:** walks the `ast` of every `.py` under `common/` and `games/` and fails on any
call to `A` whose enclosing definition is not one of `Link`, `IconLink`, `ControlLink`,
`ControlButton`.

**Two constraints, both from real call sites — a guard missing either is worthless:**
1. **Do not match on `href=` as a keyword.** `DropdownLinkItem`, `TruncatedText`, and
   `ControlButton` all pass attributes positionally as `A([("href", url), …])`. Flag *any*
   `A(...)` call, however href is passed.
2. **Allowlist by enclosing definition, not by call shape** — the four builders call `A`
   themselves. Reject aliased imports of `A` rather than trying to resolve them.

Include a self-check test (the pattern `tests/test_color_tokens.py` uses) asserting the walk
catches both the keyword form and the positional form on synthetic source, so the guard cannot
silently stop working.

- [ ] **Step 1:** Write the guard and its self-check
- [ ] **Step 2:** `make test ARGS="tests/test_anchor_builders.py -v"` — expect it to name any
  anchor Task 7 missed
- [ ] **Step 3:** Migrate the stragglers until green
- [ ] **Step 4:** `make test ARGS="tests/test_anchor_builders.py"`
- [ ] **Step 5:** Commit

---

### Task 9: Delete the styling-at-a-distance hacks

**Files:**
- Modify: `common/components/primitives.py` — `TableRow` (~1898)
- Modify: `games/views/stats_content.py` — `_session_link` (~60)

**Delete** `[&_a]:underline [&_a]:underline-offset-4 [&_a]:decoration-2` from the row class, and
the `decoration-transparent` opt-out it forces on the play glyph.

Safe **only** because Task 7 covered every anchor that relied on the forced underline — the
adversarial review confirmed the migration list is complete. Do this task after Task 7, never
before.

- [ ] **Step 1:** Write a failing test — a rendered table row's class contains no `[&_a]`
  fragment, and a game name inside a row still renders `underline`
- [ ] **Step 2:** `make test ARGS="tests/test_components.py -k table -x"`
- [ ] **Step 3:** Delete both
- [ ] **Step 4:** `make check-fast`
- [ ] **Step 5:** Commit

---

### Task 10: Docs, follow-up issue, PR 2 gate

**Files:**
- Modify: `docs/visual-conventions.md`

**Docs:** add the link half of the section — the rule, the token, the builder split, and both
pare-back levers. **Amend the existing table row** "Accent / focus / links | `brand` family":
`brand` is accent and focus; links have their own token.

**File the follow-up issue** (`gh issue create`): convert `PriceConverted` from its native
`title=` tooltip to a real `Popover`, which is what finally retires `decoration-dotted` app-wide
and lets the JIT-safelist hack inside `_tooltip_panel` go. Reference this spec.

- [ ] **Step 1:** Update the docs
- [ ] **Step 2:** File the issue
- [ ] **Step 3:** Full `make check` — the gate
- [ ] **Step 4:** Commit, push, open the PR
- [ ] **Step 5:** Screenshot a list page and the stats page in both themes and attach them —
  both dials in this PR are explicitly "we'll see how it looks"

---

## Verification checklist

- [ ] `make check` green (incl. `e2e/`) on each PR before pushing — never a hand-picked subset
- [ ] No popover renders `decoration-dotted` (`PriceConverted` excepted — deferred)
- [ ] `scripts/contrast_audit.py` reports no new failures
- [ ] The AST guard fails when a bare `A(href=…)` is added, in either call form
- [ ] Both pare-back levers are one-line edits: the popover reveal constant, the link token
