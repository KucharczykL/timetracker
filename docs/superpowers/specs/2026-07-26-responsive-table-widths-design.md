# Design: responsive list-table widths — pinned name, no wrapping, no dead space

> Approved design and implementation contract for this branch.

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
same 202px hole with no wrapping; purchases wraps TYPE and PRICE.

The reported symptom was the dead space. The stated priority, on clarification,
is that **no column may wrap** and **names must fade rather than hard-cut**.

## What `w-full max-w-0` actually buys

`max-w-0` is the shrink-enabler: it is the only way to tell Chrome's auto-table
algorithm that a column may go below its content width. `w-full` is the
slack-hog. They are separable in intent but not in effect — `max-w-0` alone
collapses the column to 69px (icon only).

Its entire benefit is **22px of avoided horizontal scroll at 390px on rows whose
name reaches the 256px cap**. That is the whole return on 247px of desktop dead
space and a wrapped date column. This trade was never examined; the original
spec (`2026-07-21-truncated-text-fade-design.md`, §Step 0) adopted it as an
empirical fallback for a mobile probe and applied it at every width.

## Approaches ruled out, with evidence

Each was measured on the running app against a copy of the dev database, at
container widths swept 600→1400px on the sessions, games and purchases lists.

**Container query gating the greed.** Mechanically sound — `container-type:
inline-size` on the scroll wrapper caused no scroll issue and took sessions from
551/256 to 234/186 at 1217. But no viable constant exists. A safe threshold must
sit between the width where greedy dead space begins (`O + 304`) and the width
above which non-greedy stops overflowing (`O + N`), where `O` is the other
columns' natural total and `N` the name column's own natural width capped at
256+48. The window is therefore `304 − N`, which **closes to zero on any page
containing one name at the cap**:

| table | O | widest name clip | N | overflow clears | dead space starts | window |
|---|---|---|---|---|---|---|
| sessions | 672 | ~128 | ~176 | 848 | 976 | 128 |
| games | 711 | 226 | 304 (capped) | 1016 | 1016 | **0** |
| purchases | 999 | 63 | ~140 | 1140 | 1308 | 164 |

Games needs ≤1016, purchases needs ≥1140 — empty intersection. Worse, the
window is a per-*page* property: purchases only has one because purchase names
happen to be short today. Also note `container-type` implies `contain`, which
`StyledTable`'s shell explicitly forbids (it would become a containing block for
the `position: fixed` dropdown menus — see `e2e/test_dropdown_clipping_e2e.py`).

**Capping the column.** `max-width: 19rem` on the `<th>` holds at 1024 but
Chrome hands the column slack past it at 1100 and 1217. Table-cell max-width is
not honored during slack distribution.

