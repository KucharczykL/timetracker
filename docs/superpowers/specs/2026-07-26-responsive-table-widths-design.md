# Design: responsive list-table widths — phased

> Approved design and implementation contract for this branch.
> Five phases, shipped as separate PRs in dependency order.

## Context

`bbbd86e` ("reveal truncated text by rendered width") gave the Name column
`w-full max-w-0` on all four list views. Two width authorities now fight in
every list table:

| authority | says |
|---|---|
| `w-full max-w-0` on the Name `<th>` | column contributes 0 preferred width, then absorbs **all** table slack |
| `max-w-[16rem]` on `<truncated-text>` | its content never exceeds 256px |

Measured on the sessions list at a 1217px container: the Name cell is 551px,
the `<truncated-text>` inside it is 256px, the text is 103px. **247px of dead
space**, and DATE is starved to 118px so it wraps to two lines. Games shows the
same 202px hole; purchases wraps TYPE and PRICE.

Stated requirements: **no column may wrap**, and **names must fade rather than
hard-cut**.

Additional stated constraint, which drives the phasing: the column set is
expected to **grow**, and columns may become **user-toggleable**. A design that
only fits today's 4–9 fixed columns is not acceptable.

## Root cause

`max-w-0` is the shrink-enabler — the only way to tell Chrome's auto-table
algorithm a column may go below its content width. `w-full` is the slack-hog.
Separable in intent, not in effect: `max-w-0` alone collapses the column to 69px
(icon only).

Its entire benefit is **22px of avoided horizontal scroll at 390px on rows whose
name reaches the 256px cap**. That is the return on 247px of desktop dead space
and a wrapped date column. The trade was never examined; the prior spec
(`2026-07-21-truncated-text-fade-design.md`, §Step 0) adopted it as an empirical
fallback for a 390px mobile probe and then applied it at every width.

**Deleting the greed above `md` fixes both stated requirements on today's data.**
Measured with no other change — no nowrap:

| | today | greed deleted only |
|---|---|---|
| sessions @1217 | 247px dead, DATE wraps | 0 dead, no wrapping |
| purchases @1217 | TYPE + PRICE wrap | 0 dead, no wrapping |

Purchases is the instructive case: the Name column releases 77px, TYPE and PRICE
absorb it, and both stop wrapping. Nothing else in this document is required to
fix the reported bug. Everything else exists to make the table survive a growing
and user-toggleable column set.

## The 16rem cap changes job

The cap is not "untouched" by this change — it changes role. Today, against a
551px cell, it is a self-limit that *creates* the hole. After the greed is
mobile-only it becomes the column's max-content clamp, which is the right job
for it. Removing it instead would fix the dead space but not the wrapping, and
would let one pathological name set the column width for the whole page: the
prior spec measured 852 names at p50 96px / p90 187px / p95 219px and set the
cap at roughly p96 deliberately.

Note the consequence for Phase 2: with a 10-row page and p90 = 187px, roughly
65% of pages contain at least one name at or near the cap, so hugging buys less
than it appears on a full list — the real win is on filtered views.

## Approaches ruled out, with evidence

Measured on the running app against a copy of the dev database, sweeping
container widths 600→1400px on sessions, games and purchases.

**Container query gating the greed.** Mechanically sound. But a safe threshold
must sit between the width where greedy dead space begins (`O + 304`) and the
width above which non-greedy stops overflowing (`O + N`), where `O` is the other
columns' natural total and `N` the Name column's own natural width capped at
256+48. The window is `304 − N`, which **closes to zero on any page containing
one name at the cap**:

| table | O | widest name clip | N | overflow clears | dead space starts | window |
|---|---|---|---|---|---|---|
| sessions | 672 | ~128 | ~176 | 848 | 976 | 128 |
| games | 711 | 226 | 304 (capped) | 1016 | 1016 | **0** |
| purchases | 999 | 63 | ~140 | 1140 | 1308 | 164 |

Games needs ≤1016, purchases ≥1140 — empty intersection. The window is a
per-*page* property, so it cannot be pinned per table either. Separately,
`container-type` implies `contain`; that is safe on the scroll wrapper
(`primitives.py:2106`) but the neighbouring shell (`primitives.py:2130`) carries
an explicit prohibition on `contain` because it would become a containing block
for the `position: fixed` dropdown menus — a hazard Phase 1 removes at the root.

