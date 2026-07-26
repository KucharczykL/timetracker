# Table Widths Phase 2 — `Column` owns width policy

**Goal:** Make one place decide how wide a table's columns may be. Cells on a
table of records stay on one line, names cap and fade on every list page rather
than three of seven, and the horizontal scroll that a one-line table produces is
reachable from the keyboard.

**Design:** `docs/superpowers/specs/2026-07-26-responsive-table-widths-design.md`
§ Phase 2. **Tracked by** #523. **Needs** Phase 0 (#525, shipped).

**Architecture:** an explicit `StyledTable(data_table=True, caption=…)` gate.
Everything the phase adds hangs off it, so the four stats-card tables that render
through the same component are unaffected by construction rather than by
remembering to exclude them. `Column` gains `wrap` as the per-column opt-out.

---

## What shipped

- [x] **2a — cells do not wrap.** `TableTd` gains `nowrap`; `_header_cell` and
  `TableRow` add `whitespace-nowrap` on a data table unless the column sets
  `wrap`. The row-header `<th>` was already single-line, so `wrap` is the only
  thing that can now release it.
- [x] **2b — the data-table gate.** `StyledTable(data_table=…)`, defaulting off.
  `paginated_table_content` passes it (7 list tables), and the 3 game-detail
  mini-tables pass it directly. The 4 stats tables are untouched.
- [x] **2c — uncapped first columns.** Devices, platforms and status changes
  rendered their first cell as a bare string; play events rendered a `GameLink`,
  which has no cap and no fade either. All four now go through `TruncatedText`,
  so the 16rem cap and the fade apply on all seven list pages.
- [x] **2d — the accessible scroll region.** A visually hidden `<caption>` opens
  each data table and names a `role="region" tabindex="0"` scroll wrapper, plus
  `scroll-padding-inline-start` so a control tabbed into from off-screen does not
  land where Phase 4 will paint the pinned column.

## Decisions made during implementation

**The gate defaults to off.** The spec says "gate on an explicit `StyledTable`
parameter" without fixing the default. Off makes the stats cards byte-identical
structurally — verified by snapshotting their rendered `<table>` markup before
and after: all 6 tables identical — and keeps the 18 test call sites meaning what
they meant. The cost is that a future data table rendered through `StyledTable`
directly, rather than `paginated_table_content`, has to opt in.

**`TableTd(nowrap=…)`, not `TableTd(wrap=…)`.** The spec's wording has `TableRow`
pass `columns[i].wrap` straight through, which would apply the one-line rule to
every table including the stats cards. Since the gate has to reach the cell
anyway, the cell takes the decision (`data_table and not column.wrap`) rather
than a column policy it would have to reinterpret.

**The caption is required, not defaulted.** `data_table=True` without a caption
raises. A defaulted or empty caption yields an unlabelled region — the exact
failure the spec calls out for bare `randomid()` — and it fails silently.
`TableData` therefore gains a required `caption` key, so every list view names
its own table.

**The refund row fragment carries the column list.** `refund_purchase` re-renders
one row outside the list view. Left alone it would have landed between nowrap
rows without the rule, on top of the missing `shrinkable` class already filed as
#526. The purchase column list moved to a module constant and the call site now
passes it with `data_table=True`, which closes #526 as a side effect. The wider
"refund reloads the list" item on #523 still stands and retires the endpoint.

**`GameLink` in the play-events first column.** Not in the spec's 2c list, which
enumerated only the three bare-string cases. `GameLink` renders a `truncate-container`
span that has no CSS rule anywhere in the project, so it capped nothing; under
nowrap a long game name would have set the column width for the page. Replaced
with `TruncatedText(link=…)`, matching how sessions and games render their names.

**Phase 0's `Column.shrinkable` asymmetry (#527) is left alone.** `TableRow` now
reads `columns[i]` for every cell, which makes the header/body split on
`shrinkable` more visible, but the fix that issue prefers is a raise on
construction and belongs with it.

## Measured end state

Container widths are the page container, not the viewport. Four rows, one name
past the cap. `dead` is the first cell's inner width minus its `<truncated-text>`.

| page | viewport | container | h-scroll | wrapped columns | name cell | dead |
|---|---|---|---|---|---|---|
| sessions | 1024 | 976 | 165 | none | 304 | 0 |
| sessions | 1280 | 1232 | 0 | none | 328 | 24 |
| sessions | 1440 | 1280 | 0 | none | 341 | 37 |
| games | 1024 | 976 | 65 | none | 304 | 0 |
| games | 1280 | 1232 | 0 | none | 360 | 56 |
| games | 1440 | 1280 | 0 | none | 374 | 70 |
| purchases | 1024 | 976 | 285 | none | 304 | 0 |
| purchases | 1280 | 1232 | 29 | none | 304 | 0 |
| purchases | 1440 | 1280 | 0 | none | 309 | 5 |

Two things to read off it:

- **The Phase 0 interim regression at ~1024 is closed.** That table recorded
  purchases still wrapping TYPE and PRICE there. Nothing wraps now, on any of the
  three pages, at any of the three widths.
- **Wrapping became scroll, as designed.** Purchases at 1024 goes from 174px of
  overflow to 285px. That is the trade 2a makes, and it is why 2d is in the same
  change: all of it is now inside a focusable, named region instead of a plain
  `overflow-x-auto` div. Phase 3 is what reduces the number itself.

Residual dead space is the proportional slack share already recorded as #522
(51px measured there, 0–70px here) — ordinary auto-layout distribution, not the
247px hoard Phase 0 removed.

## Coverage

| file | what it pins |
|---|---|
| `tests/test_components.py::DataTableWidthPolicyTest` | the gate: nowrap on/off, `wrap` opt-out in header, body and row header, the caption's position and `sr-only`, the region's label resolving to it, the missing-caption raise, a row fragment carrying the policy, and a ragged row still degrading instead of raising |
| `tests/test_table_width_policy.py` | the cross-page contract: every list page has exactly one named, focusable region; every first column self-clips; stats cards have neither; the Note column's header is unpinned; the refunded row fragment keeps the policy |
| `e2e/test_table_width_e2e.py` | rendered lines, not classes: no cell on any of the 7 list tables occupies more than one line at 390 / 768 / 1280, counted by walking text nodes and de-duplicating `Range.getClientRects()` tops; the Note column *does* take several lines with a realistic note; the region is focusable, named "Purchases", and actually scrolls |
| `tests/test_navbar_log_button.py` | rewritten, not deleted: the deleted `<caption>` action strip stays deleted — one caption per list page, `sr-only`, holding nothing clickable |

The no-wrap assertion excludes only `Note`, and that exclusion is not vacuous —
the companion test seeds a multi-line note and asserts it wraps.

## Not in this phase

No priority-based column dropping (Phase 3), no sticky first column (Phase 4a),
no top-layer panels (Phase 1). The `max-md` positional column-hiding rules stay
exactly as they are; Phase 3 is what retires them.