**Making the cell's min-content shrinkable without `max-w-0`.** `overflow:
hidden` on the `<td>`, `min-width: 0` on the host — both no-ops. Only `width: 0`
on the clip collapses it, which collapses it on desktop too.

**Reflowing rows to cards below a breakpoint.** Ruled out on accessibility.
Adrian Roselli, *Under-Engineered Responsive Tables*: overriding `display` on
table elements breaks table semantics in some browsers and strands screen-reader
users, and ARIA cannot replicate table semantics (no ARIA equivalent for the
`headers` attribute).

**Priority / column-toggle columns** (Tablesaw `data-tablesaw-priority`,
DataTables `columns.responsivePriority`, or the repo's own
`ts/elements/priority-plus.ts` that already drives `QuickFilterBar`). Not ruled
out — deferred. It is the correct heavier tier if horizontal scrolling at
tablet widths proves annoying, but it is not needed once the name column is
pinned. See *Follow-up issues*.

## Prior art adopted

- **Scroll container, done accessibly** — Roselli's `role="region"` +
  `tabindex="0"` + accessible name + `overflow: auto`. His stated position is to
  start here before anything clever.
- **Frozen first column** — Excel freeze-pane; MUI and AG Grid pinned columns;
  `position: sticky; left: 0` on the first cell of each row.

Pinning the name is what makes "let the overflow become scroll" acceptable: the
name never scrolls out of view, so it never has to be squeezed, which retires
the floor, the per-table tiers and the threshold hunt together.

## Decisions (settled)

- **Short names hug their content.** The column tracks the widest name on the
  page, capped at 16rem. Column width varying between pages is accepted — it is
  what the pre-`bbbd86e` behavior did.
- **Greed becomes mobile-only, not deleted.** Below `md` it is beneficial: with
  two columns it hands the leftover to the name (250px vs 204px without it) and
  removes the 16–22px long-name scroll. Above `md` it is pure harm.
- **Mobile keeps hiding middle columns.** Measured the alternative — with all
  columns plus a pinned name at 390px: sessions 768px table (1.15 screens of
  scroll), games 834px (1.33), purchases 955px (1.67) with the pinned name
  squeezed to 104px, permanently occupying 29% of the viewport to show ~5
  characters. Not worth it.
- **Column policy is expressed on `Column`**, not as raw Tailwind in views. Four
  views currently hand-write a load-bearing `class_="w-full max-w-0"`.
- **Names always fade, never hard-cut.** The 256px cap and mask are untouched.

## Design

### 1. Greed becomes mobile-only — `Column(..., shrinkable=True)`

`Column` gains `shrinkable: bool = False`. When set, its header `<th>` and the
row-header `<th>` get `max-md:w-full max-md:max-w-0`; above `md`, nothing.
`Column.class_` stays for genuine per-view sizing.

Call sites drop the literal and state intent: `games/views/session.py:96`,
`games/views/game.py:111`, `games/views/game.py:634`,
`games/views/purchase.py:177`.

Docstring: *the column may shrink below its content width when the table is
crowded; its content is expected to self-clip.*

### 2. Cells do not wrap — `Column(..., wrap=False)`

`TableTd` currently sets no `white-space`; the row-header `<th>` in `TableRow`
already carries `whitespace-nowrap`, so only `<td>`s and header `<th>`s wrap
today. Both get `whitespace-nowrap` by default.

`Column.wrap = True` opts a column out, for genuinely free text. The only
current consumer is the playevents `NOTE` column. `TableRow(data)` called
without `columns` defaults to nowrap.

`TableTd()` gains a `wrap: bool = False` parameter; `TableRow` passes
`columns[i].wrap`.

### 3. Sticky first column

On every row's first cell (`<th scope="row">` in the body, first `<th>` in the
head):

```
sticky left-0 z-[2] bg-inherit
```

plus a subtle right-edge `box-shadow` on the pinned cell so it reads as a layer
over the scrolling content rather than a seam — the AG Grid / MUI pinned-column
convention.

Two traps, both confirmed by prototype:

- **Background bleed.** Sticky cells are transparent by default and the zebra
  striping lives on `<tr>` (`odd:bg-neutral-primary-soft
  even:bg-neutral-secondary-medium`), so scrolled content shows through the
  pinned column. `bg-inherit` on the sticky cell resolves against the parent
  `<tr>`, which works for body rows and follows the `hover:` state for free.
- **Header background must move.** `<thead>` carries `bg-neutral-tertiary`, so
  `bg-inherit` on a header `<th>` resolves against `<tr>` — transparent. Move
  the background from `Thead(class_=…)` onto the header `<tr>`. This also aligns
  with the repo's rule that elements carry their own classes.

`position: sticky` does **not** create a containing block for `position: fixed`,
so the dropdown-clipping constraint on the shell is unaffected. The `z-2` does
create a stacking context; the popover panels use `z-10` in the same context and
therefore still paint above the pinned column. This must be asserted, not
assumed — see *Verification*.

### 4. Accessible scroll region

The wrapper is currently `Div(class_="relative overflow-x-auto")` with no
`role`, no `tabindex` and no accessible name, and the tables have no
`<caption>`. The horizontal scroll is unreachable by keyboard — a live WCAG
2.1.1 failure, independent of this work.

`StyledTable` gains an **optional** `caption: str = ""`. When supplied it
renders a visually hidden `<caption class="sr-only">` with a `randomid()` id,
and the wrapper becomes:

```
Div(role="region", tabindex="0", aria_labelledby=caption_id,
    class_="relative overflow-x-auto")