**Capping the column.** `max-width: 19rem` on the `<th>` holds at 1024 but Chrome
hands the column slack past it at 1100 and 1217. Table-cell max-width is not
honored during slack distribution.

**Shrinking the cell's min-content without `max-w-0`.** `overflow: hidden` on the
`<td>`, `min-width: 0` on the host — both no-ops. Only `width: 0` on the clip
collapses it, which collapses it on desktop too.

**Reflowing rows to cards.** Ruled out on accessibility. Roselli,
*Under-Engineered Responsive Tables*: overriding `display` on table elements
breaks table semantics in some browsers and strands screen-reader users, and
ARIA cannot replicate them (no ARIA equivalent for `headers`).

**Static per-column breakpoint tiers** (`appears_at="lg"`). Values are per-table
guesses that drift silently as columns and data change — and with a
user-toggleable column set they are undefinable in principle.

## Prior art adopted

- **Scroll container, done accessibly** — Roselli's `role="region"` +
  `tabindex="0"` + accessible name + `overflow: auto`.
- **Priority columns** — Tablesaw `data-tablesaw-priority`, DataTables
  `columns.responsivePriority`. A user-toggleable column set *is* a priority
  order, which is why this becomes the core mechanism (Phase 3) rather than a
  follow-up.
- **Frozen first column** — Excel freeze-pane, MUI and AG Grid pinned columns.
- **Top layer for floating UI** — the native popover API, so a panel cannot be
  occluded or clipped by any ancestor stacking context (Phase 1).

---

# Phase 0 — greed becomes mobile-only

**This is the reported bug fix and it ships alone.**

`Column` gains `shrinkable: bool = False`. When set, its header `<th>` and the
row-header `<th>` get `max-md:w-full max-md:max-w-0`; above `md`, nothing.
`Column.class_` stays for genuine per-view sizing.

Call sites drop the literal and state intent: `games/views/session.py:96`,
`games/views/game.py:111`, `games/views/game.py:634`,
`games/views/purchase.py:177`.

### Acceptance

- sessions and purchases at 1217 container: 0 dead space, no wrapping.
- 390 and 640 unchanged.
- **`e2e/test_truncated_text_e2e.py:184` changes at 768 and the change is
  intended.** Tailwind `max-md` is `@media (width < 48rem)`, so at exactly 768
  the greed is off *and* all columns are visible — peak pressure. Verified on the
  test's own fixture (games list, one long-named row): wrapper overflow goes
  **0 → 132px**. The prior spec's Step-0 criterion 4 ("at 768px … still no
  wrapper scroll") is deliberately repealed; say so in the test. The 390 and 640
  branches stay as they are.
- Component test: `shrinkable=True` emits the `max-md:` classes on header and
  row-header `<th>` and nothing above `md`; `shrinkable=False` emits neither.
  Replaces the literal-string assertions at `tests/test_components.py:1770`,
  `:1772` and `:1777` (the last in `test_direct_table_row_keeps_columns_optional`).

---

# Phase 1 — floating panels move to the top layer

**Prerequisite for Phase 4. Independently valuable.**

Promote `[data-pop-over-panel]` (and the dropdown panels) into the top layer via
the native popover API, in the shared tooltip controller
(`ts/elements/tooltip-behavior.ts`) and `attachMenu`.

### Why

`position: sticky` creates a stacking context **unconditionally** — no z-index
value avoids it. The `<truncated-text>` tooltip panel is a DOM descendant of the
Name cell, so once that cell is sticky the panel's `z-10` is scoped *inside* the
cell's context and loses to the sticky cell of any later row. Measured, with a
tooltip flipped downward from row 0 (`ts/elements/anchored-position.ts:121`
flips `side` when there is no room above):

| | panel points occluded by later rows' pinned cells |
|---|---|
| panel in normal flow, sticky applied | **18 / 24** |
| same panel, same position, promoted to top layer | **0 / 24** |
| control: sticky removed | 0 / 24 |

Top-layer promotion also retires the standing fragility at
`primitives.py:2124-2129` — the "never add `transform`/`filter`/`contain`/
`backdrop-filter` to the shell" rule exists only because panels are clippable
today.

### Acceptance

- The occlusion probe above: 0/24 with sticky applied.
- `e2e/test_dropdown_clipping_e2e.py` stays green.
- Panels still dismiss, reposition on scroll/resize, and keep their
  `aria-describedby` relationships (ids resolve document-wide, so portaling does
  not break them).
