# Which facets the quick bar shows inline

Issue #1254, in the
[Selectable tables and Session organization wave](2026-09-19-selectable-tables-wave-design.md),
after #717. The wave's section "The question the sole-run rule never asked"
leaves which facets ride inline to this issue.

## The problem

The quick filter bar keeps its facets in one row and moves the ones that do
not fit into the `⋯` overflow (`ts/elements/quick-filter-bar.ts`). The row
keeps a prefix of `QUICK_FACETS[mode]`: position is the only priority. The
order of each list was written to mirror the list's columns, not to rank
the facets.

Three costs follow:

1. A link that lands with a facet applied can hide that facet. The Library
   page's Outside dates and Imported history cards land on the session list
   with facets 7 and 6 applied; the stats page lands on the purchase list
   with Purchased (6) and Refunded (7), and the Library page with Refunded;
   the stats page's record link lands on the Historical tab with When (5).
   Each sits in `⋯` at every width.
2. Nothing on a facet's trigger says it is applied. `ComboboxDropdown`
   renders `Label ▾` whatever the widget holds. An applied facet in the row
   reads the same as an idle one; in `⋯` it is not seen at all.
3. Name and note facets hold leading slots although the search field
   (#1146) already searches those columns.

## The rule

The rule is the bar's, so every mode takes it.

### Priority is not position

A facet is **applied** when the page's filter holds its key. The server
knows this from `QuickFilterBar.existing` and stamps
`data-quick-facet-applied` on the facet's `<drop-down>`. A value the person
has changed in an open panel but not applied does not count: Apply
navigates, so the mark always states the filter the list shows.

A key whose criterion narrows nothing (`{"game": {"value": []}}`, reachable
only by a hand-written URL or a builder preset; the bar never emits one)
marks its facet applied too. The mark states the filter's keys, the same
set Clear drops; judging each criterion would need every kind's emptiness
rule on the server.

`layoutOverflow` builds a priority sequence: the applied facets in declared
order, then the idle facets in declared order. `priorityPlusFitCount` runs
over the widths in that sequence and keeps a prefix of it: the **kept
set**. The kept facets stand in the row in **declared** order; the spilled
facets stand in `⋯` in declared order too.

Neither holds today. The row loop assumes the kept facets are indices below
`fitCount`, and the `⋯` loop only appends a newly spilled facet, so a row
narrowed in two steps leaves `⋯` as `[f3, f2]`. Both loops are rewritten
over the kept set: the row reinserts kept facets in declared order before
the host, and `⋯` receives every spilled facet again in declared order on
each layout.

So an applied facet spills only after every idle facet has spilled, and
the facets' relative order never changes: in the row, in `⋯`, before and
after Apply. Apply reloads the page, so an applied facet that sat in `⋯`
comes into the row and pushes an idle one out; that is the rule, not a
move. The fit stays a
prefix of the priority sequence: a narrow idle facet never takes the slot a
wider applied facet could not get, because a row that skips ahead reorders
itself at each width.

`ts/elements/priority-plus.ts` does not change. The selection tray and the
responsive table use it with their own orders.

### The mark

An applied facet's trigger shows a leading dot (`bg-brand`) and its label
in `text-fg-brand`. The trigger stays a ghost. The ghost tone puts
`text-heading` on the button, and in the compiled stylesheet
`.text-heading` comes after `.text-fg-brand`, so a class on the button
loses. The label is therefore its own `Span(class_="text-fg-brand")`
inside the trigger, and the dot a `Span` beside it. The trigger's text
gains a screen-reader-only "(applied)"; the facet trigger carries no
`aria-label`, so its content is its name. `ComboboxDropdown` takes
`applied: bool` and emits these nodes itself; no stylesheet reaches in.

The `⋯` trigger holds the same dot, rendered `invisible` rather than
`hidden`: it takes its width at connect, when `⋯` is measured, so showing
it later cannot widen `⋯` past the reserved width and wrap the furniture.
The `⋯` trigger is an `IconTrigger`, whose `aria-label` overrides its
content, so `layoutOverflow` sets that label: "More filters" while `⋯`
holds no applied facet, "More filters, some applied" while it holds one,
and toggles the dot's `invisible` with it. On a phone the row fits few
facets, and an applied facet can still spill; the `⋯` mark says so.

One mark for every kind. The mark states **that** a facet is applied, not
**what** it holds; the value shows when the panel opens. A value summary
(`Game: Elden Ring +1`) was weighed and refused: it needs a summarizer for
each of the five kinds and each modifier, and a wider trigger pushes more
facets into `⋯`.

The widths are measured once, at connect. The mark is part of the
server-rendered trigger, so it is in the measured width, and it cannot
change until the next page load.

## The orders

Each mode's `QUICK_FACETS` list is its declared order. The applied rule
rescues each landing above; the orders make the idle row useful, so the
row does not depend on the rule for its everyday facets.

| Mode | Order |
|---|---|
| sessions | Game, Day, Playthrough, Outside dates, Device, Timing, Duration |
| purchases | Type, Purchased, Refunded, Ownership, Price, Infinite, Created, Name |
| historical_playtime | Game, When, Provenance, Device, Duration, Created |
| games | Status, Platform, Year, Playtime, Mastered, Sessions, Purchases, Total price, Name |
| playthroughs | Activity, Game, Started, Completed, Days to finish, Created, Note |
| devices | unchanged: Name, Type, Created |
| platforms | unchanged: Name, Group, Created |

- **sessions**: Game and Day are the everyday pair. Playthrough and Outside
  dates are the organizer's questions and the Library cards' landings.
  Device drops out of the idle row; an applied Device keeps its slot.
- **purchases**: Purchased and Refunded are what the stats page links
  with; the Library page links with Refunded.
- **historical_playtime**: Game and When, as on the session list.
- **games** and **playthroughs**: only the search-duplicating facet moves.
- **devices** and **platforms**: three facets fit a desktop row, so the
  order decides only on a phone, where Name leads as the list's first
  column.

Name and note facets go last and stay, except on devices and platforms,
whose Name is the list's first column and whose rows fit. The search field matches a
substring in several columns; the facet states `is empty`, `is not` and
the other string modifiers on one column, which the search cannot. A
stored preset or link naming them stays editable.

How many facets fit depends on the labels and the furniture. The spec
names orders, not a count.

## What this forecloses

- **Per-person pinning.** The declared order is the only idle priority. A
  stored order per person would feed the same priority sequence, so the
  element does not need a new shape to take one later.
- **The value on the trigger.** Refused above.
- **Order by use.** Nothing counts which facets a person applies. The
  orders are the maintainers' reading of each list.

## Out of scope

- Links whose filter the facets cannot state (`purchases_unfinished`,
  `games_played`, `sessions_for_platform`, the Game detail's purchase
  link) degrade the bar to its pill. #1249 owns that.
- Where the preset picker stands among the furniture: #1267.
- No new element.

## Tests

- **vitest** (`ts/elements/quick-filter-bar.test.ts`): an applied facet
  stays in the row while idle facets to its left spill; kept facets keep
  declared order in the row, spilled ones in `⋯`, across a stepwise
  narrowing (1000 → 400 → 300) and a narrow-wide-narrow cycle; the `⋯` dot
  and `aria-label` change only while `⋯` holds an applied facet.
- **pytest** (`tests/test_quick_filter_bar.py`): the stamp and the mark
  render for an applied key only, in every kind; `ComboboxDropdown`
  without `applied` renders as before; each mode's order is pinned.
- **e2e** (`e2e/test_quick_filter_e2e.py`): the session list opened from
  the Outside dates filter shows that facet in the row and marked; a
  narrowed row spills idle facets first and marks `⋯` when an applied facet
  spills.
- **Tests the new orders break**, updated in the same change:
  `e2e/test_quick_filter_e2e.py` asserts Timing is not in `⋯` at 2000px
  (Timing becomes sixth) and its docstring says four fit;
  `e2e/test_set_filter_e2e.py` clicks the Device trigger on a sessions
  harness with no `⋯` fallback (Device becomes fifth), which takes the
  `_open_facet` fallback of `e2e/test_number_filter_e2e.py`; comments in
  `e2e/test_quick_filter_e2e.py` naming facet positions.
- `make render-pages` before and after, every differing file attributed to
  a moved trigger or a mark.
