# Table Widths Phase 3 — priority-plus column dropping

**Goal:** Columns drop by priority until the table fits, continuously and
without breakpoints, so the mobile two-column view becomes an emergent outcome
and the column set can grow (or become user-toggleable) without re-tuning
per-table constants.

**Design:** `docs/superpowers/specs/2026-07-26-responsive-table-widths-design.md`
§ Phase 3. **Tracked by** #523. **Needs** Phase 2 (#531, shipped).

**Architecture:** a `<responsive-table>` custom element wrapping each data
table's scroll region. `Column` gains `priority`; the header `<th>` carries it
as `data-priority`. The element measures each column's natural width, computes
the set that fits, and expresses the decision as table-level
`[&_tr>*:nth-child(N)]:hidden` classes.

---

## The measurement model (designed first, per the spec)

The spec flags four problems the QuickFilterBar precedent does not solve. One
decision each:

**1. Natural widths are measured on the live table, inside one task.** A
column's natural (max-content) width is unobservable in the steady state: the
table is being slack-distributed by `w-full`, and any column the no-JS
fallback has hidden measures 0. On (re)measure the element lifts its own drop
classes, forces `width: max-content` on the live table, reads each header
cell's width (in table layout the header cell's resolved width *is* the
column's width — including columns that were `display:none` a statement ago),
and reverts — all synchronously, so no intermediate state is ever painted.
One extra layout pass per measurement, on a table capped at the page size —
not per resize.

An off-screen clone was the first design and was rejected on a real hazard:
connecting a clone upgrades every custom element inside it (row actions,
tooltips, dropdowns), running their `connectedCallback`s and pouring
duplicate ids into the document.

- **Wrap columns are clamped arithmetically.** A free-text column's
  max-content width is the whole note on one line (easily >1000px), which
  would eat the entire fit budget and drop every other column. Its measured
  width is clamped to the name cap (`min(natural, 304px)`) in the cost model —
  no per-cell style mutation — because past the cap it wraps instead of
  widening the table. Under `width: max-content` each column resolves its own
  max-content independently, so the oversized raw measurement never inflates
  its neighbours.

