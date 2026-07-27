# Design: responsive list-table widths — phased

> Approved design and implementation contract for this branch.
> Five phases, shipped as separate PRs in dependency order.
> Tracked by **#523**; stage issues get filed as each phase is picked up.
>
> **Status:** Phase 0 shipped (#525), Phase 2 (#531), Phase 3 (#532) — 4b shipped
> with 2d, as planned. **Phase 4a is the only phase left in this epic**, and its
> section is the live contract. **Phase 1 is cut** — its prerequisite role is void
> (see § Phase 4a) and it continues as #544. Shipped sections are kept as the
> record of why, marked as such and corrected where the implementation decided
> otherwise.
>
> Every `file:line` below points at the tree as of #532.

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
(`primitives.py:2283`) but the neighbouring shell (`primitives.py:2312`) carries
an explicit prohibition on `contain` because it would become a containing block
for the `position: fixed` dropdown menus. That prohibition stands: Phase 1, which
would have removed the hazard at the root, is cut (#544), and could not have
removed it entirely anyway.

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
  occluded or clipped by any ancestor stacking context. Adopted in the original
  Phase 1, then cut (#544) once the occlusion proved fixable in CSS.

---

# Phase 0 — greed becomes mobile-only

**Shipped in #525.** **This is the reported bug fix and it ships alone.**

`Column` gains `shrinkable: bool = False`. When set, its header `<th>` and the
row-header `<th>` get `max-md:w-full max-md:max-w-0`; above `md`, nothing.
`Column.class_` stays for genuine per-view sizing.

Call sites drop the literal and state intent: `games/views/session.py:97`,
`games/views/game.py:112`, `games/views/game.py:635`,
`games/views/purchase.py:116`.

### Acceptance

- sessions and purchases at 1217 container: no wrapping, and the name column
  stops hoarding — **not** literally 0 dead space. A capped column still takes
  its proportional share of the table's slack; that residue is #522, and the
  shipped test bounds it at under 10% of the container (measured 69px of 1232px
  on its fixture, against 229px with the allowance reapplied unscoped).
- 390 and 640 unchanged.
- **~1024 is a recorded interim regression, not an oversight.** "Deleting the
  greed fixes both stated requirements" holds at 1217. Between roughly 768 and
  each table's overflow-clears width (sessions 848, games 1016, purchases 1140)
  Phase 0 *introduces* wrapper scroll that the greed used to absorb, while the
  wrapping bug persists there until Phase 2. Measured after Phase 0 shipped, at
  a 1024px viewport (961px container):

  | page | dead space | h-scroll | wrapping | name column |
  |---|---|---|---|---|
  | sessions | 0 | 0 | none | 185px |
  | games | 0 | 49px | none | 298px |
  | purchases | 1px | 174px | TYPE, PRICE | 136px |

  Sessions is already clean at this width. Games gains 49px of scroll that the
  greed used to absorb — the predicted interim cost. Purchases was **already**
  overflowing here before Phase 0 (it fits only from a 1048px container up) and
  the overflow roughly doubles; its TYPE and PRICE columns still wrap, which is
  Phase 2's job. All of this scroll is keyboard-unreachable until the region
  semantics land in Phase 2d, which is why 2a and 2d ship together.
- **`test_table_constraints_hold_at_mobile_and_intermediate_widths`
  (`e2e/test_truncated_text_e2e.py:203`) changes at 768 and the change is
  intended.** Tailwind `max-md` is `@media (width < 48rem)`, so at exactly 768
  the greed is off *and* all columns are visible — peak pressure. Verified on the
  test's own fixture (games list, one long-named row): wrapper overflow goes
  **0 → 132px**. The prior spec's Step-0 criterion 4 ("at 768px … still no
  wrapper scroll") is deliberately repealed; say so in the test. The 390 and 640
  branches stay as they are.
- Component test: `shrinkable=True` emits the `max-md:` classes on header and
  row-header `<th>` and nothing above `md`; `shrinkable=False` emits neither.
  Replaces the literal-string assertions that lived in
  `test_first_column_class_reaches_header_and_body_cell` and
  `test_direct_table_row_keeps_columns_optional`; the shipped block is
  `tests/test_components.py:1809-1874`, three new tests among the two rewritten
  ones. The mobile-only assertion scans `<th>`
  and `<td>` class attributes specifically — a document-wide scan for a bare
  `w-full` can never pass, because `StyledTable`'s own `<table>` carries one
  (`primitives.py:2259`).

---

# Phase 1 — floating panels move to the top layer

**Cut from this epic. Tracked separately as #544.**

It was written as "prerequisite for Phase 4 and for nothing else". That premise
is dead: Phase 4a's occlusion is removed by raising the pinned cell in CSS, which
measures the same 0/24 as top-layer promotion (see § Phase 4a). Nothing else in
this document depends on it.

The audit it was supposed to perform has also already answered its own question,
in the negative: a tooltip-and-dropdown migration could never have been *total*.
`Modal` renders `fixed z-40 inset-0` (`primitives.py:1608`) and `SessionActions`
(`domain.py:389`) embeds one in the actions cell of **every** session row
(`session.py:63`). A fixed, non-top-layer panel therefore survives inside table
cells regardless, so the shell's `transform`/`filter`/`contain`/`backdrop-filter`
prohibition (`primitives.py:2306-2311`) keeps its stated rationale and stays.

What remains is a real but independent argument — one dismissal engine instead of
two, UA-native Esc and light-dismiss, no hand-rolled outside-click — weighed
against a jsdom shim, a UA-stylesheet neutralisation pass on every panel, and the
manual-vs-auto state-ownership question below. That trade belongs to #542, judged
on its own, not to a table-widths epic. Today's panels already escape clipping
via `position: fixed`, guarded by `e2e/test_dropdown_clipping_e2e.py`.

The rest of this section is preserved as the research #542 starts from.

Promote `[data-pop-over-panel]` (and the dropdown panels) into the top layer via
the native popover API, in the shared tooltip controller
(`ts/elements/tooltip-behavior.ts`) and `attachMenu`.

### This phase is not yet an implementation contract

Unlike Phases 0/2/4 it needs decisions made before it can be estimated:

- **`manual` vs `auto`, and state ownership.** Both engines track openness
  themselves — `tooltip-behavior.ts:83,118` (`isOpen` plus `panel.hidden`),
  `menu-behavior.ts:185` (`isOpen = !menu.hidden`). Under `popover="auto"` the UA
  light-dismisses and Esc-closes behind the controller's back: `isOpen` stays
  true, `open()` becomes a permanent no-op, and the per-open scroll/resize
  listeners (`tooltip-behavior.ts:122`) leak. Either adopt `manual` and keep the
  existing dismissal engine, or adopt `auto` and drive state from
  `beforetoggle`/`toggle`. The modes also differ on nesting — under `auto`, a
  tooltip opening inside an open dropdown survives only via DOM-ancestor
  nesting. Pick one explicitly.
- **UA stylesheet overrides.** `[popover]` brings `margin: auto`, border,
  padding, `background-color: canvas`, and `overflow: auto`. The last clips the
  arrow, which deliberately overhangs the panel edge
  (`tooltip-behavior.ts:67` sets `top`/`bottom: -half`), and `tintArrow`
  (`:37`) reads the panel's computed background — `canvas` tints arrows wrong.
  Every panel's classes must neutralise these.
- **jsdom has no popover API — measured, twice.** On the pinned jsdom 29.1.1,
  `showPopover`, `hidePopover` and `togglePopover` are all `undefined`, the
  `popover` IDL property is absent from `HTMLElement`, and `ToggleEvent` is
  undefined. `:popover-open` **does** parse without throwing, so a feature check
  must test `typeof element.showPopover === "function"` — the selector is
  useless as a probe. `pop-over.test.ts`, `menu-behavior.test.ts` and
  `drop-down.controller.test.ts` all drive open/close through `hidden`, so this
  work includes either a popover shim for the vitest environment or a
  capability check with a `hidden` fallback path.

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

Top-layer promotion also relaxes the standing constraint at
`primitives.py:2306-2311` — the "never add `transform`/`filter`/`contain`/
`backdrop-filter` to the shell" rule exists because a `position: fixed` panel can
be captured by an ancestor containing block, and top-layer elements cannot be.

**The audit this section demanded has been done, and the answer is no.** The
migration cannot be total: `Modal` renders `fixed z-40 inset-0`
(`primitives.py:1608`) and `SessionActions` (`domain.py:389`) embeds one in the
actions cell of every session row (`session.py:63`). A fixed, non-top-layer panel
therefore survives inside table cells whatever #544 does, so the
`primitives.py:2309` comment stays and Phase 4a's ban on `filter: drop-shadow`
keeps its stated rationale — `box-shadow` is both cheaper *and* required.

The 18/24 above is also no longer an argument for this work: raising the pinned
cell in CSS scores the same 0/24 (see § Phase 4a).

### Acceptance

- The occlusion probe above: 0/24 with sticky applied.
- `e2e/test_dropdown_clipping_e2e.py` stays green.
- Panels still dismiss, reposition on scroll/resize, and keep their
  `aria-describedby` relationships (ids resolve document-wide, so portaling does
  not break them).
- htmx swaps do not leave orphaned open panels.

---

# Phase 2 — `Column` owns width policy

**Shipped in #531.** Written before implementation; see
`docs/superpowers/plans/2026-07-26-table-widths-phase-2.md` § Decisions made
during implementation for where the shipped code chose differently.

Policy was split: `Column.class_` on the `<th>` plus `NAME_MAX_WIDTH_CLASS`
on the leaf `TruncatedText` (`primitives.py:491`). A new column re-introduces two
authorities. `Column` becomes the single declaration site for `wrap`, the name
cap, and (Phase 3) `priority`.

### 2a — cells do not wrap

`TableTd` set no `white-space`; the row-header `<th>` already carried
`whitespace-nowrap`; the header `<th>` (`_header_cell`, `primitives.py:2066`)
did not. Both gain it **only on data tables** (see the gate below).
`Column.wrap = True` opts a column out.

`TableTd()` gains a nowrap flag; `TableRow` reads the column's `wrap`
**with a bounds guard** — `primitives.py:2204-2215` deliberately raises
the cell-count mismatch in DEBUG only, because "prod degrades to a ragged table
over a 500". Indexing `columns[i]` unguarded converts that documented
degradation into an `IndexError`. (Shipped as `TableTd(nowrap=…)` with the cell
taking the decision, `column_at()` doing the guarded read.)

### 2b — the data-table gate

Nowrap, and everything in Phase 4, apply **only to tables that can scroll**. Of
the 26 `StyledTable` call sites (18 are tests, 8 production):

| call sites | treatment |
|---|---|
| 7 list tables via `paginated_table_content` — session, game, purchase, playevent, device, platform, **statuschange** | full treatment |
| 3 game-detail mini-tables (`game.py:633`, `:665`, `:693`) | full treatment — they scroll, and `game.py:635` is one of the four Phase 0 conversions |
| 4 stats tables (`stats_content.py:84`, `:297`, `:318`, `:333`) | **untouched** |

The stats tables must be excluded on their own merits, not by omission: they are
2-column cards inside `md:grid-cols-2`, and their value cells wrap today by
design — `f"{floatformat(total_spent)} ({floatformat(spent_per_game)}/game)"`
(`stats_content.py:286-287`), the `_count_link` percent strings (`:265`). Nowrap
would convert that wrapping into per-card horizontal scroll inside a `min-w-0`
card, on tables that get no scroll region.

Gate on an explicit `StyledTable` parameter, not on "has a caption" and not on
call path.

### 2c — uncapped first columns

`statuschange.py`, `device.py` and `platform.py` rendered the first cell
as a **bare string**, not `TruncatedText` — no 16rem cap, no fade. They sit in an
already-`whitespace-nowrap` row-header `<th>`, so a long name makes an
arbitrarily wide first column, and in Phase 4 pins it. Route them through
`TruncatedText` so the cap and fade apply uniformly, or the "names fade rather
than hard-cut" requirement holds only on three of seven list pages. (Shipped;
play events needed it too — a `GameLink` has no cap or fade either. The four
call sites are now `statuschange.py:66`, `device.py:69`, `platform.py:70` and
`playevent.py:87`.)

### 2d — the scroll region moves here from Phase 4

Nowrap removes the table's last compressibility. Today, and after Phase 0,
columns in the over-subscribed band compress by *wrapping* — ugly, but every
datum stays on screen. After 2a they slide into the `overflow-x-auto` wrapper
instead, which has no keyboard access, no scroll cue, and on overlay-scrollbar
platforms no visible affordance at all. A 1024px purchases user would go from
"PRICE wraps to two lines" to "PRICE, REFUNDED, CREATED and ACTIONS silently do
not exist" — and if Phase 3 never ships, permanently.

The region semantics in Phase 4b (`role="region"`, `tabindex="0"`, the caption,
`scroll-padding-inline-start`) depend on neither sticky nor priority-plus, so
they ship **here**, in the same PR as 2a. Phase 4b keeps only the sticky-specific
parts. Details of the caption and its `randomid(content=…)` id are unchanged —
see 4b.

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

**Shipped in #532.** The measurement model this section demands was designed
first and is written up in
`docs/superpowers/plans/2026-07-26-table-widths-phase-3.md` § The measurement
model.

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
exactly as good as today. The element must therefore **strip those classes on
mount** before applying its own decision — otherwise the two systems fight. At
widths where the JS decision differs from the CSS one this produces a visible
column-pop on load; decide whether to accept it or to gate the swap on first
measurement. (Shipped differently and better: the fallback rules were rescoped
to `responsive-table:not(:defined)` — `primitives.py:2040-2047` — so they stop
matching the instant the element upgrades and there is nothing to strip. The
element applies its first decision synchronously inside that upgrade, so the two
systems are never both live and there is no frame to pop in.)

### The measurement model is the hard part and was designed before implementation

"Reusing the QuickFilterBar primitives" is honest about 25 lines of width
arithmetic (`ts/elements/priority-plus.ts:8-24`) and misleading about everything
else. The parts that make QuickFilterBar work do not transfer:

- **It measures once at mount** (`quick-filter-bar.ts:36`, whose comment says
  exactly that) because ghost triggers have stable, label-driven widths. Table
  column widths are data-dependent, change with pagination, filtering and htmx
  row swaps, and — decisively — **change when other columns are hidden**, because
  auto layout redistributes. There is no stable per-column width to feed
  `priorityPlusFitCount`.
- What the algorithm needs is each column's **natural (max-content) width**,
  which is unobservable while a `w-full` table is slack-distributing, and is
  literally `0` for any column the server-rendered `max-md` rules have at
  `display: none` — i.e. every hideable column when the page mounts at 390px.
- QuickFilterBar *moves* free-floating nodes between two hosts. A table must
  *hide* the `<th>` plus the `<td>` at one index in every row, in lockstep.
  Cells cannot be reparented.
- Per the rule-placement hazard above, the drop state wants to be a
  `<tbody>`-level rule — but **Tailwind cannot mint `[&_td:nth-child(4)]:hidden`
  at runtime.** This needs a safelisted per-index rule family in `input.css` up
  to some maximum column count, following the existing `@source inline`
  nth-child precedent at `primitives.py:2241`. That maximum is a design
  decision, not an implementation detail. (Shipped as
  `MAX_DATA_TABLE_COLUMNS = 12`, `primitives.py:2032`, enforced by a
  `StyledTable` `ValueError`; the safelist is `common/input.css:21`.)

Design the measurement model — how natural widths are obtained, when they are
invalidated, and what the safelist ceiling is — before estimating this phase.
(Done: measure on the live table under a forced `width: max-content`, inside one
synchronous task; re-measure on every trigger, because cached widths are only
valid inside the breakpoint regime they were taken in; ceiling 12.)

### Rule-placement hazard

`align_rules` stay on `<tbody>` deliberately, "so an htmx-swapped `<tr>` aligns
from the live `<tbody>` it lands in" (`primitives.py:2237-2241`). Anything Phase 3
moves per-cell loses that property, and any future row fragment silently loses
it again. Either keep the drop state as a `<tbody>`-level rule driven by
attributes the element sets, or make row fragments go through the same column
metadata. `ts/session-row.ts:59` survives today only because it
`cloneNode(true)`s the server row. (Shipped as table-level
`[&_tr>*:nth-child(N)]:hidden` classes on the `<table>`, so a swapped `<tr>`
inherits the drop state the same way it inherits alignment.)

### Acceptance

- At 390 / 768 / 1280 on all 10 data tables: no wrapper scroll, and the Name
  column is at least ~150px, without any per-table constant.
- No-JS render matches today's `max-md` behavior, and the mounted element's
  decision replaces it without leaving both systems active.
- Natural widths are recovered correctly when the page mounts at 390px, where
  every hideable column starts at `display: none`.
- Re-measurement happens after pagination, filtering and htmx row swaps.

(An earlier draft also required "toggling a column on beyond the fit budget
drops the next-lowest priority". No phase in this document builds a user column
toggle, so that criterion was unverifiable; it belongs to whichever change
introduces the toggle.)

---

# Phase 4 — pinned first column + accessible scroll region

Only meaningful once Phase 3 exists: priority-plus makes overflow *rare*, this
makes it *navigable* in the cases that remain — a first column wider than the
region on a narrow screen, and later, columns a user deliberately enables beyond
the fit budget.

### 4a — sticky first column

On the first cell of every row of a data table:

```
sticky start-0 z-[2] bg-inherit
```

`start-0`, not `left-0` — the table carries `rtl:text-right`
(`primitives.py:2259`). Under `dir="rtl"` the scroll start edge is the right, and
a physical `left-0` pins to the wrong edge. This is the first logical inset in
the codebase: grepping `start-0`/`end-0`/`inset-inline` across `.py`, `.ts` and
`.css` returns nothing, and the one logical utility in use is a margin
(`ms-0`, `primitives.py:1970`). The recommendation stands on the `rtl:` variant
alone, with no in-repo precedent to lean on.

### The occlusion fix is CSS, not the top layer

A panel that is a DOM descendant of a pinned cell is trapped in that cell's
stacking context, so a later row's pinned cell paints over it. **Raising the
pinned cell while it holds an open panel removes the occlusion completely** — the
same 0/24 the top layer scores, with no engine change. Measured in Chrome 149 on
a synthetic table (sticky first column at `z-[2]`, a `position: fixed` panel in
row 0's pinned cell parked over the rows below, 24 sample points through
`elementFromPoint`), and reproduced independently:

| | occluded |
|---|---|
| sticky, panel in normal flow | 24/24 |
| pinned cell raised while its panel is open | **0/24** |
| same panel promoted to the top layer | 0/24 |

Two controls establish the mechanism. With the pinned cells at `z-index: auto`
and the panel at its real `z-10`, occlusion is still 24/24 — the child's z-index
is scoped inside the cell's context, which is the whole problem. And a fixed
descendant of a sticky-only ancestor stays at viewport coordinates, moving to
cell-relative ones only once the cell gains `filter` — so **`position: sticky`
creates a stacking context but never a containing block**, and no portaling was
ever required.

So the cell carries, alongside the pin:

```
has-[[data-pop-over-panel]:not([hidden])]:z-[3]
has-[[data-menu]:not([hidden])]:z-[3]
```

**`z-[3]`, not something larger.** The occluders are sibling pinned cells at 2,
so 3 is sufficient; anything at or above 10 inverts a different pair. Measured: a
cell raised to `z-[30]` covers an overlapping open dropdown menu (`z-20`,
`custom_elements.py:699`) at 15 of 24 points. The documented strata — popovers
10, dropdown panels 20, modal overlay 40, toasts 50 (`primitives.py:1602-1606`) —
stay intact only if the pinned cell stays beneath them.

**Panels in non-pinned cells need nothing.** A static `<td>` creates no stacking
context, so a menu's own `z-20` already outranks a pinned cell at 2: measured
0/24. (With the menu at `z-index: auto` it is 18/24, so the panels' own z-indexes
are load-bearing and the pin must stay below them.)

This rests on two conventions, each pinned by a test because the rule is silently
wrong if either breaks:

- **A pinned cell's z-index stays below 10.**
- **In-table panels toggle the `hidden` *attribute*,** not a class — true of
  every panel that renders in a table today (tooltips
  `tooltip-behavior.ts:118,129`; menus `menu-behavior.ts:206,225`; delegated
  comboboxes `search-select.ts:187-190`; the inline session-reset modal
  `session-actions.ts:61,66`). The one class-toggling panel is the *standalone*
  SearchSelect (`search-select.ts:223`), which is `absolute z-10` and never
  renders in a table.

### The edge cue appears only when something is behind it

The scroll region gets `container-type: scroll-state`, and the pinned cell's
right-edge **`box-shadow`** lives inside
`@container scroll-state(scrollable: inline-start)`. Verified in Chrome 149: no
shadow at rest, shadow once scrolled, none again on return. Priority-plus makes
most tables fit at most widths, so an unconditional shadow would draw a permanent
seam down every list page for a scroll that is usually not happening. Where the
query is unsupported the shadow never paints and the pin still works — the cue
degrades, the feature does not.

`box-shadow`, never `filter: drop-shadow`: `filter` makes the cell a containing
block for the `position: fixed` panels it hosts. `container-type: scroll-state`
does not — a fixed descendant stays at viewport coordinates under one (measured),
so the region can host the query without tripping the shell's prohibition.

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
- **Phase 1 is not a prerequisite.** An earlier draft made it one, on the
  strength of the occlusion the CSS elevation above removes. (The two probes
  report different totals — 18/24 in § Phase 1 against a real page, 24/24 here
  against a synthetic table whose panel sits entirely over the rows below. They
  measure the same defect on different fixtures; what matters is that both fall
  to 0/24.) Phase 1 survives on its own merits, not this phase's — see #544.

### 4b — accessible scroll region (**shipped with Phase 2d in #531**, specified here)

Written against the pre-#531 tree, where the wrapper was
`Div(class_="relative overflow-x-auto")` with no `role`,
`tabindex` or accessible name, and the tables had no `<caption>` — the
horizontal scroll was unreachable by keyboard, a WCAG 2.1.1 failure that already
existed and that Phases 0 and 2 both make more visible. Nothing in it
depends on sticky or priority-plus, so it lands with 2a; it is written here for
cohesion with the rest of the pinning work.

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

Plus `scroll-padding-inline-start`: without it, tabbing to a control scrolled off
to the right scrolls it flush to the region's start edge, which is exactly where
the pinned cell paints, hiding the focused control and its focus ring. The
pinned column's actual width is per-table and per-page, so "equal to the pinned
width" is not expressible as a static class. Pin the value to the cap constant
(256px + cell padding ≈ 304px) — a safe over-estimate that stays pure CSS —
rather than measuring and writing a custom property. (Shipped as
`md:scroll-ps-[19rem]`, `primitives.py:2277`: from `md` up only, because 19rem
is wider than a phone's scrollport and the browser clamps the reservation into a
meaningless snap position there.)

`tests/test_components.py:2011`
(`test_scroll_and_clip_live_on_separate_elements`) asserts the exact substring
`"relative overflow-x-auto"` on the wrapper — append classes, never prepend.

Accepted trade-offs, stated rather than discovered later: the caption is
announced twice (as the table's name and as the region's), and `tabindex="0"` is
a focus stop even on a table that currently fits.

### Acceptance

- Pinned column stays flush with the region's start edge after `scrollLeft` is
  driven to the end, in both `ltr` and `rtl`.
- Pinned cell's computed `background-color` is non-transparent in header and body
  rows, in **both themes**, and tracks the row `hover:` surface.
- Tooltip flipped downward from the top row: 0/24 occluded points — and an open
  dropdown menu overlapping a pinned cell: 0/24 the other way, so the elevation
  does not trade one occlusion for the other.
- A pinned cell's z-index is below 10, and every in-table panel toggles the
  `hidden` attribute. Both are asserted, not assumed: the elevation is silently
  wrong if either drifts.
- The edge shadow is absent at rest and present once the region is scrolled.
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

`refund_purchase` (`games/views/purchase.py:514`) currently returns row HTML plus
an `hx-swap-oob` template that closes the modal. Its sibling `split_purchase`
(`:574`) returns `204` with `HX-Redirect`.

**Do not copy `split_purchase` verbatim.** It redirects to a bare
`reverse("games:list_purchases")` (`:603`), so refunding row 30 of
`?filter=…&sort=-price&page=3` lands on page 1 of the unfiltered, default-sorted
list.

**And do not reach for `use_custom_redirect` — it cannot express this.** Verified:
`request.session["return_path"]` is written in exactly three places —
`view_game` (`games/views/game.py:745`), `stats_alltime`
(`games/views/general.py:113`) and `stats` (`:128`). **No list view sets it**, and
all three store `request.path` with **no query string**. `use_custom_redirect`
(`general.py:93`) then redirects to whatever stale value is in the session, so a
user who viewed a game detail earlier and then refunds from the purchases list
lands on that game's page; a user who never visited one falls through to the
bare-list redirect this paragraph just condemned. The motivating scenario is
unreachable with this mechanism as it exists.

Carry the origin explicitly instead: put `request.get_full_path()` of the list
into the confirmation modal's form as a hidden field and redirect to it after
validating it as a safe internal URL (`url_has_allowed_host_and_scheme`). That
keeps filter, sort and page without touching session state.

**Pin the response shape.** The modal form keeps `hx_post`
(`purchase.py:477`), so a plain `302` would be answered into the form element —
htmx's default target is the triggering element — and the redirected page would
be swapped into the modal. Either return `204` + `HX-Redirect` (htmx does the
navigation) or de-htmx the form to a plain POST. State which; leaving it implicit
will produce a wrong first implementation.

`split_purchase` losing context the same way is a pre-existing bug worth a
follow-up, and it needs the same hidden-field treatment rather than
`use_custom_redirect`.

Also delete: the now-dead `hx_target="#purchase-row-{id}"` / `hx_swap="outerHTML"`
on `_refund_confirmation_modal` (`purchase.py:478-479`), and the row `id` if nothing
else consumes it.

**`tests/test_middleware_integration.py:74-101` exists to forbid exactly this
change** — it asserts `assertNotIn("HX-Redirect", response)` with the docstring
"without navigating away (preserving URL/query params)". Rewrite it to assert the
new contract (redirect target preserves `return_path`), do not delete it: there
are no refund e2e tests, so it is the only coverage this endpoint has.

The success toast survives — `games/htmx_middleware.py:34` returns early when
`HX-Redirect` is present, so the message renders on the reloaded page.

---

## Follow-up issues (filed)

- **#517** — `use_custom_redirect` redirects to a stale, arbitrary page. Blocks
  any attempt to use it for the refund/split origin problem.
- **#518** — `split_purchase` discards filter/sort/page context on redirect.
  Same hidden-origin-field fix as refund.
- **#519** — Per-row disclosure for columns hidden on narrow viewports.
  DataTables Responsive's child-row pattern; today that data is only reachable
  via the detail page.
- **#520** — Scroll-cue gradients on the region. Lea Verou's
  `background-attachment: local, scroll`, recommended by Roselli; must be
  reconciled with the shell's rounded clip and the pinned column.
- **#521** — No print styles; printing a list page clips off-screen columns.
  Pre-existing, measurably worsened by Phase 2.
- **#522** — The 51px slack residue. Ordinary proportional distribution, not a
  defect; a zero-min-content filler column is the pure-CSS answer if it ever
  matters. (An earlier draft of this document wrongly claimed removing it
  required JS.)

## Implementation order

Phases are numbered by identity, not by sequence. Ship them **0, 2, 3, 1, 4**:

0. Rebase onto `origin/main` before touching anything.
1. ~~**Phase 0**~~ — shipped, #525. `shrinkable`, four call sites, e2e 768 branch
   updated, 1024 interim behavior recorded.
2. ~~**Phase 2**~~ — shipped, #531. `Column` owns wrap + cap, data-table gate,
   uncapped first columns, **and the scroll region (2d)**. 2a and 2d landed
   together: nowrap without a keyboard-reachable region is a net regression.
3. ~~**Phase 3**~~ — shipped, #532. Priority-plus, measurement model designed
   first.
4. ~~**Phase 1**~~ — cut, continues as #544. Its only claimed beneficiary was
   Phase 4, which no longer needs it.
5. **Phase 4** — sticky column (4a), with the CSS elevation in place of the
   top layer; 4b already shipped with 2d. **Next, and last in this epic.**
6. Refund reload — independent; any time after Phase 0.

If the work stalls after Phase 3, the app is in a good state and nothing has
been paid for a beneficiary that never arrived.

Each phase ends on a full `make check` including `e2e/`.

Code comments follow the repo convention: explain non-obvious intent only, no
references to this document, issues or history.