- htmx swaps do not leave orphaned open panels.

---

# Phase 2 — `Column` owns width policy

Today policy is split: `Column.class_` on the `<th>` plus `NAME_MAX_WIDTH_CLASS`
on the leaf `TruncatedText` (`primitives.py:476`). A new column re-introduces two
authorities. `Column` becomes the single declaration site for `wrap`, the name
cap, and (Phase 3) `priority`.

### 2a — cells do not wrap

`TableTd` sets no `white-space` today; the row-header `<th>` already carries
`whitespace-nowrap`; the header `<th>` (`_header_cell`, `primitives.py:1959`)
does not. Both gain it **only on data tables** (see the gate below).
`Column.wrap = True` opts a column out.

`TableTd()` gains `wrap: bool = False`; `TableRow` passes `columns[i].wrap`
**with a bounds-guarded read** — `primitives.py:2051-2062` deliberately raises
the cell-count mismatch in DEBUG only, because "prod degrades to a ragged table
over a 500". Indexing `columns[i]` unguarded converts that documented
degradation into an `IndexError`.

### 2b — the data-table gate

Nowrap, and everything in Phase 4, apply **only to tables that can scroll**. Of
the 26 `StyledTable` call sites (18 are tests, 8 production):

| call sites | treatment |
|---|---|
| 7 list tables via `paginated_table_content` — session, game, purchase, playevent, device, platform, **statuschange** | full treatment |
| 3 game-detail mini-tables (`game.py:632`, `:662`, `:688`) | full treatment — they scroll, and `game.py:634` is one of the four Phase 0 conversions |
| 4 stats tables (`stats_content.py:84`, `:297`, `:318`, `:333`) | **untouched** |

The stats tables must be excluded on their own merits, not by omission: they are
2-column cards inside `md:grid-cols-2`, and their value cells wrap today by
design — `f"{floatformat(total_spent)} ({floatformat(spent_per_game)}/game)"`
(`stats_content.py:284`), the `_count_link` percent strings (`:270`). Nowrap
would convert that wrapping into per-card horizontal scroll inside a `min-w-0`
card, on tables that get no scroll region.

Gate on an explicit `StyledTable` parameter, not on "has a caption" and not on
call path.

### 2c — uncapped first columns

`statuschange.py:65`, `device.py:67` and `platform.py:67` render the first cell
as a **bare string**, not `TruncatedText` — no 16rem cap, no fade. They sit in an
already-`whitespace-nowrap` row-header `<th>`, so a long name makes an
arbitrarily wide first column, and in Phase 4 pins it. Route them through
`TruncatedText` so the cap and fade apply uniformly, or the "names fade rather
than hard-cut" requirement holds only on three of seven list pages.

### Acceptance

- No cell on any of the 10 data tables renders across more than one line, at
  390 / 768 / 1280. Detect by walking **text nodes** and counting
  `Range.getClientRects()`: a per-cell range count picks up stray whitespace
  nodes, and a `querySelectorAll('*')` leaf walk misses bare text nodes such as
  the sessions DATE cell. Both mislabeled columns during design.
- The playevents `NOTE` column is excluded from that assertion, and has its own
  test asserting it *does* wrap with a realistic multi-line note. A blanket
  no-wrap assertion over playevents is vacuous today and fails the moment
  someone seeds a note.
- Stats cards render byte-identically.

---

# Phase 3 — priority-plus column dropping

**The mechanism that makes a growing / user-toggleable column set work.**

`Column` gains `priority: int`. A `<responsive-table>` element observes the
scroll wrapper and drops the lowest-priority columns until the table fits,
reusing `ts/elements/priority-plus.ts` (`priorityPlusFitCount`,
`priorityPlusTotalWidth`) — the same primitives already driving `QuickFilterBar`.
Continuous, no breakpoints, self-tuning per table and per page.

This **replaces** the two positional rules

```
max-md:[&_th:not(:first-child):not(:last-child)]:hidden   (on <thead>)
max-md:[&_td:not(:first-child):not(:last-child)]:hidden   (on <tbody>)
```

so mobile's two-column view becomes an emergent outcome rather than a hardcoded
breakpoint, and a user column-toggle feature layers on top as an explicit
priority override.