**2. Invalidation: every trigger re-measures.** The first design split cheap
re-fit (cached widths, on resize) from full re-measure (on content change).
The e2e suite refuted the premise that widths survive a resize — twice:
crossing `md` invalidates the shrinkable column (below md its `max-md:max-w-0`
greed corrupts the max-content measurement to near zero; the floor masks that
below md but the cached garbage would be used raw above), and crossing `sm`/`lg`
invalidates every column, because cell padding is responsive
(`px-2 sm:px-3 lg:px-6` — cached-at-768 widths under-predict 1280 by ~26px on
the purchases table). Widths are only valid inside the breakpoint regime they
were measured in, and rather than enumerating regime boundaries (a trap for
whoever adds the next responsive cell class), every trigger — connect,
`document.fonts.ready`, `<tbody>` subtree mutation (the refund swap,
`session-row.ts`'s clones), and region resize — runs the same
frame-coalesced measure-then-fit.

**3. Fit.** `available` is the region's `clientWidth`. Every column costs its
natural width, with one exception: below `md`, a `shrinkable` first column
costs a flat floor (`NAME_FLOOR_PX = 160`) instead — the Phase 0 greed
(`max-md:w-full max-md:max-w-0`) squeezes it to whatever is left, and the
floor is what guarantees "the Name column is at least ~150px" without any
per-table constant. Columns are dropped in (priority ascending, index
descending) order — least important first, rightmost first among equals —
until the total fits. The first column never drops: it is the row header that
gives every row its name.

**4. The hidden state is a table-level class, and the ceiling is 12.**
Per the rule-placement hazard, the drop decision must survive an htmx `<tr>`
landing in the live `<tbody>`, so it cannot live per-cell. The element toggles
`[&_tr>*:nth-child(N)]:hidden` classes on the `<table>` (one selector covers
`<th>` and `<td>`), safelisted in `input.css` via `@source inline` for
N ∈ 2..12, following the existing align-rule family. 12 matches that
precedent and today's widest table (purchases, 9) with room; a data table
with more than 12 columns raises in `StyledTable`, so the ceiling fails
loudly instead of silently not hiding column 13.

## The no-JS handover: `:not(:defined)`, not strip-on-mount

The spec proposed stripping the server's `max-md` classes on mount and asked
whether to accept a column-pop or gate the swap. Both halves dissolve with a
better gate: the fallback hiding classes on `<thead>`/`<tbody>` become
`:not(:defined)`-scoped arbitrary variants —

```
max-md:[responsive-table:not(:defined)_&_th:not(:first-child):not(:last-child)]:hidden
max-md:[responsive-table:not(:defined)_&_td:not(:first-child):not(:last-child)]:hidden
```

No JS (or JS failed to load): the element never upgrades, the selector keeps
matching, behavior is exactly today's. JS: the module registers after parse,
upgrade runs `connectedCallback` with children complete, the first measure +
class application happen synchronously in that same task — and the instant the
element is defined the fallback selector stops matching. The two systems
cannot both be active, and there is no frame between them, so there is no pop
to gate. Nothing needs to know the class literals to strip them.

These fallback classes now render only on data tables. The stats cards lose
the old (vacuous — they are 2-column, and the selector only ever matched
middle cells) hiding rule from their class strings; their rendering is
unchanged.

## Per-view priorities

Default `priority=1`. Actions is highest everywhere (row operations must
survive the longest), the primary datum next, audit columns (Created,
Wikidata, Infinite…) stay at 1 and drop first, rightmost first among equals.

| table | 4 | 3 | 2 | 1 (drop first, rightmost first) |
|---|---|---|---|---|
| sessions | Actions | Date | Duration | Device, Created |
| games | Actions | Status | Year, Playtime | Wikidata, Created |
| purchases | Actions | Price | Type, Purchased | Infinite, Finished, Refunded, Created |
| playevents | Actions | Started | Ended, Days to finish | Note, Created |
| devices | — | Actions | Type | Created |
| platforms | — | Actions | Icon, Group | Created |
| statuschanges | — | Timestamp | New Status | Old Status |
| game detail: purchases | — | Actions | Date, Price | Type |
| game detail: sessions | — | — | Duration | Device |
| game detail: playevents | shares the playevents list columns |

## What this replaces / what stays

- The positional `max-md` rules survive only as the `:not(:defined)` no-JS
  fallback; the mounted element's decision is the real behavior at every width.
- Phase 0's `shrinkable` greed stays `max-md`-gated and untouched; the fit
  model accounts for it via the floor.
- The scroll region (Phase 2d) stays. With priority-plus active it rarely
  scrolls — that is the point — but it remains the escape hatch when even the
  kept set overflows (pathological content, tiny viewports) and under no-JS.

## Measured end state

Container widths are the page container. Two games (one name past the cap),
four sessions, two purchases. `dropped` is what the element hid; `name` is the
rendered first-cell width.

| page | viewport | container | h-scroll | columns | dropped | name |
|---|---|---|---|---|---|---|
| sessions | 390 | 358 | 0 | 2/6 | Date, Duration, Device, Created | 250 |
| sessions | 768 | 720 | 0 | 4/6 | Device, Created | 304 |
| sessions | 1024 | 976 | 0 | 4/6 | Device, Created | 408 |
| sessions | 1280 | 1232 | 0 | 6/6 | — | 324 |
| games | 390 | 358 | 0 | 2/7 | Year, Playtime, Status, Wikidata, Created | 250 |
| games | 768 | 720 | 0 | 5/7 | Wikidata, Created | 293 |
| games | 1024 | 976 | 0 | 6/7 | Created | 336 |
| games | 1280 | 1232 | 0 | 7/7 | — | 373 |
| purchases | 390 | 358 | 0 | 2/9 | all but Name + Actions | 204 |
| purchases | 768 | 720 | 0 | 5/9 | Infinite, Finished, Refunded, Created | 290 |
| purchases | 1024 | 976 | 0 | 6/9 | Finished, Refunded, Created | 330 |
| purchases | 1280 | 1232 | 0 | 8/9 | Created | 336 |
| purchases | 1440 | 1280 | 0 | 9/9 | — | 309 |

Three things to read off it:

- **Zero wrapper scroll everywhere** — including purchases at 1024, which
  still carried 285px of keyboard-only scroll after Phase 2.
- **Mobile's two-column view is emergent**: exactly Name + Actions at 390 on
  every page, from the fit arithmetic rather than a breakpoint — and the name
  column never fell below its floor (204px worst case, floor 160).
- **Drop order follows the declared priorities**: audit columns (Created,
  Wikidata, Infinite) go first, Actions never dropped in practice.

## Coverage

| file | what it pins |
|---|---|
| `ts/elements/responsive-table.test.ts` | the fit math and class application with stubbed widths: drop order (priority asc, index desc), the first column never dropping, the below-md floor substitution, the wrap-column cap in the clone, re-fit vs re-measure triggers |
| `tests/test_components.py` | `data-priority` stamped on data-table headers only, the `<responsive-table>` wrapper gated on `data_table`, the >12-column raise, fallback hiding classes `:not(:defined)`-scoped and absent from stats tables |
| `tests/test_table_width_policy.py` | every list page mounts exactly one `<responsive-table>`; stats pages mount none |
| `e2e/test_responsive_table_e2e.py` | rendered behavior: no wrapper scroll on the list pages at 390/768/1280; the name cell ≥150px at 390; columns reappear as the viewport widens; the decision is re-applied to a row swapped in by refund; a JS-disabled context still hides middle columns below `md` (the fallback) |
| `e2e/test_table_width_e2e.py` | the scroll-region test moves to the no-JS context, where overflow still genuinely exists |
