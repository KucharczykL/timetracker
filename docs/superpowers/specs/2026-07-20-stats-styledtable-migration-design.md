# Stats tables → StyledTable (mechanical migration) — design

Issue: [#409](https://github.com/KucharczykL/timetracker/issues/409).

## Context

`#409` is the last item retiring the third table styling generation. `common/input.css`'s
`.responsive-table` block — indigo/slate zebra, 16px cells, `table-fixed`, and
styling-at-a-distance (`.responsive-table tr:nth-child(even)`) — has one consumer:
`games/views/stats_content.py`'s `_table()`. The issue asks to route the stats tables through
the tokenized `StyledTable` / `Column` / `make_row` family (`common/components/primitives.py`),
delete the CSS block, and resolve the dead `max-w-20char` utility.

Brainstorming first expanded this into a two-column card-grid redesign. Three adversarial Fable
reviews (verify-against-code, defect-hunt, altitude) established two things: (1) `StyledTable` is
**already fully tokenized** (semantic `neutral-*` zebra, `font-condensed`, responsive
column-hiding), so the grid has no hard dependency on the other token-migration follow-ups and no
urgency; and (2) the grid drags in roughly eight incidental taste changes — fixed cell padding,
kv-label weight inversion, forced link underlines, name overflow in narrow columns, a
zero-`<h1>` accessibility regression, row-major ordering shuffle, standalone-link styling — none
of which belong to `#409`'s mechanical core.

**Decision: split.** This spec covers only the mechanical migration; the card-grid redesign is
deferred to its own issue where it can be screenshot-iterated.

Outcome: one zebra treatment app-wide, `.responsive-table` and the dead `*-char` utilities gone,
and the stats tables inheriting `StyledTable`'s semantic tokens, `font-condensed`, and responsive
chrome. This also hands the remaining token/radius follow-ups (#404, #411) a clean substrate.

## Decisions

- **Split** — mechanical only. The existing single-column layout and per-section `PageHeading`
  titles are kept. No grid, no heading retirement, no data drop.
- **KV tables → headerless `StyledTable`.** The three key-value tables (Playtime, Purchases,
  Playtime-per-month) have no header today. `StyledTable` always emits a `<thead>`, so it is
  extended with `show_header: bool = True`; `show_header=False` suppresses the header while
  `columns` is still consumed for the DEBUG cell-count guard and the alignment rules. Chosen over
  inventing synthetic "Metric/Value" headers, which would ship a filler uppercase band on blocks
  that never had one — a header that labels nothing the row labels don't already say.
- **Unfinished table stays 3-col, reordered `Name / Date / Price (CZK)`.** `StyledTable`'s mobile
  rule hides the *middle* column below `sm`; ordering Date in the middle keeps Price on mobile,
  with no data loss.
- **font-mono dropped** on numeric value cells. `StyledTable`'s `tbody` is `font-condensed`, whose
  digits are already tabular (visual-conventions §7 records `font-mono` here as a style choice,
  not an alignment mechanism).

## Implementation

### 1. Extend `StyledTable` (`common/components/primitives.py`)

Add `show_header: bool = True`. Wrap both the `header_row` build and the `<thead>` append in
`if show_header:`. The DEBUG count-guard, `align_rules`, and `<tbody>` build are unchanged —
`columns` remains required for count and alignment even when the header is suppressed. Add a unit
test to `tests/test_components.py`: `show_header=False` renders a `<tbody>` but no `<thead>`; the
default still renders a `<thead>`.

### 2. Rewrite `games/views/stats_content.py`

Delete the helpers `_table`, `_tr`, `_td`, `_th`, `_kv`, `_view_all_row` and the constants
`_CELL_SPACING`, `_CELL`, `_CELL_MONO`, `_NAME_TH`, `_CELL_TH`. Drop the dead `purchase-name`
class reference. Keep `_FILTER_LINK_CLASS`, `_session_link`, `_count_link`, `_purchase_name` (its
`Safe(...)` return is a valid first-cell child), `_year_nav`, `_dur`, and the `stats_content`
section assembly with its `PageHeading`s.

Each section builds `StyledTable(columns=[Column(...)], rows=[make_row(...)], show_header=…)`:

- **kv tables** (`_playtime_table`, `_purchases_table`, month block): `show_header=False`, two
  placeholder `Column("")`s. The first cell (label) auto-renders as `<th scope="row">`.
- **ranked** (`_two_col_table` for Games/Platforms, `_finished_table`): `show_header=True`, real
  `Column` labels.
- **`_priced_table`** (Unfinished): `show_header=True`, three columns `Name` / `Date` /
  `Price (CZK)` (reordered), rows
  `make_row(_purchase_name(p), date_filter(p.date_purchased, "d/m/Y"), floatformat(p.converted_price))`.

Type fixes so cells satisfy `Cell = Node | str` under mypy (today some cells pass `list`/`int`):

- `Fragment(...)`-wrap the multi-node value cells in `_game_row` and the First-play / Last-play
  blocks of `_playtime_table`.
- `str(...)` the raw-int value cells (`total_year_games`, the two `Finished` counts).
- Add `decoration-transparent` to `_session_link`'s anchor so the row's forced `[&_a]:underline`
  doesn't draw under the play-icon glyph. **Not** `no-underline`: the row rule's specificity
  (0,1,1) beats `.no-underline` (0,1,0); since the row never sets a decoration *color*,
  `decoration-transparent` (0,1,0) wins uncontested and hides the line.

**"View all"** moves out of the table (a colspan row cannot pass through `make_row`). Render it
below each capped `StyledTable`, gated on `total > _LIST_CAP`, reusing the `_game_section`
convention (`games/views/game.py:471`): a gray `ControlButton` with an `arrowright` icon and a
`View all (N)` label. Count source per helper: `_finished_table` / `_priced_table` already take an
explicit `total=` (use it); `_two_col_table` has no total param — keep its `len(items)` (its
`top_10_games_by_playtime` queryset is actually uncapped, so `len()` is the true total; the
misleading name is flagged for the follow-up issue, not fixed here).

Imports: drop `Table`, `Tbody`, `Td`, `Th`, `Thead`, `Tr`; add `StyledTable`, `Column`,
`make_row`, `ControlButton`. (`Icon`, `ICON_BUTTON_SIZE_CLASS`, `Fragment`, `PageHeading`, `A`,
`Div`, `GameLink`, `Safe`, `ContentContainer`, `YearPicker` are already imported.)

### 3. Cleanup

- `common/input.css`: delete the `.responsive-table` rule group (keeping the `@layer utilities`
  closing brace) and the two dead commented `@utility *-20char/30char/35char/40char` blocks.
- `scripts/contrast_audit.py`: delete the five stale stats-zebra tuples and the palette-dict keys
  they orphan (`indigo-100`, `indigo-200`, `slate-500`, `slate-800`, `slate-900`). `StyledTable`'s
  neutral tokens are audited elsewhere, so no coverage is lost. (No CI/test hook runs this script.)

### 4. Fix tests (`tests/test_rendered_pages.py`)

- `test_stats_alltime`: replace the `"responsive-table"` marker with a discriminating
  thead-anchored regex `r"<thead[^>]*bg-neutral-tertiary"` (a bare substring would also match every
  row's `hover:bg-neutral-tertiary-medium`). The Games/Platforms tables render unconditionally, so
  a `<thead>` is always present. Keep the section markers and the `<table>` balance assertion.
- `test_stats_table_uses_type_tokens`: rewrite to the new reality — `text-type-micro` lives on
  `<thead>` and `text-type-body` on `<table>`, not on the cells. Regexes:
  `r"<thead[^>]*\btext-type-micro\b"` and `r"<table[^>]*\btext-type-body\b"`.
- `tests/test_stats_content_links.py`: verify it still passes (the `ControlButton` label contains
  "View all", the gate holds, hrefs are unchanged, and tests run with `DEBUG=False` so the
  count-guard is inert). No change expected.

## Verification

- `direnv exec . make check` green (lint, format-check, mypy, ts-check, vitest, and the full
  pytest suite including `e2e/`) — never a subset.
- Preview `games:stats_alltime` and a `stats_by_year` in both themes and at mobile and desktop
  widths. Confirm: kv tables have no header band, ranked tables have headers and working "View
  all" buttons, Unfinished shows Name/Date/Price (Date hides below `sm`, Price stays), no
  indigo/slate anywhere, no play-icon underline.

## Update — card-grid redesign folded in (split reversed)

The split was **reversed** after live review: on the kept single-column layout the `w-full`
StyledTables read poorly (values floating mid-width, headings hard against the table below,
cramped "View all"). Rather than one-off patches, the card-grid redesign (originally deferred to
#435) is now included so the layout is consistent by construction:

- **Two-column responsive grid** — `Div(grid grid-cols-1 md:grid-cols-2 gap-6 items-start)`, one
  **card per section**. `gap-6` gives the section rhythm; `items-start` top-aligns uneven cards;
  collapses to one column below `md`.
- **Card unit** — `_card(title, table)` = `Div(min-w-0)[ _card_title, table ]`. `min-w-0` lets a
  wide table scroll inside its own box instead of blowing out the grid column.
- **Headings** — one page `PageHeading` (`<h1>`, `ctx["title"]`) replaces the former per-section
  `<h1>`s; each card title is an `<h2>` at `text-type-subheading` (`Element("h2", …)` to avoid the
  size token baked into the `H2` builder).
- **Right-aligned values** — every value/number column uses `Column(align="right")` via the
  existing nth-child align rule (safelisted 1–12). Fixes the "floats in space" gap.
- **Unfinished table → 2-col `Name / Price (CZK)`** (Date dropped) to match the other 2-col cards.
- **"View all"** stays a gray `ControlButton` below its table (`mt-3` + grid gap for rhythm).

Verified live (computed styles, both themes, mobile + desktop): page `h1`, 2-up grid at ≥`md`
collapsing to 1 column, right-aligned values, headerless kv / headed ranked tables, Unfinished
`Name/Price`, spaced view-all buttons, no indigo/slate.

## Still deferred

- **StyledTable shell rounding** → #438 (square bottom corners without a footer; intrinsic
  rounding + a general footer slot). Affects all list pages; kept separate.
- The misleading `top_10_games_by_playtime` name and `_two_col_table`'s `len(items)` count.