Server-rendered initial state keeps the current `max-md` set, so a no-JS page is
exactly as good as today.

### Rule-placement hazard

`align_rules` stay on `<tbody>` deliberately, "so an htmx-swapped `<tr>` aligns
from the live `<tbody>` it lands in" (`primitives.py:2079`). Anything Phase 3
moves per-cell loses that property, and any future row fragment silently loses
it again. Either keep the drop state as a `<tbody>`-level rule driven by
attributes the element sets, or make row fragments go through the same column
metadata. `ts/session-row.ts:59` survives today only because it
`cloneNode(true)`s the server row.

### Acceptance

- At 390 / 768 / 1280 on all 10 data tables: no wrapper scroll, and the Name
  column is at least ~150px, without any per-table constant.
- Toggling a column on beyond the fit budget drops the next-lowest priority
  rather than overflowing.
- No-JS render matches today's `max-md` behavior.

---

# Phase 4 — pinned first column + accessible scroll region

Only meaningful once Phase 3 exists: priority-plus makes overflow *rare*, this
makes it *navigable* when the user deliberately enables more columns than fit.

### 4a — sticky first column

On the first cell of every row of a data table:

```
sticky start-0 z-[2] bg-inherit
```

`start-0`, not `left-0` — the table carries `rtl:text-right`
(`primitives.py:2100`) and the codebase already uses logical insets
(`date_range_picker.py:277`). Under `dir="rtl"` the scroll start edge is the
right, and a physical `left-0` pins to the wrong edge.

Plus a right-edge **`box-shadow`** so the pinned column reads as a layer. It must
not be `filter: drop-shadow` — `filter` makes the cell a containing block for
`position: fixed`, the same hazard `primitives.py:2124` warns about for the
shell.

Traps, all confirmed or flagged:

- **Background bleed (confirmed by prototype).** Sticky cells are transparent by
  default and the zebra striping lives on `<tr>`
  (`odd:bg-neutral-primary-soft even:bg-neutral-secondary-medium`).
  `bg-inherit` resolves against the parent `<tr>` and follows `hover:` for free.
- **Header background must move (confirmed).** `<thead>` carries
  `bg-neutral-tertiary`, so `bg-inherit` on a header `<th>` resolves to
  transparent. Move it onto the header `<tr>`. This breaks
  `tests/test_rendered_pages.py:543`, which asserts
  `<thead[^>]*bg-neutral-tertiary` and is deliberately anchored on `<thead>` so a
  row's `hover:bg-neutral-tertiary-medium` cannot false-match — update it to
  match the header row with the same anti-false-match property.
- **Collapsed borders do not travel (flagged, must verify).** Preflight sets
  `border-collapse: collapse`, so borders live in the table's collapsed-border
  layer rather than the cell box and may not move with a sticky cell.
  `dark:divide-y` on `<tbody>` puts a `border-bottom` on each non-last `<tr>`,
  visible only in dark mode — expect a possible 1px divider discontinuity down
  the pinned column. A background-transparency guard cannot detect this; it needs
  an explicit dark-mode check.
- **Panels must already be in the top layer** (Phase 1). Without it this phase
  ships the measured 18/24 occlusion.

### 4b — accessible scroll region

The wrapper is `Div(class_="relative overflow-x-auto")` with no `role`,
`tabindex` or accessible name, and the tables have no `<caption>` — the
horizontal scroll is unreachable by keyboard, a live WCAG 2.1.1 failure that
exists today and that Phases 2–3 make more visible.

Data tables get a visually hidden `<caption class="sr-only">` **prepended as the
table's first child** (a `<caption>` must be the first child of `<table>`;
`StyledTable` currently builds `[thead, tbody]`), with an id from
`randomid(content=…)` — **not** bare `randomid()`, which returns `""` when given
neither `seed` nor `content` (`common/components/core.py:510`), yielding an empty
`aria-labelledby` and no accessible name.

```
Div(role="region", tabindex="0", aria_labelledby=caption_id,
    class_="relative overflow-x-auto")
```

Plus `scroll-padding-inline-start` equal to the pinned column's width: without
it, tabbing to a control scrolled off to the right scrolls it flush to the
region's start edge, which is exactly where the pinned cell paints, hiding the
focused control and its focus ring.

`tests/test_components.py:1913` asserts the exact substring
`"relative overflow-x-auto"` on the wrapper — append classes, never prepend.