```

Without a caption the wrapper stays exactly as today. This mirrors Roselli's own
scoping — his CSS ties `overflow: auto` to
`[role="region"][aria-labelledby][tabindex]` so a region never behaves like one
unless it is properly labeled — and it keeps the change targeted: `StyledTable`
has 27 call sites, but most are the headerless key-value stats blocks in
`games/views/stats_content.py`, which are small, non-scrolling, and need no
region. The six scrolling list tables get captions, threaded through
`paginated_table_content` (7 call sites).

Plus a focus outline on the region. Per Roselli, do not replace native
scrollbars with custom ones. A scroll-cue gradient on the wrapper is **not** in
scope — it risks fighting the shell's rounded clip, and the pinned column's own
edge shadow (§3) already signals that content continues; see *Follow-up issues*.

The caption is the accessible name rather than the page `<h1>` so it travels
with the table through htmx fragment swaps.

The `tabindex="0"` is static, so a captioned table that happens to fit is still
a focus stop. That is Roselli's own trade and is accepted here; making it
conditional would require JS measuring overflow on every resize.

### 5. Mobile column hiding stops being positional

Replace the two positional descendant selectors

```
max-md:[&_th:not(:first-child):not(:last-child)]:hidden   (on <thead>)
max-md:[&_td:not(:first-child):not(:last-child)]:hidden   (on <tbody>)
```

with `max-md:hidden` stamped by `StyledTable`/`TableRow` on the cells whose
index is neither first nor last. Same behavior; removes a selector that reaches
across the DOM to style cells it does not own, which CLAUDE.md prohibits.

**Prerequisite:** `games/views/purchase.py:510` renders a swapped row via
`TableRow(data=row_data)` with no `columns`, so per-cell stamping would drop the
hiding on a refunded row. Extract the purchase column list (currently inline at
`purchase.py:177`) into one shared definition and pass it at both call sites.

The `align_rules` nth-child selectors on `<tbody>` stay as they are: they are
deliberately table-level so an htmx-swapped `<tr>` aligns from the live
`<tbody>` it lands in.

## Verified end state

Sessions list, with all five changes applied:

| viewport | container | cols | NAME | text | dead | h-scroll | wrapping |
|---|---|---|---|---|---|---|---|
| 390 | 358 | 2 | 250 | fills cell | 0 | 0 | none |
| 820 | 757 | 6 | 280 | 256 | 0 | 188 (name pinned) | none |
| 1280 | 1217 | 6 | 234 | 186 | 0 | 0 | none |
| 1280, all names at cap | 1217 | 6 | 355 | 256 | 51 | 0 | none |

The 390 row is today's behavior, preserved by keeping greed below `md`; the 820
and 1280 rows were measured with the desktop half of the change applied. Rows
were measured on the sessions list.

Today at 1280: NAME 551, text 256, 247px dead, DATE wrapped.

The 51px worst-case residue is ordinary auto-layout slack distribution across
six columns, not the defect — every column receives a proportional share.

## Verification

- **New e2e, all list pages** (sessions, games, purchases, playevents, devices,
  platforms) at 390 / 768 / 1280:
  - no text node in any cell renders across more than one line. Detect by
    walking text nodes and counting `Range.getClientRects()` — a per-cell range
    count picks up stray whitespace nodes and a `querySelectorAll('*')` leaf walk
    misses bare text nodes such as the sessions DATE cell. Both mislabeled
    columns during design.
  - the name column's left edge stays flush with the scroll region's left edge
    after `scrollLeft` is driven to the end (pinning holds).
  - the pinned cell's computed `background-color` is not transparent (bleed
    guard), in both the header row and body rows, and it still tracks the row's
    `hover:` surface.
- **New e2e, stacking:** with the region scrolled right, open a device dropdown
  and a name tooltip; assert each paints above the pinned column.
- **New e2e, a11y:** the scroll region is focusable, has `role="region"` and a
  non-empty accessible name.
- **Existing** `test_table_constraints_hold_at_mobile_and_intermediate_widths`
  must stay green **unmodified** — mobile behavior is deliberately unchanged.
- **Component tests:** `Column(shrinkable=True)` emits the `max-md:` classes on
  header and row-header `<th>` and nothing above `md`; `shrinkable=False` emits
  neither; `wrap=True` suppresses `whitespace-nowrap` on that column's `<td>`s.
  Replaces the literal-string assertions at `tests/test_components.py:1770`.
- Full `make check`, including `e2e/`.

## Not doing

- **The 51px worst-case residue.** Removing it needs either JS measurement or a
  scroll band; neither is justified for 51px.
- **Priority / column-toggle columns.** Deferred; see below.
- **Per-row disclosure of hidden columns.** Dropped columns go nowhere today,
  below `md`; unchanged here.

## Follow-up issues to file

1. **Priority-plus table columns.** Apply the existing
   `ts/elements/priority-plus.ts` primitives (`priorityPlusFitCount`,
   `priorityPlusTotalWidth`), already driving `QuickFilterBar`, to table columns:
   `Column(..., priority=N)` plus a ResizeObserver that drops the lowest-priority
   columns until the table fits. Continuous, no breakpoints, self-tuning per
   table and per page. Worth doing if tablet-width horizontal scrolling proves
   annoying in practice.
2. **Per-row disclosure for columns hidden on mobile.** DataTables Responsive's
   child-row pattern — currently that data is only reachable via the detail page.
3. **Free-text columns should truncate, not wrap.** The playevents `NOTE` column
   is the one `wrap=True` consumer; giving it `TruncatedText` would let every
   column be nowrap and remove the opt-out.
4. **Scroll-cue gradients on the table scroll region.** Lea Verou's
   `background-attachment: local, scroll` technique, as recommended by Roselli
   for browsers that hide scrollbars. Left out here because it has to be
   reconciled with the shell's rounded clip and the pinned column.

## Implementation order

0. Rebase this branch onto `origin/main` before touching anything.
1. `Column.wrap` + nowrap on `TableTd`/header cells.
2. `Column.shrinkable` + the four view call sites.
3. Sticky first column, header background move, bleed and stacking guards.
4. Accessible scroll region + caption + scroll shadows.
5. Shared purchase column definition, then per-cell `max-md:hidden`.
6. Tests, then full `make check`.

Code comments follow the repo convention: explain non-obvious intent only, no
references to this document, issues or history.