Accepted trade-offs, stated rather than discovered later: the caption is
announced twice (as the table's name and as the region's), and `tabindex="0"` is
a focus stop even on a table that currently fits.

### Acceptance

- Pinned column stays flush with the region's start edge after `scrollLeft` is
  driven to the end, in both `ltr` and `rtl`.
- Pinned cell's computed `background-color` is non-transparent in header and body
  rows, in **both themes**, and tracks the row `hover:` surface.
- Tooltip flipped downward from the top row: 0/24 occluded points.
- Dark mode: row dividers are continuous across the pinned column.
- Region is focusable, has `role="region"` and a **non-empty** accessible name.
- Keyboard-focusing the last Actions button does not place it under the pinned
  column.
- Measured end state on **purchases and games**, not only sessions — purchases is
  the hard case (`O = 999`; at a 768 viewport that is ~435px of scroll, 62% of a
  screen, with the pinned column taking the leftmost ~140px). If Phase 3 has not
  reduced that to something reasonable, Phase 4 is not ready.

---

# Independent: refund reloads the list

Requested directly, and not a prerequisite for anything once Phase 3 owns column
hiding. Kept because it removes an htmx fragment endpoint, in the direction of
the wider HTMX-removal work.

`refund_purchase` (`games/views/purchase.py:497`) currently returns row HTML plus
an `hx-swap-oob` template that closes the modal. Its sibling `split_purchase`
(`:585`) returns `204` with `HX-Redirect`.

**Do not copy `split_purchase` verbatim.** It redirects to a bare
`reverse("games:list_purchases")`, so refunding row 30 of
`?filter=…&sort=-price&page=3` lands on page 1 of the unfiltered, default-sorted
list. The repo owns the right tool — `use_custom_redirect` /
`request.session["return_path"]` (`games/views/general.py:93`), already used at
`purchase.py:365`, `game.py:302`, `platform.py:127`. Use it, so the reload
returns to the list the user was actually looking at. `split_purchase` losing
context the same way is a pre-existing bug worth a follow-up.

Also delete: the now-dead `hx_target="#purchase-row-{id}"` / `hx_swap="outerHTML"`
on `_refund_confirmation_modal` (`purchase.py:461`), and the row `id` if nothing
else consumes it.

**`tests/test_middleware_integration.py:74-101` exists to forbid exactly this
change** — it asserts `assertNotIn("HX-Redirect", response)` with the docstring
"without navigating away (preserving URL/query params)". Rewrite it to assert the
new contract (redirect target preserves `return_path`), do not delete it: there
are no refund e2e tests, so it is the only coverage this endpoint has.

The success toast survives — `games/htmx_middleware.py:34` returns early when
`HX-Redirect` is present, so the message renders on the reloaded page.

---

## Follow-up issues to file

1. **Per-row disclosure for columns Phase 3 drops.** DataTables Responsive's
   child-row pattern; today that data is only reachable via the detail page.
2. **`split_purchase` loses filter/sort/page context** — same `use_custom_redirect`
   fix as refund.
3. **Scroll-cue gradients on the region.** Lea Verou's
   `background-attachment: local, scroll`, recommended by Roselli; left out here
   because it must be reconciled with the shell's rounded clip and the pinned
   column.
4. **Print styles.** There are none. Nowrap widens tables inside an
   `overflow-x-auto` container, and printing an overflow container clips the
   off-screen columns. Pre-existing, measurably worsened by Phase 2.
5. **The 51px slack residue.** Ordinary proportional distribution, not a defect.
   If it ever matters, a zero-min-content filler column carrying `w-full` is a
   pure-CSS answer — it vanishes when the table overflows and absorbs all slack
   when it does not. (An earlier draft of this document wrongly claimed removing
   the residue required JS.)

## Implementation order

0. Rebase onto `origin/main` before touching anything.
1. Phase 0 — `shrinkable`, four call sites, e2e 768 branch updated.
2. Phase 1 — top-layer panels.
3. Phase 2 — `Column` owns wrap + cap, data-table gate, uncapped first columns.
4. Phase 3 — priority-plus.
5. Phase 4 — sticky + scroll region.
6. Refund reload (independent; may land any time after Phase 0).

Each phase ends on a full `make check` including `e2e/`.

Code comments follow the repo convention: explain non-obvious intent only, no
references to this document, issues or history.
